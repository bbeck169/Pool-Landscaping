# Test Credentials — Pool & Landscaping of Vistancia

> Reset to password123 by reset_demo_passwords_to_default.py on 2026-07-27T08:38:37.671303+00:00 (demo mode)

## Auth mechanism
- POST `/api/auth/login` with `{email, password}` returns `{access_token, user}`.
- Tokens are Bearer JWTs — send `Authorization: Bearer <token>` on every subsequent call.
- Demo mode: all seeded accounts share the plaintext `password123`. Rotate with `scripts/rotate_demo_passwords.py` for a security review.

## Accounts
- **super_admin** · `super@aquaterra.com` · `password123`
- **manager** · `manager@aquaterra.com` · `password123` — Phase 53c (Feb 2026) restored this seed: an unrelated migration had promoted the row to `role=admin` (surfaced during Phase 53b E2E verification of the manager read-only branch). `seed_demo_manager()` in `backend/seed.py` now heals the drift on every boot. Verified Feb 2026 via `/api/auth/me` → `role=manager`.
- **admin** · `admin@aquaterra.com` · `password123` — Phase 49 hotfix (Feb 2026) corrected the role here: this account is `role=admin` in the live env, NOT `role=customer` as previously documented. Verified via a direct `db.users` lookup.
- **technician** · `carlos@aquaterra.com` · `password123` — Phase 49 hotfix corrected: this account is `role=technician`, NOT `role=admin`.
- **technician** · `landscaper@aquaterra.com` · `password123` — landscape tech (`department="landscaping"`) used by `test_ai_employees_ae1.py::tech_headers` fixture. Verified Feb 2026 via `/api/auth/me`.
- **technician** · `mike@aquaterra.com` · `password123` — **POOL tech** (`department="pool"`). Phase 41.1b (Feb 2026) restored this seed: previously the row lived only inside the one-shot `seed()` function which early-returns when the users collection is non-empty, so any deployment where another user was created first never got Mike. Now backfilled on every boot via `seed_pool_tech_mike()` in `backend/seed.py`. Verified Feb 2026 via `/api/auth/me`.
- **customer** · `customer@aquaterra.com` · `password123`

## Password policy — testing note (Phase 34 · Feb 2026)
The **change password** flow (`POST /api/auth/change-password`) enforces a
policy that requires **at least one uppercase letter, one lowercase letter,
one digit, and a minimum length of 8 characters**. The seeded demo
password `password123` deliberately violates that policy (no uppercase),
so the change-password endpoint will reject a re-set to the same value.

Workarounds for tests that need to exercise the change-password flow:

1. Use a policy-compliant value like `Password123` when targeting the
   change-password endpoint.
2. To restore the demo default afterwards, run
   `python /app/backend/scripts/reset_demo_passwords_to_default.py`
   which bypasses the change-password policy by writing the bcrypt hash
   directly into the users collection. This is the ONLY sanctioned way
   to snap a demo account back to `password123` between tests.
3. If a test needs the account to end each iteration at a
   policy-compliant password, do NOT reset to `password123` — pick a
   value like `Password123` and update the test data fixture instead.

The **login** endpoint applies no such policy — it accepts any password
that matches the stored bcrypt hash, which is why `password123` continues
to work for `POST /api/auth/login`.

## Notes
- Landscape techs carry `role: "technician"` + `department: "landscaping"` and are required to
  finalize their onboarding checklist before route assignment.
- Emergent LLM key, Resend API key, Stripe test/live keys are in `/app/backend/.env`.
- `SEED_DEMO_USERS` gate is unchanged — production still refuses to seed these demo users.

---

## Second portal customer for isolation testing

For cross-customer PII / identity-leak testing on preview, use these
two portal-enabled customer accounts. Both live in the same tenant
so a leak between them would be immediately visible (distinct names
+ distinct balances).

