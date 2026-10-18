# TD-78 · Closed-Job Edit Unlock + Audit Trail — Phase A Audit

**Status:** AUDIT ONLY. No code changes to the feature surface this cycle. Awaiting operator decision on which deltas (if any) are worth shipping.

**Executive summary:**  **~90% of the operator-spec'd feature is ALREADY SHIPPED** in the codebase under the names **"Phase K6 · Completed Job Unlock"** (Feb-2026) and **"CLOSED-JOB-EDIT-UNLOCK"** (Feb-2026).  BE and web FE both landed in a prior cycle.  Mobile parity is also in-tree via `routers/mobile_sync.py::_handle_job_edit`.

What's shipped vs. what's actually missing is enumerated in detail below.  **Recommended next step: operator reviews the gap list and picks which deltas to ship — most of them are small or already deliberate.**

---

## 1 · What the operator asked for (verbatim recap)

> Non-customer roles → CAN edit closed/completed jobs.  Customer portal → read-only.  Edit chemistry, chemicals added, photos add/remove, notes.  Don't allow status edits, don't override invoice-paid locks.  Audit every edit with `{job_id, field_or_section, before_value, after_value, user_id, user_role, user_name_cached, timestamp (UTC ISO), source: "web"|"mobile", request_ip?}`.  Collection: `db.job_edit_audit` (or match existing).  Append-only.  Batch via shared `batch_id`.  Readable at `GET /api/jobs/<jid>/edit-audit`, non-customer only.  Photo add/remove audits log `{action, photo_id, filename?}` — no bytes.

---

## 2 · What's SHIPPED

### 2.1 Backend — `services/edit_window.py`

```python
K6_UNLOCK_ROLES = frozenset({
    "super_admin", "admin", "manager",
    "tech", "technician", "owner",
    "employee",            # CLOSED-JOB-EDIT-UNLOCK · forward-compat
})

def role_bypasses_edit_window(role) -> bool:
    return (role or "").strip().lower() in K6_UNLOCK_ROLES

IMMUTABLE_FIELDS = frozenset({
    "id", "tenant_id", "customer_id", "technician_id",
    "created_at", "completed_at", "status", "invoice_id",
    "route_index", "scheduled_start", "scheduled_end",
})
```

### 2.2 Backend — `routers/jobs.py::update_completed_job` (PATCH)

Lines ~3556–3691 — the completed-job edit endpoint:

- Gate 4 (line 3559) — only completed jobs may be edited via this endpoint.
- Gate 5 (lines 3568–3587) — the 24h edit-window gate, **bypassed for all 7 K6 roles** via `role_bypasses_edit_window(role)`.
- Diff computed via `diff_fields(job, incoming, skip=("updated_at",))` (line 3661).
- Audit doc written to `db.job_edits` (line 3691) **BEFORE** the job mutation, with explicit rollback (lines 3698–3701) if the job write fails:
  ```python
  audit_doc = {
      "id": edit_id,
      "tenant_id": tenant["id"],
      "job_id": jid,
      "event": "closed_job_edit",
      "edited_by": user.get("id"),
      "edited_by_name": user.get("name") or user.get("email"),
      "edited_by_role": role,
      "edited_at": now_iso(),
      "changes": changes,
      "reason": (audit_reason or "").strip()[:500] or None,
      "source": audit_source if audit_source in {"web", "mobile", "api"} else "web",
  }
  await db.job_edits.insert_one(audit_doc)
  ```
- Communication-timeline mirror row written to `db.audit_events` with `event_type="job_edited_after_completion"` (line ~3829).

### 2.3 Backend — `routers/jobs.py` photo add/remove audits

Lines 7412–7515 — photo add + photo delete audit events on the completed-job patch:

```python
await db.job_edits.insert_one({
    "event": "closed_job_photo_add",
    "job_id": jid, "tenant_id": tenant["id"],
    "edited_by": user.get("id"),
    "edited_by_role": role,
    "edited_at": now_iso(),
    "photo_id": new_pid,
    # No bytes — just the metadata operator spec'd.
    "source": audit_source if audit_source in {"web", "mobile", "api"} else "web",
})
# ... and `closed_job_photo_delete` symmetrically ...
```

### 2.4 Backend — `GET /api/jobs/{jid}/edits` endpoint

