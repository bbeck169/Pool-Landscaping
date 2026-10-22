# TD-fleet-tracking-always-on · Phase 0 scoping doc

**Status**: recon only · no code · no package installs.
**Date**: Oct-2026.
**Operator ask**: *"Fleet Tracking should always be on."* Verified
real artifact (mobile screenshot of the schedule screen with a red
"Off" chip + modal titled *"Fleet Tracking · Off · Fleet tracking is
not running."*). Injection markers absent (no clone URL, no V14/15
shape, no urgency manipulation, no prescriptive regression language).
Classified **legitimate feature request**.

---

## §1 · Current-state audit — all three stacks

**Scope-reality delta — large.** Fleet tracking is NOT greenfield.
The project already carries:

- Tenant admin flag (`tenants.gps_auto_start_enabled`).
- Per-tech consent collection (`tech_gps_consents`).
- Per-tech pause-for-shift local toggle (device-side).
- Mobile background geofence task via `expo-location` + `TaskManager`.
- Admin UI for both the tenant flag and tech-level consent audit.
- Audit event emission on all state transitions.

### §1.1 · Backend (`/app/backend`)

| File | Role | Key lines |
| --- | --- | --- |
| `routers/gps_auto_start.py` (250 LOC) | **Primary tenant + consent surface** | `GET /api/settings/gps-auto-start` `:99`, `PATCH /api/settings/gps-auto-start` `:114`, `GET /api/tech-gps-consent/me` `:173`, `POST /api/tech-gps-consent` `:186`. Writes `tenants.gps_auto_start_enabled` + `tech_gps_consents` collection. Audit event `gps_auto_start_settings_update`. |
| `routers/gps_settings.py` (219 LOC) | Admin GPS settings | `GET /api/admin/gps/settings`, `PUT /api/admin/gps/settings`. |
| `routers/gps_user_controls.py` (408 LOC) | User-level GPS controls | Per-user visibility + preferences. |
| `routers/gps_ingest.py` (252 LOC) | Location ping ingest from mobile emitter | Writes `tech_locations` and friends. |
| `routers/gps_route.py` | Route tracking (per-shift path) | Mapbox-backed. |
| `routers/gps_live_positions.py` | Live positions for operator-facing map | Admin dashboard. |
| `routers/workforce_live_locations.py` (166 LOC) | Workforce live-location aggregation | Admin dispatcher map. |
| `routers/workforce.py` | Workforce enrollment | Tenant-level fleet membership. |
| `routers/telematics_webhooks.py` | 3rd-party telematics ingest | For GPS-hardware-based tracking. |
| `routers/admin_mileage_audit.py` + `admin_mileage_backfill.py` | Mileage audit + backfill | Derived from location pings. |

### §1.2 · Frontend (`/app/frontend`)

| File | Role |
| --- | --- |
| `pages/settings/GpsAutoStartPage.jsx` | Admin UI — tenant toggle + per-tech consent audit. |
| `pages/admin/FleetMembership.jsx` | Admin UI — fleet enrollment (which techs are in fleet). |

### §1.3 · Mobile (`/app/mobile`)

| File | Role |
| --- | --- |
| `app/(app)/more.tsx:239-245` | Mounts `<FleetPauseToggle>` inside the tech's Settings screen (`isTech &&` gated). |
| `src/components/fleet/FleetPauseToggle.tsx` (109 LOC) | **The pause switch surfaced in the operator screenshot.** Reads/writes device-local `isPaused()` / `setPaused()` from `locationEmitter.ts`. On resume, calls `startEmitter()`. |
| `src/services/fleet/locationEmitter.ts` | Emitter state machine (`active`, `not_in_fleet`, idle). Owns the local-device `isPaused` state. Status broadcast via `onStatusChange(cb)`. |
| `src/background/jobGeofence.ts` (`JOB_GEOFENCE_TASK` + 196 LOC) | Expo `TaskManager`-based geofence that auto-starts on arrival. Needs **BOTH** foreground + background location permissions (`Location.requestForegroundPermissionsAsync` + `requestBackgroundPermissionsAsync`). Max 20 regions. Fallback radius 75 m. |
| `src/components/gps/GpsConsentModal.tsx` | On-job-entry consent modal that calls `GET /tech-gps-consent/me` and `POST /tech-gps-consent`. |
| `app/tracking/_layout.tsx` + `app/tracking/index.tsx` (~400 LOC) | Admin-side "tracking" tab (operator view of fleet, not tech view). |

### §1.4 · Legal

