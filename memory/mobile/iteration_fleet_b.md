# Iteration FLEET-B — Mobile GPS Emission + Manual Check-ins

## What was implemented

### Screens/Components
1. **FleetStatusChip** (`src/components/fleet/FleetStatusChip.tsx`) — Persistent header chip showing fleet tracking status
   - Green = In Fleet (actively emitting GPS)
   - Yellow = Idle / Paused
   - Red = Off / Not in fleet / No permission
   - Tap opens a modal with status description

2. **CheckInButtons** (`src/components/fleet/CheckInButtons.tsx`) — "On My Way" and "Arrived" buttons
   - Added to both `job/[id].tsx` and `job/[id]/checklist.tsx`
   - POST `/api/fleet/checkin` with kind="on_the_way" or "arrived"
   - 10s cooldown between taps, toast feedback on success/error

3. **FleetPauseToggle** (`src/components/fleet/FleetPauseToggle.tsx`) — Settings toggle
   - "Pause tracking for this shift" in the Profile/More screen
   - Persisted in AsyncStorage, survives app restart

4. **locationEmitter** (`src/services/fleet/locationEmitter.ts`) — Core GPS emission service
   - Foreground-only: stops when app goes to background
   - Cadence: 15s active / 60s idle
   - Battery-aware: <20% degrades to 60s active / 300s idle
   - Error handling: 403→stop, 400→skip, 429→skip, network→retry once 5s backoff
   - Subscribable via `onStatusChange()` listener

5. **useFleetEmitter** (`src/hooks/useFleetEmitter.ts`) — Root-level hook
   - Starts emitter for technician users on app launch
   - Stops on logout or role change

## Web-to-Mobile Mapping Decisions
- Fleet membership check: Tech's emitter probes via POST /fleet/ping (handles 403 gracefully) rather than admin-only GET /fleet/membership
- FleetStatusChip placed above tabs in (app)/_layout.tsx — visible on all screens
- CheckInButtons placed on both job detail (`[id].tsx`) and checklist (`[id]/checklist.tsx`) routes since schedule navigates to `/job/{id}/checklist`

## Dependencies Installed
- `expo-battery` — Battery monitoring for adaptive cadence

## Known Issues
- None — all lint checks pass, app compiles correctly

## Deferred Items
- Background location tracking (out of scope — foreground-only by design)
- Drawing pad signature (not part of FLEET-B)
