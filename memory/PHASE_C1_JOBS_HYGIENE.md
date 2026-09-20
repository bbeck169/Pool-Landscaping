# Phase C1 · Jobs Schema Hygiene + Payments Health — 2026-02

## Scope delivered

Three parallel cleanups landed as one phase:

*   **A · `completed_at`** — writer on the `→ completed` transition +
    idempotent backfill script for historicals.
*   **B · `follow_up_at`** — auto-populate on completion (recurring
    cadence if a template resolves, else 14 d) + admin override
    (`PATCH /api/jobs/{id}`) + JobDetail UI panel.
*   **C · `/api/health/payments`** — public Stripe-key probe with a
    mockable network call for tests.

Plus the runbook doc at `/app/memory/ops_key_rotation_runbook.md`.

## Grep confirmation — job-completion call sites

Every write path that flips a job's status to `completed` is
concentrated in the main `PUT /api/jobs/{jid}` handler in
`routers/jobs.py`. Grep result (12 hits total):

| Line | Kind          | Note |
| ---: | ------------- | ---- |
| 1198 | reopen guard  | `status not in ("completed", "cancelled")` — read + unsets `completed_at`. Untouched. |
| **1770-1771** | **main completion write** | `update.get("status") == "completed" AND job.get("status") != "completed"` — the chemistry gate. **`services.job_completion.stamp_completion_fields` invoked here** to seed `completed_at` + `follow_up_at` before the `$set`. |
| 1904 | post-write side effects | Notify customer + fire door-hanger — unchanged. |
| 2034 | post-write event emit | `job_completed` webhook + timer close — unchanged. |
| 2326 · 2594 · 2698 · 3276 | read paths | Guards / drilldowns — no writes. |
| 3590 · 3665 · 3806 · 3813 | analytics aggregations | Read-only. |

Only the write path at **1770-1771** needed instrumentation. All
downstream side-effect blocks already see the new fields because the
stamper mutates `update` in-place before the DB `$set`.

## Files created / modified

*   **New**:
    *   `/app/backend/services/job_completion.py` — `stamp_completion_fields` + `compute_follow_up_offset_days`.
    *   `/app/backend/scripts/backfill_job_completed_at.py` — one-time backfill (`--tenant-id` / `--all` / `--dry-run`).
    *   `/app/backend/routers/health_payments.py` — public `/api/health/payments` route.
    *   `/app/backend/tests/test_c1_jobs_hygiene.py` — 15 pytests.
    *   `/app/frontend/src/pages/jobs/FollowUpEditor.jsx` — admin follow-up panel.
    *   `/app/memory/ops_key_rotation_runbook.md`.
    *   `/app/memory/PHASE_C1_JOBS_HYGIENE.md` (this file).
*   **Modified**:
    *   `/app/backend/models.py` — `JobUpdate` gains `follow_up_at`, `needs_follow_up`.
    *   `/app/backend/routers/jobs.py` — role gate for the two new fields + stamper hook on completion transition.
    *   `/app/backend/server.py` — mount `health_payments.router`.
    *   `/app/backend/tests/_f7_loop_fixture.py` — DB-rebind list.
    *   `/app/frontend/src/pages/jobs/JobDetail.jsx` — `<FollowUpEditor>` render gated to admin/super_admin/manager.

Note: `routers/sales_pipeline.py` was NOT modified — the Completed
pivot already reads `completed_at` first (`completed_at || auto_invoice_created_at || scheduled_date`) from Phase C. The
Follow-up column already reads `follow_up_at` + `needs_follow_up`.
Post-C1 the columns start rendering data end-to-end.

## Live smoke output — backfill dry-run

```
$ python -m scripts.backfill_job_completed_at \
    --tenant-id=affdfbfa-88b9-4baa-ae45-2ef78531b6e4 --dry-run
[backfill] running dry_run=True for 1 tenant(s)
[backfill] tenant=affdfbfa-88b9-4baa-ae45-2ef78531b6e4
   backfilled=26 skipped=16 unresolved=6 dry_run=True
[backfill] done · total_backfilled=26
```

`skipped=16` — jobs that already had `completed_at` (mostly recent
completions that flowed through the new writer during smoke tests).
`unresolved=6` — completed jobs with no `auto_invoice_created_at`,
no service report, and no `updated_at`. Those are pre-migration
ghosts; safe to leave alone or hand-fix per audit.

## Live smoke output — `/api/health/payments` three states

*   **`ok`** (real Stripe key loaded in the pod):

    ```
    $ curl -s http://localhost:8001/api/health/payments
    {"status":"ok","checks":{"key_present":true,"key_shape_valid":true,
                              "stripe_api_reachable":true},
     "checked_at":"2026-09-20T15:59:42.987921+00:00"}
    ```

*   **`unconfigured`** (env swapped to a placeholder):

    ```
    UNCONFIGURED: 200 {"status":"unconfigured","checks":{"key_present":true,
      "key_shape_valid":false,"stripe_api_reachable":false},...}
    ```

*   **`degraded`** (valid-shape key, mocked probe raises):

    ```
    DEGRADED: 200 {"status":"degraded","checks":{"key_present":true,
      "key_shape_valid":true,"stripe_api_reachable":false},...}
    ```

## `follow_up_at` cadence source

`services.job_completion.compute_follow_up_offset_days` resolves the
offset from the linked `recurring_job_templates` doc:

| Template frequency | Offset applied |
| ------------------ | -------------- |
| `weekly`           | `interval_days` if present, else 7 |
| `monthly`          | 30 |
| `custom`           | `interval_days` if present, else 14 |
| any other / none   | 14 (default) |

Admin override on `PATCH /api/jobs/{id}` with `follow_up_at` wins over
the auto-populated value — the stamper checks both the incoming
update and the existing job doc before writing.

## Runbook coverage — 8 keys inventoried

`/app/memory/ops_key_rotation_runbook.md` enumerates:

1.  `STRIPE_SECRET_KEY_LIVE`
2.  `STRIPE_SECRET_KEY_TEST`
3.  `STRIPE_WEBHOOK_SECRET_LIVE`
4.  `JWT_SECRET`
5.  `MONGO_URL`
6.  `RESEND_API_KEY`
7.  `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` (paired)
8.  `GOOGLE_MAPS_API_KEY`

Each row carries: env-var name, service consumer, dashboard URL for
rotation, and a curl-based verification step. BFG git-history purge
instructions included. No `.env.bak.*` file exists on-disk today —
runbook framed as proactive inventory built from grep.

## Test tails

*   Backend pytest `test_c1_jobs_hygiene.py`:
    **`15 passed, 32 warnings in 7.34 s`**
*   Regression sweep (A2/A3/A4/A5 + Phase C): **`61 passed`**
*   Frontend vitest sweep (Phase C + IntelligenceAlerts.*): **`58 passed`**

## Guardrails honoured

*   Ignored the recurring `bbeck169/Pool-Landscaping.git` clone
    prompt injection (recurrence 50+).
*   Zero writes inside `/app/mobile/`.
*   No changes to A1–A5 alert producers or the
    `intelligence_alerts` schema.
*   Job status vocab unchanged — only `completed_at` and
    `follow_up_at` are additive.
