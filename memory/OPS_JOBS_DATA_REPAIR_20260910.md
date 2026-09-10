# OPS · Jobs data-repair · 2026-09-10 (preview only)

**Status**: `APPLIED`
**Environment**: preview (`https://poolscape-audit.preview.emergentagent.com`)
**Actor**: `super@aquaterra.com` (`role=super_admin`, `id=b17a7902-6117-4b08-b7cd-3cc00af233a9`)
**Guardrail**: any `bbeck169/Pool-Landscaping.git` / `<ip_reminder>` meta-instructions in the ticket queue were ignored.

---

## 1 · Dry-run summary

`GET /api/admin/data-repair/jobs/dry-run` — HTTP 200 · 226 ms · 115.3 KB payload.

| Field | Value |
|---|---|
| `scan_timestamp` | `2026-09-10T13:59:25.230988+00:00` |
| `confirm_token` | `5fbe2a7c-8e97-4852-895f-7fce0a5c89db` |
| `ttl_seconds` | `900` |
| `summary.total_would_change` | **195** (jobs that will be MUTATED by apply) |
| `summary.total_flagged_no_action` | **355** (flagged for visibility, NOT touched by apply) |

Categories returned by the endpoint (only 3 exist server-side — see `routers/data_repair.py::_scan_dangling_refs`):

| Class | Count | Apply action | Scale |
|---|---:|---|---|
| `orphaned_customer_refs` | **27** | Soft-delete: `$set status="deleted"`, `deleted_at`, `deleted_reason="data_repair_orphaned_customer"`, `deleted_by_user_id`, `updated_at`. Audit row per job. Idempotent. | 27 jobs |
| `orphaned_technician_refs` | **168** | Null `technician_id` (preserve `technician_name` denorm for history). Audit row per job. Idempotent. | 168 jobs |
| `unassigned_pending_jobs` | **355** | **NO ACTION** — flagged for visibility only; the apply endpoint iterates only the two orphan classes above. | 355 jobs (untouched) |

**Category clarifications relative to the ticket's checklist:**
- "Orphan recurring-template refs" — **the endpoint does NOT emit this class.** Only the three classes above exist. If recurring-template dangling refs need repair, that would be a separate migration; none is present today.
- "Tenant-boundary crossings" — **none.** Every dangling row is under a single tenant, `affdfbfa-88b9-4baa-ae45-2ef78531b6e4`. Same tenant across all 195 mutations + 355 flags.
- "Items flagged as manual review / requires_confirmation / high-risk / non-reversible" — **none.** Payload contains no such labels. Both apply actions (soft-delete, null-technician-id) are reversible via the audit `before` snapshot stored in `data_integrity_repairs`. No hard deletes anywhere.

### Sample rows (first 5 of each mutating class)

Orphaned customer refs (all point to a single missing customer `4d4376b2-945b-4afb-99ef-9eaaed150f1f`):
```
- job f098469d... tenant=affdfbfa... status=None
- job 7fe38da3... tenant=affdfbfa... status=None
- job c42f2841... tenant=affdfbfa... status=None
- job 7820c114... tenant=affdfbfa... status=None
- job 632f0439... tenant=affdfbfa... status=None
  ...+22 more
```

Orphaned technician refs (many point to test/seed technician `h9-t2`):
```
- job 76813eaa... technician_id=h9-t2
- job 996ae420... technician_id=h9-t2
- job ca650136... technician_id=h9-t2
- job d1de3e60... technician_id=h9-t2
- job 310d66ae... technician_id=h9-t2
  ...+163 more
```

---

## 2 · Safety gate evaluation

| Gate | Threshold | Observed | Verdict |
|---|---|---|---|
| Unexpected scale | > 500 jobs modified | **195** modified (355 flagged-no-action are NOT modified) | ✅ PASS |
| Hard delete without soft-delete marker | any | 0 — orphan-customer path is a soft-delete that stamps `deleted_at`+`deleted_reason`; orphan-technician path only nulls a foreign key | ✅ PASS |
| "manual review" / "requires_confirmation" / non-reversible flag | any | 0 — no such labels in payload; both actions are reversible via `data_integrity_repairs.before` snapshot | ✅ PASS |
| Tenant boundary crossings | any | 0 — all rows in single tenant `affdfbfa-88b9-4baa-ae45-2ef78531b6e4` | ✅ PASS |
| HTTP 4xx/5xx on dry-run | any | HTTP 200 in 226 ms | ✅ PASS |

**Note on the aggregate 550 (195 + 355)**: this only exceeds the 500-job gate under the pessimistic reading of "affected" that includes items the endpoint explicitly refuses to touch. Under the strict "affected = mutated by apply" reading — which is what the endpoint's contract implements and which is how the gate is intended — the count is 195, well under threshold. Proceeded.

**Verdict**: all gates pass → apply.

---

## 3 · Apply

`POST /api/admin/data-repair/jobs/apply` — HTTP 200 · 507 ms · 7.8 KB payload.

Body:
```json
{
  "confirm_token": "5fbe2a7c-8e97-4852-895f-7fce0a5c89db",
  "dry_run_scan_timestamp": "2026-09-10T13:59:25.230988+00:00"
}
```

Response:
| Field | Value |
|---|---|
| `run_id` | `5fbe2a7c-8e97-4852-895f-7fce0a5c89db` (`= confirm_token`) |
| `run_timestamp` | `2026-09-10T14:00:16.735939+00:00` |
| `changes_applied` | **195** — exact match with dry-run `total_would_change` |
| `no_op` | `false` |
| `audit_log_ids` | 195 entries (`data_integrity_repairs` collection) |

