# Phase F4 · Feb-2026 — Widget-Embed Check-ins Map + Admin Moderation

## Delivered (Option A: extend existing `public_checkins` collection + `/api/widget.js` stack)

### Backend
- `services/coord_obfuscator.py` — deterministic ±0.001° jitter seeded by job_id.
- `services/public_checkin_enqueue.py` — auto-enqueues a `pending_review` row on job completion. `source='auto'`. Hooked from `routers/jobs.py:1617-1625`.
- `routers/public_checkins_map.py` —
  - `GET /api/public/checkins/{tenant_slug}/pins` → JSON, 60/min per-IP, allow-list projection (`lat, lng, service_type, completed_at_month_year, area_label`), zero PII.
  - `GET /api/public/checkins/{tenant_slug}/map.html` → Leaflet + OSM (CDN) + `<script type="application/ld+json">` LocalBusiness JSON-LD.
- `routers/moderation_public_checkins.py` — list endpoint returns new `source` discriminator so admin UI can show Auto vs Tech.

### Frontend
- `pages/admin/WidgetEmbedPage.jsx` — dual-preview tabs:
  - `data-testid=widget-embed-tab-list` (default) / `data-testid=widget-embed-tab-map`.
  - Card-list snippet (`<script>`) + map iframe snippet (`<iframe>`) each with its own Copy button (`widget-embed-copy` / `widget-embed-copy-map`).
  - Info banner in Map mode noting ±0.001° jitter + JSON-LD.
- `pages/admin/ModerationCheckinsPage.jsx` — source pill (Auto = blue #DBEAFE/#1E40AF, Tech = green #DCFCE7/#065F46) on every list row (`moderation-item-source-{id}`) and in the detail panel (`moderation-detail-source`).

### Bugs Found + Fixed During Testing
- **HIGH · index collision**: original enqueue wrote `source_checkin_id=None`, but `tenant_source_unique` was NOT sparse — so only ONE auto row could ever exist per tenant, and every subsequent completion was silently dropped as `duplicate_race`. Fix: derive `source_checkin_id = f"auto:{job_id}"` + log E11000 as WARN. Regression test: `tests/test_public_checkins_auto_enqueue_no_index_collision.py` (3 new cases).
- **LOW · copy silently no-oped in headless**: `_writeClipboard` didn't fall through to `execCommand` when the Clipboard API rejected — fixed to try modern API then always fall back.
- **LOW · map header chip overlapped Leaflet zoom control** — shifted `left: 8px → 52px` with ellipsis overflow.

### Tests
- **Backend F4**: 31/31 pass — `test_coord_obfuscator_deterministic.py` (7), `test_public_checkins_auto_enqueue_on_completion.py` (6), `test_public_checkins_source_field.py` (4), `test_widget_map_html_endpoint.py` (3), `test_widget_map_html_hides_pii.py` (2), `test_widget_map_html_only_approved.py` (4), `test_widget_map_pins_endpoint_rate_limit.py` (2), `test_public_checkins_auto_enqueue_no_index_collision.py` (3, new).
- **Backend testing_agent (iteration_24)**: 5/5 curl checks pass (pins allow-list, map.html schema, 404 for unknown slug, source field in moderation list, MR0 widget regression).
- **Frontend testing_agent (iteration_25)**: 6/6 Playwright flows pass (tabs, controls, copy buttons, map load, source badges on list + detail).

### Seeded Demo Data (aquaterra tenant)
- `demo-auto-59c68fa1` — "Weekly Pool Cleaning (F4 demo · auto)" · source=auto · state=pending_review
- `demo-tech-e176a553` — "Palm Tree Trim (F4 demo · tech)" · source=tech · state=pending_review
- `demo-approved-6e677c3d` — "Filter Cartridge Swap (F4 demo · approved)" · source=auto · state=approved (renders 1 pin on /pins and 1 card on /feed).

### Route
`/admin/moderation/widget-embed` (unchanged from prior phase).

## Tech Debt Logged (deferred per user scope constraint)
- TD-13 Split run_id from confirm_token (backend security nit).
- TD-14 Paginate `data_repair_history` (perf at scale).
- TD-15 Tenant-scope the data-repair scan (perf).
- TD-19 Move `find_one` into bg task in notification bundle (perf).
- **NEW · TD-F4-1**: `moderation_public_checkins` list returns full raw rows including `lat_raw`/`raw_address` — admin-only so acceptable, but consider explicit projection.
- **NEW · TD-F4-2**: `/pins` and `/map.html` share a 60/min per-IP bucket with the widget feed — an iframe embed + custom pins consumer on the same NAT IP would contend for one budget.
- **NEW · TD-F4-3**: Startup integrity check with `enforce=True` bricked the backend during testing on 9 orphan `LL-*` test jobs (customer_id='c-x'). Testing agent cleaned them up; consider degrading to CRITICAL log + health flag rather than exit(1).
- **NEW · TD-F4-4**: 12-month cutoff uses ISO-string $gte comparison; correct for +00:00/Z rows but would mis-sort rows stored with a non-UTC offset. Normalise on write.
