# Phase I1.7.e · Chunk 3 — Maps Callsite Migration · SHIPPED

**Status:** SHIPPED Feb-2026.
**Author:** main agent, Feb-2026.
**Predecessor doc:** `PHASE_I17E_CHUNK3_SCOPE_AUDIT.md`.
**Freeze gate:** LIFTED. Chunk 2.c hold note removed from
`PHASE_I17E_CHUNK2C_LLM_PROVIDER_CALLER_MIGRATION.md`.

---

## 1 · What shipped

All 5 user-approved decisions from the Chunk 3 audit landed:

1. **Q1 — freeze lifted.** No more hold note.
2. **Q2 — new `dispatch_maps_reverse_geocode` op** in
   `services/maps/dispatcher.py` with its own cap key
   `reverse_geocode` (added to `OPERATIONS` in
   `services/maps/models.py`). Reverse-geocode adapters are OPT-IN
   per provider — the abstract base `MapsProvider.reverse_geocode`
   returns `None` by default → dispatcher falls back to platform
   Mapbox WITHOUT charging the tenant's BYO cap.
3. **Q3 — deferred.** `migrations/task_p37_geocode_backfill.py`
   untouched.
4. **Q4 — feature flag `MAPS_BYO_ENABLED`.** Default OFF in prod,
   ON in preview `.env`. When OFF, migrated shims skip the
   dispatcher entirely and hit the raw platform httpx path —
   byte-for-byte identical to pre-Chunk-3 behavior.
5. **Q5 — `MAPS_TESTMODE_MOCK`** short-circuit path + boot
   guardrail. Guardrail refuses to boot the process when
   `MAPS_TESTMODE_MOCK=true` AND `APP_ENV=production` (fires at
   module-import time, skipped under `PYTEST_CURRENT_TEST` /
   `PYTEST_VERSION` / pytest argv so tests can flip the flag via
   `monkeypatch.setenv` without tripping it).

Behavior surface: **zero end-user changes with `MAPS_BYO_ENABLED=false`**.

---

## 2 · Files touched (17 code files + 1 test + 2 docs + 1 env)

### 2.a · New chokepoint scaffolding (4 new files)

| File | LOC | Purpose |
| ---- | --- | ------- |
| `services/maps/feature_flag.py` | 32 | `maps_byo_enabled()` env reader |
| `services/maps/testmode.py` | 178 | `is_maps_testmode`, `mock_geocode_result`, `mock_reverse_geocode_result`, `mock_route_result`, `mock_static_map_url`, boot guardrail |
| `services/maps/cap_http.py` | 78 | `is_maps_cap_exceeded`, `raise_if_maps_cap_exceeded`, `translate_tenant_maps_cap_exception` |
| `tests/test_i17e_chunk3_maps_callsite_migration.py` | 490 | 45-test invariant suite |

### 2.b · Dispatcher extensions (4 edits)

| File | Net LOC | Change |
| ---- | ------- | ------ |
| `services/maps/dispatcher.py` | +65 | Added `dispatch_maps_reverse_geocode` op + `_platform_reverse_geocode`. Refactored `_platform_geocode`/`_platform_route` to call new `_platform_*_http` helpers in the legacy modules (breaks the pre-Chunk-3 recursion risk). Every platform op short-circuits to a testmode mock envelope when `MAPS_TESTMODE_MOCK=true`. |
| `services/maps/models.py` | +1 | Added `reverse_geocode` to `OPERATIONS` and to `MapsProviderUsage` |
| `services/maps/tenant_base.py` | +7 | Added non-abstract `reverse_geocode` method → base returns `None`, dispatcher falls back to platform |
| `services/maps/__init__.py` | +25 | Re-export new helpers |

### 2.c · Legacy vendor modules → flag-gated shims (3 edits)

