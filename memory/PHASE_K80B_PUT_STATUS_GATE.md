# Phase K80.b — Server-side status gate on `PUT /api/quotes/{id}`

**Ship date**: Feb-2026
**Priority**: P0 · Security hardening
**Scope**: Backend only. Frontend unchanged (K80.a covers the UI).

## Problem

K80 recon proved `PUT /api/quotes/{id}` in `backend/routers/quotes.py`
had **zero** status gating. A curl/dev-tools fetch could rewrite the
line items of a `sent` / `accepted` / `paid` / `voided` document,
bypassing every confirmation guard the `PATCH` endpoint enforced.

## Product policy (locked this session)

| doc_type   | status         | PUT allowed? |
|------------|----------------|:------------:|
| estimate   | draft          | ✅           |
| estimate   | sent           | ✅           |
| estimate   | accepted       | ❌           |
| estimate   | declined       | ❌           |
| estimate   | voided / void  | ❌           |
| invoice    | draft          | ✅           |
| invoice    | sent           | ❌ *(delta vs PATCH)* |
| invoice    | partially_paid | ❌           |
| invoice    | paid           | ❌           |
| invoice    | voided / void  | ❌           |

**Delta vs PATCH**: `PATCH /api/quotes/{id}` still allows edits on
`sent` invoices (with `confirm_edit_sent`) and on `paid` invoices
(with a typed invoice number). K80.b **does not touch PATCH**. If
product wants PATCH aligned to the stricter PUT policy later, it's a
separate phase — see "Follow-ups" below.

## Helper extracted

`backend/services/quotes/status_gate.py`

Pure module — importable from any router that later wants the same
gate. Four public symbols:

- `is_quote_mutable_for_put(quote) -> bool` — pure predicate.
- `assert_quote_mutable_for_put(quote)` — raises `HTTPException(409)`
  with the structured body on denial.
- `denial_payload(quote) -> dict` — returns the 409 body without
  raising (used by tests and by anyone who wants a peek).
- `audit_put_denial(db, *, quote, actor)` — persists a denial row to
  `db.audit_logs`. Best-effort (swallows exceptions so an audit-log
  outage never converts a 409 into a 500).

**External vocabulary translation**: the DB stores `doc_type` as
`quote|invoice`. The gate exposes `estimate|invoice` on the wire so
API consumers see a stable, customer-friendly label. K71/K79/K80.a
UI code already speaks "estimate" in copy — this keeps the API in
sync.

**Whitelist not blacklist**: `_ALLOWED` maps doc_type → allowed
statuses. Any unknown status fails closed. Data-migration artefacts
and future workflow additions won't accidentally sneak past the gate.

## Denial response shape

```
HTTP 409 Conflict
Content-Type: application/json

{
  "detail": {
    "error": "status_locked",
    "current_status": "paid",
    "doc_type": "invoice",
    "message": "This invoice is locked because its status is 'paid'. Only draft invoices accept full edits via PUT. Void the invoice and issue a new one, or use the invoice edit modal for a scoped change."
  }
}
```

FastAPI's `HTTPException(detail=…)` wraps the body under `detail`.
Tests unwrap both plain and wrapped shapes so the contract is
resilient to a future move to a middleware-flattened response.

## Audit trail

Every denied PUT writes a row to `db.audit_logs`:

```
{
  "event": "put_quote_status_denied",
  "at": ISO-8601,
  "user_id": <actor.id>,
  "user_email": <actor.email>,
  "tenant_id": <quote.tenant_id>,
  "quote_id": <quote.id>,
  "doc_type": "estimate" | "invoice",
  "current_status": <normalised status string>
}
```

Locked-in by `test_put_denial_writes_audit_log`.

## OpenAPI surfaced

`GET /api/openapi.json` — `PUT /api/quotes/{qid}` now advertises
`409` with the denial shape example, alongside `200` and `422`:

```
PUT /api/quotes/{qid} responses:
   200 -> Successful Response
   409 -> Status-locked: PUT is denied when the doc's status is not
          draft (estimates also allow sent). Response body shape:
          `{ error: 'status_locked', current_status, doc_type,
          message }`.
   422 -> Validation Error
```

## Tests — 12/12 green

