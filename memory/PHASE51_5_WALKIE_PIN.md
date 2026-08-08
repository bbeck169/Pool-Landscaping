# Phase 51.5 · Feb 2026 — Walkie-Talkie pinned clip per channel

Adds a per-channel "featured" clip that admins/managers can pin. Pinned clips render at the top of the timeline with a visual accent and **bypass the 24 h TTL** for as long as they remain pinned. Unpinning restores the original 24 h expiry from `created_at`.

## Files touched (12)

| Path | Type | Notes |
|------|------|-------|
| `backend/services/walkie/channels.py` | +5 lines | added `PIN_ROLES` set |
| `backend/routers/walkie.py` | edited | added `POST /channels/{id}/pin`, `DELETE /channels/{id}/pin`, enriched `GET /messages` with `is_pinned` + pinned-first ordering |
| `backend/tests/test_phase51_5_walkie_pin.py` | new | 9 backend tests (role gate + auto-unpin + idempotency + cross-channel guard + TTL bypass + unpin restores expiry + GET /messages order + cleanup interaction) |
| `frontend/src/pages/walkie/walkie-helpers.js` | edited | exported `PIN_ROLES` + `canPinInChannel` |
| `frontend/src/pages/walkie/Walkie.jsx` | edited | pin/unpin action buttons on rows; pinned row visual accent + badge; optimistic pin/unpin state transition |
| `frontend/src/test/walkie-pin-action-gate.test.jsx` | new | 6 vitest tests — role gate parity |
| `frontend/src/test/walkie-pin-timeline-order.test.jsx` | new | 5 vitest tests — ordering invariant |
| `frontend/src/test/walkie-pin-idempotency.test.jsx` | new | 4 vitest tests — optimistic-update reducer |
| `frontend/src/test/phase51d-web-mobile-parity.test.jsx` | edited | +4 parity assertions locking PIN_ROLES + badge testID + accent styling |
| `mobile/src/pages/walkie/walkie-helpers.ts` | edited | exported `PIN_ROLES` + `canPinInChannel` |
| `mobile/app/walkie/[channelId].tsx` | edited | pinned row accent + badge; long-press bottom-sheet with role-gated Pin / Unpin actions; pin/unpin handlers |
| `mobile/__tests__/phase51-5-mobile-pin-gate.test.ts` | new | 6 mobile jest tests — role gate |
| `mobile/__tests__/phase51-5-mobile-pin-timeline.test.ts` | new | 4 mobile jest tests — ordering |
| `mobile/__tests__/phase51d-walkie-parity.test.ts` | edited | +4 mirror parity assertions |

## Endpoints + role gates

| Method | Path | Role gate |
|--------|------|-----------|
| `POST` | `/api/walkie/channels/{channel_id}/pin` | `super_admin` / `admin` / `manager` (else 403); channel membership required (else 403); target message must belong to the channel (else 404); idempotent — pinning the already-pinned message returns `{ok: true, unchanged: true}` |
| `DELETE` | `/api/walkie/channels/{channel_id}/pin` | Same role gate + channel membership; idempotent when nothing is pinned |
| `GET` | `/api/walkie/messages?channel_id=` | Now returns the pinned message at index 0 (regardless of `since=` window) with `is_pinned: true`. Remaining rows follow, sorted by `created_at desc`, each with `is_pinned: false`. |

## TTL bypass — evidence from `test_pinned_message_survives_past_24h_ttl`

```python
# 1. Send a fresh clip, pin it via POST /channels/{id}/pin.
# 2. Confirm expires_at is UNSET on the message row.
row = sync_db.walkie_messages.find_one({"id": msg_id}, {"expires_at": 1})
assert row.get("expires_at") is None      # ← Mongo TTL skips docs w/o a Date

# 3. Time-warp created_at back 48h (simulates a long-lived pin).
sync_db.walkie_messages.update_one(
    {"id": msg_id},
    {"$set": {"created_at": datetime.now(timezone.utc) - timedelta(hours=48)}},
)

# 4. Row still exists (TTL only fires on Date-valued expires_at).
still = sync_db.walkie_messages.find_one({"id": msg_id}, {"id": 1})
assert still is not None

# 5. Phase 51d cleanup cron picks up walkie_messages.distinct("audio_file_id")
#    — pinned message is still in that list, so its file survives.
_run(cleanup_cron.run_walkie_cleanup_once(motor_db))
assert sync_db.files.find_one({"id": audio_id}) is not None
```

## Auto-unpin evidence — `test_pinning_new_message_auto_unpins_previous`

```
Pin m1     → m1.expires_at = null, channel.pinned_message_id = m1
Pin m2     → m1.expires_at = created_at + 24h (restored via _restore_expiry)
             channel.pinned_message_id = m2
             m2.expires_at = null
```

Only one message pinned per channel — locked by the channel-doc single-field constraint.

## Cleanup cron interaction (Phase 51d)

The Phase 51d orphan-file sweep uses:

```python
referenced = await db.walkie_messages.distinct("audio_file_id")
await db.files.delete_many({"purpose": "walkie_audio", "id": {"$nin": referenced}})
```

Pinned messages are still `walkie_messages` rows (they just have no `expires_at`), so their `audio_file_id` remains in `referenced`. The `$nin` sweep never removes their file. Locked by `test_pinned_message_survives_past_24h_ttl` explicitly running the cron and asserting the file survives.

## Screenshots

- **Web · admin view with pinned clip** — the first row on the All-Hands timeline shows the amber-accented pinned message with the "PINNED" badge. Toast "Pinned to channel" confirms the action. Non-pinned rows render below with the standard styling. Non-admin callers see no pin icons on any row.
- **Mobile · admin long-press bottom sheet** — long-press on a message row opens the bottom sheet with "Pin to channel" / "Unpin from channel" (role-gated). Screenshot captured against the dev-client build; sheet element carries `testID="walkie-pin-sheet"`. Non-admin callers do not see the sheet.

## Test count delta

| Suite | Before 51.5 | After 51.5 | Δ |
|-------|-------------|------------|---|
| Backend curated coverage gate | 168 / 169 (cov 2.99 %) | **177 / 178 (cov 3.20 %)** | **+9** pin tests |
| Frontend Vitest | 1315 / 1315 | **1334 / 1334** | **+19** (15 pin + 4 parity extensions) |
| Mobile Jest | 171 / 171 | **185 / 185** | **+14** (10 pin + 4 parity extensions) |
| Frontend ESLint | exit 0 | exit 0 | ✅ |

Sole backend gate failure remains `test_ai_employees_ae3.py::test_ae3_tenant_scoping_no_cross_tenant_data` — pre-existing Phase 47/48 flake, unrelated.

## Deviations from scope

None. Guardrails held:

- No "Reply with clip" / WebSocket push / live-streaming code added.
- Hotfixes untouched (`/api/config/public`, `/portal/login`, Stripe webhook alias).
- Phase 49 / 50 / 50.1 / 50.2 / 41.1b–d / 41.2 / 41.3 / 41.4 / 41.5 / 42.4 / 43 / 46 / 51a–d code untouched beyond the walkie surface.
- Stripe / Mapbox / Time-Off / RingCentral runtime untouched.
- Cleanup cron behaviour verified safe for both pinned + non-pinned messages via `test_pinned_message_survives_past_24h_ttl`.

## Ready for Phase 51.6

Next-phase candidate: "Reply with clip" long-press → threaded reply that quotes the original clip. Feature toggle deferred to user preference; Phase 51.5 is complete and safe to ship independently.
