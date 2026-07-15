# Handoff — Phase 26 Wave A (Feb 15 2026)

## Aggregate
- **OpenAPI: 520 → 532 (+12 endpoints)**
- **Tests: 42/42 pass** across inventory, checks, property-lookup, and Wave A test suites (0 regressions).

## Module 26.1 — Route Auto-Dispatcher
- `POST /api/dispatch/auto-assign` — ranks active techs by min-distance-to-existing-stops + time_pressure_factor, assigns winner.
- `POST /api/dispatch/reassign` — manual override + writes `dispatch_audit` doc.
- `GET  /api/dispatch/preview` — same ranking, non-mutating.
- `GET/PUT /api/dispatch/settings` — persists `settings.dispatch.*` block.
- `settings.dispatch.auto_assign_on_create` (default False) — when True, `POST /api/jobs` auto-dispatches jobs missing `technician_id`.
- Tenant-isolated. Tech / customer / marketing all get 403.

## Module 26.2 — Weather-Triggered Auto-Reschedule
- `POST /api/dispatch/weather-scan` — scans today+tomorrow outdoor jobs against Open-Meteo forecast, produces `weather_reschedule_events`.
- Modes: `manual` (creates proposals; admin accepts/rejects) or `auto` (moves jobs + writes `auto_weather_rescheduled_at`).
- Idempotent (re-scanning skips already-proposed events).
- `GET /api/dispatch/weather-events?status=` · `POST .../accept` (optional `override_date`) · `POST .../reject`.
- APScheduler cron `weather_scan` runs daily 05:00 UTC across all tenants.
- Outdoor detection: `service_type` includes landscape/hardscape/D2D/exterior + excludes "pool interior" / "repair" / "warranty" / "diagnostic".
- Test hook: `settings.dispatch._test_forecast` dict override (documented as dev-only; not surfaced in UI).

## Module 26.3 — Batch Checks + Payroll CSV (Phase 24 extension)
- `POST /api/checks/batch` — atomic N-check creation. Idempotent by client-supplied `batch_id`. Fails fast on any unknown payee.
- `POST /api/checks/batch/{bid}/print` — 3-up business-check PDF (default) or 1-up single-check layout when `settings.checks.batch_layout == "1up"` (falls back to 3-up if no PdfWriter available). Same non-silent MICR + SAMPLE watermarking as single-check flow.
- `GET  /api/checks/payroll/template.csv` — sample CSV download.
- `POST /api/checks/payroll/import-csv?bank_account_id=&execute=` — CSV preview OR execute. Auto-creates missing payees with kind=`employee`. Row-level warnings (missing name, bad amount) block execute (422).
- All admin-only. Tech + customer 403.

## Frontend
### Web (admin only)
- `/admin/dispatch` — unassigned-jobs list, per-row auto-assign, bulk button, settings toggle.
- `/admin/dispatch/weather` — mode toggle, rain/wind thresholds, run scan, per-event accept/reject.
- `/admin/checks/batch/new` — multi-line check composer with total preview and one-click Print PDF.
- `/admin/checks/payroll` — CSV upload → preview table with row-level status pills → execute.
- Sidebar entries added: Batch Print, Payroll Import, Weather Reschedule, Auto-Dispatch.

### Mobile
- No mobile surfaces added for Wave A (all admin ops). Mobile Wave B queued.

## Third-party / integrations
- Open-Meteo (keyless) — used for weather forecast; no rate limit issues.
- Reportlab — reused for batch PDF; `pypdf`/`PyPDF2` used opportunistically for 1-up merge (graceful fallback to 3-up if neither is installed).

## Known TODOs / follow-ups
- Weather scan cron currently 05:00 UTC only; per-tenant local-time is a phase 26 polish task.
- Auto-dispatcher time-pressure weight (`TIME_PRESSURE_WEIGHT=500m/unit`) is tuned by hand; consider surfacing as `settings.dispatch.time_pressure_weight` once we have real dispatcher usage data.
- Batch print merge for 1-up layout requires `pypdf` (already installed for phase 24 tests? Verify before flipping the setting default).

## Wave B queued
Customer Sentiment · Content Refresh · Photo Chemical Dosing.

## Wave C queued
Warranty Portal.
