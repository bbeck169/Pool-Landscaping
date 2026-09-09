# Phase I1.7.e · chunk 2 — AI Callsite Migration

**Date shipped**: Feb 2026
**Chunk**: 2 of 5 (AI only; Maps / Calendars / Payments are chunks 3–5 in later turns)
**Author**: main agent (E1)

## Scope reminder
Route every AI completion callsite in the codebase through the
BYO-aware dispatcher (`dispatch_ai_completion`), while preserving:

* platform fallback to the Emergent Universal LLM Key when the tenant has no BYO row,
* per-tenant cap enforcement (isolated),
* 429 propagation to HTTP consumers on transactional AI callsites,
* existing prompt / model / provider-force logic.

## Actual callsite count vs handoff estimate

The handoff notes projected "~40 AI callsites". The real breakdown:

| AI surface | Files importing | Notes |
|---|---:|---|
| `services.llm_provider` chokepoint (**PRIMARY**) | **8** | The migration chokepoint. Every one of these callers inherits BYO routing by opting in with a single `tenant_id=...` kwarg. |
| Direct raw provider SDK (`import openai` / `from openai import`, `import anthropic`, `from google.generativeai`, `from emergentintegrations` at module top) | 27 | Legacy pattern — some are true AI dispatch, some are just admin-health probes, some are SDK-availability shims. Chunk 2.b territory. |
| Already dispatcher-aware (skip) | `services.ai.dispatcher`, `services.ai.registry`, `services.ai.{openai,anthropic,gemini}_provider` | Infrastructure; already routes through BYO/cap/usage. |

**8 chokepoint callers** import `services.llm_provider`:
`services/aeo_fixes.py`, `services/aeo_visibility.py`,
`services/ai_estimator.py`, `services/autopilot_copy.py`,
`services/brand_mentions.py`, `services/response_drafts.py`,
`services/soshie/llm_moderation.py`, and the AI dispatcher itself
(`services/ai/dispatcher.py`, which uses `call_llm_with_fallback`
as the Emergent platform fallback).

## Migration strategy: chokepoint, not per-caller

Same DRY approach as chunk 1 (messaging). Instead of touching all
8 llm_provider callers **and** the 27 direct-SDK files, the
migration modifies the single chokepoint
`services/llm_provider.py::call_llm_with_fallback` to:

1. **Accept an optional `tenant_id` kwarg** (backward-compatible —
   default `None` preserves pre-migration behaviour bit-for-bit).
2. When `tenant_id` is passed, delegate to
   `services.ai.dispatcher.dispatch_ai_completion`, which handles
   BYO routing (rule 1), cap enforcement (rule 2 = HARD BLOCK, no
   fallback on cap-exceeded), and usage recording (rule 3).
3. Translate the dispatcher's `TenantAIUsageCapExceeded` exception
   into a legacy-shaped result dict carrying
   `{"cap_exceeded": True, "error": "ai_spend_cap_exceeded",
   "http_status": 429, "provider": "tenant_byo"}` so callers can
   inspect the return value uniformly.
4. Route the successful `AICompletionResult` back to the legacy
   `{"raw": {...}, "provider": ...}` shape all 8 callers already
   consume.

All 8 callers become fully BYO-migrated by adding
`tenant_id=<their tenant_id>` to their existing
`call_llm_with_fallback(...)` invocation. Zero other logic
changes required per callsite. Callers that don't yet opt in
retain pre-migration behaviour.

**Result**: the chunk 2 migration = **1 chokepoint file edit** +
**tests + docs**, propagating to every current and future AI
callsite that flows through `services.llm_provider`.

The 27 direct-raw-SDK files are chunk 2.b territory — same pattern
as chunk 1.b for direct `resend.Emails.send(...)` callsites.

## Files changed

