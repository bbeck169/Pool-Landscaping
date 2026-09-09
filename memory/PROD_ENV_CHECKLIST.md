# Production ENV Checklist — `*_TESTMODE_MOCK` flags

**Feb 2026 — P0 safety net.** A single stale `*_TESTMODE_MOCK` flag on
production silently mocks every outbound call for that subsystem while
every safety gate (guard_outbound, comms whitelist, kill-switch, BYO
health) still reports LIVE. The K9 portal-chat SMS bug and the Feb 2026
"add-card link / portal invite / auto post-visit email" outage were
both caused by this shape.

## Required prod values

When `APP_ENV=production`, **every** flag below MUST be `false`
(or unset). Flipping any to `true` silently disables the associated
provider integration.

| Env var | Prod value | What it mocks when truthy |
|---|---|---|
| `MESSAGING_TESTMODE_MOCK` | `false` | Email + SMS via all centralized adapters (`services/comms_email_adapter`, `services/comms_sms_adapter`, `services/email/resend_adapter`, `services/sms/rc_adapter`, `services/messaging/byo_passthrough`). Every send returns `status="sent"` / `provider="mock"` with a deterministic `mock-<sha1>` provider response id. |
| `AI_TESTMODE_MOCK` | `false` | LLM completions (OpenAI / Anthropic / Gemini) — every call returns a canned response. |
| `CALENDARS_TESTMODE_MOCK` | `false` | Google Calendar + Outlook OAuth start / callback / push / pull mock. Real calendar sync stops. |
| `PAYMENTS_TESTMODE_MOCK` | `false` | Stripe SetupIntent / PaymentIntent / Connect flows are mocked. **No card is actually captured or charged.** |
| `ZILLOW_TESTMODE_MOCK` | `false` | RapidAPI Zillow property lookups return canned fixtures. |

Additional related flags (informational — different semantics):

| Env var | Prod value | Notes |
|---|---|---|
| `APP_ENV` | `production` | Drives `comms_env_guard`, `is_comm_allowed` prod bypass, and every K-phase kill-switch. Must never be `preview` / `staging` / unset on `app.plofv.com`. |
| `FEATURE_CUSTOMER_EMAIL_KILL_SWITCH` | `off` | Emergency incident-response break. `on` blocks every `audience="customer"` send regardless of `APP_ENV`. |
| `STRIPE_TESTMODE_MOCK_CONNECT` | (deployment-dependent) | Separate Stripe Connect OAuth mock; distinct from `PAYMENTS_TESTMODE_MOCK`. |
| `SMS_TESTMODE_MOCK` / `EMAIL_TESTMODE_MOCK` | unset | Legacy per-channel flags (`services/messaging/_helpers.py`). Prefer `MESSAGING_TESTMODE_MOCK`. |

## Boot-time guardrail (Feb 2026)

`server.py` startup runs a `[PROD-GUARDRAIL]` check that:
1. Emits `logger.critical(...)` when `APP_ENV=production` AND any of
   the five `*_TESTMODE_MOCK` flags above is truthy, naming each
   offending flag.
2. Fails `/health/ready` with `503` and `failures[].reason =
   "mocking_in_production"` plus `flags=[...]` so k8s + monitoring
   pull the pod out of rotation until the flag is flipped.

The check re-reads `os.environ` on every probe hit, so
`sudo supervisorctl restart backend` after a `.env` flip is
sufficient — no code change required to clear the alarm.

## Verification steps after any prod `.env` change

1. `sudo supervisorctl restart backend`
2. Confirm boot log line: `[PROD-GUARDRAIL] ok — no *_TESTMODE_MOCK flags truthy (prod=True)`
3. `curl -sS "${REACT_APP_BACKEND_URL}/api/health/ready" | jq` → `status: "ready"`, `checks.prod_guardrail: "ok"`.
4. Fire one live send through the fastest path (add-card link) and
   confirm the provider response id does NOT start with `mock-`.

## Where each flag is honored (grep anchors)

- `MESSAGING_TESTMODE_MOCK` → `services/messaging/testmode.py` (single definition), consumed by 6 adapters.
- `AI_TESTMODE_MOCK` → search `AI_TESTMODE_MOCK` in `services/ai/*` and `services/llm/*`.
- `CALENDARS_TESTMODE_MOCK` → `services/calendars/*` (Google + Outlook adapters).
- `PAYMENTS_TESTMODE_MOCK` → `services/stripe/*` and `services/payments/*`.
- `ZILLOW_TESTMODE_MOCK` → `services/property_data.py`.

## History

- **Feb 2026** — First mass mocking incident. `MESSAGING_TESTMODE_MOCK=true` shipped to prod together with `APP_ENV=production`; add-card link, portal invite (indirect), and auto post-visit emails silently succeeded with mock envelopes for hours before user noticed nothing arrived. Fix: flip all five flags to `false` + ship `[PROD-GUARDRAIL]` boot check + `/health/ready` `prod_guardrail` gate.
