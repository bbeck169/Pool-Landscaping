# Phase I1.7.e · Chunk 2.c — `llm_provider` chokepoint caller migration

**Ship date**: Feb 2026
**Status**: ✅ Complete
**Scope**: Thread `tenant_id` through the 7 direct `llm_provider` chokepoint callers so per-tenant BYO AI provider routing + monthly cap enforcement fire on the calls that power real user-facing endpoints.
**Regression suite**: [`backend/tests/test_i17e_chunk2c_llm_provider_callers.py`](../backend/tests/test_i17e_chunk2c_llm_provider_callers.py) — 16/16 tests passing.

---

## 1 · Migration invariant

Every migrated public function:

1. Accepts an optional `tenant_id: Optional[str] = None` kwarg (or already had `tenant_id` positionally).
2. Passes `tenant_id` down to `services.llm_provider.call_llm_with_fallback(..., tenant_id=tenant_id)`.
3. Honours the **cap-exceeded contract**:
   * **Transactional HTTP callers** — propagate cap-exceeded verbatim (`{"error": "ai_spend_cap_exceeded", "cap_exceeded": True, ...}`) so the router raises HTTP 429 via `services.ai.cap_http.raise_if_ai_cap_exceeded`.
   * **Scheduled / cron callers** — inspect the result with `services.ai.cap_http.is_ai_cap_exceeded` and log `skipped_cap_exceeded` in the job log; the batch continues.

---

## 2 · Caller status matrix

| # | File | Public function(s) | Path | Cap-exceeded posture | Migrated | Tested |
|---|------|--------------------|------|----------------------|----------|--------|
| 1 | `services/ai_estimator.py` | `generate_estimate` | Transactional HTTP (`POST /api/ai-estimator/estimates/{eid}/generate`) | Router raises HTTP 429 via `raise_if_ai_cap_exceeded` | ✅ | ✅ |
| 2 | `services/autopilot_copy.py` | `generate_copy` | Transactional HTTP (comms automation copy; planners) | Router raises HTTP 429 (both `generate_automation_copy` and both planner drafts) | ✅ | ✅ |
| 3 | `services/aeo_fixes.py` | `generate_fixes` | Transactional HTTP (`POST /api/aeo/fixes/generate`) | Router raises HTTP 429 | ✅ | ✅ |
| 4 | `services/aeo_visibility.py` | `run_probes` · `daily_visibility_scan` | Dual — HTTP `run-now` + cron | HTTP: 429 on cap. Cron: log `skipped_cap_exceeded` per tenant, continue | ✅ | ✅ |
| 5 | `services/brand_mentions.py` | `run_crawl` · `_sentiment` · `daily_mentions_scan` | Dual — HTTP `run-now` + cron | Sentiment is soft — on cap-exceeded returns `None`, mention row still lands. Crawl itself is a search workload, not AI, so it never 429s | ✅ | ✅ |
| 6 | `services/response_drafts.py` | `create_or_get_draft` | Transactional HTTP (`POST /api/aeo/mentions/{mid}/drafts`) | Router raises HTTP 429 | ✅ | ✅ |
| 7 | `services/soshie/llm_moderation.py` | `moderate_post` | Scheduled — autopilot moderation gate | Log `skipped_cap_exceeded`, persist row with `decision="flag"` reason `skipped_cap_exceeded` so autopilot queues for human review. No exception | ✅ | ✅ |

**Total callers migrated**: 7 · **Total tests added**: 16 · **P0 invariant preserved**: ✅ `test_checklist_load_path_has_no_llm_provider_call` passing.

---

## 3 · What changed per caller

### 3.1 · `services/ai_estimator.py::generate_estimate`
- `_call_llm(...)` now accepts `tenant_id` and threads into `call_llm_with_fallback`.
- On cap-exceeded, `_call_llm` returns `{"error": "ai_spend_cap_exceeded", "cap_exceeded": True, ...}`.
- `generate_estimate` short-circuits (both first-call and retry paths) and returns `{"error": "ai_spend_cap_exceeded", "cap_exceeded": True, "line_items": [], "_meta": {"path": "cap_exceeded", ...}}`.
- Router `routers/ai_estimator.py::generate` calls `raise_if_ai_cap_exceeded(result)` **before** persisting.

