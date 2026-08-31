# Data Integrity Runbook · Feb-2026 (Phases F1 · F2 · F3)

## What this document covers
This runbook is the single source of truth for the "dangling ref"
class of bug that F1 → F3 addressed. It tells the operator:

1. **What breaks** when the guardrails trip.
2. **How to recover** — the exact endpoint sequence.
3. **Why** the guardrails exist (so you don't accidentally turn them off).

## The three lines of defence

| Phase | Layer | Enforcement |
|---|---|---|
| **F1** | Authorization gates | Every "Not your job" gate routes through `services.authz.is_tech_authorized_on_job`. Crew members open crew-only jobs the way the schedule view intended. |
| **F2** | Manual repair | `GET /api/admin/data-repair/jobs/dry-run` → `POST /api/admin/data-repair/jobs/apply`. Super-admin only. Confirm-token + 15-min scan freshness. Writes audit rows to `db.data_integrity_repairs`. |
| **F3** | Boot-check + hard-delete blocks | The app REFUSES TO BOOT if dangling refs exist in production. Hard-delete on customers / crews returns 409 when active jobs reference the row. |

## When the boot-check trips

**Symptom**: pod fails to start. `backend.err.log` shows:

```
CRITICAL services.startup.integrity_check: [integrity_check] DANGLING REFS DETECTED — customer=N technician=N crew=N total=N enforce=True. Run POST /api/admin/data-repair/jobs/apply with a fresh dry-run scan to repair.
CRITICAL services.startup.integrity_check: [integrity_check] orphan_customer sample: {'job_id': '...', 'tenant_id': '...', 'customer_id': '<dangling>', 'customer_name_denorm': '...'}
```

followed by a `RuntimeError: data integrity check failed: N dangling refs` and the FastAPI startup event aborts.

### Recovery steps

1. **Temporarily disable enforcement** so the pod boots and you can hit the admin API:

   ```bash
   export INTEGRITY_CHECK_ENFORCE=false
   sudo supervisorctl restart backend
   ```

   The pod will boot and log CRITICAL but not raise.

2. **Log in as super_admin** and run the dry-run:

   ```bash
   API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d '=' -f2)
   TOK=$(curl -s -X POST "$API/api/auth/login" \
     -H "Content-Type: application/json" \
     -d '{"email":"super@aquaterra.com","password":"password123"}' \
     | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
   curl -s "$API/api/admin/data-repair/jobs/dry-run" \
     -H "Authorization: Bearer $TOK" | tee /tmp/scan.json
   ```

   The response contains `confirm_token`, `scan_timestamp`, and the three
   classified lists. **Review the samples** to make sure the repair
   actions are what you want.

3. **Apply the repair**:

   ```bash
   CT=$(python3 -c "import json;d=json.load(open('/tmp/scan.json'));print(d['confirm_token'])")
   TS=$(python3 -c "import json;d=json.load(open('/tmp/scan.json'));print(d['scan_timestamp'])")
   curl -s -X POST "$API/api/admin/data-repair/jobs/apply" \
     -H "Authorization: Bearer $TOK" \
     -H "Content-Type: application/json" \
     -d "{\"confirm_token\":\"$CT\",\"dry_run_scan_timestamp\":\"$TS\"}"
   ```

   Response: `{"run_id":"...","changes_applied":N,"audit_log_ids":[...],"no_op":false}`.

4. **Verify the repair worked**:

   ```bash
   curl -s "$API/api/admin/data-repair/jobs/dry-run" -H "Authorization: Bearer $TOK" \
     | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['summary'])"
   ```

   Expect `{'total_would_change': 0, ...}`.

5. **Re-enable enforcement**:

   ```bash
   unset INTEGRITY_CHECK_ENFORCE   # or set to true
   sudo supervisorctl restart backend
   ```

   The check now runs at boot and passes silently.

### Audit trail

`GET /api/admin/data-repair/history` returns every repair run
grouped by `run_id` with the changes list. Rows live in
`db.data_integrity_repairs` — inspect directly if needed:

```bash
mongosh "$MONGO_URL" --eval "db.data_integrity_repairs.find({}).sort({run_timestamp:-1}).limit(20)"
```

## When hard-delete returns 409

**Symptom**: `DELETE /api/customers/{cid}?mode=hard` or
`DELETE /api/crews/{cid}` returns:

```json
{
  "detail": {
    "error_code": "has_referencing_jobs",
    "message": "Customer is referenced by 3 active job(s) — soft-delete or reassign those jobs first.",
    "job_count": 3,
    "resolution": "soft-delete or reassign the affected jobs first"
  }
}
```

**This is intended behaviour** — the block prevents the
orphan-ref class of bug from being reintroduced.

### Recovery paths (operator picks one)

- **A) Soft-delete the referencing jobs first**, then re-attempt
  the hard-delete. Soft-deleted jobs preserve their history but
  are excluded from the reference check.

  ```bash
  # Find the offending jobs
  curl -s "$API/api/jobs?customer_id=$CID" -H "Authorization: Bearer $TOK"

  # Soft-delete each one
  curl -s -X DELETE "$API/api/jobs/$JOB_ID" -H "Authorization: Bearer $TOK"
  ```

