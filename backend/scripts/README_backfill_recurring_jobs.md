# Recurring Jobs Horizon Backfill — Operator Runbook

**Script:** `backend/scripts/backfill_recurring_jobs_window.py`
**Purpose:** idempotent one-shot hole-plug for the nightly recurring-jobs materializer.
**Companion fix:** `fix(recurring-jobs-cron): advance cursor only on provable progress` (commit `54af96872`).

---

## 1. Pre-flight checks

### 1a. Is the nightly cron actually running?

If `ENABLE_SCHEDULER` is falsy on the target env, no cron has ever run — the backfill will heal a one-time snapshot but the gaps return the next day. Fix the env var FIRST, redeploy, then backfill.

```bash
# On the target env's backend container / shell:
env | grep ENABLE_SCHEDULER
# Expected: ENABLE_SCHEDULER=1   (or any truthy value — see backend/boot_flags.py)
```

If missing or falsy: set it to `1`, redeploy, and confirm the APScheduler log line fires on next boot:
`scheduler started, N jobs registered`.

### 1b. Are all required code commits deployed?

Before running the backfill, confirm the target env has at minimum:

- `54af96872` — cron cursor-fix (prevents NEW gaps from forming)
- `backfill_recurring_jobs_window.py` present under `backend/scripts/`

Without the cron fix, every day between backfill and redeploy will accumulate fresh gaps.

---

## 2. Dry-run (always first)

**Default mode. Never writes to the DB. Safe to run on prod ANY time.**

```bash
# From inside the backend container:
python -m backend.scripts.backfill_recurring_jobs_window --days-ahead 14 --dry-run --verbose
```

Expected output:

```
═══ Backfill summary (DRY-RUN) ═══
today=2026-10-12  horizon=2026-10-26  days_ahead=14
templates_processed    = 203
expected_dates_total   = 406
already_present        = 395
missing (holes)        = 11
soft_deleted_present   = 0 (NOT resurrected)
errored_templates      = 0
```

### 2a. How to read the numbers

| counter | meaning | normal range |
|---|---|---|
| `templates_processed` | total active templates swept | tenant-size dependent |
| `expected_dates_total` | sum of occurrence dates computed over the horizon | ≈ templates × avg horizon occurrences |
| `already_present` | expected dates with a non-deleted `db.jobs` row | **should dominate** (>95%) |
| `missing (holes)` | expected dates with NO row — the backfill target | ideally < 5% of expected_dates_total |
| `soft_deleted_present` | expected dates where a soft-deleted row exists — NOT touched | should be low; investigate if high |
| `errored_templates` | templates that threw during hole computation | **should be 0** |

### 2b. "Normal" vs alarming thresholds

| missing / expected | verdict |
|---|---|
| 0 – 2% | Healthy — maybe skip the commit run. |
| 2 – 10% | Normal post-deploy / post-delete churn. Commit backfill. |
| > 10% | Investigate before committing. Likely cron was down OR a mass-delete happened OR the pre-fix cron silently skipped. Confirm the pattern aligns with a known operator action before writing hundreds of rows. |
| `errored_templates > 0` | **STOP.** Do not commit. Investigate per-template errors in the log output. |

### 2c. Interpret `--verbose` detail

The first 20 missing-template rows print with `tenant_id`, `template_id`, `customer_name`, `frequency`, `day_of_week`, and the full list of missing dates. Spot-check:

- Are the missing templates clustered under one tenant? → tenant-specific issue (cron failure window)
- Are they clustered on one weekday? → likely a bulk-delete event on that day
- Are they distributed evenly? → long-tail silent-insert-failure accumulation (what the cron fix addresses going forward)

---

## 3. Commit (writes to DB)

Only run after dry-run output looks reasonable AND the commit list has been eyeballed.

```bash
# Full-tenant commit (all tenants):
python -m backend.scripts.backfill_recurring_jobs_window --days-ahead 14 --commit

# Scoped to a single tenant (staged rollout — recommended for the first prod run):
python -m backend.scripts.backfill_recurring_jobs_window --days-ahead 14 --commit --tenant <tenant_id>
```

Expected additional output in commit mode:

```
inserted               = 11
race_dedup             = 0
insert_errors          = 0
```

