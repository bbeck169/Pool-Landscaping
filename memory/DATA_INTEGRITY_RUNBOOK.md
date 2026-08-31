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
