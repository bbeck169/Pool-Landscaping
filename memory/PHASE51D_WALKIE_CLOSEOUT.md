# Phase 51d · Feb 2026 — Walkie-Talkie MVP closeout

Ships the last three items on the Phase 51 plan: 24 h cleanup cron
(defense-in-depth for orphan receipts + files), cross-platform parity
snapshot tests, and consolidated docs. Walkie MVP is now complete.

## Files touched (7)

| Path | Type | Notes |
|------|------|-------|
| `backend/services/walkie/cleanup_cron.py` | new | 1-min tick + `run_walkie_cleanup_once` + `register_walkie_cleanup_cron` |
| `backend/server.py` | edited (+6 lines) | wires the cleanup cron into the same `AsyncIOScheduler` singleton (see grep evidence below) |
| `backend/tests/test_phase51d_walkie_cleanup.py` | new | 6 tests (orphan sweeps + idempotency + env-flag skip + register + non-walkie safeguard) |
| `frontend/src/test/phase51d-web-mobile-parity.test.jsx` | new | 9 source-inspection assertions on shared invariants |
| `mobile/__tests__/phase51d-walkie-parity.test.ts` | new | 10 mirroring assertions on the mobile side |
| `memory/PRD.md` | prepended | consolidated Phase 51 (a → d) section |
| `CHANGELOG.md` | prepended | consolidated Phase 51 (a → d) entry |

## Cron cadence + evidence

- **Cadence:** every 1 minute (`IntervalTrigger(minutes=1)`).
- **Env flag:** `WALKIE_CLEANUP_ENABLED` — default `1` (on). Setting `=0` short-circuits the tick without a DB call.
- **Singleton evidence** (grep against `server.py`):

```
663:scheduler = AsyncIOScheduler(timezone="UTC")
1229:                from services.lana.reminder_cron import register_lana_reminders_cron
1230:                register_lana_reminders_cron(scheduler)
1235:                from services.walkie.cleanup_cron import register_walkie_cleanup_cron
1236:                register_walkie_cleanup_cron(scheduler)
```

`scheduler` is the same `AsyncIOScheduler` instance that owns the Phase 49 Lana reminder tick. No new scheduler was stood up.

Live boot log confirms registration:

```
INFO:walkie.cleanup.cron:[walkie.cleanup.cron] minute-cadence cleanup tick registered
```

## Cleanup criteria

The cron does two independent `$nin` sweeps against the DB Mongo TTL doesn't cascade into:

1. **Orphan receipts** — `walkie_receipts` rows where `message_id` is not in `walkie_messages.distinct("id")`. Fires when Mongo's TTL index evicts a message row at the 24 h mark; the receipts don't follow, so we clean them up here.
2. **Orphan walkie files** — `files` rows where `purpose == "walkie_audio"` AND `id` is not in `walkie_messages.distinct("audio_file_id")`. The `purpose` filter guarantees the sweep can only ever touch rows the walkie flow itself created — invoice PDFs, before-after photos, etc. are impossible to hit.

Idempotent: the second run against a clean state is a no-op (locked by `test_cleanup_is_noop_when_nothing_to_clean`). Logs only when it actually deletes something (`walkie cleanup: N receipts, M files`).

## Parity test approach

Two "source-inspection" files (one on each side) read the actual walkie source at test time and assert the shared invariants literally:

| Invariant | Assertion |
|-----------|-----------|
| Channel ordering | `priority = { all_hands: 0, department: 1, direct: 2 }` present in **both** helper files |
| 30 s recorder cap | `MAX_RECORD_MS = 30_000` present in **both** page files |
| `walkie_muted` persistence key | `const MUTE_KEY = "walkie_muted"` present in **both** helper files |
| `BROADCAST_ROLES` set | `{super_admin, admin, manager}` — same three roles on both sides |
| Server-parity error message | `"Only admins can broadcast to all-hands"` — literal match on both sides |
| Waveform fallback contract | both files contain the `-fallback` testID suffix |
| MIME candidates | mobile subset ⊂ backend whitelist (`webm`/`mp4`/`aac`/`mpeg`/`ogg`) |
| Shared testID manifest | `walkie-page`, `walkie-record-btn`, `walkie-message-row`, `walkie-own-tag`, `walkie-play-btn` present on both sides |

Vitest file: 9 tests. Mobile jest file: 10 tests. Any drift on either side red-lights the corresponding assertion.

## PRD + CHANGELOG diff summary

- **`memory/PRD.md`** — prepended a Phase 51 (a → d) section (~55 lines): feature scope, env flags table, native deps, API surface table, collections + indexes, sub-phase deliverables, test count deltas, sub-phase memo links, non-goals.
- **`CHANGELOG.md`** — prepended a Phase 51 consolidated entry (~50 lines): Added items, env additions, native deps, test count delta, sub-phase memos, non-goals.

## Test count delta

| Suite | Before 51d | After 51d | Δ |
|-------|-----------|-----------|---|
| Backend curated coverage gate | 162 / 163 (cov 2.79 %) | **168 / 169 (cov 2.99 %)** | **+6** cleanup tests |
| Frontend Vitest | 1306 / 1306 | **1315 / 1315** | **+9** parity tests |
| Mobile Jest | 161 / 161 | **171 / 171** | **+10** parity tests |
| Frontend ESLint | exit 0 | exit 0 | ✅ |

Sole gate failure remains `test_ai_employees_ae3.py::test_ae3_tenant_scoping_no_cross_tenant_data` (pre-existing Phase 47/48 flake, unrelated).

## Deviations from scope

None. Guardrails held:

- No `Reply with clip`, `Pinned clip`, or WebSocket push in this phase — those remain flagged for user surfacing as optional Phase 51.5+ items.
- Hotfixes untouched (`/api/config/public`, `/portal/login`, Stripe webhook alias).
- Phase 49 / 50 / 50.1 / 50.2 / 41.1b–d / 41.2 / 41.3 / 41.4 / 41.5 / 42.4 / 43 / 46 code untouched beyond the standard integration surface (`server.py` cron registration append).
- Stripe / Mapbox / Time-Off / RingCentral runtime untouched.
- Cron attached to the **existing** `AsyncIOScheduler` singleton — grep evidence above.

## Phase 51 MVP — complete

Cumulative test delta over the whole MVP (Phase 51a → 51d):

| Suite | Baseline pre-51 | End of 51d | Δ |
|-------|----------------|------------|---|
| Backend curated | 151 / 152 | **168 / 169** | **+17** |
| Vitest | 1272 / 1272 | **1315 / 1315** | **+43** |
| Mobile Jest | 132 / 132 | **171 / 171** | **+39** |
| ESLint | 0 | 0 | ✅ |

Ready for user handoff. Optional 51.5+ candidates to surface separately: WebSocket push, "Reply with clip" long-press, "Pinned clip" per-channel SOP broadcast.