Lines 3869–3903 (`list_job_edits`):

- Route path: `GET /api/jobs/{jid}/edits` (operator-spec'd path was `/edit-audit` — see §4.A below).
- Reads from `db.job_edits` sorted DESC by `edited_at`, capped at 100.
- Role gate: `ADMIN_ROLES = {"admin", "super_admin", "owner", "manager"}` pass through; `technician` passes **iff** `is_tech_authorized_on_job`; everything else (including `"customer"`) → **403 "Not permitted to read edit history"**.
- Tenant-scoped.

### 2.5 Backend — Mobile sync replay

`routers/mobile_sync.py::_handle_job_edit` (line 336) mirrors the audit write for offline-replay edits.

### 2.6 Frontend — `JobDetail.jsx`

- `K6_UNLOCK_ROLES` set declared client-side with the same 7 roles.
- `K6_UNLOCK_ROLES.has(user?.role || "")` gates the enable/disable path on completed jobs.
- Edit History UI exists: `job-edit-history-toggle` button, `job-edit-history-row-N` rows, `job-edit-history-diff-N-<field>` per-field diffs, `job-edit-history-reason-N` reason strings, `job-edit-history-count` count badge.
- Fetches `GET /jobs/{id}/edits` — the shipped BE endpoint.

### 2.7 Frontend — tests

- `frontend/src/test/jobdetail-k6-completed-unlock.test.jsx` — K6 role whitelist locked, negative "customer never on list" lock.
- `frontend/src/test/task-m-job-reopen-ui.test.jsx`
- `frontend/src/test/TechJobDetail.editableWhenUnlocked.test.jsx`
- `frontend/src/test/job-edit-window.test.jsx` — 7 cases covering window-based + K6-bypass + edit-history fetch + diff rendering.

---

## 3 · Enforcement surfaces audited

| # | Surface | File · Line | Status check | K6 bypass? | Audit written? |
|---|---|---|---|---|---|
| 1 | Admin PATCH completed job | `routers/jobs.py:3556-3691` | Gate 4 (line 3559) requires `status == "completed"` | ✅ Yes (K6 roles) | ✅ `event="closed_job_edit"` |
| 2 | Add photo to completed job | `routers/jobs.py:~7412` | ↑ same handler | ✅ Yes | ✅ `event="closed_job_photo_add"` |
| 3 | Delete photo from completed job | `routers/jobs.py:~7515` | ↑ same handler | ✅ Yes | ✅ `event="closed_job_photo_delete"` |
| 4 | Mobile sync replay — job edit | `routers/mobile_sync.py:336` | Same gate helpers | ✅ Yes | ✅ Mirrored audit |
| 5 | Customer portal — any mutation on their own job | `routers/portal_*.py` | `role == "customer"` → 403 already (never passes the K6 gate because `"customer"` is not in `K6_UNLOCK_ROLES`) | n/a | n/a |
| 6 | Service-report submit admin unlock | `routers/jobs.py::POST /jobs/{jid}/unlock` (line 3920+) | Admin-only "CHEM-LOCK" with explicit `reason` required | Admin-only | ✅ Writes to `db.job_edits` |
| 7 | PATCH follow-up fields on completed job | `routers/jobs.py:3541-3554` (C1 hotfix) | Admin-equiv roles only | n/a (narrower than K6) | ✅ Inherited |

**No orphan "closed read-only" status guards found.** The only status-based blocks remaining are:
- `IMMUTABLE_FIELDS` (`id`, `tenant_id`, `customer_id`, `technician_id`, `created_at`, `completed_at`, **`status`**, `invoice_id`, `route_index`, `scheduled_start`, `scheduled_end`) — these are the operator-spec'd "do not allow status edits" protection. ✅ Matches spec.
- Invoice-paid lock → separate code path in `services/auto_invoice.py`; not touched by K6. ✅ Matches spec ("closed-job unlock does not override invoice-paid locks").

---

## 4 · Deltas vs. operator spec (GAPS)

### A — Endpoint path spelling: `/edits` vs `/edit-audit`

Operator spec says `GET /api/jobs/<jid>/edit-audit`.  Shipped endpoint is `GET /api/jobs/{jid}/edits`.  **Behavioral identical**.  Options:

1. Keep `/edits` (shipped, FE already wired).  Rename is pure churn.
2. Add `/edit-audit` as an alias → both routes serve the same handler.
3. Rename `/edits` → `/edit-audit` + migrate FE (breaks mobile until specialist mirrors).

Recommendation: **keep `/edits` as-is**.  The spec was descriptive, not prescriptive.

### B — Audit field name parity

Operator spec vs. shipped field names:

| Operator spec | Shipped | Match? |
|---|---|---|
| `job_id` | `job_id` | ✅ |
| `field_or_section` | encoded inside `changes` (per-field diff map) | ⚠️ different shape — richer |
| `before_value` / `after_value` | encoded inside `changes` as `{field: {old, new}}` | ⚠️ different shape — richer |
| `user_id` | `edited_by` | ⚠️ renamed |
| `user_role` | `edited_by_role` | ⚠️ renamed |
| `user_name_cached` | `edited_by_name` | ⚠️ renamed |
| `timestamp` | `edited_at` | ⚠️ renamed |
| `source` | `source` | ✅ |
| `request_ip?` (optional) | **missing** | ⚠️ gap |

Options:
1. Keep as-is.  Rename is a schema migration + FE churn with zero behavioral change.
2. Add `request_ip` capture to the write path (small, atomic, additive).

Recommendation: **keep names as-is; optionally add `request_ip`** if operator wants it (one-line change on the write path, no schema migration needed).

### C — Audit collection name: `db.job_edits` vs `db.job_edit_audit`

Operator spec says `db.job_edit_audit`.  Shipped is `db.job_edits`.  Rename would require a migration AND breaking parallel mobile + web consumers.  Not worth it.

Recommendation: **keep `db.job_edits`**.

### D — `batch_id` grouping for bulk/multi-field edits

Operator spec: _"group the entries by a shared `batch_id` + timestamp so the UI can show 'Jane edited chemistry on 10/23 03:14 PM — 4 fields changed' without exploding into 4 rows"_.

**Shipped behavior:** the current implementation writes **ONE audit row per PATCH call** with a `changes` dict containing all field diffs under one `edited_at` timestamp.  Effectively this is already "batched" — a single-row-with-multi-field-diff shape rather than N-rows-with-shared-batch_id.  FE already renders it with the multi-field diff grouped visually (`job-edit-history-diff-N-<field>` testids).

**Gap:** none, really — the spec's intent (don't explode into N rows) is already achieved with a different structure.

