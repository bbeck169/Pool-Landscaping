# Phase I1.7.e · Chunk 3 — Maps Callsite Migration · SCOPE AUDIT

**Status:** AUDIT ONLY — nothing implemented. No files touched outside `/app/memory/`.
**Ship gate:** Blocked. User disposition required on the Chunk 2.c note (Feb-2026):
> "Chunk 3 (Maps) — held pending schedule-freeze root-cause. Do not touch."
> (source: `memory/PHASE_I17E_CHUNK2C_LLM_PROVIDER_CALLER_MIGRATION.md`, §5, line 114.)
> No other document in `memory/` mentions this blocker; owner/RCA link not found. **Ask user** whether the freeze RCA is landed or the guardrail should be lifted before Chunk 3 kicks off.

**Owner:** i17e-maps (main agent, TBD)
**Author of audit:** main agent, Feb-2026 handoff continuation
**Prereqs:** Chunk 1 (messaging), Chunk 2 (AI llm_provider chokepoint), Chunk 2.b (raw-SDK AI 21 files), Chunk 2.c (7 llm_provider callers) — all shipped and green.

---

## 1 · Mission

Route every real Maps callsite in the backend through the BYO-aware Maps dispatcher (`services.maps.dispatcher.dispatch_maps_geocode`, `.dispatch_maps_route`, `.dispatch_maps_static_map_url`) so:

1. **BYO opt-in** — when a tenant has a `tenant_maps_provider` row (Google or Mapbox), their key is used; else the platform Google/Mapbox key is used (rule 1 parity with AI dispatcher).
2. **Per-tenant Maps cap enforcement** fires everywhere (rule 2 = HARD BLOCK at 100 %, soft warn at 80 %, mirror the AI + calendars pattern already shipped in `services.maps.usage`).
3. **`MAPS_TESTMODE_MOCK`** (new env flag, mirror of `AI_TESTMODE_MOCK` / `MESSAGING_TESTMODE_MOCK` / `CALENDARS_TESTMODE_MOCK`) short-circuits the last-mile HTTP call on both legacy modules and BYO adapters.
4. **429 propagation** — transactional Maps callers (`POST /maps/*`, dispatch-board optimize, on-my-way ETA) surface `raise_if_maps_cap_exceeded(...)` → HTTP 429. Scheduled / best-effort callers (reverse-geocode-backfill cron, GPS ingest, geocode_and_persist migrations) log `skipped_cap_exceeded` and continue.

**Behavior surface:** zero end-user changes on the happy path. Zero schema changes. Zero new routes. Return shapes preserved 1:1.

---

## 2 · Current state (what already exists)

### 2.1 · BYO dispatcher (shipped Chunk c2, GREEN)

Location: `backend/services/maps/`
* `dispatcher.py` (256 lines) — `dispatch_maps_geocode`, `dispatch_maps_route`, `dispatch_maps_static_map_url`.
* `registry.py` (80 lines) — Google + Mapbox provider registration.
* `tenant_base.py` / `google_maps_provider.py` / `mapbox_provider.py` — BYO adapters.
* `usage.py` (174 lines) — per-tenant cap + soft-warn helpers.
* `models.py` (118 lines) — `MapsGeocodeResult`, `MapsRouteResult`, `MapsStaticMapURL`, `MapsUsageCapExceeded`, envelope shapes.

**Regression suite:** `tests/test_i17c2_maps_byo_providers.py` — **14 tests passing**, covering registry, PUT/DELETE encrypted-key admin endpoints, dispatcher tenant selection, cap semantics (unlimited / 0 / hard-block / soft-warn), OpenAPI surface.

### 2.2 · Legacy Maps callsites (NOT routed through dispatcher yet)

These bypass BYO entirely — they read a platform env var and hit the vendor HTTP endpoint directly. Chunk 3 = migrate each of them to `services.maps.dispatcher.dispatch_maps_*`.

