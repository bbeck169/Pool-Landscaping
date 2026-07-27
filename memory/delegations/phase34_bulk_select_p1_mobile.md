# Phase 34 · Task NN · Bulk-select P1 surfaces — Mobile agent brief (Feb 2026)

> **This brief covers ONLY the Expo/React-Native mobile client.** The
> web frontend for the same 5 P1 surfaces + backend endpoints is
> already shipped in this repo. Mobile agent: mirror the Task-BB
> pattern (bulk-select header checkbox, per-row checkbox, floating
> action bar, confirmation modal, `failed[]` locked pills) — same as
> the P0 mobile brief `phase34_bulk_select_crm_wide_mobile.md`.

## Backend endpoints already live (`bulk_crm_p1.py`)

| Surface | Delete endpoint | Update endpoint | Patch allow-list | Locked-state |
|---------|-----------------|-----------------|-------------------|---------------|
| Reviews | `POST /api/reviews/bulk-delete` | `POST /api/reviews/bulk-update` | `is_public`, `admin_response`, `status` | Google-clicked reviews refuse hard delete |
| Team/Users | `POST /api/users/bulk-delete` | `POST /api/users/bulk-update` | `role`, `is_active`, `assigned_regions` | Last-owner + self-user refuse delete; self-edit refuses in bulk-update |
| Customer Tags | `POST /api/customer-tags/bulk-delete` | `POST /api/customer-tags/bulk-update` | `color`, `parent_tag_id`, `is_archived` | (none) |
| Service Reports | `POST /api/service-reports/bulk-delete` | `POST /api/service-reports/bulk-update` | `is_customer_visible`, `tags` | Invoice-evidence reports refuse hard delete |
| Time Entries | `POST /api/time-entries/bulk-delete` | `POST /api/time-entries/bulk-update` | `is_approved`, `assigned_job_id`, `hourly_rate_override` | Paid-payroll entries refuse hard delete |

Shape (all endpoints):
* Accepts `{ids: [...]}` OR `{query_selector, exclude_ids}`. 400-row cap.
* Response: `{ok, deleted_count OR updated_count, deleted OR updated: [ids], failed: [{id, reason, status_code}]}`.
* Role gate: admin/super_admin/owner via `require_admin`.
* Empty `ids` → 400; empty patch (after allow-list filter) → 422.

## Mobile deliverables

For each of the 5 surfaces, the mobile screen should ship:

1. Long-press-to-select-mode (or a persistent multi-select header
   toggle) — Task-BB parity.
2. Header select-all row with tri-state (all / some / none).
3. Row checkboxes with `data-testid` **only when running under
   Detox** — plain accessibility labels otherwise:
   `bulk-select-row-<id>`.
4. Floating action bar (bottom-sheet on iOS, snackbar on Android):
   count · surface-specific edit actions · red **Delete**.
5. Confirmation modal with the Task-BB copy conventions and a
   `Locked · <reason>` inline pill for any `failed[]` rows returned
   by the backend.

## Not shipped yet — audit gaps (do NOT block mobile on these)

Referrals, Vendors, Expenses, and Maintenance Schedules were left
out of this batch because the underlying Mongo collections either
don't exist or map ambiguously to multiple candidates. Waiting for
a product decision before shipping mobile UX for those.
