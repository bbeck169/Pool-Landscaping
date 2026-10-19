# TD-86 · Crew member picker cross-tenant leakage — audit

**Date:** 2026-02-18
**Scope:** Admin OpsHub `Crews` tab — crew member picker + crew save endpoint + stored data drift.
**Phase:** AUDIT ONLY (no fix code). Awaiting operator approval of the proposed commit plan before any ship.

**Operator-reported symptom (verbatim):** saving a crew throws `tech_ids references members not in this tenant`; the crew member picker is displaying technicians from a different tenant in the members list.

---

## 1 · FE picker call-site

**Component:** `frontend/src/pages/ops/OpsHub.jsx` — the `Crews` tab (functional component `Crews`, line ~550).

**Tech-list query (line 556):**

```jsx
const [techs] = useList("/technicians");
```

Plain `useList` hook which issues `GET /api/technicians` with the standard `api` wrapper. The wrapper attaches:
- `Authorization: Bearer <jwt>` (always).
- `X-Tenant-Slug: <localStorage.tenant_slug>` (if set).

**Picker render (line 644-673):** iterates `(techs || []).map((t) => ...)` and emits a toggle button per tech with `data-testid={crew-tech-${t.id}}`. The `form.tech_ids` array is seeded from `c.tech_ids` on edit (line 568: `openEdit(c) → setForm({...tech_ids: c.tech_ids || []})`) — this means **any stale/orphan tech_id already stored on the crew doc stays in form state even if it doesn't appear in the picker's render loop** (orphan tech_ids are invisible but still submitted on save).

**Explicit tenant filter on client side?** No. Delegated entirely to the BE scoping.

---

## 2 · BE `/api/technicians` endpoint

**File:** `backend/routers/technicians.py:22-187`.

**Tenant resolution:** `tenant: dict = Depends(get_current_tenant)` → the shared `routers/tenants.py:124 get_current_tenant` helper. Resolution order:
  1. JWT-signed `_active_tenant_id_claim` → `token_active_tenant_id` (multi-tenant users).
  2. Super-admin only: `X-Tenant-Slug` header.
  3. User doc's own `tenant_id` (default for every non-super role).
  4. Anonymous header fallback.
  5. Default tenant.

**Tenant filter on query:** Yes. Both branches of the union are gated:
  * **Real tech rows** (line 73-78): `db.technicians.find({"tenant_id": tid, deleted_at∉<>})`.
  * **Synthesized user rows** (line 92-108): `db.users.find({"tenant_id": tid, "role": IN(ASSIGNABLE_ROLES), active=True, not soft-deleted})`.

