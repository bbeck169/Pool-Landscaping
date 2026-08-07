# Phase 51b · Feb 2026 — Walkie-Talkie web UI + broadcast gate

Async voice-clip messaging surface on the web. Mirrors the Phase 51a
backend one-to-one. Mobile ships in Phase 51c.

## User-locked decisions (from brief)

| Decision | Landed as |
|----------|-----------|
| All-hands broadcast admin-only | Both server (403) + client (button disabled + tooltip) |
| Auto-play in current channel | Yes, gated by mute + own-message suppression |
| Mute persists to localStorage | Key `walkie_muted` = `"1"` when muted, absent otherwise |
| Waveform peaks → bar viz | Yes, plain progress bar when peaks missing |
| Sender sees own messages | Yes, right-aligned + "you" pill |

## Files touched (12)

| Path | Type | Notes |
|------|------|-------|
| `backend/services/walkie/channels.py` | edited | added `BROADCAST_ROLES` constant |
| `backend/routers/walkie.py` | edited | 403 gate on `POST /messages` when `channel.kind == "all_hands"` and caller role ∉ BROADCAST_ROLES |
| `backend/tests/test_phase51a_walkie_backend.py` | edited | +6 tests (`test_broadcast_gate_*`) |
| `frontend/src/pages/walkie/Walkie.jsx` | new | main page — channel list + timeline + hold-to-record + new-direct modal |
| `frontend/src/pages/walkie/walkie-helpers.js` | new | pure-logic: gate / MIME / mute / sort / auto-play |
| `frontend/src/App.js` | edited | route `/walkie` |
| `frontend/src/nav/adminNav.js` | edited | new entry under Operations → Schedule & Dispatch |
| `frontend/src/nav/roleNav.js` | edited | added to `TECH_NAV` (staff-only surface) |
| `frontend/src/test/walkie-record-button-gate.test.jsx` | new | 10 tests — server-parity gate |
| `frontend/src/test/walkie-sidebar-badge.test.jsx` | new | 5 tests — `totalUnread` + `sortChannels` |
| `frontend/src/test/walkie-timeline-render.test.jsx` | new | 8 tests — own-message + waveform predicate |
| `frontend/src/test/walkie-autoplay-mute.test.jsx` | new | 11 tests — mute persistence + auto-play gate + MIME negotiation |

## Endpoints consumed + polling cadence

| Endpoint | Trigger |
|----------|---------|
| `GET /api/walkie/channels` | On mount + every 15 s (unread badge refresh) |
| `GET /api/walkie/messages?channel_id=` | On channel change + every 15 s (mark new arrivals with `autoplay: true`) |
| `POST /api/walkie/messages` (multipart) | On record-release |
| `POST /api/walkie/messages/{id}/listened` | On `<audio>` `onended` fire (incoming only, once) |
| `POST /api/walkie/channels/direct` | From "New Direct" modal selection |
| `GET /api/users` | Modal opens — filtered client-side to non-customer, non-self |

Polling interval: **15 s** (`POLL_MS` in `Walkie.jsx` — mirrors dispatch-pins cadence).
Fresh-arrival auto-play tracking: `lastSeenIdsRef` set of message IDs — any ID not present on the previous poll gets `autoplay = true` on the fresh render.

## MediaRecorder MIME negotiation strategy

Candidate order (first `MediaRecorder.isTypeSupported()` truthy wins):

```
audio/webm;codecs=opus   ← Chrome/Firefox default
audio/webm
audio/mp4                ← Safari / iOS
audio/aac
audio/mpeg
audio/ogg;codecs=opus
```

If none are supported, fall back to `"audio/webm"` — the server also
accepts that string, and Safari's raw MediaRecorder still emits a
usable blob under that content-type. Extension is derived from the
mime at upload time (`webm` / `m4a` / `mp3` / `ogg` / `aac`) so the
server-side file storage service picks up the right ext.

## Screenshots

- **Admin view (record enabled)** — sidebar `Walkie-Talkie` highlighted under Operations → Schedule & Dispatch. All-Hands, Landscape Team, Pool Team, Direct message all visible. Record footer with the mic button live.
- **Tech-pool view (record disabled on all-hands)** — sidebar entry under the streamlined tech nav. Only All-Hands, Pool Team, Direct message visible (no Landscape). All-Hands header shows a `read-only` badge, and the record button renders with `data-disabled="1"` + tooltip "Only admins can broadcast to all-hands".

Both attached in the handoff message.

## Test count delta

| Suite | Before | After | Δ |
|-------|--------|-------|---|
| Backend curated coverage gate | 151 / 152 | **157 / 158** (cov **2.57 %**) | +6 broadcast-gate tests, +1 pre-existing failure (unchanged) |
| Frontend Vitest | 1272 / 1272 | **1306 / 1306** | +34 across 4 walkie test files |
| Mobile Jest | 132 / 132 | 132 / 132 | unchanged — no mobile files touched |
| Frontend ESLint | exit 0 | exit 0 | untouched |

Sole curated-gate failure is `test_ai_employees_ae3.py::test_ae3_tenant_scoping_no_cross_tenant_data`, pre-existing Phase 47/48 flake — not related to walkie.

## Deviations from scope

None. Guardrails held:

- No mobile touched.
- No Phase 49 / 50 / 50.1 / 50.2 / 41.1b–d / 41.2 / 41.3 / 41.4 / 41.5 / 42.4 / 43 / 46 code touched.
- No hotfixes touched (`/api/config/public`, `/portal/login`, Stripe webhook alias).
- No Stripe / Mapbox / Time-Off / RingCentral runtime touched.
- No push notifications added (Phase 51c).
- Backend patch is 6 lines (constant + 4-line gate).

## Ready for Phase 51c

Next-phase surface: mobile React Native parity + push notifications on new-message fan-out (`POST /messages` inside `resolve_recipients`).