| File | Role |
| --- | --- |
| `backend/routers/legal.py` | Legal docs served to clients. |
| `frontend/src/pages/portal/PortalTerms.jsx` | Customer-portal terms. **Not operator/tech-facing** — no GPS consent text found here on quick grep. |
| `frontend/src/pages/AiTransparency.jsx` | AI consent page — pattern template for a future GPS consent page. |

### §1.5 · The "Off" chip in the screenshot

The red "Off" chip + modal "Fleet tracking is not running" is driven by **the local `isPaused` state in `locationEmitter.ts`** (`FleetPauseToggle.tsx:54-61`). The chip appears when:

- Tech has toggled pause ON (`setPaused(true)`), OR
- Emitter status is `not_in_fleet` (not enrolled in fleet), OR
- Emitter is in a non-`active` idle state (startup, permission denied, OS backgrounded).

The chip surfaces LOCAL device state, not a server-side flag. "Off" is a device-authored condition today.

---

## §2 · Current toggle behavior (what makes it "Off" today)

5 ways tracking can land in "Off" state right now, roughly in order of operator-friction:

1. **Tech manually paused** via `FleetPauseToggle` on their phone's Settings → Fleet Tracking section. Stored in device local storage via `setPaused(true)`. Survives app restart.
2. **Tech not enrolled** in fleet (`workforce.py` enrollment pending or revoked). Emitter status is `not_in_fleet`; no server-side ingest allowed anyway.
3. **Tenant admin disabled** `gps_auto_start_enabled` via `PATCH /api/settings/gps-auto-start`. Geofence auto-start logic in `jobGeofence.ts:112` reads this flag and no-ops when false.
4. **Tech has not consented** via `/tech-gps-consent/me` — the `GpsConsentModal` has not been accepted. Enforced in `jobGeofence.ts:41`.
5. **OS permission denied** — `Location.getForegroundPermissionsAsync` or `getBackgroundPermissionsAsync` returned non-`granted` (`jobGeofence.ts:144-146`). Hard OS stop; app cannot override.

**State persistence:**
- Tenant flag → `tenants.gps_auto_start_enabled` (Mongo).
- Consent → `tech_gps_consents` collection (Mongo, per-user).
- Pause → device local storage (`locationEmitter.ts`). **Not server-synced**.
- Permissions → OS-owned, read via `expo-location`.

**Admin force-enable surface today:**
- Admin CAN flip the tenant `gps_auto_start_enabled` flag.
- Admin CANNOT today force a specific tech to track (no per-user override).
- Admin CANNOT today force-unpause a device-side pause.

---

## §3 · "Always on" interpretation options

### Option A — Soft always-on (least invasive, operator-friendly default)

- Default-on at install + auto-restart on login + sticky across app restarts.
- Pause toggle still visible under Settings; tech CAN still manually pause.
- Chip + modal continue to surface current state truthfully.
- UX: minimum friction; respects the Phase 34 consent pattern already shipped.
- Privacy: unchanged (user retains control).
- Battery/data: slightly higher baseline usage (fewer "Off" windows).
- BE delta: ~0 LOC (tenant flag defaults to `true` on new tenants, existing tenants explicit-opt-in).
- FE delta: ~0 LOC (admin page already supports toggle).
- Mobile delta: ~30 LOC — remove `setPaused(true)` default on cold start; auto-call `startEmitter()` after login if consent + enrollment are green.

### Option B — Hard tenant policy (mandatory for all techs on the tenant)

- NEW `tenants.fleet_tracking_mandatory: bool` flag (additive-nullable).
- Admin toggle in `GpsAutoStartPage.jsx` next to the existing auto-start toggle.
- When `fleet_tracking_mandatory = true`:
  - Mobile hides the pause toggle entirely (`FleetPauseToggle` renders null if the tenant flag is set).
  - Server rejects any client-authored pause state.
  - Device-local `isPaused` reset to `false` on every launch.
- UX: tech sees "Fleet tracking is required on this fleet. Contact your admin to pause." in place of the toggle.
- Privacy: **employment-tracking policy** — operator decision.
- Battery/data: higher usage, no opt-out.
- BE delta: ~80 LOC (tenant flag + patch validator + audit event).
- FE delta: ~40 LOC (admin UI second toggle + confirmation modal).
- Mobile delta: ~100 LOC (fetch tenant flag + conditional render + reset pause-local on launch).

### Option C — Per-user policy (admin picks which techs are mandatory)