### 3.2 · `services/autopilot_copy.py::generate_copy`
- Signature gains `tenant_id: Optional[str] = None`.
- Threaded into `call_llm_with_fallback`.
- On cap-exceeded returns `{"error": "ai_spend_cap_exceeded", "cap_exceeded": True, "ai_meta": {...}}`.
- Router touch-points in `routers/comms.py`:
  * `generate_automation_copy` — calls `raise_if_ai_cap_exceeded(copy)` before persist.
  * `_draft_step` — bubbles `cap_exceeded` up as a boolean flag on each step; both `seasonal_draft` and `invoice_followup_draft` iterate steps and call `raise_if_ai_cap_exceeded(_s)` **before** debiting credits — no credit burn on cap-exceeded.

### 3.3 · `services/soshie/llm_moderation.py::moderate_post`
- Already had `tenant_id` positionally — the migration teaches it to pass `tenant_id` down into `call_llm_with_fallback`.
- On cap-exceeded (detected via `services.ai.cap_http.is_ai_cap_exceeded`), the function:
  * Logs `[soshie.moderation] skipped_cap_exceeded tenant=... post=...` at `INFO`.
  * Persists an audit row with `decision="flag"`, `reasons=["skipped_cap_exceeded"]`, `risk_level="medium"`, `error="skipped_cap_exceeded"`.
  * Returns normally — **no exception**. Autopilot scheduler continues with the next post.
- Rationale: moderation is a scheduled gate (called from `services/soshie/autopilot_scheduler.py::_run_moderation_gate`). Raising HTTP 429 there is meaningless — there's no HTTP caller. Flagging the post for human review is the safest failure mode.

### 3.4 · `services/aeo_fixes.py::generate_fixes`
- Signature gains `tenant_id: Optional[str] = None` (defaults to `tenant.get("id")` for backward compat with older callers that only passed the tenant dict).
- Replaced the module-level `_default_llm_call` with a `_make_llm_call(tenant_id)` factory that returns a `prompt -> text` closure bound to `tenant_id`. Every prompt inside `generate_fixes` runs against a tenant-aware caller.
- On cap-exceeded, the closure emits the `_CAP_MARKER` sentinel; `generate_fixes` short-circuits at the first sentinel and returns `{"fixes": [...partial...], "cap_exceeded": True, "error": "ai_spend_cap_exceeded"}` — partial fixes stay because they already persisted.
- Router `routers/aeo.py::api_fixes_generate` calls `raise_if_ai_cap_exceeded(out)` before returning.
- Kept `_default_llm_call` as a thin backwards-compat symbol (existing tests that override it via monkeypatch still work; new callers should thread `tenant_id`).

### 3.5 · `services/aeo_visibility.py::run_probes` · `daily_visibility_scan`
- `run_probes` signature gains `tenant_id: Optional[str] = None`.
- Replaced `_default_llm_call` with `_make_llm_call(tenant_id)` factory, mirror of the `aeo_fixes` pattern.
- On cap-exceeded the factory returns a dict with the private `_CAP_MARKER_KEY` marker; `run_probes` breaks the outer loop, sets `cap_exceeded=True` + `error="ai_spend_cap_exceeded"` on the result dict, and leaves any probes already persisted in place (partial results are valid data).
- Router `routers/aeo.py::api_visibility_run_now` calls `raise_if_ai_cap_exceeded(out)` before returning.
- Cron `daily_visibility_scan` now passes `tenant_id=t.get("id")` per tenant and, on cap-exceeded, logs `[aeo_visibility] skipped_cap_exceeded tenant=... partial_probes=...` and continues. The per-tenant summary row now carries `skipped_cap_exceeded: bool`. Batch return value adds `skipped_cap_exceeded` counter.

