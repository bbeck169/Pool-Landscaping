## Delegation Brief · Phase 32 · Mobile Offline Capability
### Client-Side Consumer of the New Sync + Bundle Endpoints

**From:** Web / backend team · Phase 32 · Feb 2026
**To:** e1_expo_frontend_dev
**Priority:** P1
**Language:** All comments, tests, and copy in **English**.
**Status:** Backend foundation shipped. Mobile client work is the entire
Phase 32 deliverable on your side.

---

### Backend contract (already live)

Two new endpoints on the FastAPI backend — both are tenant-scoped and
require an authenticated JWT (`role in ("technician","admin","super_admin")`;
customers are 403).

#### 1. `GET /api/mobile/offline-bundle`

Query params:
- `tech_id=me`               (default; also accepts a specific tech UUID for admins)
- `window_days=7`            (optional — how many days of jobs to include, default 7)

Response payload (shape — see `/app/backend/routers/mobile_sync.py`
`mobile_offline_bundle` for canonical):

```json
{
  "bundle_generated_at": "2026-02-10T15:30:00Z",
  "tech": { "id": "...", "name": "...", "role": "technician" },
  "jobs": [ /* full job docs the tech can service in the window */ ],
  "service_report_templates": { "pool": {...}, "landscape": {...}, "generic": {...} },
  "chemicals_catalog": [ ... ],
  "checklist_defaults": { "pool": [...], "landscape": [...] },
  "customers": [ /* customers linked to those jobs — enough to render address / name */ ],
  "server_snapshot_version": "2026.02.10.153000"
}
```

#### 2. `POST /api/mobile/sync`

Batched idempotent sync channel. Request body:

```json
{
  "device_id": "<expo-device-id>",
  "client_snapshot_version": "2026.02.10.153000",
  "operations": [
    {
      "client_op_id": "<uuid v4 generated on device>",
      "kind": "job.update" | "job.close" | "service_report.upsert"
             | "photo.upload" | "report.field.append",
      "entity_id": "<job or report id>",
      "payload": { ...op-specific... },
      "created_at": "2026-02-10T15:35:12Z"
    }
  ]
}
```

Response:

```json
{
  "results": [
    { "client_op_id": "...", "status": "applied" | "duplicate"
                                     | "conflict" | "rejected",
      "server_snapshot": {...} | null,
      "conflict_reason": "..." | null }
  ],
  "server_snapshot_version": "2026.02.10.153612"
}
```

Contract details (do NOT deviate on the client):

- **Idempotency:** the tuple `(tenant_id, client_op_id)` is enforced
  server-side via the `sync_receipts` collection. If the mobile retries
  the same op, the server responds `duplicate` and returns the original
  applied snapshot — safe to replay indefinitely.
- **Conflict resolution:** current policy is **mobile-wins**. When the
  server detects a fresher `updated_at` on the entity, it still applies
  the mobile payload, but writes the pre-image into
  `sync_conflict_log` for audit + returns `status="conflict"` so the
  client can surface a passive "we overrode a newer server change"
  toast (product-owner-approved).
- **Order:** operations inside a batch are applied in array order.
  The client MUST NOT reorder or dedupe locally — send the FIFO log.
- **Rejected ops:** `rejected` status means schema/permission failure.
  The client must NOT re-attempt the same op; it should hand off to a
  local error inbox for tech review.

Reference: `/app/backend/routers/mobile_sync.py`,
`/app/backend/tests/test_phase32_mobile_sync.py`.

---

### What we need from mobile

1. **Local storage layer**
   - Use `expo-sqlite` (already a dep). Create tables mirroring the
     bundle:
     - `jobs`
     - `service_reports`
     - `customers`
     - `templates_cache`
     - `pending_ops` (the outbox — one row per unsynced op)
     - `sync_receipts` (server responses, keyed by `client_op_id`)
   - Also cache the last `server_snapshot_version` at app level.

