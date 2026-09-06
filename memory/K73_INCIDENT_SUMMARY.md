# K73 · Incident Summary — Schedule Role-Gating Audit Findings

**Date:** Feb 2026
**Status:** RESOLVED — no active PII leak found on audited surface
**Original trigger:** R1.c ship report §5 flagged a probable
`GET /api/jobs` PII leak. This document explains what actually
happened, corrects the initial finding, and locks in
regression guards.

---

## Executive summary

**Initial finding was a FALSE POSITIVE caused by a faulty audit
script.** The K73 promotion to P0 was correct as a precaution
but the leak did not exist.

- The R1.c audit script compared each returned job's
  `technician_id` against the caller's **`user.id`**.
- The correct comparison is `job.technician_id` vs the caller's
  **`user.technician_id`** (a separate field on `/api/auth/me`).
- Once corrected, the audit shows every read endpoint
  in scope (`/api/jobs`, `/api/jobs/{id}`, `/api/schedule/*`)
  correctly filters to the caller's tech scope via the
  existing `scope_jobs_query` helper.

**No customer PII has been leaked through the audited surface.**
The K73 phase still shipped meaningful work:

1. A permanent, unquarantinable **contract test suite**
   (`test_k73_tech_scope_contract.py`) that hard-fails if a
   regression ever lets a tech token see another tech's job.
2. The **crew-hued deterministic palette** for schedule map
   pins + calendar legend (the UX portion of the original K73
   scope).

---

## Full endpoint audit

Test method: log in as `mike@aquaterra.com` (technician role,
`technician_id = b8a68119-…`, solo tech — no crew) and query
each endpoint. Compare each returned job's `technician_id`
against `mike.technician_id`.

| Endpoint | HTTP | rows | out_of_scope | Verdict |
|----------|------|------|--------------|---------|
| `GET /api/jobs?limit=500` | 200 | 36 | **0** | Safe |
| `GET /api/jobs?technician_id=<other>` | 200 | 36 | **0** | Safe (override ignored) |
| `GET /api/jobs/<other-tech-job-id>` | 403 | — | — | Safe |
| `GET /api/schedule/today` | 200 | 3 | **0** | Safe |
| `GET /api/schedule/day?date=today` | 200 | 3 | **0** | Safe |
| `GET /api/schedule/unassigned-pending-stale` | 403 | — | — | Safe (admin-only) |
| `GET /api/dispatch` | 403 | — | — | Safe (admin-only) |
| `GET /api/dispatch/board` | 403 | — | — | Safe (admin-only) |
| `GET /api/dispatch/route/unscheduled-jobs` | 403 | — | — | Safe (admin-only) |
| `GET /api/dispatch/route/savings/weekly` | 403 | — | — | Safe (admin-only) |
| `GET /api/customers/<unrelated>` | 404 | — | — | Safe (defence-in-depth) |
| `GET /api/timeclock/mine-jobs-today` | 403 | — | — | Mobile-only role gate |
| `GET /api/workstream/jobs` | 403 | — | — | Mobile-only role gate |

### Adjacent findings (out of K73 scope, noted for follow-on audit)

- `GET /api/customers` returns 33 customer records (tenant-scoped
  but NOT tech-scoped). Only 0 are directly assigned to mike;
  32 are unassigned; 1 is assigned to another tech. This is a
  **soft directory-style leak** (customer name / phone / email
  visible without a job link).
  - Not covered by the user's K73 brief ("jobs / schedule /
    calendar"), so **not fixed here**.
  - Recommended follow-on phase: **K73.5 — Customer Read Scope**
    to decide whether techs should see the whole customer list
    or only customers with an active job assignment.
- `GET /api/technicians` returns full contact info (name, email,
  phone) for every tech in the tenant. Almost certainly
  intentional (coworker directory) but worth an explicit
  product decision.
- `GET /api/crews` returns crew rosters. Intentional for solidarity
  routing use cases; no PII beyond names.

---

## Historical scope-violation count

- No dedicated request-log collection tracks `GET /api/jobs` reads.
- `audit_events` (~384 rows) covers business events (invoice
  actions, job edits, reminders) but not read events.
- `audit_logs` (~10,475 rows) is a mixed log with no `event_type`
  matching a scope violation shape.

**Conclusion:** we cannot retroactively count "how many times a
tech's session viewed data outside their scope" from the audit
trail. Given the current fix status (nothing was actually
leaking), the answer is almost certainly zero.

For future defence-in-depth, the R1.c ship report already
proposed adding an `audit_event` write on any 403 hit from
`scope_jobs_query`. That work is queued as **K74.5 · Deferred**
after K74 solid-navy tile swap.

---

## Fix status

| Item | Status |
|------|--------|
| Backend scope filter on `/api/jobs` | Already in place (`scope_jobs_query`, `routers/jobs.py`) — verified by contract tests |
| Backend scope filter on `/api/schedule/*` | Already in place — verified by contract tests |
| Backend scope filter on `/api/jobs/{id}` | Already in place (403 fast-path) — verified by contract test |
| Admin-only guards on `/api/dispatch/*` | Already in place — verified by parametrized contract test |
| Permanent contract test suite | **NEW** — `backend/tests/test_k73_tech_scope_contract.py` (11 tests, 100% pass) |
| Crew-hued deterministic map palette | **NEW** — `frontend/src/lib/crewPalette.js` + `k73-crew-palette.test.js` (12 tests, 100% pass) |
| Legend groups techs by crew | **NEW** — `CalendarSchedule.jsx::TechColorLegend` reworked |

---

## Was this actually exploited?

- No user-facing UI ever surfaced other-tech jobs (the map,
  calendar, and jobs list all filter via the `techColorMap` +
  `techFilter` which anyway only render what the backend
  returned).
- The backend has been correctly filtering since the
  `scope_jobs_query` helper was introduced (well before K73).
- Given the false-positive nature of the initial audit, we
  believe **the answer is No**.

---

## Recommendations for future defence

1. **Automatic contract tests on every new read endpoint.**
   Anyone adding a new `/api/jobs/*` or `/api/schedule/*`
   handler MUST extend `test_k73_tech_scope_contract.py` with a
   tech-scope check. Add this to the PR template.
2. **Role-based response filters.** Consider a shared
   `scope_response(user, docs)` middleware wrapper for every
   list handler; makes it impossible to forget the filter.
3. **Penetration test scope.** When we run the next external
   pen-test, include `/api/customers`, `/api/technicians`, and
   `/api/crews` in the K73.5 follow-on scope.
4. **Audit-log the 403s.** Track how often
   `scope_jobs_query` blocks a request (K74.5). Sudden spikes
   would indicate either a bug in a client or a probe.
5. **Better audit-script hygiene.** The R1.c false positive
   would have been caught by comparing sample `technician_id`s
   in the returned rows against the caller's `/auth/me` output
   BEFORE flagging anything as a leak. Codify this pattern in
   the runbook.

---

## Fix timeline

- **Feb 6 · R1.c ship:** initial audit flagged; K73 promoted
  P0.
- **Feb 6 · K73 kickoff:** re-audit confirmed false positive;
  K73 refocused on regression-guarding + UX palette work.
- **Feb 6 · K73 ship:** contract tests + crew-hued palette
  merged; docs written (this file).

Total elapsed: same day. No customer disclosure necessary — no
leak to disclose.
