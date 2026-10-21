# TD-82-calendar-consolidate · Phase 1 Recon

**Scope:** operator-queued cleanup. Reality-check the "calendar bulk ops consolidation + BE endpoint dedup" framing against the actual bookmark text + codebase. BE-only this cycle (mobile is parked per hard rule + a prior ticket track).

**Phase 1 = recon only. No code.**

---

## 1. Bookmark text — verbatim

Grep of `memory/TECH_DEBT.md:511-513`:

```markdown
- **TD-82-calendar-consolidate (candidate, P3 mobile + BE note).**
  - Schedule calendar bulk Complete/Move (`calendar.tsx:575/589`) run N
    sequential `PUT /jobs/{id}`, and Delete uses
    `POST /jobs/bulk-soft-delete {job_ids}` (L617). Move them onto
    `/jobs/bulk-update` / `/jobs/bulk-delete` for a single round-trip plus
    locked-job reporting.
  - **BE sub-note:** there are two job bulk-delete endpoints,
    `POST /jobs/bulk-delete {ids}` (`routers/bulk_crm.py:444`,
    `require_admin_or_manager`, `failed[]` lock reasons) and
    `POST /jobs/bulk-soft-delete {job_ids}` (`routers/jobs.py:4253`).
    Reconcile them in this ticket. Operator picks the canonical one during
    its audit; soft-delete is the likely default for admin-destructive ops,
    and hard-delete may be a legacy path.
```

### Operator-framing-vs-bookmark deltas (surfaced per hard rule)

| Operator-dispatch wording | Bookmark truth |
|---|---|
| "Bulk ops logic currently split between pages/components" | Not what the bookmark says. Bookmark cites ONE mobile file (`calendar.tsx:575/589/617`). |
| "BE may have duplicated endpoints across calendar + schedule" | **No `routers/calendar.py` exists** (confirmed §2). Duplication is `routers/bulk_crm.py` + `routers/jobs.py` on job bulk-delete — not calendar vs schedule. |
| "Mobile parity scan" | Mobile IS the primary scope of the bookmark. Hard rule says "no mobile edits" — this disqualifies the FE half of the bookmark. |

The bookmark's "soft-delete is the likely default… and hard-delete may be a legacy path" line is also inaccurate: BOTH endpoints perform **soft delete** (§2b). The real distinction is param shape, not deletion kind.

### What's actually in-scope for a BE-only web-side ship

**One concrete BE dedup** + **one web caller migration**. Mobile follow-up (`calendar.tsx:575/589/617`) is parked by rule.

---

## 2. BE endpoint audit

### 2a. No `routers/calendar.py` exists

```
find backend -name "calendar*" → services/calendars/* (BYO Google / Outlook — unrelated)
```

The term "calendar" in this codebase means Google/Outlook BYO calendar integration providers (under `services/calendars/`). There is no calendar-centric router. The web page `frontend/src/pages/schedule/CalendarSchedule.jsx` is a schedule-view variant that already calls the standard `/schedule/*` and `/jobs/*` endpoints — it doesn't have its own BE.

### 2b. The two bulk-delete endpoints — detailed comparison

**`POST /api/jobs/bulk-delete`** at `backend/routers/bulk_crm.py:444-460`
- `operation_id="jobs.bulkDelete"`
- Auth: `require_admin_or_manager`
- Body: `_BulkIdsIn` → `{ids?: list[str], query_selector?: dict, exclude_ids?: list[str]}` — supports **"select all matching filter"** semantics.
- Behavior: resolves ids via `_resolve_ids` (bulk-select-all expansion) → calls `_generic_bulk_delete("jobs", "job.soft_delete", …)`.
- **Deletion kind: SOFT** (op id is `job.soft_delete`, despite the route name).
- Response: `{deleted: [...], failed: [{id, reason, status_code}]}` with lock-reason granularity via `_job_locked`.

