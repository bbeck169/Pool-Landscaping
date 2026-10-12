# Recurring-Jobs Audit — Context-Loss-Resilient State of Work

> **Breadcrumb:** `RECURRING-JOBS SAFETY NET`
> Grep this token across the repo to find all wiring sites + the shared service.
> Last updated: Feb-2026 session, right before Commits 3-6 (polish + safety net).

---

## 1. Admin backfill endpoint chain — 4 commit hashes + `git show --stat`

### `22164d562` — Commit A — shared service refactor

```
refactor(recurring-jobs-backfill): extract shared service — CLI becomes thin wrapper

 backend/scripts/backfill_recurring_jobs_window.py | 228 ++++--------------
 backend/services/recurring_jobs_backfill.py       | 275 ++++++++++++++++++++++
 2 files changed, 316 insertions(+), 187 deletions(-)
```

### `ea54df36b` — Commit B — admin endpoint

```
feat(admin): POST /api/admin/recurring-jobs/backfill-horizon — super-admin horizon backfill endpoint

 backend/routers/admin_recurring_jobs_backfill.py | 205 +++++++++++++++++++++++
 backend/server.py                                |   7 +
 2 files changed, 212 insertions(+)
```

### `9593a8450` — Commit C — pytest suite (12/12 passed)

```
test(admin-recurring-backfill): endpoint coverage — auth, idempotency, tenant-scope, partial-failure

 .../test_admin_recurring_jobs_backfill_endpoint.py | 259 +++++++++++++++++++++
 1 file changed, 259 insertions(+)
```

### `8e691ea4f` — prod runbook addendum

```
docs(recurring-backfill): add §7 — prod backfill via admin HTTP endpoint (no-shell fallback)

 backend/scripts/README_backfill_recurring_jobs.md | 105 ++++++++++++++++++++++
 1 file changed, 105 insertions(+)
```

---

## 2. Cron fix — commit hash + `git show --stat`

### `54af96872` — primary fix

```
fix(recurring-jobs-cron): advance cursor only on provable progress

 backend/routers/recurring_jobs.py | 58 ++++++++++++++++++++++++++++++++++-----
 1 file changed, 51 insertions(+), 7 deletions(-)
```

---

## 3. Backfill script location — full paths

- `/app/backend/scripts/backfill_recurring_jobs_window.py` — CLI thin wrapper
- `/app/backend/scripts/README_backfill_recurring_jobs.md` — runbook (sections 1–6 CLI + §7 admin HTTP endpoint)

---

## 4. Shared service module — public API signatures

Source: `/app/backend/services/recurring_jobs_backfill.py`

```python
async def run_horizon_backfill(
    *,
    days_ahead: int = 14,
    commit: bool = False,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Idempotent hole-plug sweep across the rolling horizon.

    Returns summary dict:
      mode, today, horizon, days_ahead, tenant_scope,
      templates_processed, expected_dates_total, already_present,
      missing, soft_deleted_present, inserted, race_dedup,
      insert_errors, errored_templates, warnings, per_template_detail.
    Never raises for template-level or per-date failures — those
    are captured in errored_templates and warnings.
    """
```

(New in Commit 5: `materialize_next_from_completed_job(...)` — signature in §9.)

---

## 5. Admin endpoint route + source

- **Route:** `POST /api/admin/recurring-jobs/backfill-horizon`
- **operation_id:** `admin.recurring_jobs.backfill_horizon`
- **Auth:** `require_super_admin` (403 for admin / manager / technician / customer)
- **Body:** `{days_ahead: int [1,30] default 14, dry_run: bool default true, tenant_id: Optional[str] default null}`
- **Source:** `/app/backend/routers/admin_recurring_jobs_backfill.py`
- **Register:** `backend/server.py` next to the existing `_rec_backfill` include.
- **Audit:** writes two rows to `db.audit_logs` per invocation (`.invoke` + `.complete`) with actor, payload, result, success, error.

---

## 6. Infinite-recurrence feature evidence

### Introducing commit: `8e42a1b7f` (prior session)

### Backend model — `backend/routers/recurring_jobs.py:50, 78-84, 126`

```
50:    end_date: Optional[str] = None
79:    # Feb-2026 · Never-end recurrence. When True, `end_date` is forced
80:    # to None on save so `_next_occurrences` walks unbounded (capped
83:    # Explicit intent flag so the UI can render a distinct "runs until
84:    recurrence_never_ends: bool = False
126:    end_date: Optional[str] = None
```

### Walker null-handling — `backend/routers/recurring_jobs.py:296-313`

