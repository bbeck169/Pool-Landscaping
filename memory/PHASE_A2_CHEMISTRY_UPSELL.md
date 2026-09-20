# Phase A2 · Feb-2026 — Proactive Intelligence: Chemistry Upsell scan

## Scope shipped
- New scan module `backend/services/intelligence/chemistry_upsell_scan.py`
  producing `chemistry_upsell` alerts when a customer's last three
  submitted `service_reports` have the SAME measurement out of the
  tenant's configured target band on the SAME side (all three high
  OR all three low).
- Emission is per `(customer, measurement)`, so a single trio with
  multiple out-of-band chemicals yields one alert per chemical.
- `alert_key = "chemistry_upsell:cust:{cid}:{measurement}:v{sha1_12}"`
  — window shift issues a new alert; rerun on same trio dedups.
- Recommendation lookup covers salt, ph, alkalinity, cyanuric_acid,
  calcium_hardness, free_chlorine (both directions). Unknown
  measurement configured on tenant targets falls back to
  `chemistry_review`.
- Manual trigger route:
  `POST /api/intelligence/scans/chemistry-upsell/run-now`
  (admin+super_admin gate; tech → 403 `insufficient_role_for_alerts`).
- APScheduler cron at 07:15 UTC daily, staggered 15 min behind the
  A1 missed-service scan.
- Frontend `IntelligenceAlerts` row for `category=chemistry_upsell`:
  - Reading sequence chip `4200 → 4400 → 4600 ppm (target 2700-3400 ppm)`
    (oldest → newest for left-to-right trend reading).
  - Blue **Create upsell quote** CTA that deep-links to
    `/quotes/new?customer_id=…&service_type=…&source=intelligence_alert&alert_id=…`.
- `QuoteInvoiceNew` now prefills a title + note when
  `source=intelligence_alert` is present in the URL (no server-side
  quote-from-alert endpoint — pure client prefill).

## Data model reused, not rebuilt
- Chemistry readings live on `service_reports.chemical_readings`
  (array of `{key, name, value, unit}`), joined to tenant + customer
  via `service_reports.job_id → jobs.tenant_id + customer_id`.
- Tenant target bands live at `tenants.settings.chemistry.targets.{key}`
  (already backfilled by the `tenant_chemistry_defaults_backfill`
  migration). The scan reads the RAW stored block and skips any
  measurement that isn't explicitly configured.

## Tests
- Backend: `backend/tests/test_chemistry_upsell_scan_a2.py`
  → **12 / 12 passed** (`pytest`, 5.7 s wall).
- Frontend: `frontend/src/pages/admin/__tests__/IntelligenceAlerts.chemistry.test.jsx`
  → **6 / 6 passed** (`vitest`, 0.9 s wall).
- Regression sweep across A1 backend + A1 alert-bell + header-cleanup
  + customer-full-timeline: **40 / 40 + 24 / 24 passed**.

## Deferred / follow-ups
- Quote form currently prefills `title` + `notes` from the alert
  source; line-item auto-attach + supplier / pricebook lookup for
  the `service_type` slug is future work if we want a one-click
  "quote → email" flow.
- `service_type` slug → catalog pricebook item mapping is
  intentionally NOT built (spec §4.2). Follow-up ticket if desired.

## API surface
- `POST /api/intelligence/scans/chemistry-upsell/run-now` — admin+.
- Total intelligence routes in OpenAPI: **6** (2 producers × scan
  + 4 alert CRUD).