**`POST /api/jobs/bulk-soft-delete`** at `backend/routers/jobs.py:4253-4284`
- `operation_id="jobs.bulkSoftDelete"`
- Auth: `require_admin_or_manager`
- Body: `BulkSoftDeleteIn` → `{job_ids: list[str]}` — flat id list only.
- Behavior: hard-cap at 100 rows → iterates `_perform_soft_delete_job`.
- **Deletion kind: SOFT** (same as above).
- Response: `{ok: true, count: N, deleted: [...], failed: [{job_id, reason, status_code}]}`.

**Semantic truth:** both are soft-delete. Both gate on the same role. Both return a failures array. The real deltas are:

| Dimension | `/jobs/bulk-delete` (bulk_crm) | `/jobs/bulk-soft-delete` (jobs.py) |
|---|---|---|
| Param name | `ids` | `job_ids` |
| Supports `query_selector`? | ✅ yes (bulk-select-all-matching) | ❌ no (ids only) |
| Hard row cap | shared `_CAP` (per `_generic_bulk_delete`) | 100 explicit |
| Failed-row key | `id` | `job_id` |
| Response shape | `{deleted, failed}` | `{ok, count, deleted, failed}` |
| Lock-reason granularity | ✅ via `_job_locked` | ✅ via `_perform_soft_delete_job` raise |
| House pattern parity (customers / invoices / quotes bulk) | ✅ matches | ❌ outlier |

**Conclusion:** `/jobs/bulk-delete` (bulk_crm) is the canonical house-pattern endpoint. `/jobs/bulk-soft-delete` (jobs.py) is the outlier.

### 2c. Caller inventory

**`/jobs/bulk-delete` (canonical):**
- `frontend/src/pages/workstream/WorkstreamPage.jsx:547`
- `frontend/src/pages/jobs/JobsList.jsx:113`
- `frontend/src/App.js:975` (routing comment / anchor only)

**`/jobs/bulk-soft-delete` (outlier):**
- `frontend/src/pages/schedule/CalendarSchedule.jsx:641` (web — IN SCOPE)
- `app/calendar.tsx:617` (mobile — OUT OF SCOPE per hard rule)
- `backend/tests/test_jobs_soft_delete.py` (3 call sites)
- `backend/scripts/README_backfill_recurring_jobs.md:128` (doc reference)

**Non-related sibling (sanity check):**
- `POST /recurring-jobs/bulk-delete` at `routers/recurring_jobs.py:1314` — THIS is a hard-delete endpoint (recurring-job TEMPLATES, not jobs). Different concern. Not touched by this ticket. Called by `admin/RecurringJobs.jsx:761`.

### 2d. Already-consolidated / 410 Gone precedents

`memory/TECH_DEBT.md:1700-1703` references `TD-98-be-cleanup-retire` which retired lead-convert endpoints via 410 Gone. The retire pattern is codified; we can mirror it for `/jobs/bulk-soft-delete` once the one web caller is migrated.

### 2e. Other `routers/schedule.py` bulk-related endpoints — scope check

Enumerated via grep:
- `GET /schedule/today`, `GET /schedule/day`, `POST /schedule/route-leg`, `POST /schedule/reschedule`, `GET /schedule/unassigned-pending-stale-count`.
- `routers/schedule_reorder.py` + `routers/schedule_ai.py` sibling routers.

**None of these have bulk-delete semantics.** `/schedule/reschedule` is a single-job move; the actual bulk-reschedule lives at `routers/jobs.py:4655 /jobs/bulk-reschedule` and is well-used by `CalendarSchedule.jsx`. No consolidation opportunity in the schedule router.

---

## 3. FE bulk ops surface — web

### 3a. `CalendarSchedule.jsx` (web calendar view) — bulk-ops inventory