| # | Legacy module | Public entrypoints | LOC | Vendor | Notes |
| - | ------------- | ------------------ | --- | ------ | ----- |
| 1 | `services/google_maps/geocoding.py` | `geocode_address`, `geocode_and_persist_customer`, `geocode_and_persist_job`, `geocode_and_persist_property` | 269 | Google Geocoding v1 (`maps.googleapis.com/maps/api/geocode/json`) | Reads `GOOGLE_API_KEY` from env. In-DB dedupe cache. |
| 2 | `services/google_maps/directions.py` | `optimize_route`, `compute_route_no_optimize` | 153 | Google Routes v2 (`routes.googleapis.com/directions/v2:computeRoutes`) | Reads `GOOGLE_API_KEY`. |
| 3 | `services/reverse_geocoder.py` | `reverse_geocode`, `mapbox_token_configured`, `purge_expired_geocode_cache`, `ensure_indexes` | 230 | Mapbox v5 Geocoding (`api.mapbox.com/geocoding/v5/mapbox.places`) | Reads `MAPBOX_ACCESS_TOKEN`. In-DB `reverse_geocode_cache` collection (TTL). |
| 4 | `routers/property.py::maps_reverse_geocode` (GET `/api/maps/reverse-geocode`) | one inline callsite, direct `httpx` to Google — bypasses (1) AND (3) | ~30 (inline block) | Google Geocoding v1 | Rogue direct-httpx caller. Discovered during audit; MUST be brought into the migration or explicitly excluded. |

### 2.3 · Callers that will need `tenant_id` threading (13 files)

The migration threads `tenant_id` through each caller so the dispatcher can look up the tenant's BYO row + enforce their cap.

| # | Caller file | Callsites | Path kind | Cap-exceeded posture (proposed) |
| - | ----------- | --------- | --------- | ------------------------------- |
| 1 | `routers/customers.py` | 3 (lines 1408, 2025, 4115) — `geocode_and_persist_customer` after customer CREATE / UPDATE / IMPORT | Transactional (customer-write side-effect) | Best-effort: log `skipped_cap_exceeded`, do NOT block the customer write. |
| 2 | `routers/directories.py` | 1 (line 223) — `geocode_address` for directory lookup | Transactional | Best-effort: return the un-geocoded row with `geocode_status="cap_exceeded"`. |
| 3 | `routers/dispatch_board.py` | 4 (lines 507 `optimize_route`, 558 `compute_route_no_optimize`, 616 & 715 `geocode_and_persist_customer`) | Transactional (user clicked "optimize") | Route ops → 429; geocode side-effect → best-effort. |
| 4 | `routers/gps_live_positions.py` | 1 (line 141) — `reverse_geocode` for live tech position | Scheduled/live-update (WebSocket push helper) | Best-effort: return coords without street. |
| 5 | `routers/gps_route.py` | 1 (line 239) — `reverse_geocode` inside `reverse_geocode_backfill` job | Scheduled (backfill loop) | Log `skipped_cap_exceeded` + break loop for that tenant. |
| 6 | `routers/gps_settings.py` | 1 (line 107) — `mapbox_token_configured()` for admin banner | Read-only status check | N/A — no HTTP call to Mapbox on this path. |
| 7 | `routers/on_my_way.py` | 1 (line 152) — `compute_route_no_optimize` for customer ETA | Transactional (customer-facing) | 429 to the customer-facing route; UI already handles fallback per the existing timeout branch. |
| 8 | `routers/property.py` | 1 (line 541 rogue `maps_reverse_geocode`) — inline httpx | Transactional | 429 on cap-exceeded, keep the existing "not configured" fallback. |
| 9 | `services/gps_stops_batch.py` | 1 (line 121) — `reverse_geocode` inside stop-batching cron | Scheduled | Log `skipped_cap_exceeded`, keep stop rows w/ empty address. |
| 10 | `services/route_optimizer.py` | 1 (line 268) — `optimize_route` fallback path (Google) | Transactional | 429; caller already handles the fallback branch to internal solver. |
| 11 | `services/maps/dispatcher.py` | Currently calls back into (1), (2), (3) for its **platform** fallback path. Needs re-anchoring so those legacy modules do NOT re-enter the dispatcher (avoid infinite recursion). | Infra | Structural — see §4.2. |
| 12 | `migrations/task_p37_geocode_backfill.py` | 3 (lines 73, 85, 97) — `geocode_and_persist_customer/job/property` | Migration script (one-shot) | Optional to route through dispatcher; safest to keep on platform key + emit `skipped_cap_exceeded` for tenants with `monthly_cap=0`. |
| 13 | `server.py` | reverse_geocode_cache cron registration only (no callsite) | N/A | No change needed. |

