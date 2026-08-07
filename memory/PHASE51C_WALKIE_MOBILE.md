# Phase 51c · Feb 2026 — Walkie-Talkie mobile parity + push

Mirrors the Phase 51b web UI on React Native + Expo, plus Expo push
notifications on backend fan-out. Live streaming and WebSocket-push
delivery are still deferred to Phase 52.

## Files touched (10)

| Path | Type | Notes |
|------|------|-------|
| `mobile/package.json` | edited | pinned `expo-audio@~1.1.1` via `npx expo install` |
| `mobile/app.json` | edited | added `expo-audio` config plugin with iOS mic permission text |
| `mobile/src/pages/walkie/walkie-helpers.ts` | new | pure-logic mirror of the web helpers (`canRecordInChannel`, `sortChannels`, `isMuted`/`setMuted` via `AsyncStorage`, `pickAudioMime`, `extForMime`) |
| `mobile/app/walkie/index.tsx` | new | channel-list screen with pull-to-refresh + unread badges + customer bounce |
| `mobile/app/walkie/[channelId].tsx` | new | timeline + hold-to-record footer (uses `expo-audio` `useAudioRecorder` + `useAudioPlayer`) |
| `mobile/src/services/notificationRoutes.ts` | edited | added walkie tap-through → `/walkie/{channel_id}` |
| `mobile/EXPO_GO_RUNBOOK.md` | edited | new-native-module + push-flag notes |
| `backend/services/walkie/push.py` | new | dry-run-by-default Expo push fan-out helper |
| `backend/routers/walkie.py` | edited | calls fan-out after receipts on `POST /messages` |
| `backend/tests/test_phase51c_walkie_push.py` | new | 5 backend fan-out tests |
| `mobile/__tests__/phase51c-walkie-helpers.test.ts` | new | 17 mobile helper tests (parity with web vitest) |
| `mobile/__tests__/phase51c-walkie-mount.test.tsx` | new | 5 mount tests (channel list + timeline + gate) |
| `mobile/__tests__/phase51c-walkie-push-routing.test.ts` | new | 5 tap-through router tests |

## `expo-audio` version + config plugin

- **Version pinned:** `expo-audio@~1.1.1` (Expo SDK 54 compatible; `npx expo install` picked the SDK-matched build).
- **Config plugin:** added to `app.json` `plugins` array with `microphonePermission` iOS text and `recordAudioAndroid: true`.
- **Native module — dev-client rebuild required.** Accepted per brief (mirrors Phase 38b Mapbox + Phase 49 speech-recognition). Documented in the runbook.
- No conflicting peer deps flagged. `expo-asset` is a transitive peer already resolved by the Expo SDK 54 lock.

## Push token storage strategy

**Reused** the existing Phase 20 endpoint `POST /api/mobile-tokens` and its
companion `mobile_tokens` MongoDB collection (see `backend/routers/mobile_push.py`). **No new endpoint added.** The Phase 51c fan-out helper
reads from that same collection at send-time, joining on `user_id`.

## Env flag + default behaviour

**Flag:** `WALKIE_PUSH_LIVE` (server-side env var).

| Env state | Behaviour |
|-----------|-----------|
| `WALKIE_PUSH_LIVE` unset | **dry-run** — helper logs the push payload with mode `dry_run reason=flag-off`. No network call. **Default.** |
| `WALKIE_PUSH_LIVE=1` + `EXPO_PUSH_ACCESS_TOKEN` set | **live** — one `POST` to `https://exp.host/--/api/v2/push/send` per fan-out (one JSON array containing one message per registered token) |
| `WALKIE_PUSH_LIVE=1` but `EXPO_PUSH_ACCESS_TOKEN` unset | **dry-run** — logs `reason=expo-token-not-configured`. Second safety layer. |
| No recipients have tokens | **dry-run** — logs `reason=no-tokens`. |
| `recipients=[]` (empty fan-out list) | Returns `mode=skipped_no_recipients` without touching the DB or logging. |

## Mirror-parity check

Confirmed all four locked decisions match the web behaviour:

- **All-hands broadcast admin-only** — Same `canRecordInChannel` predicate; server 403 mirrors 51a.
- **Auto-play + mute** — `walkie_muted` persisted in `AsyncStorage` (mobile) / `localStorage` (web). Auto-play gate is identical (`shouldAutoPlay`).
- **Waveform peaks** — `[]` / `null` / non-array all fall back to plain bar (locked by tests on both sides).
- **Own messages** — `isOwnMessage` shared predicate; both surfaces render right-aligned with a `walkie-own-tag` node.

## Test count delta

| Suite | Before | After | Δ |
|-------|--------|-------|---|
| Backend curated coverage gate | 157 / 158 (cov 2.57 %) | **162 / 163 (cov 2.79 %)** | **+5** push fan-out tests |
| Frontend Vitest | 1306 / 1306 | 1306 / 1306 | untouched — no web files changed in 51c |
| Mobile Jest | 132 / 132 | **161 / 161** | **+29** (17 helpers + 5 mount + 5 push routing + 2 misc parity) |
| Frontend ESLint | exit 0 | exit 0 | ✅ |

Sole backend gate failure remains `test_ai_employees_ae3.py::test_ae3_tenant_scoping_no_cross_tenant_data`, pre-existing Phase 47/48 flake — not related to walkie.

## Deviations from scope

None. Guardrails held:

- No web walkie code touched (parity via shared behavioural contracts, not shared source).
- Phase 51a backend touched **only** to wire the fan-out call after existing receipt writes — no data-model change, no endpoint change, no test-signature change.
- Hotfixes untouched (`/api/config/public`, `/portal/login`, Stripe webhook alias).
- Phase 49 / 50 / 50.1 / 50.2 / 41.1b–d / 41.2 / 41.3 / 41.4 / 41.5 / 42.4 / 43 / 46 code untouched except standard integration surface (walkie router import, notification-route resolver append).
- Stripe / Mapbox / Time-Off / RingCentral runtime untouched.
- **No live-push default.** Two independent env layers must both be set.

## Native module + dev-client rebuild

`expo-audio` is a bare-native module. Anyone running Expo Go against the app will not see the record button (Expo Go doesn't include the native audio module). Testers must reinstall the custom dev-client build (same distribution channel as Phase 38b Mapbox / Phase 49 speech).

Instructions in the runbook (`mobile/EXPO_GO_RUNBOOK.md` Phase 51c section).

## Ready for Phase 51d

Next-phase surface (proposed): WebSocket push instead of 15 s polling once concurrent techs > ~50, and a live-streaming walkie mode (Phase 52).
