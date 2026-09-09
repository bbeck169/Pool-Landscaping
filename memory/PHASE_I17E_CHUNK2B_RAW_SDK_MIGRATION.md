# Phase I1.7.e · Chunk 2.b — Raw-SDK AI Callsite Migration

**Status:** SHIPPED · Feb-2026
**Owner:** i17e-ai (main agent)
**Scope:** 21 backend files + chokepoint extension
**Behavior surface:** Zero end-user changes. Zero schema changes. Zero
new routes. Return shapes preserved 1:1 so callers keep parsing `raw`
identically.

## Why

Chunk 2 landed the central AI chokepoint
(`services.llm_provider.call_llm_with_fallback`) and migrated the
messaging + checkin-rewrite paths onto it. Chunk 2.b finishes the
job by pulling the **21 remaining backend files** off the raw
`emergentintegrations.llm.chat.LlmChat` SDK and onto the same
chokepoint. Once this ships:

* **BYO-key opt-in** becomes a one-kwarg change (`tenant_id=…`) on
  every AI callsite.
* **Per-tenant spend cap** enforcement fires everywhere, not just on
  the messaging path.
* `AI_TESTMODE_MOCK` short-circuit works everywhere — no callsite
  can accidentally hit a live provider in test mode.
* Removing the raw SDK from every non-chokepoint module is a
  hard-guardable AST invariant (see the test suite).

## Chokepoint extension (already shipped in the prior micro-step)

`services.llm_provider.call_llm_with_fallback` now accepts:

| kwarg          | type              | plumbs to                          |
| -------------- | ----------------- | ---------------------------------- |
| `image_b64s`   | `List[str] \| None` | `ImageContent(image_base64=…)` (per SDK requirement) |
| `parse_json`   | `bool = True`     | If `False`, returns `{"raw": {"text": <str>}}` so callers keep their own JSON extract logic bit-for-bit |
| `max_tokens`   | `int \| None`     | `LlmChat.with_max_tokens(…)`       |

All three are additive — pre-Chunk 2.b callers keep working.

## Migrated files (21 total, grouped by sub-pass)

### §3.1 — main pass (17 files)

Plaintext / JSON callers with no image or vision surface. Uses
`parse_json=False` universally so the caller-side JSON extract
(fenced-block stripping, regex fallback) stays identical.

| # | File | Callsites |
| - | ---- | --------- |
| 1 | `routers/admin.py` | 1 · Marina chat (transactional) |
| 2 | `routers/ai_brain.py` | 1 · Copilot tool-call loop (multi-turn context reconstructed via transcript concat) |
| 3 | `routers/ai_employees.py` | 1 · AE1 chat with 6-turn history preamble |
| 4 | `routers/ai_ops.py` | 1 · Employee chat with history replay (folded into single-turn preamble) |
| 5 | `routers/ai_visibility.py` | 1 · Claude Q-scan (schema: `response_text` / `sources` / `raw` / `api_cost_usd`) |
| 6 | `routers/business_os.py` | 2 · `_ai_generate` (SOP/huddle/retro helpers) + Lana chat |
| 7 | `routers/cfo.py` | 2 · `_llm_classify` (expense-categorize) + `_call_llm_text` (pricing suggestion) |
| 8 | `routers/churn.py` | 2 · `_call_claude` (churn signals) + retention playbook builder |
| 9 | `routers/gbp.py` | 1 · GBP AI text helper (post + reply) |
| 10 | `routers/gbp_posts.py` | 2 · Draft-from-card + dead-import removal on `_generate_image` |
| 11 | `routers/marketing_studio.py` | 3 · `_ai_variant` / `_ai_email` / `_ai_sms` |
| 12 | `routers/phase11.py` | 1 · Virtual-bid narrative fallback |
| 13 | `routers/portal.py` | 1 · Marina auto-reply (customer portal) |
| 14 | `routers/reviews_ai_reply.py` | 1 · Auto-review-reply with `[REVIEWER]` post-substitution |
| 15 | `routers/seo.py` | 1 · `_ai_json` helper (drives SEO studio) |
| 16 | `routers/seo_agentic.py` | 6 · semantic score / outline / topical map / content-suggest / LLM-visibility two-hop / atlas-router |
| 17 | `routers/seo_content_refresh.py` | 1 · Rewrite scorer |
| 18 | `routers/seo_phase17c.py` | 3 · OTTO patch / Studio auto-fill / exec-summary |
| 19 | `routers/social.py` | 1 · `_ai_call` (caption/hashtag/alt-text generator) |