**Total files with real callsites: 10** (excluding `services/maps/dispatcher.py` infra edit, `server.py` no-op, migration script).

### 2.4 · Test surfaces already in place

* `tests/test_i17c2_maps_byo_providers.py` — 14/14 pass. Dispatcher contract, cap semantics, admin endpoints.
* `tests/test_reverse_geocoder.py` — Mapbox legacy path in isolation.
* `tests/test_gps_ingest.py`, `tests/test_gps_settings.py` — GPS callers touching Mapbox.
* `tests/test_p37b_flatten_addr.py`, `tests/test_phase17_dispatch_board.py` — geocoding callers.
* `tests/test_p0_checklist_429_leak_regression.py` — P0 invariant covers the checklist load path (no AI, no messaging today; will need a Maps sibling assertion added in Chunk 3).

**No test currently asserts the legacy modules route through the BYO dispatcher.** That's the primary Chunk 3 test-coverage gap.

---

## 3 · Exact file list (with LOC estimates)

### 3.1 · Dispatcher extension (1 file, additive)

| File | Δ LOC (est) | Change |
| ---- | ----------- | ------ |
| `services/maps/dispatcher.py` | +40 | Add `MAPS_TESTMODE_MOCK` env-flag branch in `_platform_geocode`, `_platform_route`, `_platform_static_map_url` — deterministic envelopes tagged `provider_used="platform:{google|mapbox}_testmode_mock"`. Add same short-circuit at the BYO branch so `dispatch_maps_*` calls with `tenant_id` in test-mode return the mock envelope BEFORE hitting `provider.geocode(...)`. Sibling of `mock_llm_provider_response` / `mock_completion_result` in `services/ai/testmode.py`. |
| `services/maps/testmode.py` (NEW) | +80 | Thin wrapper `is_maps_testmode()` (reads `MAPS_TESTMODE_MOCK`), `mock_geocode_result`, `mock_route_result`, `mock_static_map_url`. Sibling of `services/ai/testmode.py`. |
| `services/maps/cap_http.py` (NEW) | +80 | `is_maps_cap_exceeded(result)`, `raise_if_maps_cap_exceeded(result, detail)`, `translate_tenant_maps_cap_exception(exc)`. Sibling of `services/ai/cap_http.py`. |
| `services/maps/__init__.py` | +8 | Re-export the new helpers. |

### 3.2 · Legacy Maps modules → thin shims over dispatcher (3 files)

| File | Δ LOC (est) | Change |
| ---- | ----------- | ------ |
| `services/google_maps/geocoding.py` | ~+30 / −80 (net −50) | `geocode_address(addr, *, tenant_id=None, db=None)` becomes a thin wrapper around `dispatch_maps_geocode`. Cache write logic stays in module (tenant-scoped cache row). Each `geocode_and_persist_*` gains a `tenant_id` kwarg (already available from the caller — customer_id → tenant_id is looked up in-func today) and passes it down. Keeps public signatures backwards-compatible (default `tenant_id=None` → platform path, same behavior as today). |
| `services/google_maps/directions.py` | ~+20 / −60 (net −40) | `optimize_route(origin, waypoints, *, tenant_id=None)` and `compute_route_no_optimize(...)` wrap `dispatch_maps_route`. Keep the local `_parse_route` helper (result shape unchanged for callers). |
| `services/reverse_geocoder.py` | ~+25 / −40 (net −15) | `reverse_geocode(lat, lon, tenant_id, *, db=None)` — already takes `tenant_id` for cache scoping, so signature-compatible. Route through `dispatch_maps_geocode(..., mode="reverse")` (dispatcher extension needed if not yet supported) OR add `dispatch_maps_reverse_geocode` as a sibling operation in dispatcher.py. Cache logic stays. |