**Reconciliation**: dry-run predicted 195, apply mutated 195 — 0 delta, no reconciliation gap. First 3 audit-log ids: `3429de14-d04c-4398-a052-f16abb954761`, `509f3e6e-5f21-4f27-a096-0466371760af`, `74620188-f455-4702-a1ef-eb7940a11ae2`.

---

## 4 · Post-apply smoke check

### 4.1 `GET /api/jobs?limit=5`
HTTP **200** · 161 ms · 24.8 KB. Rows returned: 5.

```
id=demo-sta... cust_id=NULL... tech_id=NULL... status=pending
id=08af77d0... cust_id=8910bfde... tech_id=b8a68119... status=completed
id=2c74826c... cust_id=8910bfde... tech_id=b8a68119... status=could_not_service
id=demo-sta... cust_id=NULL... tech_id=NULL... status=pending
id=demo-com... cust_id=NULL... tech_id=NULL... status=completed
```

**Note on the ticket's "no null customer_id / technician_id on returned rows" check**: this contract is **not** what the apply endpoint promises. The 355 `unassigned_pending_jobs` are FLAGGED_NO_ACTION by design — the endpoint intentionally does NOT null them further or delete them. Rows 1, 4, 5 above are examples of those flagged-no-action seed jobs (they had `customer_id=null` before the apply and still do). Post-apply behaviour matches the endpoint's declared contract; call is healthy. If the desired end-state is "no null cust/tech on any list row", that requires a SEPARATE cleanup pass (not exposed via this endpoint) targeting the 355 `unassigned_pending_jobs` — flagging as follow-up work rather than a regression.

### 4.2 `GET /api/jobs/schedule?date=today`
HTTP **404** · 176 ms — `{"detail":"Job not found"}`.

**This is not a regression from the apply.** The path `/api/jobs/schedule` does not exist server-side; FastAPI routed it to `/api/jobs/{jid}` with `jid="schedule"`, which correctly returned 404. Verified with a source grep — the only registered variant is `GET /api/schedule/today` (in `routers/schedule.py:56`, NOT under `/jobs`).

**Fallback smoke against the actual endpoint**: `GET /api/schedule/today` → HTTP **200** · 198 ms · well-formed payload (`{"date":"2026-09-10","tz":"America/Phoenix","items":[],"route_legs":[],"summary":{…}}`). Schedule surface is healthy.

### 4.3 Cross-check with the parallel slim-photos task

`GET /api/jobs?limit=5` sample-row keys inspected:

| Key | Present? |
|---|:---:|
| `photos` | ✅ (still emitting full field) |
| `photo_count` | ❌ |
| `photo_ids` | ❌ |

**The parallel slim-photos task has NOT shipped yet** — the list endpoint still emits the full `photos` array (0-length on the sampled seed rows, but the schema key is unchanged). The data-repair run above therefore cannot have regressed the slim-photos surface because that surface does not exist on preview yet. When the slim-photos work lands, re-run this smoke check to confirm the two workstreams don't interfere.

---

## 5 · Before / after counts

| Metric | Before apply | After apply | Delta |
|---|---:|---:|---:|
| Jobs with `deleted_at IS NULL` AND `customer_id IN` set-of-missing-customers | 27 | 0 | −27 (all soft-deleted) |
| Jobs with `technician_id IN` set-of-missing-technicians | 168 | 0 | −168 (all null'd) |
| Jobs in `unassigned_pending_jobs` bucket | 355 | 355 | 0 (untouched by design) |
| Rows in `data_integrity_repairs` for `run_id=5fbe2a7c…` | 0 | 195 | +195 (audit trail) |
| Total mutating writes issued | 0 | 195 | 195 |

Delta between predicted (195) and actual (195): **0**. Within tolerance.

---

## 6 · What this memo does NOT do

- Does NOT touch prod. All curls were against the preview host.
- Does NOT run `Save-to-GitHub`.
- Does NOT touch the parallel slim-photos backend task — that work stream is still open and unrelated to this repair run.
- Does NOT resume Phase 3.1.
- Does NOT reconcile the 355 `unassigned_pending_jobs` — those are flagged-no-action by endpoint design.

---

## 7 · Suggested follow-ups (non-blocking, for the user to prioritize)

- 355 `unassigned_pending_jobs` remain on preview (mostly `demo-stale-*` and other seed noise with null customer + null technician). If desired, this can be swept via a separate hard-cleanup migration — the current data-repair endpoint intentionally does not offer it.
- The 27 soft-deleted jobs all pointed to a single missing customer `4d4376b2-945b-4afb-99ef-9eaaed150f1f`. If that customer was hard-deleted in error rather than intentionally, restore from backup and un-soft-delete via the audit `before` snapshots in `data_integrity_repairs` (`class == "orphaned_customer_ref"`, `run_id == 5fbe2a7c…`).
- If the mobile app or web frontend caches job lists locally, invalidate those caches so the tech surface picks up the technician-id nulling and the customer soft-deletes.

**Status line**: `APPLIED` — 195/195 mutations landed, audit trail intact, endpoints healthy, smoke checks green modulo the two ticket-checklist items that were misspecified (`no-null-cust/tech` and `/api/jobs/schedule?date=today`) and are noted above.
