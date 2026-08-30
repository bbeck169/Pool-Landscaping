## Phase O6 — Full Write Parity + UX Polish

### What was implemented

**New files created (10):**
- `src/services/offlineWrite.ts` — unified write wrapper with offline fallback (online: direct API, offline: enqueue to O2 sync queue, network error: auto-fallback).
- `src/components/sync/OfflineBanner.tsx` — persistent amber top banner when offline, dismissible per session, auto-re-shows on new offline transition.
- `src/components/sync/PendingChangesChip.tsx` — tappable chip showing "N pending", opens bottom sheet with all queued items + retry/delete.
- `src/components/sync/ConflictSheet.tsx` — bottom sheet for conflict resolution showing field-level diffs (client vs server), "Keep server" / "Keep mine" actions.
- `src/components/sync/SyncToast.tsx` — toast notifications for sync events (synced, failed, back online).
- `src/components/sync/StoragePressureBanner.tsx` — warning banner when pending photos > 50MB or queue > 100 entries.
- `src/components/sync/ManualSyncButton.tsx` — "Sync now" button for More/Settings screen with last sync time + pending count.
- `src/components/sync/index.ts` — barrel export.
- `src/services/storageWatchdog.ts` — storage pressure monitor (useStoragePressure hook + checkStoragePressure utility).
- `__tests__/o6-write-parity.test.ts` — 12 Jest tests for offlineWrite, storage pressure, diffKeys, component exports.

**Write flows wired with offlineWrite (30 callsites across 17 files):**

W-A (silent queue):
- job/[id].tsx: saveEdit, setStatus, assignTech
- FieldReport.tsx: save
- MaintenanceLog.tsx: save
- ServiceIssues.tsx: submit, approve
- CouldNotServiceButton.tsx: submit
- ServiceNotes.tsx: addNote
- CustomerTagsSection.tsx: detach, attach, createAndAttach
- MuteControlSheet.tsx: toggle
- GpsConsentModal.tsx: grant
- time-clock.tsx: clockIn
- landscape-time-clock.tsx: doPunch
- LandscapingClockWidget.tsx: doPunch
- checklist.tsx: autosave (service_report.patch)
- settings/notifications.tsx: save

W-B (queue with warning):
- job/new.tsx: save (job.create)
- customer/new.tsx: runSave (customer.create / customer.update)
- NewLeadForm.tsx: submit (lead.create)
- time-off.tsx: submit (time_off.request)
- dispatch.tsx: doAssign (job.assign)

W-C (hard block — left as-is):
- All payment flows (Stripe)
- All live SMS/email sends
- All AI/ML calls
- Auth flows
- Route optimization
- Portal writes
- Visit recap sends

**Other changes:**
- `_layout.tsx`: integrated OfflineBanner, StoragePressureBanner, ConflictSheet, SyncToast.
- `(app)/index.tsx`: added PendingChangesChip to dashboard header.
- `(app)/more.tsx`: added ManualSyncButton in "Offline & Sync" section.
- `cacheInvalidation.ts`: expanded from ~7 op_types to ~30+ op_types.
- Fixed broken `load` callback in dashboard index.tsx (syntax error from previous session).

### Web-to-mobile mapping
- offlineWrite pattern: equivalent to wrapping web fetch calls with offline detection + IndexedDB queue fallback.
- OfflineBanner: equivalent to the web's `<OfflineBar>` but uses RN Animated for slide-in.
- PendingChangesChip: equivalent to web's badge-on-header pattern.
- ConflictSheet: equivalent to web's diff modal.

### Known issues / deferred items
- Preview tunnel sleeping (known recurrence) — tested via Metro bundler logs + unit tests.
- Admin CRUD flows (chemicals, forms, team reset-password/delete) remain W-C hard-blocked.
- The `visit_recap` send-recap endpoint remains W-C since it triggers live SMS/email.

### Dependencies installed
None new — all components use existing expo-sqlite, @react-native-community/netinfo, expo-file-system.

### Test results
```
PASS __tests__/o6-write-parity.test.ts (12/12 tests passing)
  - offlineWrite online path ✓
  - offlineWrite offline path ✓
  - Network error fallback ✓
  - Non-network error re-throw ✓
  - queuedMessage strings ✓
  - op_type propagation ✓
  - Storage pressure OK ✓
  - diffKeys utility ✓
  - OfflineBanner export ✓
  - PendingChangesChip export ✓
  - SyncToast export ✓
  - ManualSyncButton export ✓
```