2. **Bundle download**
   - On login (or on "Refresh" button in the tech dashboard header),
     call `GET /api/mobile/offline-bundle?tech_id=me&window_days=7`.
   - Wipe + rebuild the local tables from the response payload.
   - Store `bundle_generated_at` + `server_snapshot_version` in
     app-level `AsyncStorage` for the sync request.

3. **Outbox pattern**
   - Every write action the tech takes (edit job, submit report, upload
     photo, close job) writes to BOTH the local table (optimistic UI)
     AND `pending_ops` (persistent queue).
   - A `SyncManager` singleton flushes `pending_ops` when:
     - App comes to foreground
     - Network reconnects (`@react-native-community/netinfo`)
     - Every 60s while online (background timer)
     - Manual pull-to-refresh
   - Batches up to 50 ops per POST. On success, delete applied ops
     from `pending_ops` and store the receipt.
   - On `conflict`: keep the local snapshot (server already accepted
     it — mobile-wins). Show a subtle "Synced with override" toast so
     the tech is aware.
   - On `rejected`: mark the op with `error` state + surface in an
     "Unsynced errors" screen. Do NOT auto-retry.
   - On `duplicate`: treat as success (retry safe).

4. **Photo/video upload**
   - Photos and videos are uploaded via the existing
     `/api/service-reports/{report_id}/media` endpoint (NOT part of
     `/api/mobile/sync` — sync only handles JSON deltas). Queue the
     multipart upload separately in a `pending_media` table with the
     local file URI. Retry with exponential backoff up to 5 attempts.
     After success, POST a `photo.upload` op to `/api/mobile/sync`
     referencing the returned server media ID.

5. **UI affordances**
   - Header pill: `Online · Synced` / `Online · N pending` /
     `Offline · N queued`. `testID="sync-status-pill"`.
   - "Unsynced errors" screen: lists ops with `status="rejected"`.
     `testID="sync-error-inbox"`.
   - Job list badge: an unsynced job shows a small dot.
     `testID="job-{id}-unsynced-dot"`.

6. **Testing**
   - Jest unit tests for the reducer that projects `pending_ops` onto
     the local read model.
   - Detox / Maestro e2e: airplane mode → edit job → toggle airplane
     off → assert the sync pill flips to `Synced` within 10s.

---

### Non-goals for Phase 32 mobile

- **Do NOT** implement collaborative real-time updates. The sync is
  outbox-style — polling / event-driven, not websocket.
- **Do NOT** try to resolve conflicts client-side. Server is
  authoritative on ordering; mobile is authoritative on payload
  content. Just apply what the server tells you.
- **Do NOT** send passwords, PII beyond what's already in the bundle,
  or unrelated app-analytics events through `/api/mobile/sync`. It's a
  strict CRUD sync channel.

### Guardrails

- English-only strings, commits, tests.
- Preserve the existing tech-facing dashboard layout — just add the
  sync pill + error inbox affordances.
- Do NOT touch the backend routes. Any contract gap → open an issue
  and tag the web team.
- `client_op_id` must be a UUID v4 generated locally BEFORE the op is
  written to `pending_ops`. Never let the server assign it.
- Never retry a `rejected` op automatically.

---

### Reference paths

- Backend router:  `/app/backend/routers/mobile_sync.py`
- Backend tests:   `/app/backend/tests/test_phase32_mobile_sync.py`
- Web-side notes:  none (this is a mobile-only feature)
- DB collections created by backend:
  - `sync_receipts` — idempotency store (`tenant_id + client_op_id` unique index)
  - `sync_conflict_log` — audit log of mobile-wins overrides
  - `mobile_devices` — `{device_id, user_id, tenant_id, last_seen_at, last_sync_at, os, app_version}`

### Deploy

- Mobile: OTA/EAS update after merge. `expo-sqlite` is already in the
  deps; no native module addition expected.
