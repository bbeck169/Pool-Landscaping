# SPEC: AI Live Dispatcher + Predictive Maintenance (queued brief)

**Status:** QUEUED — position 3.5. **DO NOT START.**
Saved at: Feb-2026 (during Pool Service PS-B build window).

## Precedence over prior specs
- This brief BUILDS the actual `live_dispatcher` + `maintenance_scanner` services. Prior `SPEC_TENANT_CONFIG_HUB.md` assumed these existed and would just wire tenant thresholds through. Reality: they don't exist yet.
- **TCH-A `automation_rules` sub-doc** → this brief owns it now (fields identical). Delete/no-op TCH-A when TCH runs.
- **TCH-C wire-through** → superseded; the services in this brief READ tenant settings from day one, so TCH-C becomes empty.
- **TCH-D UI** → extend to include "Manage Automations" sub-section alongside "Manage AI Workforce". Or split into two tabs. Note choice.
- **TCH-B (AI Dock enable-list filter)** + **TCH-E (JWT audit)** remain distinct — unaffected.

## Scope
Two new services + tenant-configurable rules + management UI.

## Sub-phases (5)

### LDM-A — Tenant `settings.automation_rules` sub-document
- Add to tenant model (`backend/routers/tenants.py` or `backend/models.py`):
  ```
  settings.automation_rules = {
    dispatch_delay_threshold_mins: int (default 20),
    dispatch_sms_customer_count: int (default 3, range 1-10),
    filter_clean_interval_months: int (default 6),
    salt_cell_replacement_months: int (default 36),
    quiet_hours_start: "20:00",  # inherit from comms_sms_adapter if already present
    quiet_hours_end: "08:00",
  }
  ```
- Idempotent migration `automation_rules_v1.py` — backfill defaults on all tenants. Sentinel-gated.
- PATCH endpoint (or extend existing tenant PATCH): **JWT-derived tenant_id only**, reject body-supplied tenant_id (403).
- Tests: field addition, PATCH auth, cross-tenant 403, migration idempotent.

### LDM-B — AI Live Dispatcher service
- New file `backend/services/live_dispatcher.py`.
- Cron cadence: every 5 minutes. Register alongside MARCO cron in `server.py`.
- Algorithm:
  1. For each tenant, load `settings.automation_rules.dispatch_delay_threshold_mins` (fallback 20).
  2. Query techs currently on-route (grep `techs` / `crew_shifts` / `visits` for the "in-progress" filter). For each:
     a. Get latest `gps_pings` row for tech (last 10 min).
     b. Get next scheduled visit → `scheduled_start`.
     c. Compute projected arrival = current location → next visit location via routing helper (grep for existing route/ETA helper; if missing, fall back to Haversine distance / avg speed 30mph — note fallback).
     d. Delay = projected_arrival - scheduled_start.
     e. If delay > threshold → trigger delay-notification flow (step 3).
  3. Delay-notification flow:
     - Pick next N customers on the route where N = `dispatch_sms_customer_count`.
     - For each: invoke `services.comms_sms_adapter.send_sms(customer_phone, message, tenant_id=...)`. Message template: MARCO-branded, includes new ETA. Draft template inline as `_MARCO_DELAY_SMS_TEMPLATE`.
     - **Respect quiet hours + opt-out**: `comms_sms_adapter.send_sms` must enforce these (grep the adapter — if not enforced there, add pre-send guard).
     - Log dispatch event to new `dispatch_events` collection: `{tenant_id, tech_id, delay_mins, customers_notified: [id], initiated_at, initiated_by="marco_live_dispatcher"}`.
     - Idempotency: don't re-send within a 30-min window for the same tech + visit combo (dedupe by `(tenant_id, tech_id, visit_id)` last-notified timestamp).