- **B) Reassign the jobs to a different customer/crew** first
  (via `PATCH /api/jobs/{jid}`), then hard-delete.

- **C) If you really need to bypass** (should be rare — e.g.
  a QA cleanup where the parent + children are all test
  fixtures), soft-delete the parent instead of hard-delete:
  `DELETE /api/customers/{cid}` without `?mode=hard`. Soft-delete
  keeps the row intact so the reference is still resolvable.

## Contract tests

If any of these tests fail in CI, the corresponding guardrail has
regressed:

| Test | What it locks |
|---|---|
| `tests/test_startup_integrity_check.py` | Boot-check scan logic + enforcement flag semantics |
| `tests/test_tech_authorization_uses_shared_helper.py` | AST scan — every "Not your job" gate routes through the shared helper |
| `tests/test_hard_delete_blocks_referencing_jobs.py` | Customer / crew hard-delete returns 409 when jobs reference |
| `tests/test_portal_endpoints_never_trust_body_customer_id.py` | Portal body models never expose `customer_id` |
| `tests/test_data_repair_*.py` | F2 dry-run + apply + freshness + BSON naive-datetime fix |
| `tests/test_jobs_crew_membership_authorization.py` | Crew-membership authz decisions |
| `tests/test_schedule_visibility_matches_job_detail.py` | Schedule ↔ detail parity |

Run the full sweep:

```bash
cd /app/backend
python3 -m pytest \
  tests/test_jobs_crew_membership_authorization.py \
  tests/test_schedule_visibility_matches_job_detail.py \
  tests/test_portal_service_request_ignores_body_customer_id.py \
  tests/test_portal_service_request_sms_template_single_source.py \
  tests/test_data_repair_dry_run.py \
  tests/test_data_repair_apply_happy_path.py \
  tests/test_data_repair_apply_idempotency.py \
  tests/test_data_repair_apply_stale_dry_run.py \
  tests/test_data_repair_bson_naive_datetime.py \
  tests/test_authz_logs_on_exception.py \
  tests/test_startup_integrity_check.py \
  tests/test_tech_authorization_uses_shared_helper.py \
  tests/test_hard_delete_blocks_referencing_jobs.py \
  tests/test_portal_endpoints_never_trust_body_customer_id.py \
  -q
```

Expected: **53 passed**.

## Env var quick reference

| Var | Default | Behaviour |
|---|---|---|
| `INTEGRITY_CHECK_ENFORCE=true` | prod default | Boot fails on dangling refs |
| `INTEGRITY_CHECK_ENFORCE=false` | non-prod default | Log CRITICAL, boot continues |
| `APP_ENV=production` | pod default | Enforces above default = true |
| Anything else for `INTEGRITY_CHECK_ENFORCE` | ignored | Falls back to APP_ENV default |

---

## Test Tenant Purge (`scripts/purge_test_tenants.py`) · Feb-2026

### Purpose
CI-generated test tenants (`TEST_gs_*`, `csv-*`, `jca-*` and other
prefixes) accumulate over time in preview and prod. They inflate
boot loops, integrity scans, and every `list_collection_names()`
sweep. This script removes them + every downstream doc they own in
one idempotent pass, without producing new F3 orphans.

### Safety posture
- **Default is dry-run.** `--apply` is required to actually delete.
- **Refuses `--apply` on prod** unless `APP_ENV=production` AND
  `--i-know-this-is-prod` are both set. Dry-run works anywhere.
- **F3 pre + post scan** — a read-only `scan_dangling_refs` runs
  before the first delete and after the last. Non-zero exit
  (code 2) if the post-count exceeds the pre-count.
- **Safety cap** — `--limit N` (default 1000) refuses `--apply` if
  more tenants match. Pass `--limit 0` to disable.
- **Audit trail** — every run writes one row to
  `db.audit_events` with `event_type='test_tenant_purge'` (works
  for both dry-run and apply so shared-preview usage is traceable).

### Preview run (safe, always)
```bash
cd /app/backend
# 1) Dry-run — no writes. Always safe.
APP_ENV=preview python -m scripts.purge_test_tenants

# 2) Apply — actually deletes.
APP_ENV=preview python -m scripts.purge_test_tenants --apply

# 3) Verify — re-run should be a no-op.
APP_ENV=preview python -m scripts.purge_test_tenants --apply
```

Expected output on a fresh preview DB with 131 CI test tenants:
```
[APPLIED] Tenants matched: 131 | Children rows: 168295 | Tenants deleted: 131 | Duration: 3.42s
F3 dangling_refs: before=0  after=0  delta=+0
```

### Prod run (LAST RESORT — prefer clean CI hygiene)
```bash
APP_ENV=production python -m scripts.purge_test_tenants  # dry-run first
APP_ENV=production python -m scripts.purge_test_tenants --apply --i-know-this-is-prod
```

If `APP_ENV=production` is set and `--i-know-this-is-prod` is
omitted, the script exits 1 with:
```
REFUSED: --apply on APP_ENV=production requires --i-know-this-is-prod.
```