| # | Email                       | Password    | Name             | Notes                                    |
|---|-----------------------------|-------------|------------------|------------------------------------------|
| 1 | `customer@aquaterra.com`    | `password123` | Jennifer Carson | Original seeded portal customer          |
| 2 | `rblake@outlook.com`        | `password123` | Robert Blake     | Second portal-enabled customer (isolation) |

### Quick verification
```
API=$REACT_APP_BACKEND_URL
# Robert should get first_name="Robert" (never "Jennifer") from /portal/home
TOK=$(curl -s -X POST "$API/api/auth/login" -H 'Content-Type: application/json' \
      -d '{"email":"rblake@outlook.com","password":"password123"}' \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s "$API/api/portal/home" -H "Authorization: Bearer $TOK" \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["customer"]["first_name"],d["identity_mismatch"])'
# → Robert False
```

If `identity_mismatch` is `True` at any point, the JWT and the
resolved customer's email don't agree — surface as a P0.

---

## Testing gotchas (Feb-2026 callouts)

### `.test` TLD rejected by portal `create-login`
Pydantic's `EmailStr` (via `email-validator`) requires the domain to have a real MX record or an explicit `check_deliverability=False`. `.test` is RFC 6761-reserved and has no MX, so any auto-test that POSTs `foo@bar.test` into portal invite / create-login flows gets a 422.

**Do not** add a code-level whitelist for `.test` — it risks blessing throwaway addresses on real customer data. Instead auto-tests should use:
- `foo@bar.local` (also RFC 6761 reserved) — accepted by `email-validator` in bypass modes but WILL still fail deliverability in some configs.
- Preferred: a dedicated seeded mailbox on a domain the tenant already owns (`qa+run<N>@aquaterra.com`) — the existing demo seed uses this pattern for `admin@aquaterra.com`, `super@aquaterra.com`, `mike@aquaterra.com`, `customer@aquaterra.com`.

### `ALLOW_TEST_HOOKS` gated off on preview
The preview pod's `backend/.env` sets `APP_ENV=production`, which force-clears `ALLOW_TEST_HOOKS=0` at server-start regardless of the `.env` value (see `server.py:829-832`). Tests that need direct Motor-async re-entry must either:
- Drive through a real HTTP endpoint (recommended — matches production semantics).
- Or use a fresh Motor client instantiated inside the test process (heavier; avoid unless the endpoint route doesn't exist).
Do NOT ship a code change that flips `APP_ENV=preview` on this pod to bypass the gate.

### `COMMS_TEST_ALLOWLIST_*` hygiene (Backlog #iv · Feb-2026)

The `COMMS_TEST_ALLOWLIST_PHONES` / `COMMS_TEST_ALLOWLIST_EMAILS` env vars gate live outbound in **non-production** environments — every recipient that ISN'T in these lists gets DRY-RUN'd. The pattern is intentionally permissive so QA can smoke-test the real RingCentral / Resend path.

**However**: the allowlist MUST NEVER contain a live workforce, tenant business-card, or `RC_FROM_NUMBER` / `EMAIL_FROM` address. When it does, any bogus recipient value that happens to match a live admin-owned address gets delivered — the exact leak vector root-caused for Backlog #iv Bug 2 (`+16028874400` was both the tenant's `RC_FROM_NUMBER` AND on the allowlist).

**Boot check (log-only)**: `services/comms_hardening/deny_list.py::allowlist_overlap_check` runs on every startup and emits one WARN log line per overlap:

```
notifications.allowlist.overlap kind=<sms|email> value=<addr> tenant_ids=<...> sources=<workforce|tenant_business_card|env_from_number|env_from_email>
```

Log-only — never blocks startup. Watch `/var/log/supervisor/backend.err.log` after every deploy; any overlap needs an env-vars fix by the operator.

**Recommended QA phones/emails**: use a dedicated non-live number (Twilio test number, a personal QA line, or a Google Voice throwaway) — NEVER a workforce line or the tenant's outbound-from number. The runtime deny-list (`strip_admin_owned_recipients`) is a suspenders-layer; keeping the allowlist clean is belt-layer.

**Not enforced in code** — documented so future contributors don't re-introduce the smell.