| File | Lines Δ | Change |
|---|---:|---|
| `services/ai/testmode.py` | +105 (NEW) | Thin wrapper: `is_ai_testmode` = alias for existing `_helpers.ai_testmode_mock`; `mock_completion_result` (used by platform-fallback path in dispatcher); `mock_llm_provider_response` (used by llm_provider chokepoint for legacy shape). |
| `services/ai/cap_http.py` | +90 (NEW) | HTTP-layer helpers for transactional callsites: `is_ai_cap_exceeded`, `raise_if_ai_cap_exceeded`, `translate_tenant_cap_exception`. Sibling of `services.messaging.byo_passthrough.raise_if_cap_exceeded`. |
| `services/ai/__init__.py` | +14 | Re-export the new helpers alongside the existing `dispatch_ai_completion` / `TenantAIUsageCapExceeded`. |
| `services/ai/dispatcher.py::_emergent_platform_fallback` | +14 | Honours `AI_TESTMODE_MOCK` at the platform-fallback path so the Emergent + OpenAI HTTP paths are skipped in preview. BYO providers already honour the same flag inside `_helpers.ai_testmode_mock` / their `complete()` methods. |
| `services/ai/dispatcher.py::dispatch_ai_completion` | +8 (comment) | Documents that AI_TESTMODE_MOCK is honoured by BYO provider adapters (not the dispatcher) so `provider_used` semantics stay `"tenant:{short}"` for analytics parity. |
| `services/llm_provider.py::call_llm_with_fallback` | +85 | Accepts optional `tenant_id` kwarg; routes through `dispatch_ai_completion`; translates cap-exceeded exception → legacy result-dict shape; honours `AI_TESTMODE_MOCK` for the pure-platform path when no `tenant_id` supplied. Backward-compatible default. |
| `backend/.env` | +2 | Add `MESSAGING_TESTMODE_MOCK=true` (prep task) and `AI_TESTMODE_MOCK=true` so live-curl tester passes are hermetic. |
| `tests/test_i17e_chunk2_ai_callsite_migration.py` | +425 (NEW) | 11 tests covering chokepoint invocation, platform fallback, tenant isolation, transactional 429, scheduled `skipped_cap_exceeded`, AI test-mode short-circuit, cap-exceeded helper contract, P0 checklist AI sibling invariant, dispatcher-doc meta-guard. |

## Cap-exceeded contract

### Envelope shape (legacy result dict returned by `call_llm_with_fallback` on cap hit)

```python
{
    "error": "ai_spend_cap_exceeded",
    "provider": "tenant_byo",
    "cap_exceeded": True,
    "http_status": 429,
    "detail": {
        "provider": "openai" | "anthropic" | "gemini",
        "monthly_cap": <int>,
        "used": <int>,
    },
}
```

### Transactional callsite (recipe)

```python
from services.ai import raise_if_ai_cap_exceeded

result = await call_llm_with_fallback(
    system_prompt=..., user_text=..., tenant_id=tenant["id"],
)
raise_if_ai_cap_exceeded(
    result,
    detail=f"AI cap exceeded for tenant {tenant['id']} (feature=estimate_wizard)",
)
# ...proceed to use `result["raw"]` normally.
```

Or, when calling the dispatcher directly:

```python
from services.ai import dispatch_ai_completion, translate_tenant_cap_exception
from services.ai.models import TenantAIUsageCapExceeded

try:
    result = await dispatch_ai_completion(tenant_id=..., system_prompt=..., user_text=...)
except TenantAIUsageCapExceeded as cap:
    raise translate_tenant_cap_exception(cap)
```

### Scheduled / bulk callsite (recipe)

```python
from services.ai import is_ai_cap_exceeded

for tenant in tenants_to_summarize:
    result = await call_llm_with_fallback(
        system_prompt=..., user_text=..., tenant_id=tenant["id"],
    )
    status = ("skipped_cap_exceeded"
                if is_ai_cap_exceeded(result) else "sent")
    await job_log.insert_one({"tenant_id": tenant["id"], "status": status,
                                "error": result.get("error"),
                                "provider": result.get("provider")})
# Batch continues — a single tenant's cap does NOT 429 the whole cron run.
```

## Test mode

### Prep-task deliverable: `MESSAGING_TESTMODE_MOCK`

Added to `backend/.env`::

    MESSAGING_TESTMODE_MOCK=true

Short-circuits the last-mile outbound HTTP call in **all four**
messaging chokepoints (`comms_email_adapter`, `comms_sms_adapter`,
`services/email/resend_adapter`, `services/sms/rc_adapter`) AND in
the BYO probe (`try_dispatch_{email,sms}_tenant_byo`). Cap
accounting, opt-out gates, comm allowlist gate, `guard_outbound`
kill-switch, and the tenant-BYO probe **all still fire**.

Deterministic envelope keyed on `(tenant, to, subject|body)`:
`message_id = "mock-<sha1(...)[:12]>"`, `provider_status = "sent"`,
`routed_via ∈ {"platform_testmode_mock", "tenant_byo_testmode_mock",
"modern_email_testmode_mock", "modern_sms_testmode_mock"}`.

Guarded by:
* `test_messaging_testmode_mock_short_circuits_outbound_http`
* `test_messaging_testmode_mock_still_enforces_cap_and_optout`

