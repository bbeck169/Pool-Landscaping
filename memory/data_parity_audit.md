# Portal / Admin Data Parity Audit (Feb-2026)

Companion log for the DATA-PARITY-C1/C2/C3 commits that landed on
top of the Feb-2026 performance audit. Captures the architectural
findings per class and the admin audit endpoints shipped to lock
each contract.


## Class 1 — Credit (DATA-PARITY-C1 · commit 72f3e30fb)

### Root cause
Portal `/customer-portal/summary` computed credit INLINE by summing
invoice overpayments. Admin reads from
`customer_credits_balance.balance_cents` (the ledger-aggregated row).
Divergence trigger: an admin-granted credit (manual "Issue Credit"
or referral reward) writes to the ledger but produces zero invoice
overpayments → admin shows the value, portal shows $0.

Diane Lloyd on production — $280 admin / $0 portal — is the
canonical repro. On preview Diane has no credit records, so the
drift is production-only but the architectural bug is clearly
reproducible in pytest via a seeded ledger-only credit.

### Fix
Portal summary routes every money figure (balance_due, past_due,
credit) through the shared `services.customer_balance.
compute_customer_balance` the admin surface already uses. The
breakdown counts (open_invoice_count, past_due_invoice_count) stay
on the inline loop — UI-only, not canonical money. Defensive
fall-through on compute failure keeps the tiles from blanking.

### Audit endpoint
`POST /api/admin/customers/balance-audit` (shipped a4ecdfc5f)
already reports credit drift as part of the computed/stored diff.
Production operator action:

1. `fix=false` to list drifted customers (dry-run).
2. `fix=true` to backfill customer-doc denorm fields on drifted
   accounts.
3. Verify Diane Lloyd + any other drifted account on both surfaces
   post-deploy.


## Class 2 — Service records (DATA-PARITY-C2 · commit f5daa9cd6)

### Root cause
No preview-reproducible architectural divergence. Both portal
(`list_my_service_reports`) and admin (`notes_archive` /
`_build_archive_pipeline`) filter to `submitted_at: {$ne: null}`
on customer-scoped jobs — same visible-set definition by design
(drafts are tech work-in-progress). The user's hypothesis of a
stale `visibility=portal` / `is_published` filter does not reproduce
on preview code.

The `is_customer_visible` field exists (writable via
`routers/bulk_crm_p1.py` bulk-patch) but no query reads it —
half-wired admin-only setting.

### Fix
No preview-side code change required. New
`services/customer_service_records.py::visible_service_report_filter`
locks the canonical Mongo filter shape so future readers can
import it instead of hand-rolling the predicate.

### Audit endpoint
`POST /api/admin/customers/service-records-audit?fix=&limit=` —
scans every customer, counts admin-visible vs portal-visible via
the canonical filter, reports drift. `fix=true` is a report-only
no-op (schema-level drift, not auto-repairable).

If the user reports persistent portal-side missing records post-
production-redeploy, running the audit will immediately surface
whether the drift is schema-level (fixable in code) or data-level
(fixable by submitting the drafts via the admin UI).


## Class 3 — Photos + videos (DATA-PARITY-C3 · commit a9ced23b7)

### Root cause
Three routers all registered under `/api/portal/photos` and
`/api/portal/videos`, each walking a DIFFERENT subset of the four
media sources (`jobs.photos[]`, `estimates.photos[]`,
`service_reports.photos[]`, `files` collection). FastAPI first-match
ordering made `portal_media.py` dead code for photos/videos while
`portal_photos.py` only saw service-report embeds and
`portal_videos.py` only saw job-embed videos with
`visibility="customer"`.

**Live preview data confirms the gap:**
- 13 jobs with embedded `photos[]`
- 7 admin-uploaded images in `files`
- 1 service-report with embedded `photos[]`
- The pre-fix `portal_photos.py` only returned the service-report
  row (1 of 21 photos).

### Fix
New `services/customer_media.py::get_customer_media` merges all
four sources into a single reader. Portal routers rewritten as thin
wrappers around it (`kind="photo"` and `kind="video"`). Duplicate
routes on `portal_media.py` neutralized (replaced with
`_retired_*` stubs). Backwards-compat response shapes preserved.

Hidden-flag honoured: `hidden_from_portal` on the top-level entity
(job/estimate/service_report) hides every embedded media item from
the portal response. Admin always sees everything. Default
visibility = visible to portal.

### Audit endpoint
`POST /api/admin/customers/media-audit?fix=&limit=` — scans every
customer, compares admin vs portal counts via the shared reader,
reports mismatches with sample `hidden_media_ids`. `fix=true` is
a report-only no-op (`hidden_from_portal` is admin-authored; we
don't auto-flip).


## Audit endpoint index

| Endpoint | Class | Fix mode |
|---|---|---|
| `POST /api/admin/customers/balance-audit` | balance + credit (C1) | Writes computed values on drift |
| `POST /api/admin/customers/service-records-audit` | service records (C2) | Report-only |
| `POST /api/admin/customers/media-audit` | photos + videos (C3) | Report-only |

All three admin/owner/super_admin gated, dry-run default
(`fix=false`), optional `limit=N` for incremental audits.


## Test counts

| Class | File | Pass |
|---|---|---|
| C1 Credit | `test_portal_admin_credit_parity.py` | 4/4 |
| C2 Service records | `test_portal_admin_service_records_parity.py` | 5/5 |
| C3 Media | `test_portal_admin_media_parity.py` | 6/6 |

Zero `/app/mobile` touches across all three DATA-PARITY commits.