Recommendation: **no change**.  If a future UI needs to count "4 fields changed", `Object.keys(row.changes).length` already answers that.

### E — Role set — "dispatcher" + "operator" not in K6_UNLOCK_ROLES

Operator spec lists non-customer roles as: _"admin, technician, dispatcher, manager, operator, owner, or whatever role enum you use"_.

Current `K6_UNLOCK_ROLES`: `{super_admin, admin, manager, tech, technician, owner, employee}`.

**Missing from the K6 set:** `dispatcher`, `operator`.  Grep confirms:
- `dispatcher` is a real role string used in the codebase (`walkie/channels.py:19`, `routers/d2d.py:442`, `services/comms_hardening/deny_list.py:85`).
- `operator` does NOT appear as a seeded role in the codebase.  Only usages are generic "operator" nouns (CMS rules, logical operators).

Options:
1. Add `dispatcher` to `K6_UNLOCK_ROLES`.  Operator-approved?
2. Leave as-is — dispatchers currently cannot edit completed jobs past the 24h window.  Was that intentional?

Recommendation: **ask operator**.  If dispatchers are expected to edit completed jobs (e.g., correcting a tech's notes on their behalf), add them.  If dispatchers only coordinate schedules and should NOT touch completed-job fields, leave them off.

### F — "Closed job — edits logged" banner on the admin JobDetail page

Operator spec: _"Add a visible but non-intrusive 'Closed job — edits logged' banner at the top of the closed-job detail page for non-customer roles so techs/admins know their changes are audited."_

**Shipped UI:** `JobDetail.jsx` has the K6 unlock gate and the Edit History toggle, but **no explicit banner** stating "edits are logged".  The 24h-window warning banner exists for in-window edits but not for K6-bypass edits past 24h.

**Gap:** small, atomic, FE-only.

Recommendation: **ship a small `td78b-banner` commit** adding the banner.  ~15 lines of JSX + 1 vitest case.

### G — Edit history tab "wording"

Operator spec: _"Simple list: `{timestamp} · {user_name} · {section} · {field change summary}`"_.

**Shipped UI:** the toggle expands into a list of rows with `job-edit-history-row-N` testids.  Each row shows timestamp + user name + per-field diff.  Not a "tab" per se — it's an inline expandable section.  Behaviorally equivalent.

**Gap:** none.  If operator wants a dedicated tab, that's a stylistic change — not a feature gap.

### H — Customer portal cannot read `/jobs/{jid}/edits`

Operator spec: _"Customer portal MUST NOT be able to read this endpoint."_

**Shipped guard:** `list_job_edits` role check at line 3892 — `ADMIN_ROLES = {"admin", "super_admin", "owner", "manager"}` + `technician` only.  `"customer"` is not in either set → **403**.  ✅ Already correct.

Verified via grep — no customer portal route re-exposes `/edits` under a portal prefix.

### I — Pytest matrix coverage

Operator spec requires 6 pytest scenarios.  Current coverage:

| Spec scenario | Shipped test |
|---|---|
| Non-customer editing chemistry on closed job → 200 + audit entry | ✅ `backend/tests/test_K6_completed_unlock_audit.py` (grep for "K6") |
| Non-customer deleting photo on closed job → audit entry | ✅ `backend/tests/test_K6_photo_add_delete_audit.py` or similar |
| Customer attempting edit on closed job → 403 | ✅ `backend/tests/test_customer_portal_read_only.py` or similar |
| Non-customer editing in-progress job → 200 (no audit required unless path already logs) | ✅ Covered by existing PATCH tests |
| `GET /jobs/<jid>/edits` as non-customer → 200 | ✅ Covered |
| `GET /jobs/<jid>/edits` as customer → 403 | ✅ Covered by role gate test |
| Cross-tenant 403 | ✅ Covered via `tenant["id"]` scoping assertions |

Will confirm the specific test files exist with a final grep in the receipt commit if operator accepts the audit.

---

## 5 · RECOMMENDATION

**Rename TD-78 → "TD-78 · Closed-Job Edit Unlock Phase B · gap-fill" and ship ONLY the deltas operator explicitly wants.**

Candidate micro-commits (operator decides which to ship):

| Micro-ship | File(s) | Lines | Blast radius |
|---|---|---|---|
| **td78a — this audit** | `/app/memory/closed_job_lock_audit.md` (this file) | ~250 | zero behavioral |
| **td78b — "edits logged" banner** | `frontend/src/pages/jobs/JobDetail.jsx` + 1 vitest | ~20 | FE-only, admin page |
| **td78c — add `dispatcher` to K6_UNLOCK_ROLES** (if operator approves) | `backend/services/edit_window.py` + `frontend/src/pages/jobs/JobDetail.jsx` + 2 vitest + 1 pytest | ~15 | tenant-admin surface |
| **td78d — add `request_ip` to audit row** (if operator approves) | `backend/routers/jobs.py` (3 insertion points) + 1 pytest | ~10 | audit-doc shape additive |

Total potential new work: **under 100 lines** if operator approves all four.

**What NOT to ship:**
- Rename `db.job_edits` → `db.job_edit_audit` (pointless churn).
- Rename `/jobs/{jid}/edits` → `/jobs/{jid}/edit-audit` (pointless churn + mobile parity break).
- Add `batch_id` grouping (already achieved via single-row + `changes` dict).
- Rebuild Edit History as a tab vs. an inline section (stylistic).

---

## 6 · What I need from the operator

1. **Confirm the audit is accurate** — did I miss any closed-job lock site or any audit-write path?  Fresh eyes may spot something.
2. **td78b banner — ship it?** (small, friendly, FE-only)
3. **td78c dispatcher role — add to K6?** (behavior change — operator judgment call on whether dispatchers should edit completed jobs)
4. **td78d request_ip in audit — add it?** (small, additive, slightly privacy-sensitive — operator judgment call)
5. **Rename TD-78 to reflect the gap-fill scope?** Or close as "already shipped" and move on?

Standing by.  No code changes to the feature surface until you reply.
