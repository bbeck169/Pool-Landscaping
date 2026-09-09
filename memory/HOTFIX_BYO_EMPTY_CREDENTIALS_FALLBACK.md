# HOTFIX — BYO empty-credentials fallback (comms + AI + maps)

**Landed:** Feb 2026 · session in-flight with Phase 4 batched wave.

## What broke
User's tenant enabled BYOP (Bring-Your-Own-Provider) for Resend +
RingCentral. Both outbound channels silently stopped delivering.

## Root cause
`services.messaging._helpers.save_provider_config` marks the
tenant_secrets row `connected=True` as soon as
`validate_config` accepts the shape — no live probe. A user who
saved partial input (empty `api_key`, blanked field after
partial save) ended up with a `connected=True` row that had
whitespace-only required fields.

The three BYO dispatchers all treated the presence of a
`connected=True` row as authoritative. On every send the BYO
provider's `send_*` / `complete` / `geocode` call raised an
empty-auth exception, the dispatcher returned a `_envelope_failed`
/ propagated the exception, and the caller **never fell back to
the platform key**.

## Fix (one shape, three files)
Extracted a shared helper module: `services/byo_common.py` with
`byo_required_fields_present()` + `looks_like_credential_failure()`.

Wired in three dispatchers:
1. `services/messaging/byo_passthrough.py` — email + sms
2. `services/ai/dispatcher.py::dispatch_ai_completion`
3. `services/maps/dispatcher.py::_dispatch_op`

In each, TWO checks run before the BYO provider is invoked:
* pre-call — every `required=True` field on the provider schema
  must resolve to a non-blank string. If not → fall back to platform.
* post-call — on exception, `_looks_like_credential_failure(err)`
  → fall back to platform.

**Cap-exceeded semantics unchanged.** Comms cap → `_envelope_cap()`
still surfaces. AI cap → `TenantAIUsageCapExceeded` still raises.
Maps cap → `TenantMapsRequestCapExceeded` still raises. No silent
degradation on quota events.

## Tests locked in
* `tests/test_p0_byo_empty_credentials_fallback.py` — 13 tests
  (comms email + sms, guard + credential-exception fallback,
  substring helper positive/negative)
* `tests/test_p1_ai_maps_byo_empty_credentials_fallback.py` — 12
  tests (AI + Maps mirror shapes, cap-exceeded HARD BLOCK
  regression check on both)

## Verified regression clean
* `test_i17c1_ai_byo_providers.py` + `test_i17c2_maps_byo_providers.py`
  → 31/31 pass (Chunks 2 + 3 BYO contract preserved)
* `test_comms_gate_prod_bypass.py` + `test_k30_resend_adapter_allow_off_allowlist.py`
  → all pass in isolation (one pre-existing cross-test env-var
  pollution flake unrelated to this fix)
* Phase 4 RTL sweep — 40/40 pass (Phase 4 work preserved
  end-to-end)