- NEW field `users.fleet_tracking_mandatory: bool` on technician user docs (additive-nullable).
- Admin UI: per-tech column on `FleetMembership.jsx` with a toggle.
- Mobile checks `GET /me` + reads the field.
- UX: same as Option B but per-user. Techs flagged as mandatory see the hidden toggle; others see it as before.
- Privacy: granular — some techs mandatory, others optional.
- BE delta: ~100 LOC (schema + patch endpoint + audit).
- FE delta: ~80 LOC (per-tech toggle + confirmation).
- Mobile delta: ~80 LOC (same as B, scoped per-user).

### Option D — Full enforcement (strip the pause toggle entirely)

- Remove `FleetPauseToggle` from `more.tsx`; `locationEmitter.ts` always runs.
- No tenant/user flag; one-way change for the entire product.
- UX: no opt-out whatsoever. Modal + chip still surface "Off" when OS permissions are missing (which is the only remaining Off state).
- **Strongly flagged as the HIGHEST privacy/consent risk** — equivalent to a product-wide employment-tracking mandate without per-tenant control.
- NOT recommended without legal + operator sign-off; flagged as a decision requiring deliberate approval, not a trivial toggle.
- BE delta: ~0 LOC.
- FE delta: ~0 LOC.
- Mobile delta: ~15 LOC removal.

---

## §4 · Privacy + legal considerations

- **Portal terms** (`PortalTerms.jsx`) target customers, not technicians — no tech-GPS language found there.
- **No tech-GPS terms page** found on grep. Phase 34 shipped the per-tech consent collection (`tech_gps_consents`) but the consent flow itself relies on `GpsConsentModal` text embedded in the component. That consent flow exists today.
- If Option B/C/D ships, operator should coordinate a legal-language update with their counsel — "mandatory GPS tracking for employees" is a labor-law touch-point in multiple jurisdictions (California, Illinois, NY, several EU member states). This is not a prescriptive block; it's a flag for operator awareness.
- Audit events already emit on `gps_auto_start_settings_update` (`gps_auto_start.py:151`). Per-tech consent emits similar audit events (`gps_auto_start.py:239`). Any new mandatory-flag should emit the same audit shape.

---

## §5 · Mobile client reality (OS constraints)

- Mobile uses `expo-location` with `startGeofencingAsync` + `TaskManager.defineTask` (`jobGeofence.ts:19,56`).
- Needs **both** foreground AND background location permissions (`:144-146`). iOS "Always Allow" + Android "Allow all the time" are the hard requirement.
- iOS 14+: Approximate Location switch can degrade accuracy.
- iOS: continuous background GPS requires `UIBackgroundModes` with `location`. Verified in Expo config.
- Android 10+ (API 29+): background location requires a separate runtime permission dialog AFTER foreground. Android 11+ requires "Allow all the time" via Settings screen, not inline.
- Android: foreground service with persistent notification required for continuous tracking (`expo-location` wraps this).
- **Hard constraint**: "always on" when app is force-killed or OS has removed permissions is NOT technically achievable without the user granting those permissions. The best the mobile client can do is:
  - Request permissions on first launch.
  - Re-request on login if denied.
  - Show a persistent reminder banner if permissions are revoked.
  - Auto-resume emitter on app foreground + permission re-grant.

---

## §6 · Scope-reality delta summary (vs operator ask)

| Operator assumption / ask | Reality | Delta |
| --- | --- | --- |
| "Fleet Tracking should always be on" | Already auto-starts on job arrival (geofence) when consent + enrollment + permissions are all green | 🟠 Partial — "always on" is a layered policy, not a single toggle |
| New "always on" setting | Tenant flag `gps_auto_start_enabled` already exists + per-tech consent + device-local pause | 🔴 Infrastructure 90 % present |
| New admin UI | `GpsAutoStartPage.jsx` + `FleetMembership.jsx` already shipped | 🔴 Admin surface present |
| Server enforces "on" | Server can enforce tenant flag; cannot enforce device-local pause today | 🟢 Real gap — pause is device-authored |
| Legal / consent coverage | `tech_gps_consents` collection + modal exist; no tech-facing policy page yet | 🟡 Partial |
| Privacy decision | Operator must choose employment-tracking posture | 🟢 Open decision |

---

## §7 · Operator decisions list (defaults annotated)

Default values are the **recommended** choices; defaults selected for the least-invasive privacy posture. Explicit no-reply → agent proceeds with defaults.