- Failure handling: SMS failure logs warning, doesn't stamp dedupe timestamp, retries next scan.
- Tests `backend/tests/test_live_dispatcher.py`:
  - Tenant-scoped isolation (tenant A tech doesn't trigger tenant B customers)
  - Threshold respected (default 20 vs custom 30)
  - Quiet hours skip
  - Opt-out skip
  - Dedupe window (2 back-to-back runs → 1 SMS)
  - N-customer selection (default 3 vs custom 5)
  - Fallback ETA when routing helper missing
  - No pings → skip tech gracefully

### LDM-C — Predictive Maintenance Scanner
- New file `backend/services/maintenance_scanner.py`.
- Cron cadence: daily at 6am tenant-local. Register in `server.py`.
- Algorithm:
  1. For each tenant, load `filter_clean_interval_months` + `salt_cell_replacement_months`.
  2. For each customer with active pool subscription:
     a. Find last filter cleaning visit (grep visit types / service report chemistry). Compare to today. If overdue → flag.
     b. Find last salt cell replacement. Compare. If overdue → flag.
  3. For each flag, MARCO drafts a Pending cross-sell action in `ai_employee_actions` queue (grep existing collection; if missing, add minimal model):
     - `{tenant_id, customer_id, action_type: "cross_sell_filter" | "cross_sell_salt_cell", status: "pending", drafted_by: "marco_executive", drafted_at, due_reason, customer_last_service_at, suggested_price_range}`
  4. Dedupe: don't re-draft if an active pending action exists for the same customer + type.
- Tests `backend/tests/test_maintenance_scanner.py`:
  - Tenant-scoped isolation
  - Overdue filter → action drafted
  - Overdue salt cell → action drafted
  - Non-overdue → skipped
  - Custom interval respected (tenant A 3mo vs tenant B 12mo)
  - Duplicate scan doesn't create duplicate action
  - Customer without pool subscription → skipped

### LDM-D — "Manage Automations" UI
- Extend `TCH-D` "Manage AI Workforce" tab (or grep for existing settings surface; may already exist as `AdminSettings*.jsx`). Add sub-section "Manage Automations":
  - Sliders / number inputs for the 4 primary fields (`dispatch_delay_threshold_mins`, `dispatch_sms_customer_count`, `filter_clean_interval_months`, `salt_cell_replacement_months`)
  - Time-of-day pickers for quiet hours (or link to existing SMS settings if quiet hours live there — reuse, don't duplicate)
  - Save button + saved-indicator
- Palette: Navy `#1B1F5C` / Blue `#3B82F6`.
- Data-testids: `automation-slider-dispatch-delay`, `automation-slider-sms-count`, `automation-slider-filter-interval`, `automation-slider-salt-interval`, `automation-save`, `automation-saved-indicator`.
- Tests: sliders update state, PATCH fires with correct payload, JWT-guarded.

### LDM-E — Cross-tenant JWT safety audit
- Audit LDM-A/B/C/D endpoints — tenant_id always derived from JWT session, never body/query.
- GPS + scheduling lookups scoped by tenant_id.
- SMS sending: `comms_sms_adapter.send_sms` receives `tenant_id` and verifies customer belongs to that tenant before sending.
- Test: authenticated user with tenant A JWT can't PATCH automation_rules on tenant B → 403.

## Dependencies (must land before LDM starts)
- **`gps_pings` collection exists** — grep to confirm. If not, this brief expands significantly. Flag as blocker if absent.
- **`comms_sms_adapter.send_sms`** — grep. If missing, this brief becomes a mega-scope. Flag as blocker.
- **`ai_employee_actions` queue** — grep. If missing, minimal add is OK.
- **Existing route/ETA helper** — grep for `route_eta`, `travel_time`, `haversine`. If missing, use fallback per LDM-B step 2c.

## Design forks to resolve inline
- **Routing helper**: reuse existing OR haversine fallback? Note choice.
- **Cross-sell action model**: reuse existing `ai_employee_actions` collection OR new `pending_cross_sell_actions`? Prefer reuse.
- **UI split**: extend TCH-D tab vs. new "Manage Automations" tab? Pick one, note.
- **Quiet hours location**: standalone in `automation_rules` OR reference existing SMS-adapter config? Prefer single source of truth in `comms_sms_adapter` config; `automation_rules` links to it.