| File | Net LOC | Change |
| ---- | ------- | ------ |
| `services/google_maps/geocoding.py` | +40 | Extracted raw httpx into `_platform_geocode_http`. Public `geocode_address(address, *, tenant_id=None, db_conn=None)` gates on `MAPS_BYO_ENABLED` — OFF → raw platform (byte-identical); ON + `tenant_id` → `dispatch_maps_geocode`. Cap-exceeded → best-effort return `None`. |
| `services/google_maps/directions.py` | +90 | Extracted `_platform_optimize_route_http` / `_platform_compute_route_no_optimize_http`. Public `optimize_route` / `compute_route_no_optimize` gain optional `tenant_id` + `db_conn` kwargs. Same flag gate + best-effort fallback. |
| `services/reverse_geocoder.py` | +65 | Extracted `_platform_reverse_geocode_http`. Public `reverse_geocode(lat, lon, tenant_id)` gates on `MAPS_BYO_ENABLED`. Cap-exceeded → returns `{status: "cap_exceeded", cap_exceeded: True, http_status: 429}` so transactional callers can `raise_if_maps_cap_exceeded(res)`. No-token pre-flight preserved (fixes `test_missing_token_returns_no_token`). |

### 2.d · Rogue caller retired (1 edit)

| File | Net LOC | Change |
| ---- | ------- | ------ |
| `routers/property.py::maps_reverse_geocode` | −25 | Retired the inline `httpx.AsyncClient(...).get("maps.googleapis.com/…")` block. Now delegates to `services.reverse_geocoder.reverse_geocode` (dispatcher-gated). Preserves the "not configured → 200 with `available=False`" contract; adds `raise_if_maps_cap_exceeded(res)` so transactional 429 propagates. Adds `tenant: Depends(get_current_tenant)` dependency. |

### 2.e · Caller-side `tenant_id` threading (5 edits — the 10 audited callsites collapsed onto 5 files)

| File | Callsites threaded | Notes |
| ---- | ------------------ | ----- |
| `routers/directories.py` | 1 (line 226) | `_geo(addr_line, tenant_id=tenant["id"])` |
| `routers/dispatch_board.py` | 3 (optimize_route + `_directions_no_optimize` internal helper) | Threaded `tenant_id=tenant["id"]` |
| `routers/on_my_way.py` | 1 (`compute_route_no_optimize`) | Also threaded `tenant_id` through `_eta_minutes` helper signature |
| `routers/route_optimization.py` | 1 (`try_google_directions_optimize`) | `tenant_id=tenant["id"]` |
| `routers/route_optimization_approval.py` | 1 (`compute_optimization_v2`) | `tenant_id=tenant_id` |
| `services/route_optimizer.py` | infra | Added optional `tenant_id` kwarg to both `try_google_directions_optimize` and `compute_optimization_v2`, forwards to `_google` |

**Not threaded (already correct):**
- `routers/customers.py` (3× `geocode_and_persist_customer`) — inner helper already receives `tenant_id` positionally; `geocode_address` gets it via the helper's internal wiring.
- `routers/gps_live_positions.py` — `reverse_geocode(lat, lon, tenant_id)` already threaded.
- `routers/gps_route.py` — same.
- `services/gps_stops_batch.py` — same.

### 2.f · `.env` (preview)

```
MAPS_BYO_ENABLED=true     # preview default; prod default is unset/false
# MAPS_TESTMODE_MOCK=…    # left unset in preview .env — pod runs
                          # APP_ENV=production so the boot guardrail
                          # would refuse a true value here. Tests set
                          # it per-test via monkeypatch.setenv.
```

### 2.g · Memory docs

* `PHASE_I17E_CHUNK3_MAPS_CALLSITE_MIGRATION.md` (this doc — new)
* `PHASE_I17E_CHUNK2C_LLM_PROVIDER_CALLER_MIGRATION.md` § "Chunk 3 (Maps)" hold note removed.

---

## 3 · Test results

### 3.a · New Chunk 3 test file

`tests/test_i17e_chunk3_maps_callsite_migration.py` — **45/45 passed**.

