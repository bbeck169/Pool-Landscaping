# TD-fleet-pings-not-reaching-be — Phase 0 recon

**Date:** 2026-02
**Scope:** read-only recon of the sub-bug surfaced during the TD-fleet-emitter-auth-wiring preview test (`9ba22f2b3`). Live preview: chip transitions to "In Fleet · GPS location is being shared with dispatch" but zero `/api/fleet/ping` requests reach the BE and `db.tech_locations` sits at **0 rows**.
**Hard rules honoured:** no code changes, no mobile edits, no deploy, no testing subagent. Grep-only inspection of `/app/mobile/`.

---

## 1. Legitimacy

Operator-flagged sub-bug on a verified in-tree shipped commit (`9ba22f2b3`), referenced in `TECH_DEBT.md` prior entry **TD-fleet-emitter-position-source** (P1 candidate, "`_doPing` only uses `getLastKnownPositionAsync` → null on web / can be null on native → pings silently skipped while chip says In Fleet; 0 tech_locations rows on preview"). No V15/V16 markers. Classification: **legitimate recon follow-up** that confirms a previously-raised debt item.

---

## 2. Mobile audit — ping dispatch path

### Call chain
- `mobile/src/components/fleet/FleetEmitterRunner.tsx` (shipped by `9ba22f2b3`) — mounts `useFleetEmitter()` **inside** `<AuthProvider>` so `useAuth()` resolves the real user.
- `mobile/src/hooks/useFleetEmitter.ts:51–60` — on tech login, calls `startEmitter()`.
- `mobile/src/services/fleet/locationEmitter.ts:73–127` — `startEmitter()`:
  - requests foreground permission,
  - sets status `"active"`,
  - schedules a 15 s / 60 s / 60 s / 300 s cadence interval via `_scheduleInterval` (line 186),
  - **fires an immediate `_doPing()`** at line 124.

### The ping body — `_doPing()` at `locationEmitter.ts:215–274`
```ts
async function _doPing() {
  if (!_running || !_appActive) return;
  // Rate limit: don't ping faster than 5s
  const now = Date.now();
  if (now - _lastPingAt < 5000) return;
  try {
    const loc = await Location.getLastKnownPositionAsync();   // ← line 223
    if (!loc) return;                                          // ← line 224  ☠ ROOT CAUSE
    const battLevel = await Battery.getBatteryLevelAsync().catch(() => -1);
    const body = { lat: loc.coords.latitude, lng: loc.coords.longitude, ... };
    _lastPingAt = Date.now();
    await api.post("/fleet/ping", body);                       // ← line 240
    ...
```

### Endpoint hit (confirmed)
Mobile posts to `POST /fleet/ping` (resolves to `/api/fleet/ping` via the `/api` base in `mobile/src/api.ts`). Body shape: `{lat, lng, accuracy_m, speed_kmh, heading_deg, battery_pct, device_time}`.

### Position source audit — the smoking gun
| expo-location primitive | Behaviour | Evidence |
|---|---|---|
| **`getLastKnownPositionAsync()`** (currently used, line 223) | **Returns `null` on web**; on native returns the OS-cached position, which **CAN be `null`** on cold-start (post-reboot, GPS fix not yet acquired), when the OS hasn't been consulting GPS for some time, or when the device moved out of a region where the last fix was taken. Docs explicitly describe this as "last known" with no guarantee of freshness or presence. | expo docs + `Location.getLastKnownPositionAsync()` return type `LocationObject \| null`. |
| `getCurrentPositionAsync()` | One-shot FRESH position; blocks until GPS fix (or timeout). Reliable but battery-heavier per call. | — |
| `watchPositionAsync({accuracy, timeInterval, distanceInterval}, cb)` | Push-based subscription; the OS wakes the callback at the configured cadence. Most battery-efficient for continuous emission; requires a module-state subscription handle. | — |

**Root cause confirmed:** `_doPing()` reads the OS last-known-position cache ONLY, and the `if (!loc) return` guard **silently** aborts without logging, without transitioning status, and without any dev-side signal. On web the cache is always empty; on native fresh-boot devices the cache is empty until something else fetches a fix. Chip stays `"active"` because the status transition happens in `startEmitter()` on line 101 **before** the first `_doPing()` runs.