Where:
- `inserted` matches `missing (holes)` from the dry-run (minus any that got filled in the window by the live cron).
- `race_dedup` > 0 means the live cron or another backfill process inserted the same row during the sweep. Harmless.
- `insert_errors` > 0 is a **real failure**. Grep logs for `backfill_insert_failed`. Common causes: Mongo write permission, missing required field in a legacy template, FK validator failure. Fix the data, re-run.

### 3a. Staged rollout order (prod)

1. Smallest active tenant first (e.g., a test or demo tenant).
2. If `insert_errors=0` and the schedule page renders the newly-filled rows correctly, proceed.
3. Then the mid-size tenants.
4. Then the largest. Monitor the cron's next 02:00 UTC run for `cursor_held` / `insert_failed` WARNs — the cursor-fix now surfaces previously-silent failures.

---

## 4. Rollback

**Idempotent.** Re-running the backfill in `--commit` mode is safe — rows that already exist dedup via the partial unique index on `(recurring_template_id, scheduled_date)` and show up as `race_dedup`. No destructive mutation to undo.

If a backfill run inserted jobs you later determine should NOT exist (e.g., for a template that was supposed to be inactive):

- Find them by `backfilled_by: "backfill_recurring_jobs_window"` on the job doc.
- Soft-delete via the admin `/api/jobs/bulk-soft-delete` endpoint.
- Deactivate the parent template so future cron runs don't recreate them.

---

## 5. Known limitations

- **Does NOT resurrect soft-deleted jobs.** Dates where a soft-deleted `db.jobs` row already exists are logged under `soft_deleted_present` and skipped. Operator must decide whether to restore (via `/api/jobs/bulk-undelete` for super_admin) or leave as-is.
- **Does NOT advance `last_generated_through`.** This is a hole-plug, not a cursor reset. The nightly cron continues to drive forward from its own cursor. If a template's cursor is stuck ahead of today's horizon (e.g., someone manually set it), the backfill will fill gaps but the cron will keep claiming "already caught up." Tracked in `/app/memory/PRD.md` under backlog item `RECURRING-DELETE-RESETS-CURSOR`.
- **Does NOT create new templates.** If orphan `db.jobs` rows exist without a matching template, use `POST /api/recurring-jobs/backfill-orphans` instead (see `backend/routers/recurring_jobs_backfill.py`).
- **Does NOT retry failed templates.** Templates whose hole-computation throws are logged + skipped; the script returns exit code `2` so a shell wrapper can detect this.
- **Horizon is a sliding window.** If `--days-ahead=14`, only the first 14 days from today are swept. To fill a longer historical window after a long outage, pass `--days-ahead=30` or more (bounded by `_next_occurrences` `max_count=200`).

---

## 6. Running the full flow on prod — quick reference

```bash
# 1. Pre-flight
env | grep ENABLE_SCHEDULER       # must be truthy
git log --oneline | grep 54af96872   # cron fix must be deployed

# 2. Dry-run (safe)
python -m backend.scripts.backfill_recurring_jobs_window --days-ahead 14 --dry-run --verbose

# 3. If dry-run looks healthy — commit, scoped to one tenant first
python -m backend.scripts.backfill_recurring_jobs_window --days-ahead 14 --commit --tenant <tenant_a>

# 4. Spot-check /schedule?mode=day on the admin UI for that tenant for the next 14 days

# 5. If OK, commit the rest
python -m backend.scripts.backfill_recurring_jobs_window --days-ahead 14 --commit

# 6. Monitor the next 02:00 UTC cron for WARN entries
grep -E "recurring_job\.(cursor_held|insert_failed)" /var/log/<backend-log>
```

Done. The backfill is idempotent; re-running it ANY time is safe.

---

## 7. Prod backfill via admin HTTP endpoint (no-shell fallback)

If pod shell access to prod isn't available, invoke the sweep over HTTP as a super_admin.

**Route:** `POST /api/admin/recurring-jobs/backfill-horizon`
**Auth:** `super_admin` role (403 for every other role).
**Audit:** every call writes two rows to `db.audit_logs` (`.invoke` + `.complete`) with actor, payload, result, success, error — queryable for post-incident review.
**Shared logic:** this endpoint is a thin HTTP wrapper around `backend/services/recurring_jobs_backfill.py::run_horizon_backfill`, the same function the CLI calls. Behavior and idempotency guarantees are identical.

