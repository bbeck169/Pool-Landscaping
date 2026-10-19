# TD-88 · Mobile-uploaded landscaping checklist photos broken on web · audit

**Date:** 2026-02-19
**Env:** PREVIEW (dev)
**Scope:** operator-reported bugs ahead of production deployment: (1) mobile-uploaded checklist photos on landscaping jobs render as broken on web; (2) file-picker on the upload surface does not allow multi-select.
**Phase:** AUDIT ONLY. Awaiting operator approval of the proposed ship plan before any fix code.

---

## 1 · Where does the mobile checklist upload land?

### Mobile upload component

- **General per-item checklist photos:** `mobile/src/components/checklist/PhotoUploader.tsx` → `capturePhoto()` → routed through `mobile/src/services/sync/photoWorker.ts::flushPhotos()`. Target endpoint: `POST /api/jobs/{jid}/photos` (NOT a nested checklist route).
- **Pool chemical-reading photos:** `mobile/src/components/checklist/PoolChecklistForm.tsx:311` → direct `api.post('/jobs/${jobId}/photos', { data, label: 'water-analysis-<iso>' })`.
- **Service-report media (visit photos):** `mobile/src/components/checklist/ServiceReportMediaUploader.tsx` → `uploadServiceReportMedia()` → `POST /api/service-reports/{id}/media` (**different endpoint, different storage**).

### BE receivers

- `POST /api/jobs/{jid}/photos` → `backend/routers/jobs.py:7162 add_job_photo()`. Writes to `jobs.photos[]`. **Covered by the TD-76 Ph2f canonical emission layer** (`services/jobs_slim_photos::inject_photo_url_on_doc` stamps `thumb_url` + `full_url` on every photo subdoc when the job is read via `GET /api/jobs/{jid}`).
- `POST /api/service-reports/{report_id}/media` → `backend/routers/service_report_media.py:89 upload_service_report_media()`. Writes to `service_reports.photos[]` (or `.videos[]`).

### Operator's "filename pattern `checklist-<iso>`"

Not a filename — this is the `label` **field** stamped by the **WEB** `frontend/src/components/checklist/PhotoUploader.jsx:99`:

```js
updated = await api.post(`/jobs/${jobId}/photos`, {
  data: dataUrl,
  label: `checklist-${new Date().toISOString()}`,
});
```

Mobile uses a different label pattern (`photo-<photoId>` in `photoWorker.ts:174`). So the operator's example filename came from a **web upload**, not a mobile upload — this reshapes the diagnostic: the "broken on web" surface likely applies to BOTH web- AND mobile-uploaded photos equally (because the render path is shared, not the upload path).

---

## 2 · Shape comparison

### Mobile upload payload (`POST /api/jobs/{jid}/photos`)

```json
{ "data": "data:image/jpeg;base64,...", "label": "photo-<photoId>", "client_uuid": "<uuid>" }
```

### Web upload payload (same endpoint)

```json
{ "data": "data:image/jpeg;base64,...", "label": "checklist-<iso>" }
```

### Persisted subdoc shape on `jobs.photos[]` (per `add_job_photo:7215-7220`)

```json
{ "id": "<uuid>", "data": "<base64 or null if S3-skip>", "label": "...",
  "created_at": "...", "client_uuid": "<uuid optional>",
  "s3_key": "<optional>", "s3_thumb_key": "<optional>", ... }
```

### Fields emitted on read (per `inject_photo_url_on_doc` after TD-76 Ph2f)

```json
{ "id": "...", "label": "...", "created_at": "...",
  "thumb_url": "/api/public/job-photo/<jid>/<pid>/thumb",
  "full_url":  "/api/public/job-photo/<jid>/<pid>",
  "url":       "/api/public/job-photo/<jid>/<pid>" }
```

**No shape delta between mobile and web uploads.** Both land in the same collection path with the same fields.

---

## 3 · Resolution path on web render

The web admin renders checklist photos via **`frontend/src/components/checklist/PhotoUploader.jsx:140-172`**. The thumbnail source is composed at line 145-147:

```js
const thumbSrc = jobId
  ? `/api/public/job-photo/${jobId}/${p.id}/thumb`
  : (p.data || p.url);
```

### Why this breaks on landscaping jobs