`backend/tests/test_k80b_put_quote_status_gate.py` (parametrised
where beneficial, 12 cases total):

| # | Test | Status |
|---|------|:------:|
| 1 | `test_put_draft_estimate_allowed` | ✅ |
| 2 | `test_put_sent_estimate_allowed` | ✅ |
| 3 | `test_put_draft_invoice_allowed` | ✅ |
| 4-6 | `test_put_terminal_estimate_blocked_409[accepted|declined|void]` | ✅ |
| 7 | `test_put_sent_invoice_blocked_409` (delta vs PATCH) | ✅ |
| 8 | `test_put_partially_paid_invoice_blocked_409` | ✅ |
| 9 | `test_put_paid_invoice_blocked_409` | ✅ |
| 10 | `test_put_voided_invoice_blocked_409` | ✅ |
| 11 | `test_put_denial_response_shape` (contract-lock on all 4 keys) | ✅ |
| 12 | `test_put_denial_writes_audit_log` | ✅ |

**Seed strategy**: POST a real draft doc via `/api/quotes`, then flip
`status` directly in Mongo before hitting PUT. Direct DB flip is
required because the legitimate status transitions (`send`,
`mark-paid`, `void`) run through other endpoints that side-effect
customer / accounting state — irrelevant to this gate.

**Regression suite (adjacent)**: `test_k71_line_item_router_api.py`
(20) + `test_k71_line_item_edit_categories.py` (3) + all K79 tests
(22) → **57/57 green** in the K-series subset run together with
K80.b.

## Files changed

| File | Nature |
|------|--------|
| `backend/services/quotes/status_gate.py` | **NEW** — helper module (`is_quote_mutable_for_put`, `assert_quote_mutable_for_put`, `denial_payload`, `audit_put_denial`). |
| `backend/routers/quotes.py` | `PUT /quotes/{qid}` calls the gate immediately after `find_one` (before body parsing); `@router.put` decorator declares the 409 response in the OpenAPI schema with example body. |
| `backend/tests/test_k80b_put_quote_status_gate.py` | **NEW** — 12 pytest cases covering allowed + blocked matrix + denial shape + audit-log write. |

**Files deliberately NOT touched**:
- `backend/routers/invoice_edit.py` — PATCH policy is intentionally
  separate. K80.b does not modify PATCH gates.
- Frontend — K80.a already covers the affordances.
- Any I1.5 / I1.7.a / I1.7.b / K79 code — untouched.

## Follow-ups (deliberately deferred)

1. **PATCH policy alignment** — should `PATCH /api/quotes/{id}` also
   lock invoice `sent` edits (matching PUT) rather than allowing
   them with `confirm_edit_sent`? Product decision: the current
   PATCH triad exists for **scoped, confirmed** edits (typo fixes,
   discount tweaks) on sent/paid invoices. If it turns out ops
   staff never actually use PATCH's confirm flow — align. If they
   do use it — leave PATCH as-is and treat PUT as the "structural
   rewrite" surface. File as **K80.c** if aligned.

2. **Estimate `sent`-to-`accepted` handoff UX** — currently the
   frontend surfaces the K71 pencil on both `draft` and (via
   K80.a) newer states. On `sent` estimates the pencil is
   still hidden by the `canEdit` prop's draft-only filter, but the
   backend now permits a PUT. Product may want the pencil re-
   enabled on `sent` estimates to close the frontend/backend gap
   (matching the policy above). File as a follow-up ticket if
   desired — the security concern is already resolved.

3. **Failure metrics** — add a StatsD/Prometheus counter for
   `put_quote_status_denied` events so ops can spot brute-force
   attempts or misbehaving integrations. Non-blocking; file when
   observability roadmap picks up.

## No regressions

- K79 backend suite (22): all green.
- K71 backend suite (23): all green.
- Frontend full suite (`yarn vitest run`): **479 files pass · 1
  skipped · 3774 tests pass · 34 Hygiene B skips untouched**.
- `test_credentials.md`: unchanged (`super@aquaterra.com` /
  `password123` verified in test module).

## Deployment notes

Zero migrations. Zero env changes. Zero DB indexes. Deploy in the
usual backend rollout — hot reload picks up the new module + route
decorator. On rollback, the gate simply disappears; no data
compatibility concerns.
