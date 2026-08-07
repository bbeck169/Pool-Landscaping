# Phase 51a · Feb 2026 — Walkie-Talkie backend foundation

Async 5-30s voice-clip MVP. Web + mobile parity is deferred; this
phase is strictly backend + tests. Live streaming lands in Phase 52,
mobile push in Phase 51c.

## Files touched

| Path | Type | Notes |
|------|------|-------|
| `backend/services/walkie/__init__.py` | new | package marker |
| `backend/services/walkie/channels.py` | new | membership + auto-provision + `ensure_indexes` |
| `backend/routers/walkie.py` | new | 5 REST endpoints (see below) |
| `backend/server.py` | edited | imports the router + wires `ensure_indexes` + tenant bootstrap into the startup chain |
| `backend/tests/test_phase51a_walkie_backend.py` | new | 15-test regression suite |

## Endpoints (all under `/api/walkie`)

| Method | Path | Auth-gating |
|--------|------|-------------|
| `GET` | `/channels` | staff-only (super_admin / admin / manager / owner / dispatcher / technician). admin+ see all-hands + BOTH dept channels + own directs; technicians see all-hands + own dept + own directs; customer → **403** |
| `POST` | `/channels/direct` | staff-only; target must be non-customer; **idempotent** on sorted pair |
| `POST` | `/messages` | multipart; member-of-channel; ≤ 30s; ≤ 2 MB; MIME ∈ {`audio/webm`, `audio/mp4`, `audio/aac`, `audio/mpeg`, `audio/ogg`}; fan-out one receipt per recipient (excludes sender) |
| `GET` | `/messages?channel_id&since&limit` | member-of-channel; scoped to caller (sender OR recipient); default window = last 24h |
| `POST` | `/messages/{id}/listened` | idempotent; 404 when caller has no receipt |

## Test count delta

- `backend/tests/test_phase51a_walkie_backend.py` — **15** tests (all pass, 6.96 s in isolation).
- Coverage of the new file: **99 %** (129 / 130 stmts).
- Curated CI gate (10 files) — **151 / 152 passed**, coverage **2.51 %** ≥ floor 2 % → PASS.
  - Sole failure: `test_ai_employees_ae3.py::test_ae3_tenant_scoping_no_cross_tenant_data` — pre-existing (Phase 47/48 cluster), unchanged by Phase 51a.

## TTL index verification

```
db.walkie_messages.index_information()
_id_                                              : {'v': 2, 'key': [('_id', 1)]}
tenant_id_1_channel_id_1_created_at_-1            : {'v': 2, 'key': [('tenant_id', 1), ('channel_id', 1), ('created_at', -1)]}
expires_at_1                                      : {'v': 2, 'key': [('expires_at', 1)], 'expireAfterSeconds': 0}   ← TTL, 24h-native enforcement
```

Companion collections:

```
db.walkie_channels.index_information()
tenant_id_1_kind_1
tenant_id_1_department_1
tenant_id_1_member_user_ids_1

db.walkie_receipts.index_information()
tenant_id_1_recipient_user_id_1_listened_at_1
message_id_1
```

## `resolve_recipients` return shape

Function: `services.walkie.channels.resolve_recipients(channel, sender_id, db) -> list[str]`.

- **all_hands** — every active staff user_id in the tenant, minus sender.
- **department** — every active staff user_id in the tenant whose
  `users.department` matches (alias-normalised: `landscaping` → `landscape`), minus sender.
- **direct** — the frozen `channel.member_user_ids` list, minus sender.

Example (all_hands, aquaterra tenant, sender = super@):

```python
["e6...admin", "40...manager", "3e...tech_pool_mike", "aa...tech_landscaper", ...]
```

Membership is expanded **at send-time**, so if a technician joins the
department after a clip is posted, they will still see the historical
clip on their next `GET /messages` (unread count is derived from
receipt rows, and receipts are written for the live recipient set at
send-time).

## Gate status

| Gate | Before Phase 51a | After Phase 51a |
|------|------------------|------------------|
| Backend curated coverage gate | 155 / 157, cov 23.35 % | **151 / 152, cov 2.51 %** (added walkie tests; cov denominator recalibrated per Phase 42.4) — PASS |
| `test_phase51a_walkie_backend.py` (isolated) | — | **15 / 15 PASS**, 6.96 s |
| Frontend Vitest | 1272 / 1272 | untouched — no frontend files changed |
| Mobile Jest | 132 / 132 | untouched — no mobile files changed |
| Frontend ESLint | exit 0 | untouched |

## Deviations from scope

None. Guardrails held:

- Backend only. No frontend, mobile, or push code.
- Hotfixes (`/api/config/public`, `/portal/login`, Stripe webhook alias) untouched.
- Phase 49 / 50 / 50.1 / 50.2 / 41.1b / 41.1c / 41.1d / 41.2 / 41.3 / 41.4 / 41.5 / 42.4 / 43 / 46 code paths untouched except the standard integration surface (`server.py` startup chain, `models.py` — the walkie models live in `services/walkie/channels.py` alongside the resolvers per repo convention, not `models.py`, since `models.py` is a Pydantic-only file).
- Stripe / Mapbox / Time-Off / RingCentral runtime untouched.
- Reused existing `/api/files/` upload via `services.file_storage.put_object` — no new storage stack.

## Design notes worth flagging for Phase 51b

- Test file uses `requests` against the live uvicorn server (mirrors
  `test_phase56_20_auto_email.py`, `test_widget_gh0.py`) instead of
  `TestClient`. Reason: `TestClient`'s per-request anyio-portal
  spawns short-lived event loops which Motor's client latches onto
  then can't reuse — the `Phase 41.1d` conftest rebind hook keeps
  the standalone-vitest style batch green but overwrites Motor's
  loop before `TestClient.__enter__()` fires the FastAPI startup
  handler, tripping `MongoDB ping FAILED at startup: Event loop is
  closed`. `requests` sidesteps that entirely.
- Department normalisation: seeded user rows use
  `department="landscaping"` whereas the walkie brief locks the field
  to `pool` | `landscape`. `services.walkie.channels._DEPARTMENT_ALIASES`
  maps `landscaping → landscape` at read-time so no user-doc
  migration is needed. Phase 51b should render both spellings
  consistently on the frontend.

Ready to hand back for Phase 51b (web + mobile UI) verification.