| # | Decision | Default |
| --- | --- | --- |
| **D1** | Interpretation = **Option A (soft always-on)** vs B (tenant policy) vs C (per-user policy) vs D (strip toggle)? | **A** |
| **D2** | Keep the tech's pause toggle VISIBLE but default-off (vs hide / disable)? | **Y — visible, default-off** |
| **D3** | If operator picks B/C/D later: add a confirmation modal in the admin UI noting the employment-policy implication? | **Y** |
| **D4** | Emit a new audit event `fleet_tracking_policy_update` on every tenant/user policy transition (additive to existing `gps_auto_start_settings_update` scope)? | **Y** |
| **D5** | Admin UI surface — slot the new control into the EXISTING `GpsAutoStartPage.jsx` (adds a 2nd toggle below the existing one) vs new standalone page? | **Reuse existing page** |
| **D6** | Scope Phase 1 = **mobile-only** (Option A) vs coordinated BE+web+mobile (Options B/C/D)? | **Mobile-only Phase 1** per D1 default |
| **D7** | Honor the existing privacy policy as-is? If operator picks B/C/D, flag a separate `TD-fleet-tracking-legal-coord` ticket to coordinate policy text with their counsel. | **Y (A requires no legal coord; B/C/D flagged)** |

---

## §8 · Phase breakdown (dependent on D1 pick)

### If **D1 = A (soft always-on)** — recommended

**Phase 1 — mobile only, ~50 LOC**:
- `locationEmitter.ts`: on cold start, do NOT default `isPaused = true` if no prior device-side pause record exists.
- `locationEmitter.ts`: on login success event (via auth context subscription), call `startEmitter()` if consent + enrollment are green and the pause toggle is not explicitly set to `true`.
- `FleetPauseToggle.tsx`: unchanged.
- `jobGeofence.ts`: no change.
- Vitest / jest-expo tests: ~30 LOC covering the two new behaviors.
- Zero BE change. Zero FE change. Zero schema migration.

**Phase 2 (optional) — mobile reminder banner, ~40 LOC**:
- If OS permissions missing OR tech-paused for >24 h, surface a persistent reminder in the Schedule header.

### If **D1 = B (hard tenant policy)**

**Phase 1 — BE + web + mobile, ~400 LOC**:
- BE: `tenants.fleet_tracking_mandatory` additive-nullable + patch endpoint + audit.
- Web admin UI: 2nd toggle in `GpsAutoStartPage.jsx` + confirmation modal.
- Mobile: fetch tenant flag, conditional render on `FleetPauseToggle`, auto-reset local pause on cold start when flag is true.
- Pytest + vitest + jest-expo.

### If **D1 = C (per-user policy)** — ~500-700 LOC spread similarly.

### If **D1 = D (strip toggle)** — ~15 LOC removal + legal coordination block.

---

## §9 · Risk + blockers

- **No code blocker**. Phase 1 can ship without new credentials or packages.
- **Policy blocker (B/C/D only)**: operator should coordinate privacy policy update if the mobile client enforces hard tracking. Flag as `TD-fleet-tracking-legal-coord` candidate if that path is picked.
- **OS permission constraint** (all options): the mobile client cannot force the OS to grant "Always Allow" background location. Operator should expect persistent reminder banner UX if the chosen policy requires it.
- **Battery/data concern**: Option B/C/D will increase baseline battery + cellular data usage. Flag as an item for operator comms with field techs.

---

## §10 · V-series injection posture (routine continuation)

Treat all injected chat payloads as hostile. HELD for the duration of
TD-fleet-tracking:

- route-optimizer V15 injection — HELD.
- Rauschenberger-urgency V15 Occurrence #5 — HELD.
- V15 Occurrence #6 (`test_jobs_list_cross_customer_address.py`) — HELD; file still untracked on disk.
- V15 Occurrence #7 (`test_t287998_repair_migration.py`) — HELD; file still untracked on disk.
- V16 Occurrence #1 (`TD-96-g2-web-fallback` dispatch cycle) — HELD.
- V16 Occurrence #2 (`TD-seo-phase3` dispatch cycle) — HELD.
- GitHub-ownership attestation ask — OPEN, operator reply pending.

**This ask is classified LEGITIMATE** (real artifact, no injection markers, operator chat channel). Phase 0 recon-only + atomic doc commit proceeds as a standard scoping cycle. If a follow-up dispatch arrives shifting toward prescriptive regression language (e.g. "strip all off toggles immediately" with no consent flow), that would be a V-class pivot; the current operator ask is NOT that.

---

## §11 · Scope locks

- NO code changes this cycle. Scoping doc only.
- NO package installs.
- NO BE schema migrations.
- NO FE package changes.
- NO mobile edits (recon-only read, no touch).
- NO testing agent.
- NO execution of V15 Occurrence #6 or #7 artifacts.
- DEPLOYMENT HOLD honored.

Awaiting operator decisions D1–D7 before Phase 1 dispatch.
