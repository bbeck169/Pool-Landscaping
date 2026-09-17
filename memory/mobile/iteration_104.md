## Iteration 104 — P37c: GPS Job Timer wire-up

### What was implemented
1. **GpsConsentModal mount** — `<GpsConsentModal />` now renders inside `ScheduleCalendarInner` for technician-role users. It self-checks `GET /tech-gps-consent/me` on mount and shows a consent modal if `active === false`. Admin/customer users don't see it.

2. **syncJobGeofencesP37c on boot** — The root `_layout.tsx` now calls `syncJobGeofencesP37c()` during the boot `useEffect` (alongside SQLite init, net bus, photo/video workers). Fire-and-forget with try/catch. This registers up to 20 geofence regions for active jobs with coordinates.

3. **Manual arrival POST** — `OnMyWayButton.tsx` now fires `POST /api/jobs/{id}/arrive` with `{ source: "manual", lat?, lng? }` alongside the existing "on my way" SMS. The arrival is best-effort (silent catch). `already_arrived` and `already_running` responses are handled gracefully (no error alert).

### Web-to-mobile mapping
- Web `JobDetail.jsx` line 107: `api.post('/jobs/${id}/arrive', { lat: 0, lng: 0 })` → Mobile `OnMyWayButton` fires the same endpoint with real coords + `source: "manual"`.
- Web doesn't have an equivalent GpsConsentModal (it's a mobile-only feature for background location tracking consent).
- Web doesn't call `syncJobGeofencesP37c` (geofencing is mobile-only).

### Tests created (28 total, all passing)
- `phase-gps-consent-modal-mount.test.tsx` — 6 tests (auto-check, show/hide, grant, decline, network error, autoOpen)
- `phase-syncjobgeofences-startup.test.tsx` — 15 tests (web skip, perms, valid jobs, skip completed/no-coords/running, cap, fallback radius, stop-before-start, helpers)
- `phase-mobile-arrival-endpoint.test.tsx` — 7 tests (coords, no-coords, already_arrived, already_running, silent failure, sequence order, role gate)

### Dependencies installed
- None (all required packages already present)

### Known issues
- Pre-existing: `k61-checklist-contract.test.ts` still fails (unrelated to this work)
- Pre-existing lint warnings in `calendar.tsx` (`canWrite`, `hydrationMeta` unused) — not introduced by this iteration

### Deferred items
- Geofence sync could also re-fire on AppState foreground (currently only on boot). Could be added in a follow-up.
- The undo banner for GPS auto-start (notification action) is wired in `jobGeofence.ts` but the response handler is not yet built.
