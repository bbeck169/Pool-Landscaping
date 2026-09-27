# SPEC: Tenant Configuration Hub (queued brief)

**Status:** QUEUED — position 6. **DO NOT START.**
Saved at: Feb-2026 (during MARCO Sub-phase E build window).

## Scope
Let each tenant customize (a) automation thresholds/intervals used by cron/dispatch logic, (b) which AI employees are enabled, and (c) surface all of it in a settings tab.

## Sub-phases (5)

### TCH-A — Backend tenant settings sub-document
- Extend tenant model in `backend/routers/tenants.py` (or `backend/models.py` — match Sub-phase D convention):
  - `settings.automation_rules`:
    - `dispatch_delay_threshold_mins: int` (default `20` — current hardcoded value)
    - `filter_clean_interval_months: int` (default TBD via grep of Predictive Maintenance current constant, likely 6)
    - `salt_cell_replacement_months: int` (default TBD via grep, likely 36)
  - `settings.enabled_ai_employees: List[str]` — array of employee `key` strings (e.g., `["marco_executive", "casey", "buddy"]`). Default: ALL keys currently in `DEFAULT_EMPLOYEES` for that tenant.
- PATCH endpoint (or extend existing tenant PATCH): update these fields. **JWT-derived `tenant_id`** — reject any body-supplied tenant_id (403 on mismatch).
- Idempotent migration `backend/migrations/tenant_config_hub_v1.py`: backfill defaults for all existing tenants. Sentinel-gated via `migration_status`. Register in `server.py` structural-migration boot list.
- Tests: PATCH auth guard, cross-tenant 403, migration idempotent, default backfill correct.

### TCH-B — AI Dock enable-list filter
- Grep for `AIDock*.jsx` (likely `frontend/src/components/AIDock.jsx` per handover).
- Filter the persona list rendered in the Dock: only show employees whose `key` is in tenant's `settings.enabled_ai_employees` AND whose `active=true` (existing field).
- Server-side: `GET /api/ai-employees` (or equivalent list endpoint) applies the same filter — never leak disabled personas to the client.
- Preserve all `data-testid` attributes.
- Test: mock tenant with 3 enabled + 5 disabled → API returns 3, Dock renders 3.

### TCH-C — Wire tenant thresholds into existing logic
1. **AI Live Dispatcher**: grep for the hardcoded 20-minute value (likely `DISPATCH_DELAY_THRESHOLD` or inline `timedelta(minutes=20)` in a dispatcher service). Replace with a lookup: `tenant.settings.automation_rules.dispatch_delay_threshold_mins`. Cache per-tenant for the duration of a single scan cycle.
2. **Predictive Maintenance scanner**: grep for filter cleaning + salt cell replacement interval constants. Replace with tenant lookups. Same per-tenant caching pattern.
3. Fallback: if a tenant lacks the settings sub-doc (pre-migration), use the default constants — do NOT crash.
- Tests:
  - Tenant A with `dispatch_delay_threshold_mins=30` → dispatcher triggers at 30min
  - Tenant B with default (20min) → dispatcher triggers at 20min
  - Predictive Maintenance uses tenant-specific `filter_clean_interval_months` when computing next-service date

### TCH-D — Settings UI: Manage AI Workforce tab
- Add "Manage AI Workforce" tab to Admin Settings page (grep `AdminSettings*.jsx` or `SettingsPage*.jsx`).
- Layout:
  - **Automation Rules** section: 3 sliders (or number inputs with min/max)
    - Dispatch Delay Threshold: 5–60 mins
    - Filter Clean Interval: 1–24 months
    - Salt Cell Replacement Interval: 12–60 months
  - **AI Employees** section: grouped by department (Marketing, Operations, Customer, Executive — depends on 18-employee workforce landing first). Each department has a header and toggle switches for each employee. Bulk "Enable All" / "Disable All" per department.
- Palette: Navy `#1B1F5C` for section headers/backgrounds, Blue `#3B82F6` for slider tracks + toggle-on borders. Reuse existing shared `Slider` / `Toggle` components if present.
- Debounced save on change (or explicit "Save" button — pick one, note in commit). PATCH to tenant settings endpoint.
- Data-testids: `tch-tab`, `tch-slider-dispatch`, `tch-slider-filter`, `tch-slider-salt`, `tch-toggle-{employee_key}`, `tch-department-{dept}`, `tch-save`, `tch-saved-indicator`.
- Tests: sliders update state + fire PATCH, toggles filter dock immediately (or on save), department bulk toggles work, JWT-guarded (401 if unauthenticated).

### TCH-E — Security hardening (JWT isolation audit)
- Audit every new endpoint added in TCH-A/B/C to confirm `tenant_id` is derived from JWT only, never from request body/query.
- Add negative tests: authenticated user with tenant A JWT attempts to PATCH tenant B settings → 403.
- Add cross-tenant read tests: user A can't GET `/api/tenants/{other_tenant_id}/settings`.
- Log `security_event` on any 403 (reuse existing pattern).

## Dependencies (must land before TCH starts)
- Pool Service PS-A/B/C/D (Predictive Maintenance surfaces stable before we wire tenant thresholds into them)
- 18-employee hierarchical workforce (department field populated so TCH-D grouping is meaningful)

## Design forks to resolve inline
- **Where department grouping comes from**: 18-employee workforce brief adds `org_department` field. Confirm it lands before TCH-D. If it doesn't, TCH-D falls back to a flat toggle list.
- **Debounced save vs. explicit Save button**: pick based on UX consistency with rest of settings page. Note choice.
- **AI Live Dispatcher location**: grep — could be `backend/services/dispatch/` or under `scheduler/`. Note found path in commit.
