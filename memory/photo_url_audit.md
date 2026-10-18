# TD-76 · Photo URL Audit — Phase 1 (Feb-2026)

**Status**: AUDIT ONLY. No code changes yet. Awaiting operator approval of the Phase 2 root-cause diagnosis before any refactor.

**Operator ground-truth sample URL** (prod, reported broken):
```
https://app.plofv.com/api/public/service/aa49a63a-3ca2-4664-835a-4dda4985a204/photo/7545b286-8e66-41cc-be88-fceb1ca41131
```
Live `curl` result (both envs):
- **Prod** `app.plofv.com` → HTTP 404 `{"detail":"Storage path missing"}`
- **Preview** `poolscape-audit.preview.emergentagent.com` → HTTP 404 `{"detail":"Not found"}` (preview DB does not have that `public_uuid`; prod does, and the photo row is present but missing its `storage_path` field)

The prod 404 message is the key signal — the SR photo subdoc exists but has no `storage_path`, so the Phase-27 streaming handler bails before reading S3.

---

## 1 · Call-site inventory — URL CONSTRUCTION (where the URL is emitted)

### Backend emission sites

| # | File · Line | Surface | URL template | Origin | Auth model | Fallback cascade? | Notes |
|---|---|---|---|---|---|---|---|
| B1 | `backend/services/customer_media.py:215` | Portal `/api/portal/photos` (jobs.photos branch) | **raw** `p.get("url") or p.get("storage_path") or ""` | Whatever was stored on the subdoc at upload time | None applied | **No** | Tech-uploaded photos. Field is a free-for-all; may be absolute URL, relative API path, raw S3 key, raw storage path, data URI, or empty. |
| B2 | `backend/services/customer_media.py:269` | Portal `/api/portal/photos` (estimates.photos branch) | **raw** same chain | Same | None | **No** | Estimate attachments. |
| B3 | `backend/services/customer_media.py:317` | Portal `/api/portal/photos` (service_reports.photos branch) | `/api/public/service/<public_uuid>/photo/<pid>` IF `r.public_uuid` else raw `p.url` | Composed server-side when `public_uuid` present | Public (no auth) | **No** | Only this branch composes a canonical URL — but even it 404s when the photo subdoc has no `storage_path` (operator's sample). |
| B4 | `backend/services/customer_media.py:358` | Portal `/api/portal/photos` (files branch) | `/api/files/<file_id>/download` | Composed | Bearer + `?auth=` fallback (per `routers/files.py`) | n/a | Admin-linked uploads. Distinct endpoint. |
| B5 | `backend/routers/service_report_media.py:215` | Upload-time persistence on `service_reports.photos[].url` | `/api/public/service/<public_uuid>/photo/<media_id>` IF `public_uuid` else `""` | Composed at upload, **stored** on the subdoc | Public (no auth) | **No** | Only the Phase-27 upload path writes this URL + a `storage_path`. Any photo that reached `service_reports.photos[]` by any OTHER path (e.g., tech-upload mirror, legacy import) does NOT have this URL stored, and more critically does NOT have `storage_path` → public SR streaming handler 404s. |
| B6 | `backend/routers/workstream.py:359` (`_photo_thumb`) | Workstream `_media_summary` (admin list) | `/api/public/job-photo/<jid>/<pid>` | Composed | Public (jid+pid magic pair) | **Yes — full cascade: jobs.photos → s3_key → base64 → SR fallback** | This is the canonical path for admin. Has the fallback rung Task L+P built. |
| B7 | `backend/routers/workstream.py:449-451` | Workstream `_media_summary` SR photos branch | `p.get("url")` first (if `_source=="sr"`) else `_photo_thumb(jid, pid)` | Mixed | Public | Falls back to B6 | SR photos: if the stored `url` (from B5) is set it's used; otherwise falls back to the robust `/api/public/job-photo/...` route. **This is why Workstream mostly works even when portal breaks.** |
| B8 | `backend/routers/workstream_service_log.py:119` | Service Log photo thumbs | `/api/public/job-photo/<jid>/<pid>` | Composed | Public | Yes (B6 cascade) | Mirrors Workstream admin. |
| B9 | `backend/routers/service_reports.py:3422` (`_build_customer_job_photos`) | Portal SR Detail (`/portal/service-reports/:id`) `job_photos` array | `<base>/api/customers/me/jobs/<jid>/photos/<pid>` | Composed from `_resolve_photo_url_base(request)` | Bearer header OR `?auth=` query | n/a — handler itself has S3+base64 cascade | TD-67 pattern. Authenticated-customer scoped. |
| B10 | `backend/routers/jobs.py:3054` (handler) | `/api/public/job-photo/<jid>/<pid>` streaming handler | n/a (serves bytes) | n/a | Public (jid+pid magic pair) | Yes — s3_key → base64 → SR fallback | Resilient. |
| B11 | `backend/routers/service_report_media.py:356` (handler) | `/api/public/service/<public_uuid>/photo/<pid>` streaming handler | n/a (serves bytes) | n/a | Public (public_uuid magic token) | **No — hard 404 if `storage_path` missing** | **Primary failure point for the operator's prod symptom.** |
| B12 | `backend/routers/service_reports.py:3443` (handler) | `/api/customers/me/jobs/<jid>/photos/<pid>` streaming handler | n/a (serves bytes) | n/a | Bearer header OR `?auth=` query (TD-67) | Yes — s3_key → base64 | Authenticated. |

### Frontend render sites

| # | File · Line | Surface | What goes into `<img src>` | Base URL | Token wrapping | Observed |
|---|---|---|---|---|---|---|
| F1 | `frontend/src/pages/portal/PortalPhotos.jsx:142` | **Portal `/portal/photos`** | `p.thumb || p.url` **raw**, no prefix, no token | None (relative resolves to current origin) | **None** | **Primary broken surface.** First few load because they correspond to the handful of SR photos that have `storage_path` populated; the rest 404 on B11. |
| F2 | `frontend/src/pages/portal/PortalPhotos.jsx:165` | Portal `/portal/photos` lightbox | `photo.url || photo.thumb` **raw** | None | None | Same breakage pattern. |
| F3 | `frontend/src/pages/portal/PortalServiceReports.jsx:1272` | Portal SR Detail job-photos grid | `withAuthToken(_raw, token)` on non-data URIs | None (relative) | `withAuthToken` **stamps `?token=`** — but B12 reads `?auth=` → **drift** | TD-67 was verified only via direct `curl ?auth=`; the FE wrapper never satisfies the handler. Loads only when Bearer header happens to attach (fetch, not `<img>`). |
| F4 | `frontend/src/pages/portal/PortalServiceReports.jsx:1307` | Portal SR Detail visit-photos grid | `p.url || p.data_url || p.data || p.thumb_url` **raw** | None | None | Breaks on URL-shape rows; works on inline data URIs. |
| F5 | `frontend/src/pages/portal/PortalServiceReports.jsx:1347` | Portal SR Detail lightbox (job photos branch) | `withAuthToken(_raw, token)` | None | `?token=` (drift from B12 `?auth=`) | Same as F3. |
| F6 | `frontend/src/pages/workstream/WorkstreamPage.jsx:134` | **Admin Workstream list** `MediaStrip` thumbs | `` `${BACKEND}${_thumbSrc(t.url)}` `` — prepends env `REACT_APP_BACKEND_URL`, appends `/thumb` only on `/api/public/job-photo/` URLs | `REACT_APP_BACKEND_URL` | None (urls are public) | Mostly works — B6 cascade is robust. |
| F7 | `frontend/src/pages/workstream/WorkstreamPage.jsx:186` | Admin Workstream lightbox photo | `` `${BACKEND}${preview.url}` `` | `REACT_APP_BACKEND_URL` | None (photos); `withAuthToken` on videos only | Mostly works. |
| F8 | `frontend/src/pages/workstream/WorkstreamPage.jsx:197` | Admin Workstream lightbox **video** | `withAuthToken(url, token)` (`?token=`) | `REACT_APP_BACKEND_URL` | `?token=` | Video endpoints don't require auth (`/api/media/videos/{path}` — public static), so `?token=` is harmless. |
| F9 | `frontend/src/pages/workstream/ServiceLogPage.jsx:174/200/352` | Service Log photo thumbs + lightbox | `withAuthToken(url, token)` | None | `?token=` | URLs are `/api/public/job-photo/` (public) so token is a no-op. Loads correctly. |
| F10 | `frontend/src/pages/jobs/JobDetail.jsx:1221,1254` | Admin JobDetail photo lightbox | `(job.photos[i] || {}).url || ...` raw chain | None | None | Internal admin; relies on `url` being a working absolute or `/api/public/job-photo/...`. |

**Note on `withAuthToken`:** docstring (`lib/urlToken.js:1-29`) names the param `token` because it was built for TD-66, which solved a different problem (S3 presigned-redirect double-`?` concat for a `?token=` scheme). It stamps `?token=`, NOT `?auth=`. The TD-67 streaming handler at B12 reads `?auth=`. The two never meet in the browser — this is a latent, previously-hidden bug.

---

## 2 · Backend streaming-endpoint reference

| Endpoint | File · Line | Auth guard | Fallback ladder | Tenant scoped? | Notes |
|---|---|---|---|---|---|
| `GET /api/public/job-photo/{jid}/{pid}` | `routers/jobs.py:3054` | Public (jid+pid magic pair) | 1. `jobs.photos[]` match → S3 (`s3_key`) HEAD-check → presigned 302. 2. S3 miss → base64 (`p.data`). 3. Neither → SR fallback via `_find_sr_photo_by_job_and_id` + `_serve_sr_photo`. | No (jid acts as token) | **Most resilient**. Used by admin Workstream, Service Log, email bodies, door-hangers. |
| `GET /api/public/job-photo/{jid}/{pid}/thumb` | `routers/jobs.py:3376` | Same as parent | Same cascade with thumb-sized output | No | Used by Workstream grid thumbs. |
| `GET /api/public/job-photo/{jid}/{pid}/preview` | `routers/jobs.py:3381` | Same | Same, preview size | No | |
| `GET /api/public/service/{public_uuid}/photo/{photo_id}` | `routers/service_report_media.py:356` | Public (public_uuid magic token) | **None**. Finds photo by id → requires `storage_path` present → reads from object storage. Hard 404 when `storage_path` missing. | No (public_uuid acts as token) | **Primary failure point.** Used by `/api/portal/photos` (B3) for every SR photo. |
| `GET /api/public/service/{public_uuid}/video/{video_id}` | `routers/service_report_media.py` ~ | Public | Same hard-404 shape | No | Portal videos. |
| `GET /api/customers/me/jobs/{jid}/photos/{photo_id}` | `routers/service_reports.py:3443` | Bearer header OR `?auth=<token>` query | S3 (`s3_key`) → embedded base64 (`data` / `data_url` / `preview` / `thumb`) | Yes (user.tenant_id + customer.customer_id match) | TD-67. Reads `?auth=`, **not** `?token=`. |
| `GET /api/files/{file_id}/download` | `routers/files.py:188` | Bearer OR `?auth=<token>` | Via `_resolve_bearer_or_query_auth` | Yes | For admin-linked `files` collection. |
| `GET /api/customers/me/jobs/{jid}/videos/{vid}` | `routers/service_reports.py` ~ | TD-67 pattern | | Yes | Twin of B12 for videos. |
| `GET /api/media/videos/{path:path}` | `routers/*` | Public static | n/a | No | Workstream + Service Log videos. |

---

## 3 · Mobile cross-reference (READ-ONLY per guardrail)

`/app/mobile/` was NOT inspected for edit candidates. A shallow grep hit shows mobile has its own photo renderers (`mobile/app/...`) that likely compose their own URLs — same shape drift presumably applies, but mobile parity is explicitly deferred.

---

## 4 · Observed-failure matrix

| Surface | URL shape produced | Backend handler called | Expected outcome | Actual outcome (prod) |
|---|---|---|---|---|
| Portal `/portal/photos` SR photo WITH `storage_path` | `/api/public/service/<pub>/photo/<pid>` | B11 | 200 image bytes | 200 ✅ (the "first 2") |
| Portal `/portal/photos` SR photo WITHOUT `storage_path` | `/api/public/service/<pub>/photo/<pid>` | B11 | 200 (expected) | **404 "Storage path missing"** ❌ |
| Portal `/portal/photos` jobs.photos entry | raw `p.url` or `p.storage_path` (free-form) | n/a — URL does not route to a real endpoint | 200 | **broken `<img>`** (relative to origin resolves to nothing) ❌ |
| Portal `/portal/photos` legacy mirrored SR photo | raw `p.url` (not Phase-27 shape) | n/a | 200 | **broken `<img>`** ❌ |
| Portal SR Detail job-photo grid | `/api/customers/me/jobs/.../photos/...?token=<jwt>` | B12 reads `?auth=` only | 200 | **401 "not_authenticated"** on `<img>` loads ❌ (works for authenticated `fetch` because Bearer header lands) |
| Admin Workstream list | `/api/public/job-photo/<jid>/<pid>/thumb` | B6 handler cascade | 200 | 200 ✅ (mostly) |
| Admin Workstream list — tech-upload photo with stale/missing `s3_key` | same | B6 falls through to base64 | 200 | 200 ✅ if base64 present; **404 "photo_not_found"** when both missing (orphan rows exist per `[p35] photo not found` log sentinel) |
| Admin Service Log photos | `/api/public/job-photo/<jid>/<pid>` | B6 cascade | 200 | 200 ✅ |

---

## 5 · ROOT CAUSE HYPOTHESIS

The operator's symptom ("only the first two thumbnails load on `/portal/photos`") is **not** one bug — it is **three overlapping issues**, in order of impact:

### 🔴 Primary (accounts for 90%+ of the breakage)

**Portal `/portal/photos` emits URLs pointing at a backend handler that has NO fallback cascade, while the equivalent admin surface uses a sibling handler that DOES.**

- Portal path: `/api/public/service/<public_uuid>/photo/<pid>` → `stream_public_service_photo` (B11) → **hard 404 on `storage_path` missing**.
- Admin path: `/api/public/job-photo/<jid>/<pid>[/thumb]` → `public_job_photo` (B6+B10) → **S3 → base64 → SR fallback cascade**.

Operator's prod sample proves this: the SR + photo IDs exist in prod DB, but the subdoc has no `storage_path` field (likely a legacy/imported/mirrored row), and B11 refuses to serve it. The admin cascade would have found the bytes via the SR fallback rung or base64.

The "first 2 work" pattern maps cleanly to: only the most-recent 2 SRs were uploaded through the Phase-27 route (`POST /service-reports/{id}/media`), which is the only path that writes a `storage_path`. Everything older or mirrored from `jobs.photos[]` is a dead URL on the portal.

### 🟡 Secondary (contributes to the long tail)

**`customer_media.get_customer_media` emits raw `url || storage_path` passthrough for the `jobs.photos[]` and `estimates.photos[]` branches (B1, B2).** These fields can be anything — absolute URLs, relative API paths, raw S3 keys, raw storage paths, data URIs, or empty. Any shape that is not a resolvable HTTP path from the browser's origin produces a broken `<img>`.

### 🟡 Latent (hidden since TD-67; not yet operator-reported)

**`withAuthToken` stamps `?token=`; TD-67 handler reads `?auth=`.** This means the Portal SR Detail `<img src>` loads (F3, F5) never satisfy the TD-67 handler via query-param fallback. They load only when the browser happens to attach the Bearer header, which does not happen for `<img>` elements. This surface likely has broken thumbnails too, just not yet reported — the operator may have only noticed on `/portal/photos` because that's where the volume is.

---

## 6 · PROPOSED FIX SPACE

The scope lives on a spectrum. Three options for the operator to choose from:

### Option A — Minimal targeted patch (one commit, ~2 files)
Change `customer_media.get_customer_media` so the **service_report photos branch emits `/api/public/job-photo/<job_id>/<photo_id>` instead of `/api/public/service/<public_uuid>/photo/<photo_id>`** when a `job_id` is available. The job-photo endpoint has the full fallback cascade (including SR fallback), so this single swap recovers 90%+ of the broken thumbs with zero FE changes and zero schema migration.
- **Pro**: tiny, atomic, operator can verify with one curl + one screenshot.
- **Con**: still relies on the `jobs.photos[].url` free-form branches (B1, B2) which remain fragile. Does not fix the `withAuthToken` ↔ `?auth=` drift.

### Option B — Shared helper (two commits)
A. Fix `withAuthToken` (or add a sibling `withImgSrcAuth`) that stamps `?auth=` to match the TD-67 handler contract. B. The Option-A swap above. Also fold in TD-76's Portal Photos grouped-layout UI change.
- **Pro**: closes the latent SR Detail bug too. Modest scope.
- **Con**: still doesn't touch the `jobs.photos[].url` free-form passthrough; the long tail of truly orphan `jobs.photos[]` rows still render broken.

### Option C — Full canonicalization (3–4 commits, as the operator originally scoped)
Backend emits a unified `{id, job_id, taken_at, thumb_url, full_url}` object shape with URLs already resolved and tenant-scoped. FE loses all composition logic. Also fixes `withAuthToken`/`?auth=` drift and ships Portal Photos grouped layout.
- **Pro**: Permanent. Consistent across every surface. Future-proofs the long tail.
- **Con**: Touches 5+ surfaces + schema + migration risk + requires more exhaustive test coverage.

---

## 7 · RECOMMENDATION

Based on the evidence, **Option A is the minimum fix that actually resolves the operator-reported symptom**, and **Option B is the right fix** because it costs almost no additional complexity (one helper tweak) but closes the latent SR Detail breakage before it becomes the next ticket.

**Option C is justified only if** the operator wants the schema normalization for its own sake — e.g., to simplify FE forever, or to decommission one of the overlapping public endpoints. The operator-reported symptom does not require Option C.

**Portal Photos grouped layout** (the fold-in from the original TD-76 scope) is UI-only and can ride on either A, B, or C — it's a separate FE commit regardless.

---

## 8 · WHAT I NEED FROM THE OPERATOR

1. **Pick A / B / C** (or combine).
2. If B or C: confirm the helper split — do you want me to (i) change `withAuthToken` in place to stamp `?auth=` (small blast radius; all current call-sites are either TD-67 handlers or public endpoints that ignore the param), or (ii) add a sibling `withImgSrcAuth` and migrate call-sites one at a time?
3. Confirm I should fold the Portal Photos grouped-layout UI into the chosen fix (yes/no).
4. Any objection to the Option-A single-line swap in `customer_media.py` (SR branch → `/api/public/job-photo/` instead of `/api/public/service/`)?
