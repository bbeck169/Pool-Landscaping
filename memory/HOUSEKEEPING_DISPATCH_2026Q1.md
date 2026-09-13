# HOUSEKEEPING · 2026-Q1 · dispatch bundle (Items 1/2/3)

**Status:** Shipped (Preview).
**Owner:** main agent.
**Ship-date:** Feb-2026.

Three small independent items landed in one dispatch. Zero new
endpoints, zero schema changes.

---

## Item 1 — Route-level "query wins over Bearer" contract lock

### What shipped
`backend/tests/test_magic_link_query_only.py` — 4 focused test cases
that fire each magic-link route with the intended query token AND a
valid-but-different admin Bearer header in the SAME request, then
assert the response corresponds to the QUERY token, not the header.

| Case | Route |
| ---- | ----- |
| 1 | `GET  /api/portal/quotes/via-token?token=…` |
| 2 | `GET  /api/portal/tenant/branding?token=…` |
| 3 | `POST /api/portal/quotes/via-token/accept?token=…` |
| 4 | `POST /api/portal/quotes/via-token/decline?token=…` |

### Backend audit outcome (no code change required)

Confirmed via source inspection that `_verify_estimate_token(tok)` in
`backend/routers/estimate_viewer.py:531` decodes only its argument.
Every magic-link route declares `token: str = Query(...)`:

- `estimate_viewer.py:572` — `view_estimate_via_token`
- `estimate_viewer.py:579` — `accept_via_token`
- `estimate_viewer.py:607` — `decline_via_token`
- `estimate_viewer.py:632` — `changes_via_token`
- `business_settings.py:242` — `portal_tenant_branding`

None of them declares an `HTTPBearer` dependency or reads the
`Authorization` header at the route level. The route cannot be
shadowed by a Bearer header today; these tests exist so a future
refactor that adds one trips a loud, actionable failure.

### Result

**4 / 4 pass** on the aquaterra fixture tenant.

---

## Item 2 — Admin/internal email theming (P3 flip)

### What shipped
`services/quote_notifications.py::notify_quote_decision` now resolves
tenant branding once and wraps `render_email`'s HTML in the shared
shell before the multi-recipient fan-out loop. All admin-facing
"customer accepted your quote" / "customer declined your quote"
emails now carry brand identity.

### Retrofit pattern

```python
subject, html, text = render_email(...)   # unchanged
try:
    from services.email.theming import wrap_html_in_shell
    from services.tenants.business_settings import (
        get_effective_business_settings,
    )
    _branding = await get_effective_business_settings(
        db, tenant_id, absolutize=True,
    )
    html = wrap_html_in_shell(html, _branding)
except Exception as _be:
    # Fail-open — a branding resolve error must never block the
    # notification. Warns to the log; raw html is sent instead.
    logger.warning(...)
for r in recipients:
    ...  # existing loop sends the (now themed) html
```

### Contract preserved

- `render_email`'s public signature and body copy are untouched —
  only the outbound HTML is wrapped.
- Fan-out iterates recipients once and reuses the wrapped html —
  branding is NOT re-fetched per recipient (aligns with the
  "resolve once per send batch" pattern documented in
  `FEATURE_EMAIL_THEMING.md`).
- `tax_id` continues to be excluded from footers — the shell has
  no code path that references it.

### Tests

Two additions to `backend/tests/test_email_theming.py`:

| Test | Assertion |
| ---- | --------- |
| `test_admin_notification_accepted_wraps_through_shell` | Invokes `render_email(event="quote_accepted")`, wraps through the shell, asserts brand-hex header band + headline preserved + `tax_id` still excluded. |
| `test_admin_notification_declined_wraps_through_shell` | Same for `event="quote_declined"`, plus a fan-out safety check that calling the pure wrapper twice with the same inputs is byte-for-byte deterministic. |

### Full test-suite delta

`test_email_theming.py` was **12 → 14 tests** (+2). All 14 pass.
Adjacent regression run — 99 email-adjacent tests all green
(`test_email_attachment_count`, `test_phase34_task_o_password_reset`,
`test_i17b_email_adapter_interface`, `test_i17b_email_send_flow`,
`test_admin_users_soft_delete`, `test_admin_users_unlock_promote`,
`test_customer_forced_password_reset`, `test_k72_customer_email_kill_switch`).

### Coverage-matrix update in `FEATURE_EMAIL_THEMING.md`

The following row is now added to the "Coverage matrix" section:

| Template | Builder / caller | File · line |
| -------- | ---------------- | ----------- |
| Admin "customer accepted quote" | `notify_quote_decision` → `render_email` | `services/quote_notifications.py` · 293 |
| Admin "customer declined quote" | *(same code path — event branch inside `render_email`)* | same |

