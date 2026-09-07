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


## Post-tester fix (2026-02) — Preserve-Stored-Secrets on partial edits

**Bug reproduced by tester:** `PUT /tenants/me/integrations/ai_openai` with
`{"config": {"default_model": "gpt-4o-mini"}, "monthly_token_cap": 0}`
returned **400** (missing `api_key`) even when the provider was already
connected. Impact: tenants couldn't adjust cap/model without re-typing
the api_key, and the "cap = 0 kill-switch" flow was unreachable via the
UI's "leave blank to keep current" affordance.

**Fix** (backend, `routers/tenant_integrations.py`):

Added a router-scoped helper `_preserve_stored_secrets(...)` invoked
BEFORE validation on the `PUT /tenants/me/integrations/{provider_key}`
handler for BOTH the AI branch AND the messaging (SMS/Email) branch. It:

1. Loads the tenant's stored decrypted config for this `provider_key`
   (empty return → no merge, incoming payload passes through unchanged).
2. Merges incoming values on top of the stored dict. For fields marked
   `secret=True`, blank/`None` incoming values PRESERVE the stored
   value (so a blank api_key input rotates nothing). For non-secret
   fields, blank/`None` incoming values propagate as-is — the tenant
   remains able to clear an optional non-secret field explicitly.
3. Validation runs against the MERGED result. Unconnected providers
   with a missing required field still hit the pre-fix 400/422 path.

**Contract (added to the integrations save contract):**

> If a tenant already has a stored secret for `{provider_key}`, blank
> or omitted `secret=True` fields on the PUT payload preserve the
> stored value. Non-secret fields on the payload always win. This
> makes cap/model/from-number/etc. edits possible without re-typing
> the api_key or auth_token.

**Tests added (all green):**
- `test_cap_only_edit_preserves_stored_secret` — cap edit only, verifies
  `last_4` unchanged, cap updated, adapter still decrypts the ORIGINAL
  `api_key`.
- `test_model_only_edit_preserves_stored_secret` — same shape for the
  `default_model` field.
- `test_missing_api_key_on_unconnected_provider_still_422` — regression
  guard that unconnected providers still reject partial-config PUTs.
- `test_cap_zero_via_edit_only_saves_and_blocks_dispatch` — end-to-end
  kill-switch: cap-only edit → 0, `/usage` reports `status="blocked"`,
  `dispatch_ai_completion` raises `TenantAIUsageCapExceeded` (no
  platform fallback).
- `test_messaging_partial_edit_preserves_secret_uniformly` — proves the
  fix is uniform: connect twilio, PUT only `from_number`, stored
  `auth_token` intact at rest.

**Frontend tests added:**
- `cap-only edit on connected provider posts PUT WITHOUT api_key` —
  locks the UI contract that the blank `api_key` input is a preserve
  signal.
- `disconnect flips the card back to disconnected state` — locks the
  post-DELETE reload → visual state flip that the tester found
  inconclusive via browser-use.

**Numbers post-fix:**
- Backend I1.7 suite: **112/112 green** (17/17 in `test_i17c1_ai_byo_providers.py`).
- Frontend I1.7 suite: **27/27 green** (9/9 in `i17c1-ai-byo-card.test.jsx`).
- Tester's exact curl repro now returns `HTTP 200`.
