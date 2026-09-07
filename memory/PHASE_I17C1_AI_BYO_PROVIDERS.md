# Phase I1.7.c.1 · Tenant Integrations: AI BYO Providers

**Feb-2026 · Status: SHIPPED (green — 12/12 backend + 7/7 new frontend)**

## Scope
Add tenant-scoped Bring-Your-Own-Key support for **OpenAI · Anthropic · Gemini**,
with encrypted-at-rest secret storage, monthly token usage tracking, and
soft-warn / hard-block cap enforcement. Existing app AI callsites are
intentionally NOT rewired yet (I1.7.e follow-up).

## Backend
- `services/ai/tenant_base.py` — `AIProvider` ABC.
- `services/ai/openai_provider.py`, `anthropic_provider.py`, `gemini_provider.py`
  — thin httpx wrappers; short-circuit under `AI_TESTMODE_MOCK=true`.
- `services/ai/registry.py` — provider registry + short-name mapping
  (`ai_openai ↔ openai`).
- `services/ai/_helpers.py` — JSON-encode config → encrypted blob via
  `services.secrets.put_secret`. `primary_secret_field="api_key"` drives
  `last_4` correctly (regression guard from I1.7.b.fix).
- `services/ai/usage.py` — two collections:
    - `tenant_ai_provider` (plaintext sidecar: cap + default_model)
    - `tenant_ai_usage` (per-`(tenant, provider, yyyymm)` counters)
  Cap semantics (locked with user, 2026-02):
    - `null` → **unlimited** (default)
    - `0` → **block all** (explicit kill-switch)
    - `>0` → hard-block at `used >= cap` (checked against `tokens_total`);
      soft-warn at `used >= 0.8 * cap`.
- `services/ai/dispatcher.py` — `dispatch_ai_completion(...)`:
    - No BYO row → **platform fallback** to Emergent LLM Key (via existing
      `services.llm_provider.call_llm_with_fallback`).
    - BYO row + cap hit → **raise `TenantAIUsageCapExceeded`** (HTTP 429),
      NO platform fallback.
    - BYO row + cap ok → dispatch, `record_usage(...)` after success.

## Endpoints (all `/api`-prefixed)
- `PUT /tenants/me/integrations/ai_{openai|anthropic|gemini}` — accepts
  `{config: {api_key, default_model?}, monthly_token_cap?}`.
  admin+ / super_admin only. Never echoes plaintext.
- `DELETE /tenants/me/integrations/ai_{provider}` — removes BOTH the
  encrypted secret row AND the metadata sidecar.
- `GET /tenants/me/integrations/ai/usage` — per-provider snapshot for the
  current month: `{provider, tokens_prompt, tokens_completion, tokens_total,
  monthly_token_cap, default_model, connected, pct_used, status}` where
  `status ∈ {ok, warn, blocked}`.
- `GET /tenants/me/integrations/schemas` — now includes `ai: [{provider_key,
  kind:"ai", fields, models}]` so the FE renders schema-driven forms.

## Frontend
- `components/settings/TenantIntegrationsCard.jsx` — new `AICard` sub-component
  renders one card per AI provider with:
    - `api_key` password input (never echoes stored value)
    - `default_model` dropdown fed by `schema.models[]`
    - `monthly_token_cap` numeric input (empty = null = unlimited, 0 = block)
    - Usage progress bar (green < 80% · amber 80–99% · red ≥ 100%)
    - Warn banner at soft-warn state, hard-block banner at blocked state
- Root component now fetches `/tenants/me/integrations/ai/usage` in parallel
  with list + schemas.
- Manager role sees the cards but no save/disconnect controls (parity with
  I1.7.b behaviour).

## Tests
- `tests/test_i17c1_ai_byo_providers.py` — **12 cases** (registry contents,
  PUT masking, secret roundtrip, `last_4` regression guard, encryption at rest,
  DELETE cleanup, dispatcher BYO happy path, platform fallback path,
  cap null / soft warn / hard block / kill-switch).
- `frontend/src/test/i17c1-ai-byo-card.test.jsx` — **7 cases** (render, save
  body shape, null cap, 0 cap, warn state, blocked state, manager gate).
- `i17a-integrations-page.test.jsx` updated to reflect: AI is now a real card
  (coming-soon list dropped `ai`; `_seedSchemas` includes AI providers;
  mock handles `/ai/usage`).

## Compatibility
- Existing I1.7.a + I1.7.b endpoints unchanged. All 107 I1.7-series backend
  tests + all 25 I1.7-series frontend tests green.
- Existing app AI callsites (`services/llm_provider.py`, `ai_estimator`, etc.)
  are **untouched**. Migration to `dispatch_ai_completion` is deferred to
  Phase I1.7.e.
- Emergent LLM Key remains the platform default when no BYO configured.

## Follow-ups (deferred, not in this phase)
- **I1.7.e** — Rewire existing AI callsites through `dispatch_ai_completion`
  so ALL tenant AI runs through the same cap/fallback gate.
- **I1.7.c.2 / .c.3** — Maps + Calendars BYO (same registry pattern).
- **429 mapping** — surface `TenantAIUsageCapExceeded` as HTTP 429 at every
  future callsite in I1.7.e.