File is 3,616 LOC. Bulk operations present:
- `doBulkDelete` at `:637` → `POST /jobs/bulk-soft-delete {job_ids}` — **OUTLIER, needs migration.**
- `doBulkReassign` at `:657` → `POST /jobs/bulk-reassign {job_ids, …}` — canonical.
- `doBulkNavigateRoute` at `:689` → client-side URL builder (no BE call).
- `bulkReschedule` at `:1456` → calls shared helper `@/lib/bulkReschedule` → `POST /jobs/bulk-reschedule`.
- `BulkReorderModal` at `:535-538, 2279` → calls `routers/schedule_reorder.py` endpoints.

Only ONE outlier call (`doBulkDelete` → `/jobs/bulk-soft-delete`). Everything else already uses canonical endpoints.

### 3b. `TodaySchedule.jsx` (today-view web)

Grep shows **zero** `/jobs/bulk-*` call sites in `TodaySchedule.jsx` — bulk operations are handled by `CalendarSchedule.jsx`, which `TodaySchedule.jsx` renders inside or delegates to. (TodaySchedule is a thin view selector; the heavy lifting is in CalendarSchedule.)

### 3c. `WorkstreamPage.jsx` + `JobsList.jsx`

Already use canonical `/jobs/bulk-delete`. No change needed.

### 3d. Shared primitives

The TECH_DEBT.md Occurrence #4 history (lines 729-739) flagged the "shared primitives already exist" pattern as a recurring recon risk. Grep for shared bulk primitives:
- `@/lib/bulkReschedule.js` — already extracted and used by `CalendarSchedule.jsx:51-52`.
- `@/components/quotes/QuotesBulkToolbar` — quote-specific, not relevant.
- No shared bulk-delete helper exists. The two call sites each inline the fetch (`JobsList.jsx:113`, `WorkstreamPage.jsx:547`, `CalendarSchedule.jsx:641`). If we extract one in this ticket, scope creep.

**Recommendation:** DO NOT extract a shared bulk-delete helper in this ticket. Only migrate the one outlier call. If the operator wants a shared helper later, that's a separate `TD-82-bulk-delete-helper` ticket.

### 3e. "Calendar bulk ops consolidation" claim — rebuttal

The operator's dispatch wording ("Bulk ops logic currently split between pages/components") does not match reality:
- Each page uses its OWN bulk UI (makes sense — Workstream's workflow differs from Schedule's).
- All pages already route to the canonical `/jobs/bulk-reschedule`, `/jobs/bulk-reassign`, `/jobs/bulk-update` endpoints.
- ONE page (CalendarSchedule.jsx) uses the outlier `/jobs/bulk-soft-delete` for delete only.

There is no "split logic to consolidate" — there is **one outlier endpoint call** to migrate. The web FE consolidation claim is overstated.

---

## 4. Mobile parity scan

### 4a. Current mobile state (read-only confirmation per hard rule)

Per `memory/TECH_DEBT.md:493-510` + `:820-874`:
- **TD-82 Mobile admin Jobs list bulk actions SHIPPED (B-narrow, Oct-2026)** — mobile already got the `BulkSelectToolkit` + bulk-reschedule / assign / delete primitives extracted.
- `app/calendar.tsx:575/589/617` still runs the N-sequential-`PUT`-and-`/jobs/bulk-soft-delete`-flat-id-list pattern that this bookmark cites.

### 4b. Gap for mobile follow-up (NOT shipped here)

A follow-up ticket (recommended ID: `TD-82-mobile-calendar-bulk`) would:
- Replace N sequential `PUT /jobs/{id}` on `calendar.tsx:575/589` with a single `POST /jobs/bulk-update` call via shared `BulkSelectToolkit`.
- Switch `calendar.tsx:617` from `/jobs/bulk-soft-delete` to `/jobs/bulk-delete` with `{ids}` param shape.
- ~20-30 LOC on mobile side.

**This ticket does NOT ship that.** Mobile is strictly out of scope per hard rule.

---

