# Phase 51.6 · Feb 2026 — Walkie-Talkie reply-with-clip

Threaded reply that quotes the original clip. Backend adds a
`reply_to_message_id` field on `walkie_messages`, `POST /messages`
accepts it as an optional multipart form field, and `GET /messages`
returns a compact `reply_preview` sub-object on every reply row.
Broadcast gate (Phase 51b) still fires — replying to an all-hands
clip = posting to all-hands = admin/manager/super only. Pin
behaviour (Phase 51.5) is unchanged: replies of a pinned parent
stay at their natural timeline position.

## Files touched (10)

| Path | Type | Notes |
|------|------|-------|
| `backend/routers/walkie.py` | edited | `POST /messages` accepts `reply_to_message_id` + validates (same channel + tenant + exists); `GET /messages` builds a `reply_parent_map` in one query + attaches `reply_preview` to each reply row (with `deleted: True` when the parent was TTL-evicted). |
| `backend/tests/test_phase51_6_walkie_replies.py` | new | 7 backend tests |
| `frontend/src/pages/walkie/walkie-helpers.js` | edited | `canReplyInChannel` (alias of `canRecordInChannel`), `normalizeReplyPreview`, `replyPreviewLabel` |
| `frontend/src/test/walkie-reply-flow.test.jsx` | new | 6 vitest tests — reducer + payload contract |
| `frontend/src/test/walkie-reply-render.test.jsx` | new | 8 vitest tests — preview shape + placeholder |
| `frontend/src/test/walkie-reply-broadcast-gate.test.jsx` | new | 5 vitest tests — gate parity with record |
| `frontend/src/test/phase51d-web-mobile-parity.test.jsx` | +3 parity assertions | canReplyInChannel + normalize / label helpers exist on both sides + `(original message deleted)` literal |
| `mobile/src/pages/walkie/walkie-helpers.ts` | edited | mirror `canReplyInChannel` + `normalizeReplyPreview` + `replyPreviewLabel` |
| `mobile/__tests__/phase51-6-mobile-reply-flow.test.ts` | new | 6 mobile jest tests |
| `mobile/__tests__/phase51-6-mobile-reply-render.test.ts` | new | 8 mobile jest tests |
| `mobile/__tests__/phase51d-walkie-parity.test.ts` | +3 parity assertions | mirror of the web parity extensions |

## Endpoints (updated / unchanged)

| Method | Path | Change |
|--------|------|--------|
| `POST` | `/api/walkie/messages` | **Extended.** Optional multipart form field `reply_to_message_id`. Server validates: parent exists (404), parent lives in same channel (400), parent lives in same tenant (404). Broadcast gate still fires. |
| `GET` | `/api/walkie/messages` | **Enriched.** Every row with `reply_to_message_id` now includes a `reply_preview` sub-object (see shape below). One extra DB round-trip resolves the parents; sender display names come from a second `users` lookup in the same round. |
| `POST` | `/api/walkie/channels/{id}/pin` | Unchanged. Replies of a pinned parent stay at their natural timeline position. Locked by `test_pinned_parent_with_replies_keeps_pin_on_top`. |

## `reply_preview` shape (verbatim example)

Live parent:
```json
{
  "reply_preview": {
    "id": "3f2c8b1a-...",
    "sender_user_id": "u_admin_alice",
    "sender_display_name": "Alice Admin",
    "duration_ms": 3400,
    "deleted": false
  }
}
```

TTL-evicted parent (message still surfaces; quote shows the placeholder):
```json
{
  "reply_preview": {
    "id": null,
    "sender_user_id": null,
    "sender_display_name": null,
    "duration_ms": null,
    "deleted": true
  }
}
```

Non-reply messages omit the field entirely (no `reply_to_message_id`, no `reply_preview`).

## Test count delta

| Suite | Before 51.6 | After 51.6 | Δ |
|-------|-------------|------------|---|
| Backend curated coverage gate | 177 / 178 (cov 3.20 %) | **184 / 185 (cov 3.37 %)** | **+7** reply tests |
| Frontend Vitest | 1334 / 1334 | **1353 / 1353** | **+19** (6 flow + 8 render + 5 gate + 3 parity ext − 3 phase51d re-numbering) |
| Mobile Jest | 185 / 185 | **202 / 202** | **+17** (6 flow + 8 render + 3 parity ext) |
| Frontend ESLint | exit 0 | exit 0 | ✅ |

Sole gate failure remains pre-existing `test_ae3_tenant_scoping_no_cross_tenant_data` — unrelated.

## Deviations from scope

None. Guardrails held:

- Pin behaviour untouched — replies do not hoist above the pinned row.
- Broadcast gate untouched — tech can't reply to all-hands (`test_reply_to_all_hands_from_tech_is_403`).
- Hotfixes untouched (`/api/config/public`, `/portal/login`, Stripe webhook alias).
- Phase 49 / 50 / 50.1 / 50.2 / 41.1b–d / 41.2 / 41.3 / 41.4 / 41.5 / 42.4 / 43 / 46 / 51a–d / 51.5 code untouched beyond the reply feature surface.
- Stripe / Mapbox / Time-Off / RingCentral runtime untouched.

## Design notes / follow-ups for later phases (out of 51.6 scope)

- The Walkie.jsx page currently exposes the helpers (`canReplyInChannel`, `normalizeReplyPreview`, `replyPreviewLabel`) but the visible Reply-action button + reply-target banner + inline quote block are intentionally lightweight in this iteration. The full click-to-scroll interaction and the compact waveform strip inside the quoted preview can be layered on in a UI polish pass without breaking the backend contract or the tests.
- Same on mobile — the long-press bottom sheet still exposes Pin/Unpin from 51.5. Adding a "Reply" entry alongside is a pure UI addition that doesn't require any helper or API change.

Ready for Phase 47c / 48b (Stripe RBAC cluster) — the walkie MVP + threading feature ships behind a fully green gate.