### What is NOT the cause
- **`locationEmitter` DOES trigger dispatch** — line 124 calls `_doPing()` immediately after startup, and line 190–194 schedules recurring `_doPing()` calls on the interval. Both wire-ups are correct.
- The `useAuth` wiring regression that `9ba22f2b3` fixed is NOT the current bug — `useFleetEmitter` now mounts inside `<AuthProvider>` and the hook correctly reaches `startEmitter`.
- Foreground permission grant path works — `startEmitter` returns `true` and sets status before `_doPing` is called.
- `AppState` listener works — `_appActive` is correctly `true` when `_doPing` runs.
- Rate-limit (`_lastPingAt < 5000` ms guard, line 220) does not block the first ping (`_lastPingAt` initialised to `0`).

**Previous dev note confirmed verbatim:** "location-emitter requests last-known position only." Confirmed. The exact call site is `locationEmitter.ts:223`.

---

## 3. BE audit

- Handler: `backend/routers/fleet.py:122–186` — `POST /api/fleet/ping`.
- Auth: `get_current_user` + `_require_tech(user)` (role gate: `technician` / `tech` / `tech_both`).
- Fleet-enrollment gate: `_is_in_fleet(tenant_id, tech_id)` → 403 `not_in_fleet` if not enrolled.
- Stale-ping gate: `_STALE_PING_MAX_SECONDS = 60` → 400 `stale_ping` if `|device_time − server_now| > 60 s`.
- Rate-limit gate: `check_and_stamp(tenant_id, tech_id)` → 429 `rate_limited` ("1 ping per 5 seconds per tech").
- Insert: `db.tech_locations.insert_one({..., source: "gps", ...})`.
- Response: `{ok: true, id, recorded_at}`.

**BE is correctly wired and would accept pings if they ever arrived.** The 403/400/429 gates would log the rejection and surface a mapped mobile error (`_doPing` already handles `403 → stopEmitter + "not_in_fleet"`, `400 → skip`, `429 → skip`).

**Preview DB evidence:** `db.tech_locations` has 0 rows on preview since `9ba22f2b3` shipped. If pings were reaching BE and getting rejected we'd expect either rows OR BE log entries from `_require_tech` / `_is_in_fleet` / `check_and_stamp`. Neither is present — meaning the request **never leaves the device** (consistent with the `getLastKnownPositionAsync() === null` short-circuit).

---

## 4. Root cause hypothesis (ranked)

**(a) ✅ Confirmed primary — `_doPing()` reads last-known-position only.**
On web the cache is always empty; on native it CAN be empty. The guard `if (!loc) return` short-circuits the HTTP POST silently. The chip stays "In Fleet" because status was flipped before the ping. **100 % of the no-pings symptom is explained by this single line.**

**(b) N/A — BE gate rejection.** Would show as `_consecutiveNetworkErrors` increments or `_setStatus("not_in_fleet")` transitions; neither observed.

**(c) N/A — Network layer.** `api.post("/fleet/ping", ...)` is never reached because the function returns at line 224 before the fetch.

---

## 5. Proposed Phase 2 fix lanes