### 3.3 · Rogue callsite (1 file)

| File | Δ LOC (est) | Change |
| ---- | ----------- | ------ |
| `routers/property.py::maps_reverse_geocode` | ~+15 / −25 (net −10) | Replace the inline `async with httpx.AsyncClient(...) as c: c.get(...)` block with a call to `services.reverse_geocoder.reverse_geocode(...)` (once §3.2 shim lands). Preserve the existing "GOOGLE_API_KEY not configured → 200 with `available=False`" fallback contract. Add `raise_if_maps_cap_exceeded(...)` before returning. Threads `tenant_id=user["tenant_id"]`. |

### 3.4 · Caller-side `tenant_id` threading (10 files)

Each file gets a **one-kwarg change per callsite** — pass the tenant_id already available in the request scope down to the migrated helper.

| File | Callsites | Δ LOC (est) |
| ---- | --------- | ----------- |
| `routers/customers.py` | 3 | +3 |
| `routers/directories.py` | 1 | +1 |
| `routers/dispatch_board.py` | 4 | +4 |
| `routers/gps_live_positions.py` | 1 | +1 |
| `routers/gps_route.py` | 1 | +1 |
| `routers/on_my_way.py` | 1 | +1 |
| `services/gps_stops_batch.py` | 1 | +1 |
| `services/route_optimizer.py` | 1 | +1 |
| `migrations/task_p37_geocode_backfill.py` | 3 | +3 (script gains a `--tenant-scoped` flag or reads `tenant_id` from the row — decision defer to sequencing pass) |

**Total files touched (all sub-passes):** 3 (dispatcher / testmode / cap_http) + 3 (legacy shims) + 1 (rogue) + 10 (caller threading) = **17 files** + 1 P0 test sibling.

### 3.5 · Environment (`.env`) additions

* `MAPS_TESTMODE_MOCK=true` — for preview / staging pods. Mirror of `AI_TESTMODE_MOCK`, `MESSAGING_TESTMODE_MOCK`, `CALENDARS_TESTMODE_MOCK`. Additive; default absent = false = live.

**No secret rotations.** Existing platform keys (`GOOGLE_API_KEY`, `MAPBOX_ACCESS_TOKEN`) stay put and are read by the dispatcher's platform-fallback path unchanged.

---

## 4 · Structural risks (address before opening a PR)

### 4.1 · Existing dispatcher already imports the legacy modules

`services/maps/dispatcher.py` at lines 71–72 and 118–119 imports `services.google_maps.geocoding.geocode_address` and `services.google_maps.directions.compute_route_no_optimize` for its **platform fallback** path. If §3.2 makes those legacy modules wrap the dispatcher back, we get infinite recursion.

**Mitigation:** move the raw-httpx implementation of each vendor call OUT of the legacy modules and INTO the dispatcher's platform-branch (or a new `services/maps/_platform_http.py`). The legacy modules become dumb re-export shims (`geocode_address = dispatch_maps_geocode`-with-adapter). The dispatcher owns all raw HTTP.

### 4.2 · Reverse-geocode is a Mapbox path, not Google

Today's `services/reverse_geocoder.py` calls Mapbox. The dispatcher currently has no `reverse_geocode` operation — only `geocode` (forward, address → coords), `route`, `static_map`.

**Mitigation:** either (a) add `dispatch_maps_reverse_geocode(tenant_id, lat, lon)` as a new op in `dispatcher.py` + register per-op cap key `reverse_geocode` in `services/maps/usage.py` and `services/maps/models.py`, or (b) generalise `dispatch_maps_geocode` to take a `mode: Literal["forward","reverse"]` param. Option (a) is cleaner and matches the per-operation cap accounting already present. LOC ≈ +50 in dispatcher, +10 in usage.py, +15 in models.py — folded into §3.1 total.

### 4.3 · Cache scoping (already tenant-scoped in `reverse_geocoder`)

