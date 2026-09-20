# Phase A3 · Feb-2026 — Proactive Intelligence: Churn Risk scan

## Scope shipped
- New scan module `backend/services/intelligence/churn_risk_scan.py`
  producing `churn_risk` alerts from two independent signals per
  customer:
  * **`missed_payments`** — ≥ 2 invoices in `past_due` / `overdue`.
    Severity `urgent`.
    Alert key `churn_risk:cust:{cid}:missed_payments:{count}` — as
    the debt grows a fresh alert emits (old alert stays historical).
  * **`recurring_cancelled`** — recurring job (`is_recurring=True`)
    with `status="cancelled_by_customer"`. Severity `recommended`.
    Alert key `churn_risk:cust:{cid}:recurring_cancelled:{job_id}`
    — permanently deduped once emitted per series/job.
  * ONLY customer-initiated cancellations. `cancelled_by_office`
    and any admin-initiated status are ignored per spec.
- Manual trigger route:
  `POST /api/intelligence/scans/churn-risk/run-now`
  (admin/super_admin gate; tech → 403 `insufficient_role_for_alerts`).
- APScheduler cron: daily 07:30 UTC (30 min behind A1, 15 min
  behind A2).
- Frontend `IntelligenceAlerts` row for `category=churn_risk`:
  * `missed_payments` — monospace summary
    `$350.00 · 2 invoices · oldest 30d overdue` + blue **View
    invoices** CTA deep-linking to
    `/customers/{cid}?tab=invoices&status=past_due,overdue&source=intelligence_alert&alert_id=…`.
  * `recurring_cancelled` — monospace summary
    `Weekly Pool Cleaning · cancelled 2026-02-14` + blue **Contact
    customer** CTA deep-linking to
    `/customers/{cid}?compose=email&subject=We%20noticed%20you%20cancelled…&source=intelligence_alert&alert_id=…`.
- Tooltips added to both top-nav bells:
  * A1 `<AlertBell>` → `title="Proactive intelligence"`
  * Legacy `<NotificationBell>` → `title="Team & job notifications"`

## Data model reused
- Invoices: `db.invoices` — `status`, `amount_due_cents` (falls
  back to `total_cents` / `amount_due` / `total`), `due_date`
  (falls back to `issued_at` / `issue_date` / `created_at`).
- Recurring jobs: `db.jobs.is_recurring` + `db.jobs.status`.
  Canonical customer-cancelled status is `cancelled_by_customer`
  (same vocabulary A1 uses in `_COMPLETED_STATES`).

## Tests
- Backend: `backend/tests/test_churn_risk_scan_a3.py` → **12 / 12 passed**
  (`pytest`, 5.8 s wall).
- Frontend: `frontend/src/pages/admin/__tests__/IntelligenceAlerts.churn.test.jsx`
  → **9 / 9 passed** (`vitest`, 0.2 s).
- Full regression sweep across A1 backend + A1 alert-bell + A2
  chemistry (front + back) + header-cleanup: **all green** (36
  backend + 43 frontend).

## Follow-ups (P2 backlog)
- Query-param prefill on `CustomerDetail.jsx` for `compose=email` +
  `subject` — currently the CTA lands on the customer page and the
  operator has one manual click to open the compose modal. Small
  useSearchParams consumer would close the loop.
- Query-param prefill on the Invoices tab for
  `status=past_due,overdue` — today the tab renders "Invoices come
  in Phase 3" placeholder; when that ships, wire the status filter
  from the query param.

## API surface
- `POST /api/intelligence/scans/churn-risk/run-now` — admin+.
- Total intelligence routes in OpenAPI: **7** (3 producers × scan
  + 4 alert CRUD).