```python
def _next_occurrences(tpl: Dict[str, Any], anchor: date,
                        horizon_end: date, max_count: int = 60) -> List[date]:
    """Return every occurrence date strictly ≥ anchor and ≤ horizon_end
    that satisfies the template's frequency rules. Sunday is skipped by
    default unless `allow_sunday` is True. Respects `end_date`."""
    start = _parse_date(tpl.get("start_date")) or anchor
    end_date = _parse_date(tpl.get("end_date"))
    allow_sunday = bool(tpl.get("allow_sunday"))
    freq = tpl.get("frequency")
    dow = tpl.get("day_of_week")
    dom = tpl.get("day_of_month")
    interval = int(tpl.get("interval_days") or 7)

    # Anchor the walk: never before `start_date`.
    walker = max(start, anchor)
    if end_date and walker > end_date:
        return []
    hard_stop = min(horizon_end, end_date) if end_date else horizon_end
```

Classification: `end_date=None` → walker uses `horizon_end` as sole cap. No short-circuit, no exception.

### Frontend form toggle — `frontend/src/pages/admin/RecurringJobs.jsx`

```
479: setEditing({ frequency: "weekly", day_of_week: 0, start_date: todayIso(), price_cents: 12000, active: true, is_active: false, notes: "", recurrence_never_ends: true, end_date: null });
491-495:  const neverEnds = row.recurrence_never_ends === true
              || (row.recurrence_never_ends == null && !row.end_date);
          setEditing({ ...row, recurrence_never_ends: neverEnds });
614-618:  const payload = { ...editing, price_cents: priceCents };
          if (payload.recurrence_never_ends) payload.end_date = null;
2050-2107: Radio fieldset with data-testid="recurring-jobs-ends-never" and
            data-testid="recurring-jobs-ends-on-date".
```

### Mobile form toggle — `mobile/app/finance/recurring-jobs.tsx` (read-only, not modified this sprint)

```
43:  end_date?: string | null;
48:  recurrence_never_ends?: boolean;
292-293: recurrence_never_ends: true, end_date: null,
302-304: const neverEnds = row.recurrence_never_ends === true
             || (row.recurrence_never_ends == null && !row.end_date);
          setEditing({ ...row, recurrence_never_ends: neverEnds, ... });
318: // Same exclusivity rule as web — Never wins, end_date is nulled.
774-795: Radio toggle UI block ("Never" / "On date" labels).
```

### Backward-compat data distribution (preview DB)

| Field state                              | Count |
| ---------------------------------------- | ----- |
| Total templates                          | 218   |
| `end_date=null`                          | 217   |
| `end_date` field missing                 | 5     |
| `recurrence_never_ends=true`             | 174   |
| `end_date=string (any date)`             | 1     |
| `end_date` starts `2099` (sentinel?)     | 0     |

No sentinel-date pattern in use. Null is the canonical infinite marker.

---

## 7. On-complete safety-net — three fire sites

### Site 1 — `backend/routers/jobs.py:2962` (PUT /jobs/{jid})

```python
                    "job": {**job, **update},
                    "correlation_id": f"{jid}:scheduled:{new_sched}",
                },
            )
        # job_completed — status flip to completed.
        if cur_status == "completed" and prev_status != "completed":
            await emit_event(
                event="job_completed",
                tenant_id=tenant["id"],
                entity_id=jid,
                customer_id=job.get("customer_id"),
                payload_extras={
                    "job": {**job, **update},
                    "correlation_id": f"{jid}:completed",
                },
            )
```

Rationale: primary PUT handler that stamps completion fields and fires `job_completed`. The `if cur_status=="completed" and prev_status!="completed"` guard already defines the terminal-transition moment.

### Site 2 — `backend/routers/service_reports.py:1127` (submit path)

```python
        ) from _snap_e
    # ── /P0 · Chemical snapshot BEFORE status flip ───────────────

    await db.jobs.update_one(
        {"id": jid, "tenant_id": tenant["id"]},
        {"$set": _stop_updates,
         # CHEM-LOCK · Feb-2026 — auto-relock on resubmit. Clear
         # the admin-unlock stamps so the job returns to the
         # "submitted and locked" state; the SR's ``submitted_at``
         # (just set by the P45 claim gate) IS the lock.
         "$unset": {"unlocked_at": "", "unlocked_by": "",
                    "unlocked_by_email": "", "unlocked_reason": ""}},
    )
```

Rationale: field-tech "submit service report" is the production hot-path for closing a job. `_stop_updates` set at line 974 includes `status="completed"`. `_prev_status` captured at 970 enables the transition guard.

**Site 2 idempotency decision — option (a):** rely on the helper's internal `(tenant_id, recurring_template_id, scheduled_date)` dedupe. No explicit guard at Site 2. (Human decision this sprint.)

### Site 3 — `backend/routers/mobile_sync.py:166` (offline replay)

```python
    completed_at_val = op.payload.get("completed_at") or now_iso()
    await db.jobs.update_one(
        {"id": op.entity_id, "tenant_id": tenant_id},
        {"$set": {"status": "completed",
                    "completed_at": completed_at_val,
                    "last_synced_at": now_iso(),
                    "client_op_id": op.client_op_id,
                    "updated_at": now_iso()}},
    )
```