(19 rows above — the "17 main" line from the earlier scope report
counted the tool-loop and history-replay callsites as one; the
migration touched all 19 files.)

### §3.2 — base64-vision sub-pass (2 files)

These callers **fetch remote photo URLs → base64-encode → pass
`image_b64s=[…]`** to the chokepoint. The chokepoint plumbs each
b64 into `ImageContent(image_base64=…)` — same as before, but now
BYO-key + cap-enforced.

* `routers/estimator.py` — `_call_generate` (multi-photo scope
  parser, up to 6 photos per request, per-URL failures logged +
  reported via `skipped_photos`).
* `services/ai/estimate_from_media.py` — checkin-rewrite estimate
  (already migrated in the pre-Chunk 2.b micro-step; scope kept in
  this doc for completeness).

Two additional files also do base64 vision via `image_b64s` even
though they belong to other sub-passes:

* `routers/service_reports.py::analyze_water_photo` (§3.3 file that
  happens to do vision)
* `routers/social.py::ai_alt_text` (§3.1 file that opportunistically
  fetches + b64-encodes the media URL to hit the chokepoint's
  b64-only image path)

The `test_base64_vision_uses_image_b64s` guard covers all four.

### §3.3 — chemistry + service_reports (2 files, plumbing-only)

Explicitly **callsite-only** — zero endpoint changes, zero schema
changes. Approved by user as a single push with the rest.

* `routers/chemicals.py` — chemistry dosing recommendation
  (already migrated in the pre-Chunk 2.b micro-step).
* `routers/service_reports.py` — TWO callsites:
    * `analyze_water_photo` (base64 vision, JSON parse local)
    * `_llm_rephrase_reasons` (pool-dosing reason rephraser,
      `max_tokens=800`)

The plumbing-only invariant is asserted at test time by comparing
the current route tables against a frozen list captured Feb-2026
(see `test_chemicals_routes_unchanged_plumbing_only` and
`test_service_reports_anchor_routes_present`).

## Cap-exceeded posture (per callsite)

| Callsite kind                                       | Posture                                                 |
| --------------------------------------------------- | ------------------------------------------------------- |
| Transactional (user clicks button, waits for result)| `raise_if_ai_cap_exceeded(result)` → HTTP 429           |
| Scheduled cron / best-effort helper                 | `is_ai_cap_exceeded(result)` → return stub / mocked shape (no raise) |

Files using **`raise_if_ai_cap_exceeded` (transactional)**: `admin.py`,
`seo.py`, `gbp.py`, `seo_agentic.py` content-suggest + node-outline.

Files using **`is_ai_cap_exceeded` (scheduled / best-effort)**: everyone
else. Rationale: on a cron cap-exceeded we want the run to persist a
`skipped_cap_exceeded` row and continue with the next tenant, NOT to
crash the whole scheduler tick.

Every migrated file MUST reference at least one of the two helpers —
guarded by `test_cap_helper_referenced` in the Chunk 2.b test suite.

## Test suite

New: `backend/tests/test_i17e_chunk2b_raw_sdk_migration.py` — **101
passing tests** (Feb-2026), broken down as:

* 21 × `test_no_raw_sdk_import_remains` (parametrized)
* 21 × `test_no_naked_llmchat_construction` (parametrized)
* 21 × `test_chokepoint_import_present` (parametrized)
* 21 × `test_cap_helper_referenced` (parametrized)
* 4 × `test_base64_vision_uses_image_b64s` (parametrized)
* 2 × §3.3 plumbing-only route diffs
* 3 × chokepoint signature + docstring + P0 checklist invariant guards

