# FEATURE — Customer Service-Reports · photos merge + search/filters/pagination

**Phase:** Web · Preview only  
**Scope:** Backend (list + detail + streaming route) · Frontend (portal list page + detail viewer) · Tests · Docs  
**Out of scope:** Mobile Expo parity (delegated to `e1_expo_frontend_dev`) · Any tech-side endpoint change · Any `/api/files/{id}/download` auth change.

## Summary

The customer portal's service-reports surface got two upgrades:

1. **Detail response** — the report doc's job now contributes its own separate `job_photos: [...]` array. Tech-attached photos keep their existing home under `sr.photos`; job-attached photos never leak into that list and never bypass ownership checks. URLs are absolute + token-scoped and hit a new customer-session streaming route.
2. **List response** — the endpoint accepts `page`, `page_size` (max 100), `q`, `service_type`, `from`, `to`. Response shape: `{items, page, page_size, total, total_pages}`. Hard 200-cap dropped. `q` performs a case-insensitive substring match over `service_reports.notes`/`customer_notes` plus `jobs.customer_name`/`jobs.address`.

## Backend changes

### `backend/routers/service_reports.py`

- `GET /api/customers/me/service-reports` — rewritten (line ~2217). Adds `page`, `page_size`, `q`, `service_type`, `from`, `to` query params. Two-stage filter:
  - Stage 1 — enumerate customer-owned jobs. Optionally narrow via `service_type` (matches both new `service_type` and legacy `job_type` fields). Also collect matching `job_ids` for the substring search over `customer_name`/`address`.
  - Stage 2 — query `service_reports` for `job_id in [...]`, submitted, with optional date range on `submitted_at` (upper bound padded to end-of-day). Substring search added as an `$or` clause over `notes` + `customer_notes` + `job_id in matched_job_ids`.
  - Response shape: `{items, page, page_size, total, total_pages}`. Empty-total short-circuit stays.
- `GET /api/customers/me/service-reports/{report_id}` — appends `job_photos = _build_customer_job_photos(job)`. Tech-attached photos remain under `photos`.
- **New helper** `_build_customer_job_photos(job)` — filters soft-deleted entries, emits `{id, caption, created_at, uploader_role, thumb, url}`. `thumb` is a data-URI (renders inline, no handshake). `url` points at the new token-scoped stream route below.
- **New route** `GET /api/customers/me/jobs/{jid}/photos/{photo_id}` — customer-session only:
  - Anon → 401 `customer_only`
  - Wrong-customer session → 403 `not_your_job`
  - Missing photo → 404 · Soft-deleted → 410 · S3 failure → 502 · No storage backing → 503
  - Prefers S3 stream via `services/aws_s3/photos.get_object`; falls back to embedded base64 when `s3_key` is not set. `Cache-Control: private, no-store` on all responses.

### OpenAPI paths

- Baseline: 1735
- After this change: **1736** (delta +1 for the new customer photo-stream route)

## Frontend changes

### `frontend/src/pages/portal/PortalServiceReports.jsx`

**List (`PortalServiceReports`)**
- New state: `q`, `qDebounced` (300ms), `serviceType`, `fromDate`, `toDate`, `total`, `page`, `pageSize`, `totalPages`.
- URL-synced query params on every filter change.
- Filter bar (`data-testid="sr-list-filters"`) with:
  - `sr-list-search` — search input, 300ms debounced.
  - `sr-list-filter-service-type` — service-type text input.
  - `sr-list-filter-from` / `sr-list-filter-to` — date range inputs.
  - Stacked at `< sm`, 4-col grid at `≥ sm`.
- Pagination row (`data-testid="sr-list-pagination"`):
  - `sr-list-pagination-prev`, `sr-list-pagination-next` — buttons, disabled at edges, 40px min touch height.
  - `sr-list-page-indicator` — `Page N of M (T total)`.
  - Only rendered when `total > pageSize`.
- Row sentinel — hidden `sr-list-row-<i>` marker inside each visible card so testers can resolve rows by position without breaking the existing `portal-service-report-card-<id>` targeting.
- Defensive branch — still handles the legacy array shape from the old contract so a fork run against a pre-cutover backend doesn't blank the page.
- `useEffect` resets `page` to 1 whenever a filter changes.

**Detail (`PortalServiceReportDetail`)**
- Reads `sr.job_photos` and renders a dedicated section:
  - `data-testid="service-report-job-photos-section"` with heading "Job Photos".
  - Grid: 1 col at `< sm`, 2 col at `≥ sm`, 3 col at `≥ md`.
  - Each thumbnail uses `data-testid="service-report-job-photo-<i>"` and renders the compact `thumb` data-URI.
  - Tech-attached photos still render below under the classic "Visit photos" section, unchanged.

## Tests

### Backend — `backend/tests/test_customer_service_reports_enhancements.py`

Covers:
- Detail response emits `job_photos` as a separate array (does not merge into `photos`).
- Anon → 401 · wrong-customer session → 403 on the streaming route.
- Correct customer streams the photo (200 · image bytes).
- List endpoint accepts `page`/`page_size`, returns the paginated envelope, respects `page_size` up to 100.
- `q` matches case-insensitive substrings across `notes`, customer name, and address.
- `service_type` filter honors both new and legacy fields.
- `from`/`to` date range is inclusive at both ends.
- 200-cap is gone (`page=1&page_size=100`, `page=2&page_size=50`).

### Frontend — `frontend/src/test/portal-service-reports-enhancements.test.jsx`

Covers:
- Filter bar + pagination controls render with the correct testids.
- Search input debounces 300ms before firing the request.
- Filter change resets `page` to 1.
- URL params reflect current filter state.
- `job_photos` renders under the new section on the detail view.
- Existing `sr.photos` section stays intact when both arrays are populated.

### Regression fix — `frontend/src/test/multi-body-water.test.jsx`

The list-endpoint mock was still using strict `path === "/customers/me/service-reports"` matching + returning a bare array. Updated to:
- Match via `startsWith` (the URL now carries `?page=...` query params).
- Return the paginated `{items, page, page_size, total, total_pages}` envelope.
- Preserved the single `path === /.../{id}` guard by tightening the regex to `[^?]` after the trailing slash so the list branch keeps priority.

Result: 14/14 `multi-body-water` tests green.

## Acceptance

1. ✅ `job_photos` present on the detail response.
2. ✅ Photo URLs absolute + token-scoped; anon → 401; wrong-token → 403.
3. ✅ List endpoint accepts new params and returns the paginated envelope.
4. ✅ Search matches case-insensitive substrings across the three fields.
5. ✅ 200-cap gone; `page=2&page_size=50` verified.
6. ✅ Existing suites green; new pytest + Vitest coverage added.

## Test-suite status

- **Backend pytest** — `test_customer_service_reports_enhancements.py`, `test_public_quote_attachments.py`, `test_portal_service_report_customer_view.py` all green (10 passed, 1 skipped).
- **Frontend Vitest** — `portal-service-reports-enhancements.test.jsx` (6 passed) + `multi-body-water.test.jsx` (14 passed, previously 1 timeout — fixed).

## Files touched

- `backend/routers/service_reports.py`
- `backend/tests/test_customer_service_reports_enhancements.py` (new)
- `frontend/src/pages/portal/PortalServiceReports.jsx`
- `frontend/src/test/portal-service-reports-enhancements.test.jsx` (new)
- `frontend/src/test/multi-body-water.test.jsx` (regression fix)
- `memory/FEATURE_CUSTOMER_SERVICE_REPORTS_ENHANCEMENTS.md` (this doc)
