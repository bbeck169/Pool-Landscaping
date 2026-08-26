# Portal magic-link merge tags — Security model & operator guide

_Ships: Feb 2026_
_Owners: Backend / marketing surfaces_

## What shipped

Two new merge tags surface auto-login magic links in email + SMS
bodies without requiring the recipient to remember creds:

| Tag | Scope (`sub`) | Landing | TTL |
|---|---|---|---|
| `{{CUSTOMER_PORTAL_LOGIN_LINK}}` | `portal_home` | `/portal/home` | 14 days |
| `{{SERVICE_RECORD_LINK}}` | `job_view` | `/portal/service-reports/{sr_id}` | 14 days |

Lowercase aliases (`{{customer_portal_login_link}}`, `{{service_record_link}}`)
registered in `services/comm_tokens.py` so the comms composer's token
picker + validator surface them alongside the dotted tokens.

Both tags render to a URL of shape:

```
{APP_PUBLIC_URL}/api/portal/auto-login?t=<jwt>
```

Redemption is handled by the existing interstitial
`GET /api/portal/auto-login` (`backend/routers/portal_auto_login.py`) —
**no new endpoint was created**. The user brief mentioned
`/api/portal/magic/{token}`; we reused the existing verifier because
it already handles all four scopes (`job_view`, `portal_invoice_pay`,
`portal_estimate_view`, `portal_home`) with the correct cross-scope
replay guards.

## Security model

* **Signing**: HS256 JWT, `JWT_SECRET` from `backend/.env`
  (fail-loud ≥32 chars in prod per `config.py`).
* **Scope isolation**: each token carries a distinct `sub` claim.
  A leaked `portal_home` link can NEVER be replayed as
  `portal_invoice_pay` / `portal_estimate_view` / `job_view` — each
  scope's verifier rejects tokens with the wrong `sub` (401
  `token_wrong_scope`). Covered by
  `test_magic_link_merge_tags.py::test_portal_home_token_rejected_by_invoice_pay_verifier`
  and its sibling.
* **TTL**: 14 days on both tags (overrides the shorter scope defaults
  in `services/portal_magic_links.py`, which use 24h / 48h for
  door-hanger + invoice paths that don't route through the merge-tag
  catalog). Verified by unit tests within a ±5min drift.
* **Session shape**: the interstitial mints a
  **customer-role** access token via `utils.create_token(user)` where
  `user` is loaded from `db.users` with `role: "customer"` +
  matching `tenant_id`. **No admin escalation** possible even if a
  raw JWT were forged — the interstitial only ever mints a session
  scoped to the customer user record it looks up.
* **Tenant scoping**: `verify_*` helpers require `tenant_id` in the
  payload; the interstitial cross-references the customer against
  the SAME `tenant_id` before minting a session.
* **Rate limit**: `_check_magic_rate_limit()` in
  `routers/portal_auto_login.py` — 20 attempts / minute / IP,
  in-process sliding window (matches `auth._check_reset_rate_limit`
  pattern). Applied BEFORE JWT verify so tampered tokens still count
  against the budget. Excess = 302 → `/portal/login?reason=link_expired`.
* **Open-redirect guard**: `?redirect=` query param only honoured
  when it starts with `/portal/` (unchanged pre-existing guard).
* **Rotation**: rotating `JWT_SECRET` in `backend/.env` (via
  `sudo supervisorctl restart backend`) invalidates every outstanding
  magic link tenant-wide. (The user brief mentioned "Fernet key
  rotation" — we use JWT here, not Fernet; the effect is identical
  since JWT signatures fail after secret rotation.)

## Logging

* **Mint** (resolver-level): DEBUG on cascade fallback
  (`SERVICE_RECORD_LINK` → `CUSTOMER_PORTAL_LOGIN_LINK`). WARN on
  mint failure (missing env / crypto error) — never on success (would
  spam the log stream because tags fire on every send).
* **Verify + redemption**: existing INFO log in the interstitial
  records `outcome=<success|expired|invalid|wrong_scope|rate_limited>
  customer_id=<id> resource_type=<t> resource_id=<id> from_ip=<ip>`.
  The raw `t` value is NEVER logged.

## Send-path integration

**On-demand mint only** — the resolver is called by
`services.marketing.merge_tags.render_template` **only when the
template body contains the tag**. `_TAG_RE.sub()` calls the
substitutor per match; the resolver caches the resulting URL on
`ctx['customer_portal_login_link']` / `ctx['service_record_link']`
so a body with 3 references still mints exactly ONE JWT per render.

Send paths that want a **custom TTL or a pre-minted URL** can
populate the ctx flat key before calling `render_template` — the
resolver returns the override verbatim (skips the mint). This
mirrors the `INVOICE_PAY_MAGIC_URL` / `ADD_CARD_LINK` pattern.

Preview endpoints (`/api/marketing/preview`, etc.) automatically pick
up the mint because `DEFAULT_SAMPLE_CONTEXT` in
`services/marketing/render.py` now seeds `customer.id` +
`tenant.id`. Preview URLs verify against the same `JWT_SECRET` — the
composer preview shows what the recipient will actually receive.

## Cascade behavior

`SERVICE_RECORD_LINK` when no `job.id` is in scope cascades to
`CUSTOMER_PORTAL_LOGIN_LINK` — matches the
`INVOICE_PAY_MAGIC_URL → INVOICE_PAY_URL` precedent. Rationale: a
recipient landing on their portal home is more useful than an empty
link in an email body. Logged at DEBUG so ops can spot templates
that misuse the tag.

Full-empty fallback (no customer.id / tenant.id / job.id, or
`APP_PUBLIC_URL` unset): resolver returns empty string. Rendered
body will have a bare surrounding sentence — no literal `{{...}}`
leaks. Unit-tested.

## Files touched

- `backend/services/marketing/merge_tags.py` — new resolvers + catalog
  entries.
- `backend/services/comm_tokens.py` — lowercase aliases in
  `AVAILABLE_TOKENS`.
- `backend/services/marketing/render.py` — `customer.id` +
  `tenant.id` seeded in `DEFAULT_SAMPLE_CONTEXT`.
- `backend/routers/portal_auto_login.py` — 20/min/IP rate limiter.
- `backend/tests/test_magic_link_merge_tags.py` — new pytest suite
  (17 tests).

## Not touched (intentionally)

- No changes to `mint_portal_home_token` / `mint_job_view_token`
  in `services/portal_magic_links.py` — TTL override passed by kwarg.
- No changes to the interstitial verify path except the new rate
  limiter — cross-scope replay guards already existed and are
  covered by `test_portal_auto_login_route.py`.
- **`CUSTOMER_PORTAL_LINK` unchanged** — still renders the plain
  `/portal/login?email=…` login URL. The new tag is ADDITIVE so
  existing templates keep their old behavior.

## Where the composer picks up the new tags

- `GET /api/marketing/merge-tags` returns the catalog grouped by
  category — the two new tags appear under `Portal`.
- Frontend composer (Marketing Templates) reads this endpoint and
  auto-populates the token picker. No frontend changes required.
