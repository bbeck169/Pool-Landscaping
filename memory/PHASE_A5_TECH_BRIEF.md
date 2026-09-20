# Phase A5 · Feb-2026 — Proactive Intelligence: Tech Smart Brief

## Scope shipped (backend only)
- `GET /api/jobs/{job_id}/smart-brief` — assigned tech OR
  `admin` / `super_admin` / `manager` roles; everyone else 403
  `insufficient_role_for_brief`. Cross-tenant reads return 404
  `job_not_found` (no existence disclosure).
- Response contract exactly as spec'd:
  * `customer` sub-doc (display_name, phone, address_line, coordinates)
  * `special_access` (gate_code, key_location, dog_on_property,
    dog_notes, other_notes) — keys ALWAYS present with `None` /
    `False` defaults when unconfigured
  * `last_visits[]` — top 3 completed service_reports DESC by
    `submitted_at`, each with tech display name + duration +
    canonical 6-key chemistry snapshot + attached per-visit note
  * `open_intelligence_alerts[]` — top 5 open alerts for the
    customer, DESC by `created_at`, `dismissed_at=None`
- Chemistry snapshot key normalization: internal
  `free_chlorine` → response `chlorine`,
  `calcium_hardness` → `hardness` (stable API surface).
- **A4 nit fix** — `POST /api/agreements/{id}/resend-renewal-email`
  now returns HTTP **404** `agreement_not_found` (was 200/{ok:false}).
  Inactive contracts return 400 `agreement_inactive`. Successful
  sends stay 200.

## Data-model audit
- **`gate_code`** — canonical, first-class field on
  `customers.gate_code` (grep-confirmed via `routers/jobs.py:710`,
  `routers/workstream_job_detail.py:122`).
- **`key_location`, `dog_on_property`, `dog_notes`, `access_notes`**
  — intake-form template fields declared in
  `templates_seed/seed_templates.py:100-103` but NOT persisted on
  the customer document today (production DB has 0 rows with
  these keys). The endpoint surfaces `customer.<field>` if the
  intake template ever writes them through; otherwise defaults
  (`None` / `False`) — never omitted from the response.
- **`other_notes`** — best-effort mapping: `customer.service_notes`
  → `customer.notes` → `None`.
- **Last visits** — `service_reports` collection (per A2 findings),
  joined to `jobs` via `job_id` for `service_type` / `duration_minutes`.
- **Per-visit note** — `service_reports.notes` (single string),
  attached to the visit under the tech who submitted it.

## Tests
- Backend: `backend/tests/test_tech_brief_a5.py`
  → **12 / 12 passed** (`pytest`, 5.95 s wall).
- Full backend combined (A1 + A2 + A3 + A4 + A5 + D6 migration +
  D6.2 sweep + Phase B super-timeline): **149 / 149 passed**.

## API surface
- `GET /api/jobs/{job_id}/smart-brief` — assigned tech / admin+.
- Total intelligence-related + tech-brief routes: **10**.

## Follow-ups
- Mobile Smart Brief UI — delegate to `e1_expo_frontend_dev`.
  Endpoint contract is fully documented in the module docstring.
- If tenants want a first-class `dog_on_property` / `key_location`
  storage slot on `customers`, that's a separate schema-migration
  ticket (P2). Today the endpoint is forward-compatible — the
  moment those fields land on the customer doc the response
  populates them without any code change.