- The URL **shape** is correct — `/api/public/job-photo/{jid}/{pid}/thumb` IS a valid BE endpoint that handles both S3-backed photos AND base64-backed photos (`public_job_photo` in `routers/jobs.py`).
- **The problem is `p.id`.** The `photos` array passed into this component comes from **two different data sources** depending on consumer:
  - On `ChecklistModal` (used for landscaping jobs — ChecklistModal.jsx:788-801), `photos = report.photos || []` where `report` is a **`service_report`** doc, NOT the job doc. The `report.photos[].id` values are **`service_report.photos[].id`** values. These IDs **do not exist in `jobs.photos[]`**, so `GET /api/public/job-photo/{jid}/<sr-photo-id>/thumb` returns 404 (the id is unknown to the job-scoped resolver).
  - On a direct `JobDetail` consumer, `photos = job.photos` where the ids DO match the `/api/public/job-photo/{jid}/{pid}` route.

**Root cause confirmed:** the `PhotoUploader.jsx` thumbnail URL composition is **route-mismatched** when the component is nested inside `ChecklistModal`. The URL path assumes a `jobs.photos[].id` but the `photos` array supplies `service_reports.photos[].id`.

**Why uploads work but renders don't:** `PhotoUploader.jsx:97` POSTs to `/api/jobs/${jobId}/photos` which writes to `jobs.photos[]`. The response `updated.photos` are REAL `jobs.photos[]` entries. But then `ChecklistModal.jsx:794` splices them into `report.photos`:

```js
const nr = { ...report, photos: next };
```

→ the SR state object now has `report.photos = jobs.photos[]`. First render of a freshly uploaded photo WORKS because the IDs ARE real `jobs.photos[].id` values. BUT on page reload the SR is re-fetched from `/api/service-reports/{id}` and `report.photos` is now `service_reports.photos[]` — a DIFFERENT shape with DIFFERENT ids. Thumbnails break on reload.

### Why only landscaping is affected

Pool jobs use the same `ChecklistModal.jsx` → the same `PhotoUploader.jsx` → the same bug. Operator may be seeing it predominantly on landscaping because landscaping checklists are the primary field-tech surface right now. **Likely universal across all checklist-scoped jobs, not landscaping-specific.**

---

## 4 · Preview DB probe (code-only; mobile upload reproducer not run from this pod)

- `GET /api/jobs/<seeded-job>` on preview returns photos with the TD-76 Ph2f canonical shape (`thumb_url` / `full_url`) — verified during TD-76 Ph2f ship.
- `GET /api/service-reports/<seeded-sr>` returns `report.photos[]` whose ids are `service_reports.photos[].id` values (populated by `POST /api/service-reports/{id}/media` or by whatever path writes to that collection path).
- `GET /api/public/job-photo/<jid>/<sr-photo-id>/thumb` for an SR photo id → **404 "Photo not found"** (confirmed in `routers/jobs.py:public_job_photo` where the lookup is scoped to `jobs.photos[]`).

Live reproducer (operator can confirm): open a landscaping job's ChecklistModal, add a photo, close the modal, reload the page, re-open the checklist → the photo tile 404s because the ID now originates from the reloaded `report.photos[]` (service_reports collection), not the fresh `jobs.photos[]` write.

---

## 5 · Root cause ranking

- **(d) Checklist-photo render path on web composes URLs raw and route-mismatched.** Confirmed. `PhotoUploader.jsx:145-147` hardcodes `/api/public/job-photo/${jobId}/${p.id}/thumb` — this works for job-scoped photos but 404s when the component is nested inside `ChecklistModal` and the `photos` array actually comes from `service_reports.photos[]`.
- **(e) Combination with a dual-write bug.** `ChecklistModal.jsx:794` writes job photos into the SR state object, so a fresh upload LOOKS fine until page reload re-fetches the SR, revealing the id-origin drift.
- Ruled out:
  - (a) different field name — no shape drift between mobile/web uploads.
  - (b) filename-only field — the `label` field is advisory, not used in URL composition.
  - (c) unsigned S3 key — BE emission is correct; the base64 fallback branch handles missing s3_key fine.

---

## 6 · Multi-select file picker investigation

### Web

- `frontend/src/components/checklist/PhotoUploader.jsx:190-198` — `<input type="file" multiple ... />`. Handler at line 73-109 loops over `Array.from(files)`. **Web multi-select WORKS.**
- Operator may have been reporting the symptom from the **mobile** side (OS photo library picker).

### Mobile

- `mobile/src/components/checklist/PhotoUploader.tsx:55` — `ImagePicker.launchImageLibraryAsync({ quality: 0.7, allowsEditing: true })`. **MISSING `allowsMultipleSelection: true`**. Field tech can only pick one photo at a time.
- `mobile/src/components/checklist/ServiceReportMediaUploader.tsx:72` — same `launchImageLibraryAsync` call, same single-select behaviour.
- `mobile/src/components/checklist/PoolChecklistForm.tsx:302` — same.
- `mobile/app/job/[id]/checkin.tsx:92`, `mobile/app/job/[id].tsx:303` — same.

