# Phase 18 · Chemical Cost Report + Per-Tech Inventory + Low-Stock Notifications — Deliverables

**Executed**: 2026-08-08 (immediately after the Phase 8 webform-bug follow-up).

## User-locked decisions (2026-08-01)

- **1a** — Investigation first (report micro-report delivered before code).
- **2c** — SKU default reorder_point with per-tech override capability.
- **3d** — Notify via In-app + Email + Slack (all three channels).
- **4c** — Real-time decrement hook + daily cron scan, honour quiet hours.
- **5ab** — Same SKU system tenant-wide; reports split by department
  (`pool` / `landscape` / `both`); `department` field added to both
  `users` and `inventory_items`.
- **6a** — Auto-seed the 8 core chemicals per tenant, idempotent.
- **Cost visibility** — Admin / Super Admin / Manager (owner) only. Techs
  can see quantities in mobile "My Inventory" but NEVER cost figures.

## What ships in this phase

### Backend
| File | Type | Purpose |
|---|---|---|
| `backend/services/inventory_alerts.py` | NEW (~355 lines) | Seed catalog + threshold logic + real-time & cron fan-out |
| `backend/routers/inventory_reports.py` | NEW (~385 lines) | Cost report + mobile my-inventory + department admin + alert settings |
| `backend/routers/inventory.py` | edit | Real-time hook injected into `decrement_from_service_report()` |
| `backend/services/notifications.py` | edit | `inventory_low_stock` kind + push-default-on for admins |
| `backend/server.py` | edit | Router mount + `inventory_low_stock_daily` cron + boot seed step |
| `backend/tests/test_phase18_chemical_report.py` | NEW (~340 lines) | 8 pytest cases · all passing |

### Frontend
| File | Type | Purpose |
|---|---|---|
| `frontend/src/pages/inventory/ChemicalCostReport.jsx` | NEW | Admin+ cost report UI |
| `frontend/src/pages/inventory/InventoryPages.jsx` | edit | "Cost Report" button on inventory header |
| `frontend/src/App.js` | edit | Route + import for the cost report page |

### Mobile (Expo)
| File | Type | Purpose |
|---|---|---|
| `mobile/app/(app)/inventory/my-inventory.tsx` | NEW | Tech-facing read-only on-hand list with LOW/OUT badges + personal usage panel (NO cost data) |

## API endpoints

- `GET  /api/reports/chemical-costs` — **Admin+** (technician / customer → 403)
- `GET  /api/inventory/my-inventory` — any non-customer role (cost fields stripped at projection)
- `PUT  /api/admin/users/{uid}/department` — Admin+
- `PUT  /api/admin/inventory/{iid}/department` — Admin+
- `POST /api/admin/suggest-departments` — Admin+ (read-only inference)
- `GET/PUT /api/admin/inventory-alert-settings` — Admin+ (webhook masked in GET)

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `INVENTORY_CRON_HOUR_UTC` | `6` | Daily low-stock scan hour |
| `INVENTORY_SLACK_WEBHOOK_URL` | *(unset)* | Global fallback webhook when tenant hasn't configured its own |

## Data model additions

- `inventory_items` gains three optional fields (all nullable, no migration):
  - `is_seeded_chemical: bool`
  - `department: "pool"|"landscape"|"both"|None`
  - `low_stock_notified_at: iso-string|None` (24-hour dedup window)
- `users` gains an optional `department: "pool_tech"|"landscape_tech"|"both"|None`.
- New collection `inventory_alert_settings` (per-tenant slack_webhook_url + quiet_hours_utc).
- New collection `inventory_alert_events` (audit rows for every fan-out).

## Cost math source of truth

Every row shown in the cost report comes from:

```
SUM(quantity_used * unit_cost_at_time_cents) over chemical_usage_events
```

Values are snapshot-priced at the moment of service-report submit by
`chemical_products.snapshot_chemical_usage()`. Historical margin math is
therefore immune to retroactive price edits in the pricebook.

## Verification

- **Pytest**: 8/8 Phase 18 + 4/4 webform-bugfix regression = **12/12 pass**.
- **Curl matrix** — 7/7 scenarios return expected status codes.
- **Screenshot**: `phase18_cost_report.png` — Aquaterra tenant, 30-day window:
  $332.75 spend, 44 events, 64.5 units, department + tech + product breakdowns rendered.
- **Grep-lint**: 0 `db.invoices` writes in any Phase 18 file.

## Follow-ups / not in this pass

- Admin bulk-apply modal for `/admin/suggest-departments` (endpoint exists,
  UI-side left for a lighter follow-up pass).
- Full mobile inventory alerts screen (Expo push notification tap-through
  route). The bell/email/Slack channels are live; Expo push is opt-in via
  the existing preferences UI.
- Historical department backfill (intentionally deferred per user's
  "no bulk migration" decision).

## Prior 2026-08-08 delivery

Same date, earlier commit: webform bug follow-up (Cloudflare Worker
Origin-rewrite) — the fix that unblocked Phase 18 execution.