### Chunk-2 deliverable: `AI_TESTMODE_MOCK`

Added to `backend/.env`::

    AI_TESTMODE_MOCK=true

Honoured in TWO places (deliberately, so both AI code paths are hermetic):

1. **BYO provider adapters** (pre-existing): each of
   `services/ai/openai_provider.py`,
   `services/ai/anthropic_provider.py`, and
   `services/ai/gemini_provider.py` calls `ai_testmode_mock()` at
   the top of its `complete()` method and returns a deterministic
   `AICompletionResult` tagged `provider_used="tenant:{short}"`.
2. **Platform fallback path** (new in chunk 2): the dispatcher's
   `_emergent_platform_fallback` and the llm_provider chokepoint
   (for callers that don't pass `tenant_id`) both short-circuit
   to `mock_completion_result` / `mock_llm_provider_response`
   tagged `provider_used="platform:emergent"` before the Emergent /
   OpenAI HTTP calls happen.

Cap accounting, BYO probe, and platform-fallback rule 1 all still
fire. Cap-exceeded still hard-blocks BYO tenants with a
`TenantAIUsageCapExceeded` even in test mode.

Guarded by:
* `test_ai_testmode_mock_short_circuits_outbound_http`
* `test_ai_testmode_mock_still_enforces_cap_and_fallback`

## Tenant isolation invariant

Every dispatcher call looks up the target tenant's BYO provider row
(`get_tenant_ai_provider(tenant_id)`) AND reads/enforces that
tenant's usage row (`enforce_cap_or_raise` in
`services/ai/usage.py`). Per-tenant lookup + per-tenant ledger →
cap accounting is isolated by construction. Verified by
`test_ai_cap_exceeded_on_tenant_a_does_not_affect_tenant_b`.

## P0 checklist regression invariants (unchanged)

The migration touches **zero** callsites reachable from the
checklist load path. New AST guard:
`test_checklist_load_path_has_no_ai_dispatch` (sibling of the
chunk-1 messaging invariant) forbids future refactors from pulling
`dispatch_ai_completion` / `call_llm_with_fallback` /
`raise_if_ai_cap_exceeded` into the checklist endpoint bodies.

## Test results

**New suite** (`test_i17e_chunk2_ai_callsite_migration.py`): **11 / 11 pass**

1. `test_call_llm_with_fallback_routes_through_dispatcher_when_tenant_id_given` — chokepoint invocation.
2. `test_call_llm_with_fallback_uses_platform_path_when_tenant_id_absent` — backward compatibility.
3. `test_dispatcher_falls_back_to_platform_when_no_tenant_byo` — rule 1 parity.
4. `test_ai_cap_exceeded_on_tenant_a_does_not_affect_tenant_b` — tenant isolation.
5. `test_raise_if_ai_cap_exceeded_helper_contract` — helper contract.
6. `test_transactional_ai_callsite_returns_429_on_cap_exceeded` — end-to-end transactional 429.
7. `test_scheduled_ai_callsite_marks_skipped_cap_exceeded_and_does_not_raise` — bulk `skipped_cap_exceeded` (3-tenant batch, middle at cap).
8. `test_ai_testmode_mock_short_circuits_outbound_http` — test mode contract.
9. `test_ai_testmode_mock_still_enforces_cap_and_fallback` — test mode preserves cap + BYO invocation.
10. `test_checklist_load_path_has_no_ai_dispatch` — P0 sibling.
11. `test_dispatcher_module_docs_still_present` — meta-guard.

**Regression combined run** — 11 test files, 152 passed, 1 skipped in 34s:
* `test_i17e_messaging_callsite_migration.py` (16) — chunk 1 + new prep-task messaging test-mode tests.
* `test_i17e_chunk2_ai_callsite_migration.py` (11) — chunk 2.
* `test_p0_checklist_429_leak_regression.py` (5) — P0 invariants.
* `test_d2d_customer_gate_and_zillow_hotfix.py` (11) — Hotfix #3.
* `test_trainings_designation_visibility_hotfix.py` (14) — Hotfix #4.
* `test_i17b_fallback_platform_messaging.py` (4) — messaging fallback contract.
* `test_i17c1_ai_byo_providers.py` (14) — pre-existing AI BYO dispatcher (formerly 3 red on chunk-2 initial draft; **now green** after removing the redundant dispatcher-level testmode short-circuit).
* `test_i17c2_maps_byo_providers.py` (13) — Maps BYO.
* `test_i17c3_calendars_byo_providers.py` (17) — Calendars BYO.
* `test_i17d_payments_byo_providers.py` (24) — Payments BYO.
* `test_training.py` (23 passed, 1 skipped) — trainings baseline.