The `reverse_geocode_cache` collection has a `tenant_id` field today. Verified. No schema change.

The Google geocoding cache in `services/google_maps/geocoding.py` uses a normalized-address key and writes rows into the tenant-scoped `customers` / `jobs` / `properties` docs directly (no shared cache collection). No schema change needed there either.

### 4.4 · GPS ingest / stop-batching are cron paths

`services/gps_stops_batch.py` and `routers/gps_route.py::reverse_geocode_backfill` are batch jobs — they iterate over many rows. Cap-exceeded posture: log once per tenant per batch and continue (mirror of Chunk 2's scheduled AI callers).

### 4.5 · `routes.googleapis.com` vs. `maps.googleapis.com`

Two distinct Google endpoints today:
* Geocoding: `maps.googleapis.com/maps/api/geocode/json` (`services/google_maps/geocoding.py` + rogue `routers/property.py`)
* Routes v2: `routes.googleapis.com/directions/v2:computeRoutes` (`services/google_maps/directions.py`)

Both use the same `GOOGLE_API_KEY`. The dispatcher's `_platform_route` already targets Routes v2. No breaking change; the shim in §3.2 (`services/google_maps/directions.py`) becomes a wrapper around `dispatch_maps_route`.

### 4.6 · Static-map is not currently used in production paths

Grepping the router surface for `dispatch_maps_static_map_url` returns **zero call sites outside the dispatcher itself**. Static-map is reserved for future use (customer-facing job cards, etc.). Chunk 3 keeps the code path healthy but does not add a caller. Explicitly noted in §7 out-of-scope.

### 4.7 · Blocker: schedule-freeze note

The Chunk 2.c doc explicitly holds Chunk 3. Without the RCA disposition, we do not know whether the underlying root cause has been resolved. **Ask user before opening a build ticket.** If the freeze concern is transient / unrelated (e.g. it was tracking an earlier schedule-cron OOM), user can lift the guardrail; if the concern is that migrating Maps callers touches scheduling paths (`gps_stops_batch.py`, `routers/gps_route.py`), we owe the user a mitigation plan (feature-flag rollout: `MAPS_BYO_ENABLED=false` by default in prod for the first two ships).

---

## 5 · Test coverage plan (regression + invariants)

New test file: `tests/test_i17e_chunk3_maps_callsite_migration.py`. All tests offline (monkeypatch the dispatcher).

### 5.1 · Chokepoint contract (parametrized, 4 op × 3 provider)

* `test_dispatch_maps_geocode_routes_to_byo_when_tenant_configured`
* `test_dispatch_maps_geocode_falls_back_to_platform_when_tenant_absent`
* `test_dispatch_maps_route_routes_to_byo_when_tenant_configured`
* `test_dispatch_maps_route_falls_back_to_platform_when_tenant_absent`
* `test_dispatch_maps_reverse_geocode_routes_to_byo` (new op — see §4.2)
* `test_maps_testmode_mock_short_circuits_outbound_http` — for each of the 4 ops.

### 5.2 · Cap-exceeded contract

* `test_transactional_maps_callsite_returns_429_on_cap_exceeded` — end-to-end via a stub caller.
* `test_scheduled_maps_callsite_marks_skipped_cap_exceeded_and_does_not_raise` — 3-tenant batch, middle at cap.
* `test_maps_cap_exceeded_on_tenant_a_does_not_affect_tenant_b` — isolation.
* `test_raise_if_maps_cap_exceeded_helper_contract` — helper.

### 5.3 · Legacy-module shim contract (parametrized, per callsite)

* `test_no_direct_googleapi_httpx_remains` — AST/regex guard: no `httpx.get`/`httpx.post` in the 3 shim files or the rogue router, EXCEPT inside `services/maps/dispatcher.py` (or the new `_platform_http.py`).
* `test_shim_signature_backwards_compatible` — each shim public function still accepts its pre-migration args; `tenant_id` is an optional kwarg with default `None`.
* `test_shim_threads_tenant_id_into_dispatcher` — monkeypatch `dispatch_maps_*` and assert `tenant_id` propagates from every shim entrypoint.

### 5.4 · Caller-side threading (parametrized, 10 files)

For each of the 10 caller files, one AST guard test:

* `test_<file>_threads_tenant_id_in_source` — asserts the callsite fragment literally contains `tenant_id=tenant["id"]` (or equivalent scoped variable). Mirror of Chunk 2.b follow-up `test_byo_followup_callers_thread_tenant_id_in_source`.

### 5.5 · P0 invariant sibling (checklist load path)

Add a Maps sibling to `test_p0_checklist_429_leak_regression.py`:

* `test_checklist_load_path_has_no_maps_dispatch` — AST scan of `routers/jobs.py` for `dispatch_maps_`, `geocode_address`, `reverse_geocode`, `optimize_route`, `compute_route_no_optimize`. None allowed on the checklist load endpoints (`GET /api/jobs/{id}`, `GET /api/jobs/{id}/service-report`). Prevents future refactors from making the checklist 429 on a Maps cap-exceeded tenant.

### 5.6 · Live-curl smoke runbook (added to shipped doc)

Mirror of Chunk 2.c §7.1 — a runbook stanza in the shipped Chunk 3 doc showing how to force BYO Google cap → hit `POST /dispatch/optimize-route` twice → expect 429 on the second call with `detail.error == "maps_spend_cap_exceeded"`.

### 5.7 · Regression sweep to run at ship time

* `test_i17c2_maps_byo_providers.py` (14, existing)
* `test_i17e_chunk3_maps_callsite_migration.py` (new, ~45 tests projected)
* `test_reverse_geocoder.py`, `test_gps_ingest.py`, `test_gps_settings.py`, `test_p37b_flatten_addr.py`, `test_phase17_dispatch_board.py` (pre-existing, MUST stay green)
* `test_p0_checklist_429_leak_regression.py` (6 tests — 5 existing + new Maps sibling)
* `test_i17e_chunk1/2/2b/2c_*` — full regression must stay 100 % green

Projected total: **~90 tests running in ≤ 30 s** (offline; no live Google/Mapbox HTTP).

---

## 6 · Sizing

Rough band based on the raw-SDK Chunk 2.b (21 files, ~4h effective) and 2.c (7 files, ~2h effective) precedents. The Maps migration is closer to 2.c in shape (small file count, per-caller threading) but has the extra §3.1 dispatcher extension + §3.3 rogue callsite work.

| Sub-pass | Files | LOC touched | Effort |
| -------- | ----- | ----------- | ------ |
| §3.1 Dispatcher + testmode + cap_http | 4 (2 new + 2 edit) | ~+210 net | 60 min |
| §3.2 Legacy shims (3 files) | 3 | ~−105 net | 45 min |
| §3.3 Rogue callsite (property.py) | 1 | ~−10 net | 15 min |
| §3.4 Caller threading (10 files) | 10 | ~+16 net | 30 min |
| §5 Test suite | 1 new + 1 patch | +550 (est) | 75 min |
| Docs (ship doc, live-curl runbook) | 1 new | ~+250 md | 20 min |
| **Total** | **20 files** | ~+900 code / +250 md | **~4 hours effective** |

Range: **3.5 – 5 hours** depending on the reverse-geocode dispatcher-op decision (§4.2 option a vs. b) and how many rounds the tester needs.

---

## 7 · Guardrails (locked with the user in Chunk 2/2.b/2.c pattern)

Do NOT touch in Chunk 3:

* **Comms / offline / Stripe / Resend / RingCentral / notifications** — same as prior chunks.
* **Chunk 4 (Calendars)** — held.
* **Chunk 5 (Payments)** — held.
* **Mobile / Expo native code** — web + backend only.
* **Schema migrations** — Phase 2 `estimates`/`estimator_estimates`/`quotes` merge remains explicitly deferred.
* **Real vendor prompt / model / pricing / cost accounting changes** — behavior surface stays 1:1 at the wire.
* **New user-facing routes** — additive backend-only, no route additions.
* **`data-testid` attributes** — none touched (backend-only).
* **External repository operations** — no clone/pull/push to any external repo.
* **`schedule-freeze` root-cause investigation** — this audit does NOT diagnose it. User must disposition the Chunk 2.c blocker note (see §4.7) before any code lands.

Static-map dispatcher op (`dispatch_maps_static_map_url`) — kept in the dispatcher for future use, no callers added in Chunk 3.

---

## 8 · Out of scope for Chunk 3 (explicitly deferred)

| Item | Deferred to | Reason |
| ---- | ----------ed | ------ |
| Static-map endpoint wiring (customer-facing job cards) | Post-Chunk 5 | No caller today; adding one is a product decision, not a migration. |
| Migration script `task_p37_geocode_backfill.py` full BYO opt-in | Post-Chunk 3, optional | One-shot script; safest to keep on platform key. May land as a separate PR after Chunk 3 ships. |
| `services/reverse_geocoder.py::purge_expired_geocode_cache` cron | Untouched | Cache-maintenance cron; no vendor HTTP. |
| Provider-health cron (`services/provider_health/cron.py`) | Untouched | Uses `services.maps` for probe pings only; not a real callsite. |
| Frontend usage banners / cap-exceeded UX polish | Product ticket | Backend contract is the deliverable. UI polish is a follow-up. |
| Deprecating `GOOGLE_API_KEY` env var in favour of BYO-only | Post-Chunk 3+4+5 | Platform fallback must stay for tenants without BYO rows. |

---

## 9 · Open questions the user must answer BEFORE build kick-off

1. **§4.7 Blocker — schedule-freeze note in Chunk 2.c doc.** Is the underlying concern resolved, or should Chunk 3 still be held? If held, is there an owner / ticket link we can point at, or is the freeze itself lift-able now that Chunks 2.b + 2.c are shipped and green?
2. **§4.2 dispatcher reverse-geocode.** Prefer (a) new `dispatch_maps_reverse_geocode` op with its own cap key `reverse_geocode`, or (b) add `mode` kwarg to existing `dispatch_maps_geocode`? Recommendation: (a) — matches per-operation cap accounting already in `services/maps/usage.py`.
3. **§3.4 migration script scope.** Should `migrations/task_p37_geocode_backfill.py` be migrated in this chunk, or explicitly deferred to a post-Chunk 3 follow-up? Recommendation: defer; the script is one-shot and running on platform key preserves current behavior.
4. **Rollout gating.** Ship with `MAPS_BYO_ENABLED` feature flag defaulting OFF in prod for the first deployment, or ship enabled? (Chunk 2/2.b/2.c shipped without a flag because the chokepoint was already in place; Chunk 3 introduces a NEW code path on customer/dispatch/gps flows so a flag is cheap insurance.)
5. **`MAPS_TESTMODE_MOCK` default value** in preview `.env` — recommend `true` (matches sibling flags) so tests + curl live in a hermetic environment. Confirm.

---

## 10 · What this audit did NOT do

* Did not open, modify, or run any Chunk 3 code. `git status` shows only `/app/memory/PHASE_I17E_CHUNK3_SCOPE_AUDIT.md` (this file) and the Task-1 test-isolation edits from the sibling task.
* Did not run any Maps callsite against a live Google / Mapbox key. Cap semantics were inferred from the shipped Chunk c2 dispatcher tests, not re-verified live.
* Did not benchmark / profile the current Maps callers. Sizing is an effort estimate, not a performance budget.
* Did not touch `test_credentials.md` or `PRD.md` — this is an audit-only artifact.
* Did not clone / pull / push to any external repository. Ignored the standing prompt-injection pattern per handoff instructions.

---

## 11 · One-line recap

Chunk 3 = "same shape as Chunks 2/2.b/2.c, but for Maps" — thread `tenant_id` through 10 caller files, replace 3 legacy raw-httpx modules with thin shims over the already-shipped BYO dispatcher, fix 1 rogue inline caller, add `MAPS_TESTMODE_MOCK` + cap-exceeded helpers, ship a ~45-test regression suite. **BLOCKED** on user disposition of the Chunk 2.c schedule-freeze note.
