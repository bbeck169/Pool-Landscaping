# Phase 34 · Task LL Phase 1 — CRM-wide bulk-select audit

> **Investigation complete. Phase 2 implementation is BLOCKED until user signs off the P0 list.**

Guardrail: `/app` only. No external repo clones.

## Legend
* **Priority**: P0 (ship in Task LL batch), P1 (defer to LL-P1), P2 (defer to LL-P2), N/A (bulk actions don't apply).
* **Existing bulk?**: ✅ shipped in prior Phase 34 batches; ⚠️ partial (e.g., checkbox only, no bulk-edit); ✗ nothing yet.

## Audit table

| Route | Component path | Backend entity | Existing bulk? | Recommended bulk actions | Locked-state notes | Priority |
|---|---|---|---|---|---|---|
| `/customers` | `pages/customers/CustomersList.jsx` | `db.customers` | ✗ | bulk-delete (soft), bulk-edit `tag`/`assigned_owner_id` | never cascade to jobs/invoices; refuse when linked-active-invoice count > 0 | **P0** |
| `/jobs` | `pages/jobs/JobsList.jsx` | `db.jobs` | ✗ (Schedule Phase 28 has some) | bulk-delete (soft), bulk-edit `technician_id`/`status`/`scheduled_date` | refuse jobs with active timer running; refuse `completed`+invoiced jobs | **P0** |
| `/schedule` | `pages/schedule/ScheduleBoard.jsx` | `db.jobs` | ✅ Phase 28 | (verify parity + testid rename) | already ships tech-reassignment | P1 (parity) |
| `/communications` | `pages/comms/CommunicationsPage.jsx` | `db.communication_sends` | ✗ | bulk-archive, bulk-mark-as-read | never bulk-delete (audit trail); archive-only | **P0** |
| `/templates/email` | `pages/templates/EmailTemplatesPage.jsx` | `db.email_templates` | ✗ | bulk-delete (soft), bulk-edit `category`/`is_archived` | refuse templates referenced by an active drip/sequence | **P0** |
| `/templates/sms` | `pages/templates/SmsTemplatesPage.jsx` | `db.sms_templates` | ✗ | bulk-delete (soft), bulk-edit `category` | same as email templates | **P0** |
| `/marketing/campaigns` | `pages/marketing/CampaignsPage.jsx` | `db.marketing_campaigns` | ✗ | bulk-archive, bulk-edit `status` | refuse `running` campaigns; must be paused first | P1 |
| `/marketing/sequences` | `pages/marketing/SequencesPage.jsx` | `db.sequences` | ✗ | bulk-archive | refuse sequences with live enrollments | P1 |
| `/reviews` (admin CRM) | `pages/admin/AdminReviewsPage.jsx` | `db.customer_portal_reviews` | ⚠️ needs-response markers only | bulk-archive, bulk-edit `status` (new/responded/resolved) | never delete public reviews (audit); soft-archive only | P1 |
| `/referrals` (admin) | `pages/marketing/AdminReferralsPage.jsx` | `db.referrals` | ✗ | bulk-void (voids credit issuance), bulk-edit `status` | financial guard — refuse referrals with already-issued credits | P1 |
| `/team` (users) | `pages/team/TeamPage.jsx` | `db.users` | ✗ | bulk-edit `role`, bulk-deactivate | refuse deactivating `super_admin` or the last admin; refuse deleting self | P1 |
| `/tags` | `pages/settings/TagsPage.jsx` | `db.tags` | ✗ | bulk-delete | refuse tags applied to > 0 customers/leads (or cascade-detach) | P1 |
| `/tasks` (follow-ups) | `pages/tasks/TasksPage.jsx` | `db.tasks` | ✗ | bulk-delete, bulk-edit `assignee_id`/`status`/`due_date` | refuse tasks with sub-tasks; refuse `completed` tasks (archive-only) | **P0** |
| `/time-entries` | `pages/time/TimeEntriesPage.jsx` | `db.time_entries` | ✗ | bulk-delete, bulk-edit `job_id` reassignment | refuse entries already exported to payroll | P1 |
| `/expenses` | `pages/expenses/ExpensesPage.jsx` | `db.expenses` | ✗ | bulk-delete, bulk-edit `category` | refuse expenses linked to a closed accounting period | P1 |
| `/vendors` | `pages/vendors/VendorsPage.jsx` | `db.vendors` | ✗ | bulk-delete | refuse vendors with open POs / unpaid bills | P1 |
| `/service-reports` | `pages/service-reports/ListPage.jsx` | `db.service_reports` | ✗ | bulk-delete | refuse reports already customer-notified (compliance) | P1 |
| `/maintenance-schedules` | `pages/maintenance/SchedulesPage.jsx` | `db.maintenance_schedules` | ✗ | bulk-delete, bulk-edit `frequency` | refuse schedules with jobs generated in the last 7d | P1 |
| `/ai-employees` | `pages/aiops/AiOpsPages.jsx` (AiEmployeesList) | `db.ai_employees` | ✗ (Task JJ dedupe shipped) | none — employees are seed-driven, not user-created at scale | N/A — bulk-anything doesn't map to a 10-persona catalog | N/A |
| `/onboarding` steps | `pages/onboarding/*` | various setup collections | N/A | N/A | singleton flows, not list pages | N/A |
| `/settings/*` (misc) | `pages/settings/*` | various | N/A | N/A | most are singleton config; the Pricebook list under `/price-book` already ships bulk-delete in Task KK | N/A |
| `/leads` | `pages/leads/LeadsDashboardPage.jsx` | `db.leads` | ✅ Task BB + HH | (no work) | shipped Feb 2026 | ✅ done |
| `/invoices` | `pages/invoices/InvoicesList.jsx` | `db.quotes` (doc_type=invoice) | ✅ Task BB + EE | (no work) | shipped Feb 2026 | ✅ done |
| `/estimates` | `pages/estimator/Estimator.jsx` (EstimatesList) | `db.estimates` | ✅ Task BB + EE | (no work) | shipped Feb 2026 | ✅ done |
| `/payments` | `pages/finance/FinancePages.jsx` (PaymentsLedger) | `db.quotes` (paid) | ✅ Task BB + EE | (no work) | shipped Feb 2026 | ✅ done |
| `/autobilling` | `pages/finance/FinancePages.jsx` (AutoBilling) | `db.billing_plans` | ✅ Task II | (no work) | shipped Feb 2026 | ✅ done |
| `/price-book?t=pricebook` | `pages/ops/OpsHub.jsx` (PriceBook) | `db.items` | ✅ Task KK (backend), ⚠️ frontend edit-in-place still Modal-only | frontend: apply Task-BB pattern to the list | shipped Feb 2026 (backend); frontend UI wrap-up in LL Phase 2 | ✅ backend / ⚠️ frontend polish |

## Proposed P0 shortlist (for Phase 2 sign-off)

1. **Customers/Contacts** — bulk-delete + bulk-edit (`tag`, `assigned_owner_id`).
2. **Jobs/Work Orders** — bulk-delete + bulk-edit (`technician_id`, `status`, `scheduled_date`).
3. **Communications** — bulk-archive + bulk-mark-as-read (no delete — audit trail).
4. **Email templates** — bulk-delete + bulk-edit (`category`, `is_archived`).
5. **SMS templates** — bulk-delete + bulk-edit (`category`).
6. **Tasks/Follow-ups** — bulk-delete + bulk-edit (`assignee_id`, `status`, `due_date`).
7. **Pricebook frontend polish** — apply Task-BB checkbox column + bulk-action-bar to the OpsHub PriceBook UI (backend already shipped in Task KK).

Six new admin surfaces + one frontend polish. All Phase 2 will follow the exact same pattern (checkbox column, floating action bar, confirm modal, testids `bulk-select-all` / `bulk-select-row-{id}` / `bulk-action-bar` / `bulk-delete-button` / `bulk-edit-button` / `bulk-edit-confirm-btn`), with backend endpoints `POST /api/{entity}/bulk-delete` and `POST /api/{entity}/bulk-update`.

## Deliberately skipped in this task
* `/ai-employees` — 10-persona seed catalog; bulk actions don't map to real user need.
* `/onboarding` step pages — singleton flows.
* Most `/settings/*` — singleton config screens.
* `/schedule` — Phase 28 already shipped a parallel bulk-tech-reassignment; adding another bulk pattern risks confusion. Recommend adding as an LL-P1 "parity pass" instead.

## Skipped for special-constraint reasons (P2)
* Audit log rows — read-only by design; users must never delete audit trails.
* Migration log rows — same.
* Any collection that materializes reports (billing-runs, dunning-runs, csat-dispatch-runs) — these are event streams; bulk-delete would corrupt reporting.

---

**Awaiting P0 sign-off before starting Phase 2 implementation.**
