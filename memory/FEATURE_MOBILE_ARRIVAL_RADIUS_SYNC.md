# Feature: Mobile Arrival Radius Sync (75m)

## Problem
The mobile app used a **150m** arrival radius for foreground GPS detection (`JobTimerCard`) and background geofencing (`geofence.ts`), while the server's auto-start trigger used **75m** (`DEFAULT_ARRIVAL_RADIUS_M` in `backend/routers/gps_auto_start.py:34`). Between these thresholds was a "dead zone" (75–150m) where the mobile UI would trigger an `/arrive` call, but the server hadn't yet armed the auto-start timer, causing user-facing confusion and timer-duration drift.

## Server Constant
- **File**: `backend/routers/gps_auto_start.py:34`
- **Name**: `DEFAULT_ARRIVAL_RADIUS_M`
- **Value**: `75` (meters)
- The server also supports tenant-level overrides via `get_arrival_radius_m(tenant)`.

## Mobile Constants Changed

| File | Constant | Old | New |
|------|----------|-----|-----|
| `src/components/job/JobTimerCard.tsx:9` | `ARRIVE_RADIUS_M` | 150 | **75** |
| `src/geofence.ts:8` | `RADIUS_M` | 150 | **75** |

### Already Correct (no change needed)
| File | Constant | Value |
|------|----------|-------|
| `src/background/jobGeofence.ts:26` | `FALLBACK_RADIUS_M` | 75 (already correct; also reads server config dynamically) |

## All Mobile Call Sites

### `JobTimerCard.tsx`
- **Line 73**: Status display — `~${Math.round(d)} m away — auto-starts within ${ARRIVE_RADIUS_M} m`
- **Line 74**: Proximity gate — `if (d <= ARRIVE_RADIUS_M)` triggers `/jobs/{id}/arrive`

### `geofence.ts`
- **Line 55**: Background geofence region — `radius: RADIUS_M` in `startGeofencingAsync` regions

### `jobGeofence.ts` (enhanced P37c module)
- **Line 26**: `FALLBACK_RADIUS_M = 75` — used when server config fetch fails
- **Line 113-114**: Reads `res?.arrival_radius_meters` from `GET /api/settings/gps-auto-start`; falls back to `FALLBACK_RADIUS_M`
- **Line 184**: Uses fetched radius in `startGeofencingAsync` regions

## Comments Added
Both changed files now include:
```
// Must stay in sync with backend DEFAULT_ARRIVAL_RADIUS_M in
// backend/routers/gps_auto_start.py (currently 75m).
```

## Tests
- `__tests__/arrival-radius-sync.test.ts` — 3 tests locking all three constants to 75m via source scanning.

## Out of Scope
- Departure/leaving radius (not touched)
- Backend changes (server already at 75m)
- UI copy changes beyond the auto-generated `${ARRIVE_RADIUS_M} m` status text