## 5. Consolidation plan — in-scope

### 5a. BE changes

1. **Retire `POST /jobs/bulk-soft-delete`** (`routers/jobs.py:4253`) via **410 Gone**, mirroring the `TD-98-be-cleanup-retire` pattern — handler body replaced with `raise HTTPException(410, {...})` carrying the migration pointer.
2. Keep `POST /jobs/bulk-delete` at `routers/bulk_crm.py:444` as the canonical endpoint. **No change** to its behavior.
3. **DO NOT delete the retired handler yet.** Only 410 it. Reap after one full release cycle (standard retire-pattern cadence per TECH_DEBT.md).

### 5b. Web FE change

4. Migrate `frontend/src/pages/schedule/CalendarSchedule.jsx:641` from `/jobs/bulk-soft-delete {job_ids}` to `/jobs/bulk-delete {ids}`.
5. Update response-key handling if needed (`failed[].job_id` → `failed[].id`).

### 5c. Not-doing list (surfaced for operator sign-off)

- **Not** extracting a shared bulk-delete FE helper (scope creep per §3d).
- **Not** touching `/recurring-jobs/bulk-delete` (unrelated hard-delete on templates).
- **Not** touching mobile `calendar.tsx` (hard rule).
- **Not** moving/renaming any `routers/schedule.py` endpoints (none duplicated per §2e).
- **Not** altering `/jobs/bulk-reassign`, `/jobs/bulk-reschedule`, `/jobs/bulk-update` (all canonical already).

### 5d. External-caller / 3rd-party safety

- `/jobs/bulk-soft-delete` has no documented external callers (grep found only internal FE + tests + one script-README mention).
- `operation_id="jobs.bulkSoftDelete"` is used in generated OpenAPI clients; any client built against that id will 410 on next call after retire. Standard retire-pattern consequence — captured in the 410 payload message.
- No webhooks dispatch to or from this endpoint.

---

## 6. Risk analysis

| Risk | Blast radius | Mitigation |
|---|---|---|
| Mobile `calendar.tsx` breaks after retire | HIGH if mobile hits the retired endpoint before mobile-follow-up ships | **Delay the 410 until the mobile follow-up ticket closes.** Alternative: do a two-phase retire — this ticket migrates web + leaves `/jobs/bulk-soft-delete` as a thin shim that calls the canonical endpoint internally; mobile follow-up migrates calendar.tsx; THEN 410 the shim. |
| Tests reference `/jobs/bulk-soft-delete` | `backend/tests/test_jobs_soft_delete.py` has 3 call sites | Tests must be updated to hit `/jobs/bulk-delete {ids}` with the new response shape. In-scope. |
| Response-shape change | `{ok, count, deleted, failed}` → `{deleted, failed}` on the web caller | `CalendarSchedule.jsx:641` only reads `failed[]` for toasting — compatible with the new shape. |
| Role gate change | None — both endpoints already use `require_admin_or_manager` | N/A |
| Lock-reason granularity change | None — both already surface lock reasons | N/A |

**Recommendation on risk mitigation:** go with the **two-phase retire** approach. Ship this ticket as:
- Phase 2A (this ticket): migrate web caller + add shim at the retired handler that delegates to `/jobs/bulk-delete` internally for mobile-ongoing compatibility. Zero data risk, zero mobile risk.
- Phase 2B (follow-up): after mobile `calendar.tsx` ships, convert the shim to a 410 Gone. Operator-dispatched separately.

### Rollback complexity

- BE: revert the one commit. Shim is additive — can be rolled back in isolation.
- FE: revert the one commit. CalendarSchedule.jsx revert leaves the shim or canonical both as functional targets.
- Zero data migration — pure routing change.

---

## 7. Testing plan

### Pytest

