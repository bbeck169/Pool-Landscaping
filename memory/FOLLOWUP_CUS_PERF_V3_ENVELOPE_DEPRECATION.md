# FOLLOWUP · CUS-perf v3 — drop vestigial `counts_by_status` from list envelope

## Discovered during
CUS-perf backend follow-on (surprise S3 + R5 ruling, 2026-02).

## Issue
`counts_by_status` was kept in the paginated `list_customers`
response envelope as a vestigial alias for zero-downtime rollout
(BE ships before FE in the standard release cycle). Frontend
switched to `/customers/counts` as the single source of truth for
all tab badges.

Post-CUS-perf v3, the alias:
- Is populated from the same 5 parallel `count_documents` calls
  that back `/customers/counts` (zero extra query cost).
- Is NOT consumed by any frontend code AFTER the CUS-perf v3
  frontend consolidation ships.

## Timing
This memo is P1. Safe deploy window elapses once:
1. CUS-perf v3 backend commit is deployed to production
   (`app.plofv.com`).
2. CUS-perf v3 frontend commit is deployed to production.
3. All active mobile / web sessions have been refreshed since (2).

Rule of thumb: 1 week after both deploys complete.

## Recommended fix

### Backend (`routers/customers.py`)

Remove the 5-parallel-`count_documents` block inside the paginated
envelope branch (currently gated on `if _paginated:`). The wire
response drops `counts_by_status` entirely.

### Backend (`CustomerListPage` model)

Drop the `counts_by_status: Optional[Dict[str, int]] = None` field
from the response model.

### Frontend (`CustomersList.jsx`)

Remove the `data?.counts_by_status` read block (currently line
638-648 as of CUS-perf v3). Tab counts flow ONLY via
`loadCounts()` → `/customers/counts` → `setCounts`.

Frontend regression test that expects the field to exist:
- `frontend/src/test/p31-customers-list-counts-single-fetch.test.jsx`
  currently mocks `counts_by_status: null`. Update to omit the
  field entirely — mock parity with the post-drop wire shape.

## Priority
P1 — zero-value payload bloat once the safe deploy window elapses.

## Coordinated tests

Post-drop, add / update:
- Backend: assert `CustomerListPage.counts_by_status` no longer
  exists on the model.
- Backend: assert paginated list response body does NOT contain
  the `counts_by_status` key.
- Frontend: remove the `counts_by_status`-reading assertion in
  `p31-customers-list-counts-single-fetch.test.jsx`.

## Related landing
- CUS-perf v3 backend follow-on (this session, commit <SHA>) —
  established the vestigial alias per R5 ruling.
