# Task NN · P1 audit refresh — Feb 2026

Re-audited the P1 shortlist against the current codebase before shipping.

## Confirmed to have live collections (shipped in this batch)

| Surface | Collection | Router | Notes |
|---------|-----------|--------|-------|
| Reviews | `customer_portal_reviews` | `customer_reviews.py` | `google_click_at` = locked-for-delete anchor |
| Team/Users | `users` | `team.py` | Last-owner + self-user guards added |
| Customer Tags | `customer_tags` | `customer_tags.py` | Simple, no locked-state |
| Service Reports | `service_reports` | `service_reports.py` | `evidence_invoice_id` = locked-for-delete anchor |
| Time Entries | `time_entries` | (multiple: `workforce`, `budgets`, `cfo`) | `payroll_run_id + payroll_paid_at` = locked-for-delete |

## Deferred — audit gaps (NOT shipped this batch)

| Surface | Gap | Recommendation |
|---------|-----|----------------|
| Referrals | Two candidate collections (`referral_invites` vs `referral_codes`) with different semantics — invites are per-recipient, codes are per-inviter. | Product decision needed on which is the admin list surface. Once decided, add a bulk endpoint mirroring `customers` shape. |
| Vendors | No `db.vendors` collection exists. The Check-Writer feature has `payees` which serve as vendors for AP payments. | Ship as `payees` under a `/payees/bulk-*` route after confirming Check-Writer usage is broad enough. |
| Expenses | No `db.expenses` collection exists. Expense tracking lives inside budgeting via `budgets.py`. | Blocked on a dedicated expenses entity being introduced first. |
| Maintenance Schedules | `maintenance_records` exists but "schedules" is really a recurring-jobs concept via `recurring_jobs.py`. | Product decision needed — bulk-edit recurring_jobs vs. maintenance_records. Note bulk-delete of a recurring template with upcoming jobs in the next 7d should warn (per user's brief) — add `warning` field to `failed[]` when we ship this. |

## Shipping guardrails carried over from Task LL P2
* Task-BB testid convention exactly (`bulk-select-all`, `bulk-select-row-{id}`, `bulk-action-bar`, `bulk-{key}-button`, `bulk-clear-selection`, `bulk-delete-confirm-*`).
* Task-DD 400-row cap.
* Task-EE `{ids}` OR `{query_selector, exclude_ids}` shape.
* Server-side allow-list per surface on patch keys.
* Role gate admin/super_admin/owner via `require_admin`.
* Tenant scoping. Audit-logged. Idempotent. No cascade.