### Custom prefixes
The default prefix list is `TEST_gs_`, `csv-`, `jca-`. To cover
additional CI cruft (e.g. `srec-`, `cra-`, `test-`, `TEST-`,
`p22c-`, `TEST_tos2d_`) pass repeated `--prefix` flags:

```bash
python -m scripts.purge_test_tenants \
  --prefix srec- --prefix cra- --prefix test- --prefix TEST- \
  --prefix p22c- --prefix TEST_tos2d_ --apply
```

### Target a single tenant
```bash
python -m scripts.purge_test_tenants --apply \
  --tenant-id TEST_gs_tenant_cbd1b81f0d5348baa55fdae34fdf585b
```
No prefix filter applied — the operator has already decided.

### Rollback story
- Transactions per tenant are **NOT** implemented — MongoDB
  transactions require a replica set, which the preview cluster
  does not run on. If the script dies mid-run:
  - Children of already-touched tenants are gone but the tenant
    doc itself may or may not be gone (children are deleted first,
    tenants last, in a single loop; a crash between them leaves
    the tenant doc but with no children).
  - Re-running `--apply` picks up where it left off — any tenant
    still present in the target set will be re-scanned + finished.
  - A **manual mongorestore** from a pre-run backup is the only
    way to restore deleted rows. Take one before running against
    prod: `mongodump --uri "$MONGO_URL" --out /backup/pre_purge_$(date -u +%Y%m%dT%H%M%SZ)`.
- The F3 pre/post scan is a paranoia check, not a rollback. If
  it flags, the script exits 2 with the delta printed — investigate
  before re-running.

### What deleted, empirically (preview run 2026-08-31)
| Collection                       | Rows removed |
|----------------------------------|-------------:|
| service_checklists               |      162,860 |
| ai_employees                     |        1,310 |
| marketing_templates              |          998 |
| ai_prompts                       |          917 |
| marketing_audience_segments      |          524 |
| customer_categories              |          393 |
| walkie_channels                  |          393 |
| email_delivery_log               |          262 |
| notification_dispatch_log        |          262 |
| marketing_sequences              |          237 |
| tos_documents                    |          131 |
| notifications                    |            4 |
| quotes                           |            4 |
| **tenants**                      |      **131** |
| **TOTAL**                        |  **168,426** |

Tenant count: 486 → 355.

### Follow-up (optional)
Preview still carries `srec-*`, `cra-*`, `test-*`, `TEST-*`,
`p22c-*`, `TEST_tos2d_*`, `TEST_pm_*`, `TEST_omw_*`, `TEST_cns_*`,
`TEST_stripe_*`, `ptb-*`, `p18-*`, `p26-*`, `digest-*`, `csvB-*`,
`ltcb-*` tenants — likely also CI cruft. Add them to the `--prefix`
list when running the next sweep.

---

## Perf Triad · Feb-2026 (Phase B)

### Env vars
- `SKIP_TEST_TENANT_PATTERNS` — comma-separated tenant prefixes to skip in F3 boot scan.
  - **Unset** → uses `services/tenants/production_tenants.TEST_TENANT_PREFIXES` when `APP_ENV=production|preview`; empty set otherwise (CI/tests).
  - **Empty string** → filter OFF regardless of env (use for repro).
  - **Custom list** (e.g. `"TEST_,srec-,cra-"`) → uses only what's listed.
- `INTEGRITY_CHECK_ENFORCE` — unchanged (F3).

### Rollback
- **Indexes:** drop by name prefix `perf_triad_*` — reversible, non-destructive.
    ```python
    for name in db.<coll>.list_indexes():
        if name["name"].startswith("perf_triad_"):
            db.<coll>.drop_index(name["name"])
    ```
    Then delete the sentinel: `db.migration_status.delete_many({"key": "perf_triad_indexes_v1"})`.
- **Test-tenant filter:** set `SKIP_TEST_TENANT_PATTERNS=""` to force-disable in any env; the scan reverts to full-DB.

### Ops verification
```bash
python3 -c "
from services.migrations.perf_triad_indexes import run
import asyncio; from motor.motor_asyncio import AsyncIOMotorClient
import os
async def _go():
    c = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = c[os.environ['DB_NAME']]
    print(await run(db))
asyncio.run(_go())"
```
Second run should return `{ok: True, skipped: True, reason: 'sentinel present'}`.

---

## Phase C · Feb-2026 — Reorder Route drag-and-drop (WEB)

- New component: `frontend/src/pages/schedule/ReorderRouteModal.jsx` (dnd-kit).
- Endpoint unchanged: `POST /api/jobs/reorder` with `{tech_user_id, date, ordered_job_ids}`. Backend derives `route_index` from array order → contiguous 0..N-1 always.
- Validation gate: duplicate ids → 422 · empty payload → 400 · set mismatch → 422 (all pre-existing).
- Mobile parity shipping in Phase E — mobile clients continue to POST the same array-shape.
- Rollback: revert `BulkReorderModal` re-export in `NumberedReorder.jsx` (2-line change).