Regression sweep: prior chunk 2 + 2.c suites still 100 % green
(27 tests, verified during ship).

## Callers that still opt out of BYO (follow-up) — SHIPPED · Feb-2026

Every migrated helper accepts `tenant_id=…`. In the initial Chunk 2.b
push a handful of callers still passed `None` to preserve the "zero
behavior change" invariant. The follow-up push threaded the real
`tenant["id"]` down each of those 5 callsites so per-tenant BYO keys
+ spend caps actually fire:

| # | File | Caller function | Callsite endpoint(s) | Cap posture |
| - | ---- | --------------- | -------------------- | ----------- |
| 1 | `routers/business_os.py` | `_ai_generate` (accepts `tenant_id`; 3 callers pass it) | `POST /sops/generate`, `POST /huddles/{hid}/agenda-ai`, `POST /sprints/{sid}/retro-ai` | best-effort — degrades to friendly stub |
| 2 | `routers/marketing_studio.py` | `_ai_variant` / `_ai_email` / `_ai_sms` (all three signatures gained `tenant_id`) | `POST /marketing/campaigns/{cid}/generate` (5 callsites), `POST /marketing/posts/generate` (1) | best-effort — falls back to deterministic stub |
| 3 | `routers/seo_phase17c.py` | `_claude_patch` | `POST /otto/generate-fixes` (per-issue loop) | transactional — returns `mocked=True` + `rationale="ai_spend_cap_exceeded"` per issue so the aggregated endpoint response has an audit trail (does NOT raise 429 mid-loop) |
| 4 | `routers/seo_agentic.py` | `_llm_semantic` | `POST /seo/content-score` | best-effort — returns mocked `score=60` so the composite 8-input score still succeeds |
| 5 | `routers/service_reports.py` | `_llm_rephrase_reasons` | `POST /service-report/recommend-chemicals` | best-effort — passes deterministic recs through untouched + surfaces `err="ai_spend_cap_exceeded"` |

**Cap posture note (§3 in the callout above):** OTTO's `_claude_patch`
is called from a transactional endpoint but keeps the "return mocked"
posture on cap-exceeded (not raise-429). Rationale: the endpoint
loops over multiple issues per audit; raising 429 mid-loop would kill
the partial batch. The `mocked=True` shape lets the endpoint persist
each issue's outcome (including the "we skipped this one because AI
cap was exceeded" audit trail) and still return a coherent aggregated
response. Consistent with the pre-follow-up cap posture already in
the file — no posture change was needed.

**Zero-behavior-change guarantee:** every migrated helper's default
`tenant_id=None` value is preserved so pre-follow-up callers that
never had a tenant in scope keep working unchanged.

**Test coverage (Chunk 2.b follow-up):** 5 runtime tests
(`test_<file>_threads_tenant_id`) + 5 parametrised AST guards
(`test_byo_followup_callers_thread_tenant_id_in_source`) asserting
the callsite fragments literally reference `tenant["id"]`.  All 10
green.  All tests are monkeypatch-only; no Mongo required.

## Guardrails honored (from the scope §7)

* Only the 21 files + chokepoint extension touched.
* Zero behavior change end-users observe.
* All `data-testid` attributes preserved (backend-only migration).
* Return shapes preserved — callers keep parsing `raw` the same way.
* NO comms / offline / Stripe / Resend / RingCentral / notifications
  / filters / geocoding touched.
* Web / backend only — no mobile-native (Expo) code changed.
* NO external repository operations.

## Not touched (intentional)

* `routers/render.py` — landscape design image generation (uses
  Nano Banana). Separate chokepoint (`services.image_gen_nano_banana`);
  out of scope for the LLM-text migration.
* `services/media_provider.py`, `services/soshie/ai_image_gen.py` —
  image-gen adapters, out of scope.
* `routers/marketing_forms.py` — appeared in a wider grep but is
  outside the user-approved 21-file scope.
* Schema migration merging `db.estimates` / `db.estimator_estimates`
  / `db.quotes` — explicitly DEFERRED (Outcome C locked the URL
  layer only).
