# FEATURE — Customer Service-Reports · photos merge + search/filters/pagination

**Phase:** Web · Preview only  
**Scope:** Backend (list + detail + streaming route) · Frontend (portal list page + detail viewer) · Tests · Docs  
**Feb-2026 · Post-tester follow-up patch (this document reflects the current state):** absolute URL on `job_photos[i].url`, S3 read fallback wired to the `services.aws_s3.photos.read_object` helper (not the historical broken `get_object` symbol), `thumb` field omitted when absent (no longer emitted as empty string), and a second seeded customer login for the wrong-customer 403 branch verification.  
**Out of scope:** Mobile Expo parity (delegated to `e1_expo_frontend_dev`) · Any tech-side endpoint change · Any `/api/files/{id}/download` auth change.

## Summary

The customer portal's service-reports surface got two upgrades:

1. **Detail response** — the report doc's job now contributes its own separate `job_photos: [...]` array. Tech-attached photos keep their existing home under `sr.photos`; job-attached photos never leak into that list and never bypass ownership checks. URLs are **absolute** (`APP_PUBLIC_URL` prefix, falling back to `request.base_url`) + token-scoped and hit a new customer-session streaming route.
2. **List response** — the endpoint accepts `page`, `page_size` (max 100), `q`, `service_type`, `from`, `to`. Response shape: `{items, page, page_size, total, total_pages}`. Hard 200-cap dropped. `q` performs a case-insensitive substring match over `service_reports.notes`/`customer_notes` plus `jobs.customer_name`/`jobs.address`.

## Backend changes

### `backend/routers/service_reports.py`

- `GET /api/customers/me/service-reports` — rewritten (line ~2217). Adds `page`, `page_size`, `q`, `service_type`, `from`, `to` query params. Two-stage filter:
  - Stage 1 — enumerate customer-owned jobs. Optionally narrow via `service_type` (matches both new `service_type` and legacy `job_type` fields). Also collect matching `job_ids` for the substring search over `customer_name`/`address`.
  - Stage 2 — query `service_reports` for `job_id in [...]`, submitted, with optional date range on `submitted_at` (upper bound padded to end-of-day). Substring search added as an `$or` clause over `notes` + `customer_notes` + `job_id in matched_job_ids`.
  - Response shape: `{items, page, page_size, total, total_pages}`. Empty-total short-circuit stays.