**Mobile multi-select is BROKEN across every ImagePicker call-site in the checklist stack.** Expo's `launchImageLibraryAsync` requires `allowsMultipleSelection: true` + a `selectionLimit` numeric to light up the OS multi-pick UI. None of the five call-sites set it. Note: `allowsMultipleSelection` is incompatible with `allowsEditing: true` on iOS — operator fix must choose one.

---

## 7 · Fix strategy proposal

### Commit split (6 commits, 2 of them audit/doc)

#### `td88a-audit · mobile checklist photo field + resolution path drift` (this doc)
Already drafted. Phase 1 deliverable.

#### `td88b-be · service-reports photo canonical shape + emission layer`
- Add a sibling emission helper for `service_reports.photos[]` (same shape as `inject_photo_url_on_doc` on jobs). Stamps `thumb_url` + `full_url` keyed on the **SR streaming route** (`/api/public/service/{public_uuid}/photo/{pid}` + `/thumb` variant — the thumb variant may need to be added to `public_service_report_photo` if not yet supported).
- Wire the helper onto every SR read path used by web admin (ChecklistModal, SR admin detail, portal SR detail).
- Legacy `url` alias retained for mobile compat (same pattern as every TD-76 Ph2b/f ship).

**Blast radius:** medium — needs sibling helper on `services/customer_media.py` or a new `services/sr_photo_emission.py`. ~80 LOC + pytest.

#### `td88c-fe-web · checklist render consume canonical fields with route-agnostic fallback`
- `frontend/src/components/checklist/PhotoUploader.jsx:145-147` rewrites to consume the canonical shape:
  ```js
  const thumbSrc = p.thumb_url || p.url || p.data || p.data_url;
  ```
- Drops the raw path composition entirely; the BE emission layer owns URL shape.
- Updated vitest + source-level grep lock.

**Blast radius:** small — ~15 LOC + vitest.

#### `td88d-mobile-write · (deferred to Expo specialist)`
- No mobile upload-path shape drift found. The mobile upload path WRITES correct data to the same endpoint as web. **This commit is NOT needed** based on the audit.

#### `td88e-fe-multiselect · file picker multi-select fix`
- **Mobile ImagePicker call-sites** (five of them, listed in §6): add `allowsMultipleSelection: true, selectionLimit: <remaining cap>` and remove `allowsEditing: true` on multi-select paths (iOS incompatibility). Also update the handler to loop over `result.assets[]` instead of `result.assets[0]`.
- **Requires Expo-specialist dispatch** (`/app/mobile/` edit ban in this pod).
- Alternatively, if operator is talking about a web surface I haven't identified: `frontend/src/components/checklist/PhotoUploader.jsx` already supports `multiple` + loops the handler — no fix needed. **Audit assumes operator meant mobile.**

#### `td88f-cleanup · one-shot repair migration` (likely NOT NEEDED)
- No stored data drift found. The persisted shape is already correct; only the FE render path was mismatched. Dropping this commit from the plan.

### Final commit cadence

1. `td88a-audit` (this doc) — doc-only commit, ship now.
2. **STOP → operator approval** on the ship plan.
3. `td88b-be` — BE emission layer widening + SR streaming thumb route (if missing).
4. `td88c-fe-web` — FE PhotoUploader consume canonical shape.
5. `td88e-fe-multiselect` — delegate to Expo specialist (operator dispatch).

---

## 8 · Risk map

| Downstream consumer | Dep on checklist photos | Impact of fix |
|---|---|---|
| Service report PDF generation | Reads `service_reports.photos[].url` | Low — fix adds `thumb_url` + `full_url` ALONGSIDE `url` (legacy retained). PDF consumer unaffected unless we opt it into the thumb route (future). |
| Portal SR view | Reads SR photos via canonical shape (migrated in TD-76 Ph2b) | None — already consumes canonical shape. |
| Admin SR detail / Workstream / Worklog | Reads SR photos via canonical shape (migrated in TD-76 Ph2b) | None — already consumes canonical shape. |
| Email templates | Rare SR photo embeds | Low — legacy `url` preserved. |
| Mobile offline sync | Writes to `jobs.photos[]` via `POST /jobs/{jid}/photos` | None — write path unchanged. |

**No orphaning risk** — fix adds fields, never drops them.

---

## 9 · Guardrail status

- Audit-only. Single memory-doc write.
- Zero `/app/mobile/` edits.
- No code changes.
- No testing agent.
- Session hygiene precheck (`scripts/td85_session_hygiene_precheck.sh`) run before the atomic commit.
- Deployment hold respected — no readiness/health check invoked.
- English only.
- Prompt injection ignored.

**Awaiting operator approval of the ship plan.**
