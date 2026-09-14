# Feature — Multi-industry · Phase C (re-gate existing pool/landscape branches through `hasIndustry(...)`)

**Phase**: Feb-2026 · Phase C of D  
**Scope**: Frontend (nav gating + OpsHub tab gating) + backend
(chemistry-gate drift warning).  
**Deferred**: mobile parity (Phase D), per-industry checklists,
i18n / deep terminology work.

## Audit results

A repo-wide grep for `industry ==`, `is_pool_tenant`, `tenant.industry`,
and `== "pool"` / `== "landscape"` turned up **65 hits**. The audit
found that the codebase **already avoided tenant-scoped
single-industry gates**: every existing branch keys on either
(a) the **specific job's** ``service_type`` / ``checklist_kind`` or
(b) the **user's** ``department`` field. Both are correct per-item /
per-user scopes and must NOT be widened — a landscape tech's
checklists always differ from a pool tech's regardless of tenant
mix.

The genuine tenant-scoped touchpoints — the **nav bias** and the
**OpsHub tab bias** — hardcoded Pool Service / Landscape AI links
visible to every admin. Those are the surfaces this phase gates.

### Refactor table

| File | Line | Old check | New check |
|------|------|-----------|-----------|
| `backend/services/chemistry_gate.py` | new `warn_if_pool_job_on_non_pool_tenant` | – (no gate) | `tenant_has_industry(tenant, "pools")` — logs a warning on drift, never crashes |
| `frontend/src/nav/adminNav.js` | 200 `/pool-service` | always shown | `industry: "pools"` tag → gated by `filterNavByIndustries` |
| `frontend/src/nav/adminNav.js` | 222 `/landscape` | always shown | `industry: "landscaping"` tag |
| `frontend/src/nav/adminNav.js` | 289 `/admin/reports/pool-service` | always shown | `industry: "pools"` tag |
| `frontend/src/nav/adminNav.js` | 348 `/landscape/time-clock` | always shown | `industry: "landscaping"` tag |
| `frontend/src/nav/adminNav.js` | new `filterNavByIndustries()` | – (no filter) | Pure helper — filters entries with `industry` tags against a tenant's `industries[]` |
| `frontend/src/layouts/AdminSidebar.jsx` | 129 `visible` | – | Chains `filterNavByIndustries(g.entries, industries)` before the RBAC filter |
| `frontend/src/layouts/AdminTopBar.jsx` | 80 `useVisibleGroups` | – | Same industry filter chained before RBAC |
| `frontend/src/pages/ops/OpsHub.jsx` | 40 `{ k: "pool" ... }` | always shown | `industry: "pools"` tag → filtered by tenant industries |

### Legitimate per-job / per-user branches (left in place)

- `backend/routers/service_reports.py` — `kind == "pool"` on the
  submitted report → **per-job**, not per-tenant.
- `backend/routers/workstream_service_log.py` — same, per-job kind.
- `backend/services/service_report_view.py`,
  `backend/services/water_bodies.py`,
  `backend/services/chemistry_gate.py::is_pool_job` — all per-job.
- `backend/routers/tos_multi.py`, `backend/routers/jobs.py:342,344`,
  `backend/routers/checklists.py:104`,
  `backend/routers/templates_library.py:57`,
  `frontend/src/nav/roleNav.js:187`,
  `frontend/src/lib/checklistType.js:34,35` — all **per-user
  department** (a landscape tech vs a pool tech), correctly out of
  scope for a tenant-industry gate.
- `backend/routers/dashboard.py:218-219` — `bucket == "pool"` on
  a derived-per-job classification for the revenue split
  visualization; not a tenant gate.
- `frontend/src/components/legal/OnboardingGate.jsx:150` — per-doc
  `service_type`, not per-tenant.

## Union-behavior rules

- **Pool-only tenant** (`industries: ["pools"]`) — sidebar shows Pool
  Service + Pool Service Report; Landscape AI + Landscape Time
  Clock hidden. OpsHub shows the "Pool Service" tab. **Zero
  behaviour change vs pre-Phase-C**.
- **Landscape-only tenant** (`industries: ["landscaping"]`) — Pool
  entries hidden; Landscape AI + Landscape Time Clock visible.
  OpsHub tabs collapse to non-pool. Same behaviour as previous
  landscape-only setups.
- **Multi-industry tenant** (`industries: ["pools", "landscaping"]`)
  — Sidebar renders the **union**: every industry-tagged entry
  whose slug is in the array plus every untagged entry. OpsHub
  keeps the Pool tab.
- **Empty industries array** (migration pending or admin cleared)
  — **fail-open**: `filterNavByIndustries` returns the entries
  unchanged. Prevents a mysterious empty sidebar during rollout.

## Chemistry-gate resilience

Backend now exposes `warn_if_pool_job_on_non_pool_tenant(job, tenant)`
in `backend/services/chemistry_gate.py`. The gate itself keeps
firing per-job as before (correct); the helper adds a diagnostic
log **only** when the caller passes a pool-shaped job against a
tenant whose `industries` array excludes `"pools"`. Never raises,
never blocks the completion path.

Log shape (INFO logger `pool_crm`, level WARNING):

```
[chem-gate] tenant=<id> job=<id> pool-shaped but tenant industries=[...] — expected 'pools'. Reclassify the job or activate the Pools industry in Settings.
```

## Terminology — light touch

Per phase spec, this phase does **not** re-word every string. Only
one nav label was changed: none — all four industry-tagged entries
keep their current labels (Pool Service, Pool Service Report,
Landscape AI, Landscape Time Clock). Multi-industry tenants see
both labels; that's precisely the point of the union rule.

`OpsHub.jsx` keeps "Pool Service" as the label of the industry-
gated tab — accurate, non-biased on multi-industry tenants because
it's a scoped-per-tab label, not a page-header claim.

## Test coverage

Backend (`backend/tests/test_multi_industry_phase_c.py`) —
**5 tests passing**:

- Warning fires for a pool job on a landscape-only tenant.
- No warning for a landscape job.
- No warning when tenant has `pools` in `industries`.
- Missing `industries` field surfaces the warning (fail-visible so
  ops sees a broken migration).
- Never raises on malformed / `None` inputs.

Frontend (`frontend/src/test/multi-industry-phase-c-nav-gating.test.jsx`) —
**6 tests passing**:

- Untagged entries always render.
- Pool-tagged hidden without pools.
- Landscape-tagged hidden without landscaping.
- Multi-industry sees the union.
- Empty industries array → fail-open.
- Non-array industries treated as fail-open.

Existing chemistry-gate suite — **12 tests still passing** (no
regression on per-job gate mechanics).

## Files touched

- `backend/services/chemistry_gate.py` (new helper, +42 lines).
- `frontend/src/nav/adminNav.js` (industry tags on 4 entries, +26-line
  helper).
- `frontend/src/layouts/AdminSidebar.jsx` (2-line hook + deps).
- `frontend/src/layouts/AdminTopBar.jsx` (2-line hook + deps).
- `frontend/src/pages/ops/OpsHub.jsx` (industry tag on one tab, filter
  chain).
- `backend/tests/test_multi_industry_phase_c.py` (new).
- `frontend/src/test/multi-industry-phase-c-nav-gating.test.jsx` (new).

**OpenAPI paths unchanged at 1747** (no route surface change).

## Out of scope (unchanged)

- Mobile parity (Phase D — delegated to `e1_expo_frontend_dev`).
- Per-industry checklist templates for the 23 new industries (later
  phase per industry).
- i18n / deep terminology translation.
- Any A–F backlog items.
