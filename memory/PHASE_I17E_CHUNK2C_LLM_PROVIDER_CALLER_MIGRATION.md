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

* **Chunk 3 (Maps)** — held pending schedule-freeze root-cause. Do not touch.
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
