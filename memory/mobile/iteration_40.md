# Phase O3 — Mobile Hardening: Service Log Offline + Photo Pipeline

## What was implemented
### Deliverable 1: Service log offline-capable
- `offlineServiceLog.ts`: cache/read/markDirty/submitOffline
- Checklist screen offline submit enqueues `service_report.upsert` → "Submitted (pending sync)"
- Full payload preserved: chemical_readings, chemicals_added, checklist_items, notes, water_bodies

### Deliverable 2: Photo pipeline
- `photoWorker.ts`: full lifecycle — downscale (2048px, 0.85 JPEG) → stage (documentDirectory) → SQLite row → upload with X-Idempotency-Key → cleanup
- 3-failure stalling + retryStalled/retryAllStalled
- Orphan cleanup via purgePhotosForEntity
- Auto-flush on reconnect via wirePhotoAutoUpload

### Deliverable 3: job.arrive
- `jobArrive.ts`: enqueueJobArrive routes through sync_queue
- Job detail On My Way button now offline-safe

### Deliverable 4: Conflict detection (starter)
- `conflicts.ts`: recordConflict persists 409 in sync_conflicts table + emits event
- Queue dispatch catches 409 → recordConflict (no UI yet — O6)

### Deliverable 5: Tests (4 suites, 25 tests)
- o3-service-log-offline.test.ts: 7 tests
- o3-photo-pipeline.test.ts: 9 tests
- o3-job-arrive.test.ts: 4 tests
- o3-conflicts.test.ts: 5 tests

### Deliverable 6: Empirical proof
- 5/5 pass: queue drain, ops done, photos uploaded, pending cleared, dirty cleared

## Dependencies added
- expo-image-manipulator@57.0.14
- expo-image-loader@57.0.1 (transitive)

## Known issues / shortcuts
- expo-file-system: import from `expo-file-system/legacy` (SDK 54 moved to new File/Directory API)
- Conflict detection records 409s but no UI surface yet (deferred to O6)
- Photo downscale mocked in tests (expo-image-manipulator needs native binary)