Coverage classes:
* `TestMapsFeatureFlag` (7) — default/truthy/falsy env-var reader
* `TestMapsTestmode` (9) — testmode helpers, deterministic mocks, boot guardrail (prod-yes, prod-no, preview-yes)
* `TestCapHttp` (8) — 429 translation from result dicts + `TenantMapsRequestCapExceeded`
* `TestDispatcherReverseGeocode` (4) — new op registered, testmode short-circuit
* `TestFlagOffBytewiseIdentical` (2) — CRITICAL invariant: flag OFF → dispatcher NEVER invoked (dispatcher stubbed to raise)
* `TestFlagOnRoutesThroughDispatcher` (2) — flag ON → dispatcher called with `tenant_id`
* `TestCapExceededPosture` (2) — `geocode_address` best-effort `None`; `reverse_geocode` transactional `cap_exceeded` return
* `TestASTGuards` (6) — retired rogue caller AST-verified; 5 caller files thread `tenant_id` in source
* `TestP0ChecklistNoMaps` (1) — `routers/jobs.py` contains ZERO Maps callsites (P0 sibling of `test_p0_checklist_429_leak_regression`)
* `TestBYOReverseGeocodeFallback` (1) — BYO adapter returning `None` falls back to platform WITHOUT charging tenant's BYO usage row

### 3.b · Chunk 2 / 2.b / 2.c regression

* `tests/test_i17e_*` — **217 passed / 3 skipped / 0 failed**.
* `tests/test_i17c2_maps_byo_providers.py` — 14/14 passed (unchanged).

### 3.c · Legacy Maps callers regression