**Live preview probe:**
  - `admin@aquaterra.com` → tenant resolves to `affdfbfa-...` → `/api/technicians` returns 17 rows, 100% `tenant_id == affdfbfa-...`. No cross-tenant leak visible for a non-super-admin.
  - `super@aquaterra.com` (super_admin) → tenant also resolves to `affdfbfa-...` (user's own tenant, no `X-Tenant-Slug` sent) → 17 rows, same result.

**Cross-tenant leak surface:** only reachable via **super_admin + explicit `X-Tenant-Slug` override** OR via a stale `_active_tenant_id_claim` JWT. Not reachable by a normal admin.

---

## 3 · BE crew save endpoints

### `POST /api/crews` (create) — `backend/routers/ops.py:97-118`

**No tenant guard on `tech_ids`.** The handler stamps `tenant_id: tenant["id"]` on the new doc and inserts it verbatim. If the FE sends a `tech_ids` array containing a foreign tenant's id (or an orphan id), it lands in Mongo unchallenged.

**This is a gap.** The 400 that the operator sees only fires on PATCH, not on POST.

### `PATCH /api/crews/{cid}` (update) — `backend/routers/ops.py:121-207`

**Tenant guard at line 175-199:**

```python
if normalised:
    tid = tenant["id"]
    resolved = set()
    async for u in db.users.find(
        {"tenant_id": tid, "id": {"$in": normalised}}, {"_id": 0, "id": 1},
    ):
        resolved.add(u["id"])
    if len(resolved) < len(normalised):
        async for t in db.technicians.find(
            {"tenant_id": tid, "id": {"$in": normalised}}, {"_id": 0, "id": 1},
        ):
            resolved.add(t["id"])
    missing = [x for x in normalised if x not in resolved]
    if missing:
        raise HTTPException(
            400,
            "tech_ids references members not in this tenant: "
            f"{missing}",
        )
```

**Behavior:** any id not present in current-tenant `users` OR `technicians` → 400.

**Error message is misleading.** The guard treats "exists in another tenant" and "doesn't exist anywhere" identically — both end up in `missing` and produce the same `references members not in this tenant` payload. The preview-DB evidence (section 4 below) shows the actual drift on preview is 100% orphan ids (hard-deleted techs), not foreign-tenant ids.

**Missing details on the 400:**
  - No `field` key to help the FE pinpoint the problem.
  - No distinction between `not_in_tenant` vs `does_not_exist` reasons.
  - No per-id categorisation (if some ids are cross-tenant and others are orphan, the message lumps them together).

---

## 4 · Stored data drift (preview DB probe)

Probe script `/tmp/td86_probe.py` scanned every crew doc, resolved each `tech_ids` entry against the owning tenant's `users` + `technicians` sets, and categorised each stale id by its actual origin.

### Grand totals

| Metric | Value |
|---|---|
| Total crews in preview DB | **2** |
| Crews with cross-tenant / orphan `tech_ids` | **2** (100%) |
| `tech_ids` that would be pruned | **4** |
| Crews with missing `tenant_id` | 0 |

### Per-tenant breakdown

| Tenant | Crews with drift | tech_ids pruned | Foreign-tenant origins seen |
|---|---|---|---|
| `affdfbfa-...` (Pool & Landscaping of Vistancia) | 2 | 4 | **`UNKNOWN`** (0 found in any tenant's users/techs) |

### Example drift rows

```
crew "Blue Crew"  (id 10851a3d-...) → tech_ids [b8a68119, cc683510]
  b8a68119-7dc6-46dd-9e24-447ca230bfde → UNKNOWN (not in users, not in technicians, any tenant)
  cc683510-b8f9-4762-b571-d1b389be8080 → UNKNOWN

crew "Green Crew" (id 1c1ec59e-...) → tech_ids [30996ed1, 3b6ebe3c]
  30996ed1-8e06-4511-9497-591c128e5bc7 → UNKNOWN
  3b6ebe3c-fa87-4dec-a5db-7a55a86cfc7c → UNKNOWN
```

**Confirmed by direct `find_one`:** none of these 4 ids exist in `db.users` or `db.technicians` anywhere in the preview DB. They are **fully orphan** — the referenced tech rows were hard-deleted (likely via `/admin/technicians/{tid}/hard-delete`) but the crew docs retained the stale ids.

**Zero cross-tenant drift observed on preview.** The operator's description of "cross-tenant" techs is a diagnostic misinterpretation of the misleading 400 payload (section 3) — the actual drift is 100% orphan ids, not foreign-tenant ids.

Prod may still have genuine cross-tenant drift (users migrated between tenants pre-guard, super_admin saves that bypassed scope, etc.) — the audit scope was preview only, as per operator dispatch. The fix must handle BOTH shapes (foreign-tenant AND orphan) because they are indistinguishable to the BE guard today and will co-exist in prod.

---

## 5 · Root cause hypothesis

**Primary cause (confirmed on preview):**
  * **(d) BE accepted stale `tech_ids` historically → tech rows later hard-deleted → crew docs now carry orphan ids** that the current guard flags as "not in this tenant".
  * The FE picker edit flow seeds `form.tech_ids = c.tech_ids` directly, so orphan ids stay in form state EVEN THOUGH the picker UI only renders current-tenant techs. The operator cannot deselect the orphans from the picker because they are invisible, and saving carries them straight into the guard which rejects.

**Secondary cause (confirmed on code read, latent on preview):**
  * **(d) `POST /api/crews` has no tenant-isolation guard on `tech_ids`.** Only `PATCH` has it. A write path that admits whatever ids the FE sends into the doc is the mechanism that allowed the stale ids to land in the first place; it will re-admit cross-tenant / orphan ids on any new crew.

**Possible secondary cause (not reproducible on preview admin user):**
  * **(e) Super_admin with an explicit `X-Tenant-Slug` override OR a stale `_active_tenant_id_claim` JWT** could see a different tenant's technicians via `/api/technicians`. The `get_current_tenant` resolver honours both signals and both resolve BEFORE the user's own `tenant_id`. This is the only path by which the picker could legitimately show cross-tenant techs — and only for the super_admin role.

**Ruled out:**
  * **(a)** FE picker calls a non-tenant-scoped endpoint — ruled out (only hits `/api/technicians`).
  * **(b)** FE picker uses the right endpoint with no / wrong tenant filter — ruled out (api.js wrapper + get_current_tenant resolve to user's own tenant for every non-super role).
  * **(c)** BE tech-list endpoint ignores a legitimate tenant filter — ruled out (both branches filter by `tenant_id`).

---

## 6 · Fix strategy proposal — 3 atomic commits

### `td86-be-guard` — BE guard on crew save (both POST and PATCH)

**Scope:**
  * **`POST /api/crews` (`create_crew`):** add the same tenant-isolation guard that `PATCH` already has. Reject on write with a clean 400 before the `insert_one`. Prevents new orphan / cross-tenant drift at the source.
  * **`PATCH /api/crews/{cid}` (`update_crew`):** keep the existing guard but improve the 400 payload shape so FE + operator can diagnose:
    ```json
    {
      "detail": "tech_ids references ids not present in this tenant",
      "field": "tech_ids",
      "invalid_tech_ids": ["...","..."],
      "reasons": {
        "<id>": "orphan"  // or "foreign_tenant"
      }
    }
    ```
    The guard categorises each `missing` id by probing a cross-tenant lookup; found elsewhere → `foreign_tenant`, not found at all → `orphan`.
  * **Both handlers:** extract the shared predicate into a `_resolve_tenant_members(db, tid, ids)` helper on `routers/ops.py` (or a new `services/crew_tenant_predicate.py` depending on blast radius) so both call-sites share one source of truth.

**Pytest matrix (per operator spec):**
  * Save crew with all-same-tenant ids → 200.
  * Save crew with any cross-tenant id → 400 with the enriched payload (field, invalid_tech_ids, reasons.id = `foreign_tenant`).
  * Save crew with orphan id (not in any tenant) → 400 with reasons.id = `orphan`.
  * Save crew with mixed cross-tenant + orphan ids → 400, both categorised correctly.
  * Save crew with duplicate ids (same tenant) → 200, deduped.
  * `POST /api/crews` with cross-tenant id → 400 (previously would have been accepted).
  * Super-admin flows constrained to the resolved `tenant["id"]` from `get_current_tenant`.

### `td86-fe-scope` — Crew picker FE scope + stale-id visibility

**Scope:**
  * `frontend/src/pages/ops/OpsHub.jsx` Crews tab:
    * Defensive filter on the picker render: `(techs || []).filter(t => !t.tenant_id || t.tenant_id === currentTenantId).map(...)` — stays no-op in the common case where BE is scoped correctly, but blocks the super-admin cross-tenant override case from leaking into the save path.
    * On `openEdit(c)`: filter `c.tech_ids` to only ids present in the current-tenant `techs` list before seeding form state. Orphan + cross-tenant ids are dropped from the form so they aren't re-submitted on save. Surface a small inline warning banner inside the modal when `c.tech_ids.length !== form.tech_ids.length` ("N member(s) were removed because they're no longer in this tenant").
  * Needs access to `currentTenantId` — either from a context hook or by passing it in. Check `frontend/src/api.js` + any auth context for an existing accessor.

**Vitest matrix:**
  * Picker only renders techs where `t.tenant_id === currentTenantId` (or `tenant_id` missing).
  * Defensive filter stays in place even when the BE accidentally returns a cross-tenant row.
  * `openEdit` prunes orphan ids on form seed + surfaces the warning banner.
  * Snapshot of the picker rendered against a two-tenant fixture (only current-tenant techs visible).

### `td86-cleanup` — one-shot migration script

**Scope:** `backend/scripts/cleanup_crew_cross_tenant_tech_ids.py`.

Mirrors the TD-76-aux `cleanup_dead_photo_rows.py` pattern:
  * `--dry-run` default; `--apply` opt-in flag.
  * Optional `--tenant <id>` to scope to a single tenant.
  * Per-tenant counters: crews scanned / crews with drift / tech_ids pruned (categorised as `foreign_tenant` vs `orphan`) / docs failed.
  * Writes `/app/memory/td86_crew_cleanup.md` with run summary.

**Pytest matrix:**
  * Predicate correctly classifies foreign-tenant ids as `foreign_tenant`.
  * Predicate correctly classifies orphan ids as `orphan`.
  * Clean docs are untouched.
  * Re-run after `--apply` is idempotent (counts drop to 0).
  * `--tenant` scope filters correctly.

**Run plan:** `--dry-run` only this cycle. Operator will greenlight `--apply` after review.

---

## 7 · Risk map — downstream consumers of crew `tech_ids`

| Consumer | File | Dependency on `tech_ids` | Impact of pruning orphans |
|---|---|---|---|
| Crew timeclock aggregate (whole-crew clock-in/out) | `routers/ops.py` (crew-timesheet handlers) | Reads `c.tech_ids` to fan out time entries | None — orphan ids never clocked in/out (users deleted) |
| Dispatch board | `routers/dispatch_board.py`, `routers/schedule.py` | Reads crew members for route planning | None — orphans don't appear on routes |
| Live tech map | `pages/dispatch/*.jsx` | Reads crew color + members for pin render | None — orphans produce no pins |
| Recurring jobs | `routers/recurring_jobs.py` | Reads crew members for auto-assignment | None — orphan assignments would fail downstream validations anyway |
| Workstream feed | `routers/workstream.py` | Reads crew membership for admin surfaces | None — orphan ids resolve to no name, already hidden |
| F1 crew-aware authz (tech can act on crew jobs) | `services/authz.py::is_tech_authorized_on_job` | Membership check uses `c.tech_ids` | None — orphan tech can't log in (hard-deleted) |
| Member-added-at map | `routers/ops.py::_crew_member_added_at_map` | Keyed by `tech_ids` | **Cleanup must also prune the corresponding `member_added_at[<id>]` keys** to keep the two shapes in sync. |

**Zero flows observed will be orphaned** by pruning stale ids from crew `tech_ids`. The `member_added_at` sister-map must be pruned in lock-step by the cleanup script (added to the ship plan).

---

## 8 · Commit plan summary (for operator approval)

| # | Commit | File-set | LOC | Risk |
|---|---|---|---|---|
| 1 | `td86-be-guard · crew save · reject cross-tenant/orphan tech_ids with categorised 400` | `backend/routers/ops.py` + new pytest file | ~80 LOC | **Low.** Only enriches an already-existing guard + adds a mirror guard to POST. No semantic change for valid saves. |
| 2 | `td86-fe-scope · crew member picker · tenant-scoped tech list + orphan prune on edit seed` | `frontend/src/pages/ops/OpsHub.jsx` + new vitest file | ~60 LOC | **Low.** Defensive filter + edit-seed prune, no visual overhaul. |
| 3 | `td86-cleanup · one-shot migration script (dry-run default) + preview dry-run report` | `backend/scripts/cleanup_crew_cross_tenant_tech_ids.py` + new pytest file + `/app/memory/td86_crew_cleanup.md` | ~150 LOC | **Low (dry-run).** `--apply` deferred to operator greenlight. |

**STOP point:** after `td86-cleanup` dry-run on preview — do NOT invoke `--apply` without a separate greenlight (per operator dispatch).

**Rogue cron accounting:** since the TD-80 audit shipped (`4f1aa05b3`), one rogue strike landed (`06b84aea2` — captured my TD-80 audit receipt text + working-tree `.ruff_cache` + mobile transient artifacts as a commit body). **TD-61 strike chain is now at 12.** Standing precedent: not reverted. Will log inline in `TECH_DEBT.md` on the next housekeeping update.

**Awaiting operator greenlight on commit plan + commit cadence.**