- `GET /api/customers/me/service-reports/{report_id}` — appends `job_photos = _build_customer_job_photos(job, base_url)` where `base_url` comes from a local `_resolve_photo_url_base(request)` helper (mirrors `routers/estimate_viewer._resolve_url_base`: `APP_PUBLIC_URL` env → `request.base_url` fallback → empty string). Tech-attached photos remain under `photos`.
- **New helper** `_build_customer_job_photos(job, base_url="")` — filters soft-deleted entries, emits `{id, caption, created_at, uploader_role, url}` and optionally `{thumb}`. Behaviour details:
  - `url` — **absolute** token-scoped streaming URL when `base_url` is non-empty (`{base_url}/api/customers/me/jobs/{jid}/photos/{pid}`); relative when the resolver returned empty.
  - `thumb` — **omitted entirely** when the underlying `photos[]` entry has no `thumb` data-URI. Rationale: the admin `POST /api/jobs/{jid}/photos` upload path does not run server-side thumbnail generation (it's a larger cross-cutting change tracked separately), so pre-fix consumers were receiving empty strings and rendering broken `<img>` tags. **Server-side thumbnail generation on the admin upload path is deferred**; today only photos taken through the tech app carry a `thumb`.
- **New helper** `_resolve_photo_url_base(request)` — imported inside the function (uses `import os as _os_env` to avoid shadowing the module-level `import os as _os` at line 1781 of the same file).
- **New route** `GET /api/customers/me/jobs/{jid}/photos/{photo_id}` — customer-session only:
  - Anon → 401 `customer_only`
  - Wrong-customer session → 403 `not_your_job`
  - Missing photo → 404 · Soft-deleted → 410 · No storage backing → 503
  - **S3 branch** — prefers `services/aws_s3/photos.read_object(s3_key)` (new helper, added to that module — see below). Per the module contract, `read_object` never raises and returns `None` when S3 is disabled / misconfigured / the read failed. When it returns `None`, the endpoint **falls through to the embedded-base64 branch** instead of emitting a 502. `Cache-Control: private, no-store` on all responses.
  - **Pre-fix bug (Feb-2026 post-tester patch)** — the endpoint originally imported the non-existent `services.aws_s3.photos.get_object` symbol, which raised `ImportError` on every live request, caught by the `try/except` and re-raised as a 502 `storage_read_failed`. That import path is gone, replaced by `read_object`. The historical 502 detail string is gone from the router source; a pytest regression check locks the invariant.

### `backend/services/aws_s3/photos.py`

- **New helper** `read_object(s3_key: str) -> Optional[bytes]` — wraps `boto3 get_object`, returns the raw bytes on success, `None` on disabled/misconfigured/failure. Mirrors the rest of the module's "never raises, return-value carries status" contract. This is the symbol the router now uses.

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
- **`job_photos[i].url` is absolute** (starts with `http://` or `https://`) and contains `/api/customers/me/jobs/`.
- `thumb` is either absent or a non-empty string — never an empty string.
- Anon → 401 · **wrong-customer session → 403** (via the new `customer2@aquaterra.com` fixture).
- Correct customer streams the photo (200 · image bytes) via the live-pod happy-path test.
- **Regression: `services.aws_s3.photos.read_object` exists, `get_object` does NOT, and the router source no longer emits `storage_read_failed` (502).** Locks the tester-reported bug so a future edit doesn't silently regress.
- List endpoint accepts `page`/`page_size`, returns the paginated envelope, respects `page_size` up to 100.
- `q` matches case-insensitive substrings across `notes`, customer name, and address.
- 200-cap gone (`page=1&page_size=100`, `page=2&page_size=50`).

## Second-customer fixture

**`seed_demo_second_customer()`** in `backend/seed.py` — new idempotent helper. Wired into `backend/server.py` (runs unconditionally at boot, mirroring `seed_demo_manager`'s posture — no `_SEED_DEMO_DATA` gate needed since the helper is a no-op when the anchor customer row is missing). Invariant:

```
customer2@aquaterra.com  ⇒  users row with role="customer",
                            linked to customers[1] (Robert Blake) via
                            customer_id (distinct from customer@aquaterra.com),
                            password_hash = hash("password123").
customers[1].email == "customer2@aquaterra.com"
customers[1].has_login == True
```

Automated login verified: `POST /api/auth/login` with `{email: "customer2@aquaterra.com", password: "password123"}` returns a valid access token, `role: "customer"`, and a `customer_id` that is different from `customer@aquaterra.com`'s.

Documented in `/app/memory/test_credentials.md` under the Accounts block.

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

- **Backend pytest** — `test_customer_service_reports_enhancements.py` (9 passed, 0 skipped after the follow-up patch — includes the new `_regression` + `_happy_path_not_502` + `_wrong_customer_403` tests), `test_public_quote_attachments.py`, `test_portal_service_report_customer_view.py` — all green.
- **Frontend Vitest** — `portal-service-reports-enhancements.test.jsx` (6 passed) + `multi-body-water.test.jsx` (14 passed, previously 1 timeout — fixed).
- **Live-pod smoke** — customer photo stream endpoint returns `HTTP 200 · image/png · 70 bytes` on the seeded aquaterra tenant (previously 502).

## Files touched

- `backend/routers/service_reports.py`
- `backend/services/aws_s3/photos.py` (new `read_object` helper)
- `backend/seed.py` (new `seed_demo_second_customer` idempotent helper)
- `backend/server.py` (wires the second-customer seed on every boot)
- `backend/tests/test_customer_service_reports_enhancements.py`
- `backend/tests/test_portal_service_reports_tech_name_resolution.py` (paginated envelope update)
- `frontend/src/pages/portal/PortalServiceReports.jsx`
- `frontend/src/test/portal-service-reports-enhancements.test.jsx` (new)
- `frontend/src/test/multi-body-water.test.jsx` (regression fix)
- `memory/FEATURE_CUSTOMER_SERVICE_REPORTS_ENHANCEMENTS.md` (this doc)
- `memory/test_credentials.md` (documented the `customer2@aquaterra.com` fixture)
