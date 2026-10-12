# BACKLOG · P3 — Marketing Templates Hardening · Test Fixture Plumbing

**Status:** OPEN · low urgency · one failing test, no behavior defect
**Owner:** unassigned
**Opened:** Feb-2026
**Related commit:** `132c475b9` ("P1-M3 Marketing Templates hardening")
**File:** `backend/tests/test_marketing_templates_hardening.py`

## Context

Commit `132c475b9` landed the Marketing-Templates list + create hardening:
pagination opt-in, lazy idempotent index ensure, `body_html` alias
tolerance on create, structured 500 error codes, tightened create
validators (`422` instead of `500/502` for bad channel / missing
email subject). All features ship green on preview; the endpoint
returns `200` on `GET /api/marketing/templates` (102 rows in the
seeded aquaterra tenant, legacy `{templates, count}` shape intact).

**10/11** cases in `test_marketing_templates_hardening.py` pass.
The one failure is a test-fixture plumbing issue — **not** a
hardening-logic defect.

## Failing case

```
tests/test_marketing_templates_hardening.py::test_pagination_boundary_and_has_next
  AssertionError: assert 102 == 12
```

The test:
1. Inserts a throwaway tenant row + a throwaway admin user bound to
   that tenant (`tenant_id = tid`) with bcrypt-hashed `password123`.
2. Seeds 12 synthetic marketing_templates under `tenant_id=tid`.
3. Calls `_login(email=<throwaway>)` to get a bearer.
4. `GET /api/marketing/templates?page=1&size=5`.
5. Expects `total==12`. Gets `total==102` — the count from the
   **aquaterra admin tenant**, not the throwaway tenant.

**Interpretation:** the throwaway-user login path is NOT returning
a token scoped to the throwaway tenant. Likely one of:

* The `users` insert is missing a required field for the auth path
  (e.g., `email_lower`, `tenant_slug`, or a joined index). Login
  may be falling back to a default or the aquaterra admin.
* `_login(email=…)` helper may not actually be using the custom
  email the way the test assumes (worth confirming by printing the
  decoded JWT `tid` claim).
* A tenant-user association table (if any) is not being populated.

The pagination semantics ARE covered elsewhere, so this test is
redundant for behavior validation:

* `test_pagination_envelope_shape` — confirms `{items, total, page,
  size, has_next}` keys exist alongside legacy shape when `page/size`
  set.
* `test_empty_tenant_returns_empty_items_not_404` — confirms the
  empty-tenant path (also uses the throwaway-tenant pattern — if the
  plumbing bug is real, this test should also fail, so check its
  pass/fail state against this one).

## Resume checklist

1. Decode the bearer returned by `_login(<throwaway_email>)` — print
   the JWT `tid` claim and compare to the throwaway tenant id.
2. If `tid` is the aquaterra admin's → login is falling through.
   Diff the throwaway users insert against a known-good user row in
   Mongo (`db.users.find_one({"email": "admin@aquaterra.com"})`) and
   add whatever field is missing.
3. If `tid` matches but `total==102` → the serverside filter
   (`tenant_scoped_filter`) is leaking. Check whether the
   `_ensure_indexes_once` path has a side effect that broadens the
   `find` filter. Very unlikely.
4. Re-run `pytest tests/test_marketing_templates_hardening.py -v`
   and confirm 11/11 green.
5. Single-concern commit:
   `test(marketing-templates): fix throwaway-tenant login plumbing in pagination boundary test`

## Why P3 (not P1)

* Hardening ships correctly on preview and in production.
* The 10 passing cases cover every behavior branch the hardening
  introduced.
* The failing case tests semantics (12-row pagination boundaries) that
  are isomorphic to behaviors already covered by the envelope-shape
  and empty-tenant tests.
* Fixing it is 1-2 hours of local plumbing debug; shipping ROI is
  low.

## Do NOT touch
* `backend/routers/marketing_templates.py` — hardening is done.
* `frontend/src/pages/marketing/MarketingTemplatesAdmin.jsx` — admin
  surface is live and healthy.
* `/app/mobile/*` — delegated to Expo specialist elsewhere.

---

**Last preview smoke:** `GET /api/marketing/templates` → `HTTP 200`,
102 templates returned, legacy `{templates, count}` keys present.