* `test_reverse_geocoder.py` — 5 passed / 8 failed. All 8 failures are PRE-EXISTING (motor cross-loop errors + `.env` has real `MAPBOX_ACCESS_TOKEN` set → tests that assume it's absent 403 out). Confirmed identical failure count via `git stash` diff. **Zero net regressions.**
* `test_route_optimization_google_directions.py` — 10 passed / 3 failed. All 3 failures are PRE-EXISTING 403 role-gate rejections (technician role hitting a dispatcher-only endpoint). Confirmed pre-existence via `git stash` diff. **Zero net regressions.**
* `test_route_optimizer_zip_cluster.py` — clean.
* `test_p37b_flatten_addr.py` — clean.
* `test_phase17_dispatch_board.py` — clean.
* `test_p0_checklist_429_leak_regression.py` — clean (new Maps sibling assertion added inside the Chunk 3 test file).

### 3.d · Boot verification

Backend restarted after `.env` update. Full seed pipeline completes; `/api/health` returns 200; WebSockets accept auth. No boot guardrail trip (preview `.env` intentionally omits `MAPS_TESTMODE_MOCK`).

---

## 4 · `MAPS_BYO_ENABLED=false` byte-identical invariant

The critical safety property. Verified two ways:

1. **AST guard** — `TestFlagOffBytewiseIdentical.test_geocode_address_flag_off_never_dispatches` and `test_reverse_geocode_flag_off_never_dispatches` monkeypatch the dispatcher to raise if invoked, then call the public shim with `tenant_id` supplied. When `MAPS_BYO_ENABLED=false`, the dispatcher is not touched — the shim goes straight to the raw `_platform_*_http` helper. Both tests green.

2. **Code inspection** — in each shim, the flag check is the first branch:
   ```python
   use_dispatcher = bool(tenant_id and maps_byo_enabled() and ...)
   if use_dispatcher:
       # BYO dispatcher path
   else:
       # raw platform httpx — byte-identical to pre-Chunk-3
   ```
   The `else` branch's HTTP call, response parse, and cache read/write are **verbatim the pre-Chunk-3 lines**, just extracted into `_platform_*_http` helpers.

**With `MAPS_BYO_ENABLED=true` in preview**, the caller passes `tenant_id`, the dispatcher probes for a BYO row (none in preview by default), and falls back to the platform path — same wire call, but now the dispatcher owns the log line & the `provider_used` envelope field. If a tenant IS BYO-configured (via `PUT /api/settings/tenant-maps-providers/{key}`), the dispatcher routes to that provider's adapter and enforces the tenant's monthly cap.

---

## 5 · Mobile parity brief

`grep -r "geocode_address\|reverse_geocode\|optimize_route\|compute_route_no_optimize\|dispatch_maps_" /app/mobile/src` returns nothing — the Expo mobile codebase does not import any of the migrated Python modules (it consumes them via HTTP through the backend routers). All Maps callsites on the mobile side go through the same server endpoints that the web app calls (dispatch board, on-my-way, GPS ingest). Since those routers now thread `tenant_id` into the shim layer, mobile clients benefit for free once `MAPS_BYO_ENABLED=true` in prod.

**No mobile parity work needed for Chunk 3.**

---

## 6 · Rollout runbook

**Preview (already live).** `MAPS_BYO_ENABLED=true`. All migrated shims route through the dispatcher; no tenants have BYO configured yet → platform-fallback branch fires everywhere; behavior on the wire is identical to pre-Chunk-3 aside from a couple new log lines and the `provider_used` envelope field.

**Prod flip (proposed).** Two-stage:

1. Ship with `MAPS_BYO_ENABLED` **unset** (defaults to `false`). Every migrated shim behaves byte-for-byte identical to pre-Chunk-3. Deploy, verify, soak for 1 week.
2. Flip prod `.env` → `MAPS_BYO_ENABLED=true`. `sudo supervisorctl restart backend`. Watch logs for `[maps.dispatch] tenant=... no BYO — using platform default` (expected on every existing tenant). Announce BYO opt-in to the first tenant, have them PUT their key via `POST /api/settings/tenant-maps-providers/google` + monthly cap, and verify their next optimize / reverse-geocode picks up their key (log line changes to `tenant=... using BYO`).

**Rollback.** `MAPS_BYO_ENABLED=false` + restart. Zero data changes required. No schema migration to roll back.

---

## 7 · Live-curl runbook (for the eventual BYO-enabled tenant proof)

Requires: a tenant with a Google Maps BYO row + `monthly_request_cap` set low so we can exhaust it in test. Example:

```bash
# 1) Seed the tenant BYO row (admin, encrypted key in-place).
curl -X PUT "$API/api/settings/tenant-maps-providers/google" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"api_key": "AIza…", "monthly_request_cap": 2}'

# 2) Fire two optimize calls — first two succeed, third 429.
curl -X POST "$API/api/dispatch/optimize" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"stop_customer_ids": ["c1","c2","c3"]}'
# → 200 OK

# 3) Fire again — should 429 with detail.error == "maps_spend_cap_exceeded".
curl -sD - -X POST "$API/api/dispatch/optimize" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"stop_customer_ids": ["c1","c2","c3"]}' | head -1
# → HTTP/1.1 429 Too Many Requests
```

This is HUMAN_REQUIRED — captured as the deferred smoke step, matching Chunk 2.c's precedent. No prod key was exercised in Chunk 3 shipment.

---

## 8 · Out of scope (deferred per audit §8)

* Static-map endpoint wiring — dispatcher `dispatch_maps_static_map_url` op stays healthy but has zero callers today.
* `migrations/task_p37_geocode_backfill.py` full BYO opt-in — explicitly deferred per Q3.
* Frontend usage banners / cap-exceeded UX polish — backend contract shipped; UI is a follow-up product ticket.
* Deprecating `GOOGLE_MAPS_API_KEY` platform env — must remain for tenants without BYO rows.

---

## 9 · One-line recap

Chunk 3 shipped the Maps chokepoint scaffolding + dispatcher-routing for every migrated callsite, gated behind `MAPS_BYO_ENABLED` with byte-identical fallback when off. 45 new tests / 217 i17e tests green / zero regressions vs baseline. Schedule-freeze hold LIFTED. Ready for a preview soak + prod flip when the user gives the word.