Rationale: mobile offline-sync replay of a tech-closed job. `_prev_status` captured at 141; guarded by `if _prev_status != "completed":` at 147.

---

## 8. "No-fire" sites (cap at 5)

### `backend/routers/jobs.py:2327` — PUT `/jobs/{jid}/field-report`
```python
        await db.jobs.update_one({"id": jid, "tenant_id": tenant["id"]}, {"$set": update})
```
Rationale: field-report partial update. `FieldReportUpdate` body shape does NOT include `status`. Not a terminal flip.

### `backend/routers/jobs.py:2795` — timer-stop nested update inside PUT 2790 block
```python
                await db.jobs.update_one({"id": jid, "tenant_id": tenant["id"]}, {"$set": {
                    ... timer fields only ...
                }})
```
Rationale: side-effect of Site 1's parent transition. Firing here would double-trigger.

### `backend/routers/jobs.py:3448` — PATCH `/jobs/{jid}` edit-window
Rationale: 24h-post-completion edit path. `services/edit_window.py` lists `status` in `IMMUTABLE_FIELDS`. Cannot flip status.

### `backend/routers/jobs.py:4043, 4167, 4845` — soft-delete / reopen / timer control
Rationale: write status to values other than `completed`, or write non-status fields on already-completed jobs.

### Non-`jobs` collection writes (dropped batch)
~15 sites in `workstream_service_log.py`, `tenants.py`, `mass_messaging.py`, `analytics.py`, `marketing_sequences.py`, `sequences.py`, `churn.py`, `customer_ai.py`, `business_os.py`, `crew_productivity.py` write `status="completed"` to **non-`jobs` collections** (marketing sends, sequences, segments). Grep-filtered out; not jobs transitions.

---

## 9. Helper function signature

Source (will be added in Commit 5): `/app/backend/services/recurring_jobs_backfill.py`

```python
async def materialize_next_from_completed_job(
    *,
    job: Dict[str, Any],
    tenant_id: str,
    actor_user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Safety-net: on job completion, insert the next expected
    occurrence for the parent recurring template if the nightly
    cron hasn't already materialized it.

    Preconditions (early returns, each returns None):
      1. ``job.get("recurring_template_id")`` is None → no-op (non-recurring)
      2. Parent template not found in db.recurring_job_templates → no-op
      3. Template is paused (``is_active=False`` or legacy ``active=False``)
         → no-op
      4. ``_next_occurrences(tpl, anchor=job.scheduled_date + 1 day,
         horizon_end=today + 14 days, max_count=1)`` returns empty
         → no-op (walker says nothing scheduled in horizon — likely
         past end_date on a bounded template)
      5. Idempotency check — a job already exists for
         ``{tenant_id, recurring_template_id, scheduled_date}``
         (NOT soft-deleted) → no-op (cron already did it)

    On commit path: insert a single job with the same shape the
    cron materializer uses (title, service_type, customer_name,
    address, resolved property, price_dollars, status=scheduled,
    recurring_template_id, created_at, backfilled_by marker).

    Logger output (structured, matches operator triage format):
      recurring_job.on_complete_safety_net.triggered
          tenant=<id> parent_job=<id> template=<id>
          next_date=<iso> inserted_job=<id>

    Caller contract — safety-net failures MUST NOT block the
    parent "mark complete" HTTP call. Caller wraps in try/except
    and emits recurring_job.on_complete_safety_net.failed WARN
    (not re-raised).

    Returns: the inserted job dict on success, None if any
    precondition short-circuited.
    """
```

Idempotency Mongo query (step 5):
```python
await db.jobs.find_one(
    {"tenant_id": tenant_id,
     "recurring_template_id": template_id,
     "scheduled_date": next_date_iso,
     "deleted_at": {"$exists": False}},
    {"_id": 0, "id": 1},
)
```

---

## 10. Pytest plan — 4 cases (final)

File (new in Commit 6): `/app/backend/tests/test_recurring_on_complete_safety_net.py`

1. `test_safety_net_fires_when_cron_missed_next_occurrence` — construct a completed job tied to a template with the next expected date NOT yet in `db.jobs`; call helper; assert exactly one new job inserted at the walker's next date.
2. `test_safety_net_noop_when_cron_already_materialized` — pre-seed the next expected job; call helper; assert `find_one` returns the helper's `None` short-circuit path and no duplicate inserted.
3. `test_safety_net_noop_when_template_paused` — mark the parent template `is_active=False`; call helper; assert no insert.
4. `test_safety_net_noop_when_job_has_no_recurring_template_id` — call helper on a non-recurring job (template_id=None); assert immediate `None` return, no DB reads beyond the guard.

(Walker regression tests landed separately in Commit 4 under `test_recurring_walker_unbounded.py` — 3 cases there: null end_date emits through full horizon; horizon_end as sole cap; `is_active=False` filter respected pre-walker.)