- **New file** `backend/tests/test_td82_bulk_delete_dedup.py`:
  1. `/jobs/bulk-delete {ids: [...]}` end-to-end soft-delete (positive).
  2. `/jobs/bulk-delete` with `query_selector` preserved (regression).
  3. `/jobs/bulk-delete` lock-reason surfaces in `failed[]` (regression).
  4. `/jobs/bulk-delete` RBAC — field tech 403.
  5. `/jobs/bulk-delete` tenant isolation.
  6. **Phase 2A ONLY:** `/jobs/bulk-soft-delete` shim still functional (delegates to canonical) and returns legacy `{ok, count, deleted, failed}` shape.
  7. **Phase 2B ONLY:** `/jobs/bulk-soft-delete` returns 410 with `migration_pointer`.
- **Update** `backend/tests/test_jobs_soft_delete.py`:
  - Switch 3 call sites to `/jobs/bulk-delete {ids}` with new response-key handling.

### Vitest

- **New file** `frontend/src/pages/schedule/__tests__/CalendarSchedule.bulkDeleteCanonical.test.jsx`:
  1. Bulk-delete fires `/jobs/bulk-delete` with `{ids: [...]}` body (not legacy shape).
  2. Response `failed[].id` reasons toasted correctly.
  3. Regression — `/jobs/bulk-reschedule`, `/jobs/bulk-reassign`, `/jobs/bulk-update` call sites unchanged.

### Migration tests

None needed. No data mutation. No schema change. Pure routing change.

---

## 8. Phase 2 cost estimate

| Scope | LOC |
|---|---|
| **Phase 2A** — Web + shim retire of jobs.py:4253 | — |
| `backend/routers/jobs.py:4253-4284` → shim delegates to `_generic_bulk_delete` with param-shape adapter | ~20 |
| `backend/tests/test_jobs_soft_delete.py` — update 3 call sites to new shape | ~15 |
| `backend/tests/test_td82_bulk_delete_dedup.py` **(new)** — 6 cases | ~110 |
| `frontend/src/pages/schedule/CalendarSchedule.jsx:641` — migrate 1 call site + response-key adjustment | ~5 |
| `frontend/src/pages/schedule/__tests__/CalendarSchedule.bulkDeleteCanonical.test.jsx` **(new)** — 3 cases | ~60 |
| **Phase 2A total** | **~210** |

**Shippable in 2 atomic commits** (BE + FE). Each <3 min edit-to-commit.

**Phase 2B** (future, operator-dispatched after mobile follow-up): ~15 LOC on the BE to convert shim → 410 Gone, plus pytest flip. Trivial.

---

## 9. Open decisions for operator

**Required Y/N:**

1. **Scope reality-check accepted?** Confirm this ticket ships ONLY the one-endpoint dedup (BE shim + 1 web caller migration), not a wholesale "calendar vs schedule BE consolidation" which does not match the actual code.
2. **Two-phase retire (recommended)** or hard 410 Gone on day one (risks mobile `calendar.tsx` the moment this ships)?
3. **Shared bulk-delete FE helper** — extract or defer? Recommend defer (scope creep).
4. **File-strategy for the shim's eventual retire note:** keep the shim handler + add a `# TODO · retire after mobile TD-82-mobile-calendar-bulk closes` comment, or add a tracker file in `memory/`?

---

## 10. Guardrail attestation

- No code changes this cycle.
- No `/app/mobile/` touches planned or made. Mobile scope is explicitly deferred to a separate follow-up ticket (`TD-82-mobile-calendar-bulk`).
- No scope creep into TD-96-g1-invoices (still at `7bed06d51`, done), TD-98-be-cleanup-retire (its pattern is referenced; its code is not touched), or any other TD ticket.
- No testing agent — manual pytest + vitest only in Phase 2.
- Operator-framing deltas were surfaced in §1 per hard rule ("report truth even when it contradicts framing"). No V15-style capitulation to the "calendar + schedule endpoint dedup" claim — the real code has no such duplication.
- TD-61 chain still at **20**.
