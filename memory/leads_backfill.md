# Leads · Backfill playbook — "Website Visitor" empty leads

Legacy pre-P17 rows on the `db.leads` collection landed with the fallback
name **"Website Visitor"** and empty contact columns because the older
public-form extractor was NOT alias-tolerant (it read `name`/`email`/`phone`
verbatim and silently dropped submissions that used `full_name` /
`email_address` / `phone_number` aliases).

The RAW payload is still on `form_submissions.values`, so we can recover
the contact info by re-running through the P17 alias-tolerant extractor.

## Migration script

`backend/migrations/task_p19_backfill_empty_website_visitor_leads.py`

## How to run against a live tenant DB

```bash
# 1. Dry-run FIRST — logs every candidate + planned diff, writes NOTHING.
cd /path/to/app
python -m backend.migrations.task_p19_backfill_empty_website_visitor_leads

# 2. Inspect the output. Expected shape:
#    {
#      "total_candidates": <N>,
#      "backfilled": 0,          # ← 0 because dry-run
#      "skipped_no_submission": <N>,
#      "skipped_no_new_data": <N>,
#      "skipped_already_populated": <N>,
#      "dry_run": True,
#    }

# 3. When it looks right, run with --commit to actually patch the leads
#    in place.
python -m backend.migrations.task_p19_backfill_empty_website_visitor_leads --commit
```

## What it does

1. Finds leads where `name == "Website Visitor"` AND at least one of
   `email` / `phone` / `address` is empty.
2. For each candidate, looks up `form_submissions.values` on the same
   tenant with `created_at` inside a ±5-minute window of the lead's
   `created_at`.
3. Re-runs the values through
   `routers.marketing._lead_row_from_form_values` — the P17 alias-
   tolerant extractor.
4. Patches the lead in place (never inserts, never deletes).
5. Idempotent: re-runs are safe — rows with populated contact info are
   skipped.

## Ingestion-side prevention

The alias-tolerant extractor is now in force on **every** ingestion
path:

| Endpoint | Router · function | Alias-tolerant |
|---|---|---|
| `POST /api/public/leads` | `routers/leads.py::public_lead_intake` | Yes (validates required fields at API boundary) |
| `POST /api/widget/form/{fid}/submit` | `routers/marketing_forms.py::submit_widget_form` | Yes (Feb-2026 widget parity fix) |
| `POST /api/public/forms/{slug}/submit` | `routers/marketing.py::submit_public_form` | Yes (P17 hotfix) |
| `POST /api/forms/{fid}/submit` | `routers/marketing.py::submit_form` | Yes (P17 hotfix) |

New rows should never land as "Website Visitor" unless the visitor
truly submitted an anonymous form with no contact fields at all.

## Not for preview

**Do not run this migration against the preview MongoDB** — the
preview has zero "Website Visitor" rows, so it's a no-op with noise.
Runs on `app.plofv.com` / prod / customer staging environments.