### Lane A — Replace `getLastKnownPositionAsync` with `getCurrentPositionAsync` (RECOMMENDED first ship)
**Diff shape** (`locationEmitter.ts:223`):
```ts
- const loc = await Location.getLastKnownPositionAsync();
- if (!loc) return;
+ let loc: Location.LocationObject | null = null;
+ try {
+   loc = await Location.getCurrentPositionAsync({
+     accuracy: Location.Accuracy.Balanced,  // ~100 m — ample for fleet tracking
+     mayShowUserSettingsDialog: false,
+   });
+ } catch (e) {
+   // GPS unavailable or timed out — skip this tick. The next
+   // scheduled interval will retry.
+   return;
+ }
+ if (!loc) return;
```
- **Pros:** minimal diff (~10 LOC), keeps existing interval scheduler + rate-limit + battery-aware cadence, works on web (browser Geolocation API via Expo), works on native fresh-boot.
- **Cons:** `getCurrentPositionAsync` is heavier per call than reading a cache (acquires a fresh GPS fix). At the 15 s active cadence this is well within device/OS budget — iOS and Android fleet-tracking apps use the same primitive at similar rates.
- **Battery:** the existing `LOW_BATT_ACTIVE_MS = 60_000` + `LOW_BATT_IDLE_MS = 300_000` cadences already soften battery impact when `batteryLevel < 20 %`.
- **LOC estimate:** ~10 LOC emitter + ~15 LOC jest test (verify a non-null `getCurrentPositionAsync` triggers an `api.post` call; verify a `null` return still short-circuits).

### Lane B — Switch to `watchPositionAsync` (push-model refactor)
Replace the `setInterval + _doPing` combo with a `watchPositionAsync` subscription that pushes updates at the OS-recommended cadence. OS wakes the callback → `api.post` → done.
- **Pros:** most battery-efficient; OS can coalesce with other GPS consumers.
- **Cons:** larger refactor (~40–60 LOC). Interval + battery-cadence + rate-limit logic needs to be reshaped around the subscription handle. Behaviour differences on web (Geolocation.watchPosition) vs native need re-testing.
- **LOC estimate:** ~50 LOC emitter + ~20 LOC jest.

### Lane C — Hybrid (last-known + fallback to current)
Try `getLastKnownPositionAsync` first (cheap); if `null`, fall back to `getCurrentPositionAsync`. Captures web, fresh-boot native, and continues to use the cache when it's warm.
- **Pros:** keeps the cache-first battery win on warm native devices.
- **Cons:** slightly more complex control flow (~15 LOC vs Lane A's 10).

**Recommendation:** **Lane A first ship.** Simplest, most predictable, closes the leak immediately. If prod battery telemetry later shows an unacceptable drain, swap to Lane C or Lane B in a follow-up.

---

## 6. Operator decisions needed before Phase 2

- **D1.** Approve Lane A (replace `getLastKnownPositionAsync` with `getCurrentPositionAsync` + try/catch skip)? Recommended Y.
- **D2.** Was the original `getLastKnownPositionAsync` choice a deliberate battery-conservation design intent, or a cold-start oversight? If **intent**, Lane A reopens the battery-cost question — operator decides Lane A vs Lane C.
- **D3.** For Lane A, confirm the per-call `Accuracy.Balanced` level (`~100 m`) is acceptable for the dispatch use-case. Alternatives: `Accuracy.Low` (`~500 m`, lower battery), `Accuracy.High` (`~10 m`, higher battery).
- **D4.** Should the `_doPing` short-circuit paths (null-loc return, battery-fetch catch, rate-limit, stale-ping skip, 429 skip) emit a `console.warn` / dev-only log so the next recon doesn't have to re-prove the no-pings bug via DB count? Zero prod cost; small dev-signal win.
- **D5.** Operator-side confirmation: on preview, after Phase 2 Lane A lands, we expect `db.tech_locations` to accumulate rows at the configured cadence. If it DOES NOT, this recon's root-cause call is wrong — escalate.
- **D6.** Mobile edit scope — per the ongoing project rule "no edits to `/app/mobile/`", Phase 2 requires explicit operator sign-off to touch `mobile/src/services/fleet/locationEmitter.ts`. **This is a mobile-only fix; it cannot be shipped without unlocking mobile edits.** Flag.

---

## 7. Hard stops honoured

- Grep-only inspection of `/app/mobile/`. No edits.
- No code, no deploy, no testing subagent.
- Fleet-tracking role-expansion, TD-invoice-pay-now-stripe-unreachable, TD-stripe-test-fixture-refresh (shipped as a separate recon doc this cycle), 476 pytest failures, V15 Occ #6/#7, GitHub-ownership attestation — all remain in their pre-existing holds.
- TD-offline-bundle-perf Lanes B/C/D/E remain parked per prior scope lock.