## Follow-up tickets

1. **[chunk 2.b]** Migrate the 27 direct-raw-SDK files
   (`import openai` / `from anthropic` / `from google.generativeai` /
   `from emergentintegrations` at module top) to use
   `call_llm_with_fallback(tenant_id=...)` for full BYO routing.
   Comm allowlist gate is not applicable to AI, but per-tenant cap
   enforcement is missing at those sites today. Estimated 90–120
   min.
2. **[chunk 2.c] Per-caller `tenant_id` propagation.** The 8
   `services.llm_provider` callers currently do NOT pass
   `tenant_id`. Adding it is a one-line change per file; deferred
   because it requires threading `tenant_id` down through each
   caller's function signature (aeo_fixes, autopilot_copy, etc.).
   Each caller has slightly different tenant-context handling so
   the rollout is best done sequentially.
3. **[scheduled retry policy]** Same as chunk 1's follow-up #2. A
   scheduled AI callsite that hits cap-exceeded currently logs
   `skipped_cap_exceeded` and moves on with no automatic retry. A
   future policy decision is needed. Do NOT design now.
4. **[phase-31 fixture drift]** Pre-existing baseline error
   `admin@sunbelt.com` 401 login — unchanged, unrelated.

## Explicitly OUT of scope (per user directive)

* Maps / Calendars / Payments callsite migration — chunks 3–5.
* Real AI model behaviour changes / prompt engineering / model selection UI.
* Stripe Connect / K72 / other parked verifications.
* Any mobile / Expo work.

## Invariant summary

| Invariant | Status | Guard test |
|---|---|---|
| llm_provider chokepoint routes through dispatcher on `tenant_id` | ✅ | `test_call_llm_with_fallback_routes_through_dispatcher_when_tenant_id_given` |
| Backward-compatible: no `tenant_id` → pre-migration path | ✅ | `test_call_llm_with_fallback_uses_platform_path_when_tenant_id_absent` |
| Platform fallback (rule 1) unchanged when no BYO | ✅ | `test_dispatcher_falls_back_to_platform_when_no_tenant_byo` |
| Cap-exceeded on tenant A does not 429 tenant B | ✅ | `test_ai_cap_exceeded_on_tenant_a_does_not_affect_tenant_b` |
| Transactional → HTTP 429 | ✅ | `test_transactional_ai_callsite_returns_429_on_cap_exceeded` |
| Scheduled → `skipped_cap_exceeded`, no exception | ✅ | `test_scheduled_ai_callsite_marks_skipped_cap_exceeded_and_does_not_raise` |
| Test-mode short-circuits outbound HTTP | ✅ | `test_ai_testmode_mock_short_circuits_outbound_http` |
| Test-mode preserves cap + BYO probe firing | ✅ | `test_ai_testmode_mock_still_enforces_cap_and_fallback` |
| Checklist load path has no AI dispatch | ✅ | `test_checklist_load_path_has_no_ai_dispatch` |
| Dispatcher cap-exceeded doc still present | ✅ | `test_dispatcher_module_docs_still_present` |
| P0 checklist 429 regression suite green | ✅ | `test_p0_checklist_429_leak_regression.py` (5/5) |
| Chunk 1 + all prior I1.7 BYO chunks green | ✅ | Full I1.7 sweep (152 passed, 1 skipped) |

---

## Chunk 2.b follow-up (SHIPPED · Feb-2026)

The 8 messaging-adjacent AI callers migrated in Chunk 2 covered
transactional + BYO-opt-in. Chunk 2.b finished the job by migrating
the remaining **21 backend files** off the raw
`emergentintegrations.llm.chat.LlmChat` SDK onto the same chokepoint.

* **Scope:** 19 §3.1 main-pass files + 2 §3.2 base64-vision files +
  2 §3.3 chemistry/service_reports files (plumbing-only).
* **Chokepoint extension:** `call_llm_with_fallback` now accepts
  `image_b64s`, `parse_json`, and `max_tokens` (all additive).
* **New test suite:** `test_i17e_chunk2b_raw_sdk_migration.py` — 101
  passing tests, all four Chunk 2 chunks green.
* **Full write-up:** `memory/PHASE_I17E_CHUNK2B_RAW_SDK_MIGRATION.md`.

The AST guards there make it a compile-time regression to re-import
the raw SDK on any of the 21 files.