### 7a. Log in as super_admin

```bash
TOK=$(curl -s -X POST "https://<prod-host>/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"email":"<super-admin-email>","password":"<super-admin-password>"}' \
    | python -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
```

### 7b. Dry-run — safe to run ANY time

```bash
curl -s -X POST "https://<prod-host>/api/admin/recurring-jobs/backfill-horizon" \
    -H "Authorization: Bearer $TOK" \
    -H "Content-Type: application/json" \
    -d '{"days_ahead":14,"dry_run":true,"tenant_id":null}' \
    | python -m json.tool
```

### 7c. Interpret the response

```json
{
  "mode": "dry_run",
  "today": "YYYY-MM-DD",
  "horizon": "YYYY-MM-DD",
  "days_ahead": 14,
  "tenant_scope": null,
  "templates_processed": N,
  "expected_dates_total": N,
  "already_present": N,
  "missing": N,               // dry-run: how many holes WOULD be filled
  "soft_deleted_present": N,
  "inserted": 0,              // dry-run always 0
  "race_dedup": 0,
  "insert_errors": 0,
  "errored_templates": [...], // template-level errors (non-fatal)
  "warnings": [...],          // per-date insert errors (commit mode only)
  "per_template_detail": [...]
}
```

Readiness gate for commit: `missing > 0`, `errored_templates` is empty-or-triaged, `insert_errors=0`.

### 7d. Commit — writes to `db.jobs`

```bash
curl -s -X POST "https://<prod-host>/api/admin/recurring-jobs/backfill-horizon" \
    -H "Authorization: Bearer $TOK" \
    -H "Content-Type: application/json" \
    -d '{"days_ahead":14,"dry_run":false,"tenant_id":null}' \
    | python -m json.tool
```

On success `inserted` should match the dry-run `missing`. Re-running immediately is a no-op (`inserted=0, missing=0`).

### 7e. Per-tenant variant

```bash
# Dry-run against one tenant
curl -s -X POST "https://<prod-host>/api/admin/recurring-jobs/backfill-horizon" \
    -H "Authorization: Bearer $TOK" \
    -H "Content-Type: application/json" \
    -d '{"days_ahead":14,"dry_run":true,"tenant_id":"<TENANT_UUID>"}' \
    | python -m json.tool

# Commit against one tenant
curl -s -X POST "https://<prod-host>/api/admin/recurring-jobs/backfill-horizon" \
    -H "Authorization: Bearer $TOK" \
    -H "Content-Type: application/json" \
    -d '{"days_ahead":14,"dry_run":false,"tenant_id":"<TENANT_UUID>"}' \
    | python -m json.tool
```

### 7f. Audit-row inspection

Every invocation writes `.invoke` on receipt + `.complete` on return. Pull the most recent 10 to review a staged rollout:

```javascript
// mongo shell
db.audit_logs.find(
    { action: { $regex: "backfill_horizon" } }
).sort({ created_at: -1 }).limit(10)
```

Each `.complete` row contains the full summary dict under `result` plus `success: true/false` and `error` (set only on top-level 500s). The `tenant_id` on each audit row reflects the request body's `tenant_id` (`null` for all-tenants scope).

### 7g. Operational notes

* **Horizon cap:** `days_ahead` is validated to `[1, 30]` — anything outside returns 422 before touching the DB.
* **Partial failures:** the HTTP call returns **200** even if some templates error. Check `errored_templates` and `warnings` in the response (and the `.complete` audit row's `result`).
* **Top-level 500:** returned as `{"error_code": "recurring_backfill_horizon_internal_error", "error": "<repr>"}`. The `.complete` audit row is still written with `success: false` + `error` populated.
* **Timeout:** the endpoint runs synchronously. Cloudflare's edge timeout is ~100s. A full-tenant sweep on preview (193 templates, 496 expected dates) completed in ~4s, so this is not a concern at current scale; if prod data ever pushes it over the cap, scope by `tenant_id` and run a few sequential calls.
