# Phase P1 · Feb-2026 — Follow-up: `jobs.address` dict-leak audit

Phase P1 locked the invariant that `jobs.address` MUST be a plain string
on write from `POST /api/jobs` and `PUT /api/jobs/{jid}` (see
`backend/routers/jobs.py::_stringify_property_address` +
`_resolve_property_for_job`). During the P1 write-side audit the
following **OTHER** write paths were spotted that also stamp
`jobs.address` from a `customer.address` or per-body source without
running that value through a canonical `_stringify_*` formatter.

None of these are exploitable today because the demo tenants + all
active seed customers persist `customer.address` as a flat string.
However, any customer doc that ever carries a dict-shaped `address`
(possible via the properties → customer denormalization path if a
future PR wires one) will silently land a dict on `jobs.address` and
500 the schedule read path exactly the way the P1 fix closed.

Flag-only — **NOT** fixed in this phase, per the P1 scope lock.

## Backlog · address-dict leak candidates (write paths that touch `jobs.address`)

| Path | File · Line | Value written to `jobs.address` | Trigger |
| ---- | ---- | ---- | ---- |
| Recurring materialization | `backend/routers/recurring_jobs.py:1418` | `cust.get("address") or ""` | Recurring template rolls forward — one occurrence created per date in the projected window. |
| Customer `POST /jobs/service-request` | `backend/routers/jobs.py:1628` | `customer.get("address", "")` | Customer-portal "Request service" surface (self-service from the customer role). |
| Legacy portal appointment → job | `backend/routers/portal_appointments.py:189` (`job["address"]` seeded at 111) | `body.address or cust.get("address")` | Public/legacy portal appointment intake — pre-multi-property era. |
| Public portal `POST /portal/service-request` | `backend/routers/portal.py:176` | `cust.get("address", "")` | Portal service-request write path. |
| Lead → job conversion | `backend/routers/leads.py:762` | `cust.get("address", "")` | Sales pipeline "convert lead → job". |
| Maintenance auto-jobs | `backend/routers/maintenance.py:66, 244, 287` | `customer.get("address", "")` | Auto-scheduled equipment maintenance boots. |
| Job-request → job accept | `backend/routers/job_requests.py:251, 259` | `body.address or customer.get("address", "")` | Admin "approve" of an inbound request. |
| Instaschedule intake | `backend/routers/instaschedule.py:618` | `contact.get("address") or cust.get("address") or ""` | Ops instaschedule surface. |

## Recommended follow-up phase

Extract `_stringify_property_address` (currently local to
`routers/jobs.py`) into a shared helper — e.g.
`services/address_stringify.py::stringify_address` — that safely
coerces `str | dict | None` down to the canonical
`line1, city, state` string, then route every write path in the
table above through it before touching the `"address"` key on a
job doc.

Optionally: add a Mongo-side guard by defining a `jobs` collection
JSON schema validator that rejects `address` values of type
`object`.  That would give architectural closure but requires a
one-time repair pass first (a handful of legacy jobs today already
carry dict `address` — the R1 dry-run counts sit in
`/app/memory/DATA_INTEGRITY_RUNBOOK.md`).