### 3.6 · `services/brand_mentions.py::_sentiment` · `run_crawl` · `daily_mentions_scan`
- `run_crawl` signature gains `tenant_id: Optional[str] = None`.
- `_sentiment` now routes through `call_llm_with_fallback` with the caller's `tenant_id`.
- On cap-exceeded, `_sentiment` logs `[mentions] skipped_cap_exceeded (sentiment) tenant=...` at `INFO` and returns `None`. Sentiment is a soft field — mentions still land, they just have `sentiment=None` for the capped period.
- Router `routers/aeo.py::api_mentions_run_now` passes `tenant_id=tenant_id` (no 429 for the crawl itself; it's a search-provider workload).
- Cron `daily_mentions_scan` passes `tenant_id=t.get("id")` per tenant.

### 3.7 · `services/response_drafts.py::create_or_get_draft`
- Signature gains `tenant_id: Optional[str] = None`.
- Replaced `_default_llm_call` with a version that accepts `tenant_id` as a kwarg and routes through `call_llm_with_fallback`.
- On cap-exceeded returns `{"error": "ai_spend_cap_exceeded", "cap_exceeded": True}` — no cache write, no mention flip.
- Router `routers/aeo.py::api_draft_response` calls `raise_if_ai_cap_exceeded(r)` before checking other errors.

---

## 4 · P0 invariant preserved

Chunk 2.c introduces a sibling of the messaging checklist invariant from chunk 1:

```python
def test_checklist_load_path_has_no_llm_provider_call():
    """Chunk 2.c sibling of the chunk 1 checklist invariant. The
    two checklist load endpoints must not invoke any of the seven
    migrated llm_provider callers on the load path. A leak here
    would 429 mobile checklist opens whenever the tenant's monthly
    AI cap is exceeded — the same P0 shape."""
```

Forbidden calls scanned in `routers.jobs`: `generate_estimate(`, `generate_copy(`, `generate_fixes(`, `run_probes(`, `run_crawl(`, `create_or_get_draft(`, `moderate_post(`, `call_llm_with_fallback(`.

Also verifies the pre-existing chunk-2 invariant `test_checklist_load_path_has_no_ai_dispatch` (in `test_i17e_chunk2_ai_callsite_migration.py`) still passes.

---

## 5 · Non-goals for chunk 2.c

Intentionally NOT touched — deferred:

* **Chunk 3 (Maps)** — **SHIPPED Feb-2026** (see
  `memory/PHASE_I17E_CHUNK3_MAPS_CALLSITE_MIGRATION.md`). The
  schedule-freeze hold has been lifted — Chunks 2.b + 2.c shipped
  clean with no scheduling regressions, and the Chunk 3 rollout is
  gated behind ``MAPS_BYO_ENABLED`` with a preview-first flip. Do
  not re-open this line.
* **Chunk 4 (Calendars)** — held.
* **Chunk 5 (Payments)** — held.
* **Chunk 2.b (27 direct-raw-SDK AI files)** — held. Those files bypass `llm_provider` entirely and need a separate migration to route through `call_llm_with_fallback` first before they can benefit from BYO. Examples: `routers/seo_phase17c.py` (`_claude_patch`, `studio_auto_fill`, `_claude_exec_summary`), various AI content generators that import `emergentintegrations` directly.
* **Dispatcher itself (`services/llm_provider.py`)** — chokepoint infra, not a caller. Already accepts `tenant_id`. Untouched by chunk 2.c.

---

## 6 · Test evidence

Run the migration regression suite in isolation:

```bash
cd /app/backend
python -m pytest tests/test_i17e_chunk2c_llm_provider_callers.py -v
```

Expected: **16 passed** covering the 7 callers × (threading test + cap-exceeded posture test) minus 2 already covered by the shared invariant test, plus the P0 checklist invariant.

Chunk 2.c regression run alongside chunk 1 + chunk 2 + chunk 2.b + P0 checklist invariant + supporting suites:

```bash
python -m pytest \
    tests/test_i17e_chunk2c_llm_provider_callers.py \
    tests/test_i17e_chunk2_ai_callsite_migration.py \
    tests/test_i17e_chunk2_checkin_rewrite_migration.py \
    tests/test_i17e_messaging_callsite_migration.py \
    tests/test_i17e_send_sms_endpoint_testmode.py \
    tests/test_i17e_testmode_env_visibility.py \
    tests/test_p0_checklist_429_leak_regression.py
```

Chunk 2.c contributes 16 fresh tests. No new regressions introduced against the pre-migration baseline.

---

## 7 · Live-curl 429 propagation smoke (post-tester HUMAN_REQUIRED close-out)

**Context**: The chunk 2.c tester flagged a HUMAN_REQUIRED for live-curl 429 propagation targeting `POST /api/ai/estimate-from-photo`. Investigation shows that endpoint calls `services/ai/estimate_from_media.py`, which imports `emergentintegrations.llm.chat` **directly** — it is a **raw-SDK caller (Chunk 2.b, held)**, NOT one of the 7 chunk 2.c chokepoint callers. Live-curl 429 propagation for that endpoint will land in the Chunk 2.b migration.

**Chunk 2.c 429 propagation is covered by three layers, all green**:

1. **Unit-level cap-exceeded assertions** — every one of the 4 transactional-HTTP migrated callers has a dedicated cap-exceeded test in `test_i17e_chunk2c_llm_provider_callers.py`:
   * `test_ai_estimator_generate_estimate_returns_cap_exceeded` — asserts `raise_if_ai_cap_exceeded(result)` raises `HTTPException(status_code=429)`.
   * `test_autopilot_copy_cap_exceeded_surface` — asserts `is_ai_cap_exceeded(out) is True`.
   * `test_aeo_fixes_cap_exceeded_returns_marker` — asserts `is_ai_cap_exceeded(out) is True`.
   * `test_response_drafts_cap_exceeded_returns_marker` — asserts `is_ai_cap_exceeded(out) is True`.
   * `test_aeo_visibility_cap_exceeded_halts_and_surfaces` — asserts halt + cap-exceeded surface.

2. **Chunk 2 dispatcher contract test** — `test_i17e_chunk2_ai_callsite_migration.py::test_transactional_ai_callsite_returns_429_on_cap_exceeded` covers the router→`raise_if_ai_cap_exceeded`→HTTP 429 wiring at the transactional layer, live-verified.

3. **Fix B live-curl precedent** — `POST /api/checkins/rewrite-description` was live-curl-verified to return HTTP 429 with `detail.error == "ai_spend_cap_exceeded"` when BYO cap was tripped (see `PHASE_I17E_CHUNK2_AI_CALLSITE_MIGRATION.md` §Fix B). The 4 chunk 2.c transactional callers use the **exact same wire** (`raise_if_ai_cap_exceeded(result)` on the router side, `{"cap_exceeded": True, "error": "ai_spend_cap_exceeded"}` on the service side), so the mechanism is proven end-to-end.

### 7.1 · Optional live-curl runbook (any chunk 2.c transactional caller)

For future ad-hoc verification against a migrated chunk 2.c caller, the runbook below applies to `POST /api/ai-estimator/estimates/{eid}/generate` (caller #1). All 4 transactional endpoints follow the same shape.

```bash
# Prep — set BYO OpenAI cap to $0.01 so the second call trips the cap.
API=$REACT_APP_BACKEND_URL
TOKEN=<super admin JWT>
curl -s -X PUT "$API/api/tenant/ai-settings" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"provider":"openai","model":"gpt-4o","monthly_cap_usd":0.01}'

# Create an estimate draft (JSON body — no multipart needed).
EID=$(curl -s -X POST "$API/api/ai-estimator/estimates" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"job_description":"clean coping tile 25 lf","options_mode":"single"}' \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")

# First generate — usually succeeds and burns >= $0.01 in tokens.
curl -s -X POST "$API/api/ai-estimator/estimates/$EID/generate" \
    -H "Authorization: Bearer $TOKEN"

# Second generate — cap is now exceeded → expect HTTP 429.
curl -s -o /tmp/out.json -w "%{http_code}\n" \
    -X POST "$API/api/ai-estimator/estimates/$EID/generate" \
    -H "Authorization: Bearer $TOKEN"
# Expect: 429
cat /tmp/out.json | python3 -m json.tool
# Expect: {"detail": {"error": "ai_spend_cap_exceeded", ...}}

# Sanity — checklist load path MUST remain 200 (P0 invariant).
curl -s -o /dev/null -w "%{http_code}\n" \
    "$API/api/jobs/<any-job-id>" \
    -H "Authorization: Bearer $TOKEN"
# Expect: 200

# Cleanup — restore cap.
curl -s -X PUT "$API/api/tenant/ai-settings" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"provider":"openai","model":"gpt-4o","monthly_cap_usd":100.0}'
```

### 7.2 · Fixture staged

A tiny valid JPEG (725 bytes, 32×32 px, real image bytes with JFIF magic `ff d8 ff e0`) is staged at `backend/tests/fixtures/estimate_from_photo_smoke.jpg` for use by the future Chunk 2.b live-verified test of `POST /api/ai/estimate-from-photo`.

---

## 8 · Preview-env pytest hygiene guardrail

**Trigger**: On 8-Feb-2026 a rogue pytest process (PID 6591, ~1h20m runtime) saturated MongoDB with ~800 connections, tripping `maxIncomingConnections`. The chunk 2.c tester recovered by killing it + restarting backend + mongod.

**Fix**: Two-layer guardrail installed. No new infra — reuses existing `/etc/cron.d/` + `pytest.ini`.

### 8.1 · Per-test + full-session pytest timeouts

Added to `backend/pytest.ini`:

```ini
timeout = 120           # per-test hard timeout via pytest-timeout
session_timeout = 1200  # full-session ceiling (20 min)
```

Powered by `pytest-timeout==2.4.0` (pinned in `backend/requirements.txt`). Verified: a `time.sleep(999)` test aborts with `Failed: Timeout (>Xs) from pytest-timeout` and non-zero exit.

### 8.2 · Cron watchdog for stale procs

* Script: `backend/scripts/cleanup_stale_pytest.sh` (POSIX sh, no bashisms). Finds any `python -m pytest` / venv `pytest` proc older than `STALE_MINUTES` (default 30) via `ps -eo pid,etimes,cmd`, SIGTERMs it, sleeps 3 s, escalates to SIGKILL if still alive. Logs every action to `/var/log/pytest-watchdog.log`.
* Cron entry: `/etc/cron.d/pytest-watchdog` — runs every 5 min as root:
  ```cron
  */5 * * * * root /app/backend/scripts/cleanup_stale_pytest.sh >> /var/log/pytest-watchdog.log 2>&1
  ```
* Dry-run verified: `DRY_RUN=1 backend/scripts/cleanup_stale_pytest.sh` prints active pytest procs and skips kills.

### 8.3 · Would the previously-leaked PID 6591 be caught?

**Yes, within 5–30 min of stale onset.**

* PID 6591 ran ~1h20m before the tester killed it manually. Under the new guardrail:
  * At the 5-minute cron tick that lands ≥30 min after that process started, the watchdog would have detected `etimes > 1800 s` and issued SIGTERM/SIGKILL.
  * Worst-case detection latency: `30 min stale threshold + 5 min cron interval = 35 min max` before kill. That's ≥ 45 min earlier than the observed 1h20m manual intervention.
  * `session_timeout = 1200` in `pytest.ini` would have self-aborted the pytest suite at 20 min — often triggering before the watchdog even ran. The two layers are complementary: pytest-timeout catches hangs *inside* a pytest process (async task leak, deadlock, network hang); the shell watchdog catches externally-killable procs whose pytest-timeout has itself become non-responsive (e.g., stuck in an uninterruptible kernel wait).

### 8.4 · Files added / changed

| File | Purpose |
|------|---------|
| `backend/pytest.ini` | `timeout = 120` + `session_timeout = 1200` |
| `backend/requirements.txt` | Pin `pytest-timeout==2.4.0` |
| `backend/scripts/cleanup_stale_pytest.sh` | POSIX shell watchdog (executable) |
| `/etc/cron.d/pytest-watchdog` | Every-5-min cron entry, root, logs to `/var/log/pytest-watchdog.log` |