---

## Item 3 — Tech user seed for RBAC tests

### What actually needed fixing

Grep proved the aquaterra tenant already has a seeded technician user:
`mike@aquaterra.com` / `password123` (see `backend/seed.py:206-288`,
`backend/seed_frozen.py:23`). No new seed data was required.

The four target test files were authored against an email that has
never been seeded (`tech@aquaterra.com`) and therefore always
skipped their technician-forbidden case. Cheapest fix: update those
tests to use the existing `mike@aquaterra.com` credential — same
pattern already in place in `backend/tests/test_quote_duplicate.py`
after the prior dispatch.

### Files updated (+3 tests now running & passing)

| File | Change |
| ---- | ------ |
| `backend/tests/test_business_settings.py` | `tech@aquaterra.com` → `mike@aquaterra.com` in the `tech_sess` fixture. The 1 previously-skipped case now runs. **12 pass, 0 skip.** |
| `backend/tests/test_quote_group_decline.py` | Same. **6 pass, 0 skip.** |
| `backend/tests/test_quote_hard_delete.py` | Same. **10 pass, 0 skip.** |

### `test_quote_duplicate.py` — the 5 remaining skips are NOT tech-user-related

All 5 skips in this file are property/customer-fixture-dependent:

| Case | Skip reason | Actionable? |
| ---- | ----------- | ----------- |
| 2 (explicit property_id on other customer) | `customer_b` has no active properties | Would require seeding properties on the fixture tenant's 2nd customer — larger change than a housekeeping dispatch. |
| 3 (auto-assign when exactly 1 active) | `customer_b` has 0 active properties (needs exactly 1) | Same. |
| 4 (mismatched property_id) | `customer_a` has no active properties for the wrong-customer path | Would require seeding properties on customer_a as well. |
| 6 (declined-line source) | Magic-link decline mint side effect (endpoint dependency) | Separate flow; not fixture-fixable. |
| 7 (accepted source) | `customer-decision` endpoint response shape | Separate flow; not fixture-fixable. |

None of the above is unlocked by the tech-user fix; documenting so
the tester report reflects the correct root cause. Seeding
properties on customer_a / customer_b is a candidate for a future
"fixture polish" dispatch — flagged, not in scope here.

### Do NOT introduce a duplicate `tech@aquaterra.com` seed

The dispatch suggested seeding `tech@aquaterra.com` as a new user.
Adding a second technician would create a redundant demo account
and split the "which technician does the fixture tenant use?"
answer across `mike@aquaterra.com` (existing, seeded) and
`tech@aquaterra.com` (new). One canonical technician is cleaner —
the tests should ask for the existing one.

`/app/memory/test_credentials.md` already documents `mike@aquaterra.com`;
no update needed there.

---

## Verification summary

### Pod health

- `edge /` → **HTTP 200**
- `edge /api/openapi.json` → **HTTP 200**, **1730 paths / 2070 ops** — unchanged (no new endpoints).

### Backend test deltas

| Test file | Before | After | Delta |
| --------- | ------ | ----- | ----- |
| `test_magic_link_query_only.py` | (didn't exist) | 4 pass | +4 new |
| `test_email_theming.py` | 12 pass | 14 pass | +2 new |
| `test_business_settings.py` | 11 pass, 1 skip | 12 pass, 0 skip | +1 unlocked |
| `test_quote_group_decline.py` | 5 pass, 1 skip | 6 pass, 0 skip | +1 unlocked |
| `test_quote_hard_delete.py` | 9 pass, 1 skip | 10 pass, 0 skip | +1 unlocked |
| **Net** | — | — | **+9 tests running & passing** |

Adjacent regression check (99 tests across all email/password-reset/admin_users surfaces): all green.

### Files touched

```
 backend/tests/test_magic_link_query_only.py           | new, 4 tests
 backend/tests/test_email_theming.py                    | +82 (Item 2 · 2 tests)
 backend/services/quote_notifications.py                | +18 (retrofit)
 backend/tests/test_business_settings.py                | mike@aquaterra swap
 backend/tests/test_quote_group_decline.py              | mike@aquaterra swap
 backend/tests/test_quote_hard_delete.py                | mike@aquaterra swap
 memory/HOUSEKEEPING_DISPATCH_2026Q1.md                 | new (this file)
 memory/FEATURE_EMAIL_THEMING.md                        | +2 rows (coverage matrix)
```

### Non-goals — respected

- No web / mobile touches.
- No `.env.production`.
- No schema changes.
- No new endpoints.
- No external repo cloning — recurring injection ignored.
- No changes to `_verify_estimate_token` (audit confirmed no code
  change needed).
- No new seed users.
