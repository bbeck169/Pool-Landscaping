# Phase 53a — Editable EBIT Report Backend + P&L Extension Foundation

**Date:** Feb 2026  
**Scope:** Backend ONLY (no frontend / mobile / UI code). The existing
`/admin/reports/profit` page is left completely untouched — 53a is
additive infrastructure that 53b (web UI) and 53c (mobile UI) will
consume.

---

## Preflight audit findings

### Existing P&L surfaces (kept untouched)
| Layer | Path | Endpoint(s) |
|---|---|---|
| Primary P&L page | `frontend/src/pages/admin/ProfitReportPage.jsx` | `GET /api/reports/profit`, `GET /api/reports/profit.csv` |
| Primary P&L backend | `backend/routers/profit_report.py` | Same |
| Secondary CFO view | `frontend/src/pages/cfo/CFODashboard.jsx` | `GET /api/cfo/dashboard` |
| Secondary CFO backend | `backend/routers/cfo.py::_revenue`, `_expenses` | Same |

**Gaps in the existing P&L that 53a fills:**
- No OpEx breakdown (only "expenses" lump sum)
- No depreciation tracking anywhere in the codebase
- No EBIT (only gross profit)
- No versioned / editable / auditable snapshots

### Depreciation audit — result: **NOT present**
- No `is_depreciation`, no boolean flag, no fixed category enum.
- Expenses live in `db.checks` with a free-form lowercase string `category`
  field, optionally overridden by an LLM-classifier row in
  `db.expense_categories` (`{tenant_id, transaction_id, category}` keyed
  on `source="check"`).

**53a strategy:** any check whose effective category (LLM override OR
`checks.category`, lowercased/stripped) matches
`{"depreciation", "amortization"}` is treated as depreciation. All other
non-voided checks are OpEx. Admins can correct misclassifications via
`line_adjustments` (delta) or `line_overrides` (absolute).

---

## Deliverables

### 1. MongoDB collection: `ebit_snapshots`
Immutable versioned history. Every save creates a NEW document; prior
versions are never mutated or deleted.

Fields:
```
id                   str (uuid)
tenant_id            str
range_kind           str (this_month|last_month|qtd|ytd|monthly|quarterly|custom)
range_from           str (YYYY-MM-DD, ISO date)
range_to             str (YYYY-MM-DD, ISO date)
revenue_basis        str (cash|accrual)
version              int (1-indexed, monotonic per (tenant, range_from, range_to))
revenue              float   ← EFFECTIVE value (overrides+adjustments applied)
cogs                 float   ← EFFECTIVE value
opex                 float   ← EFFECTIVE value
depreciation         float   ← EFFECTIVE value
ebit                 float   ← revenue - cogs - opex - depreciation
breakdown            {
  invoice_count, line_count,
  opex_payroll, opex_other,
  opex_by_category: [{category, amount}, ...],
  depreciation_by_category: [{category, amount}, ...],
  wages_by_role: {by_role, total_hours, total_wages},   ← diagnostic only
}
computed_live        {revenue, cogs, opex, depreciation, ebit}
                                                        ← pre-edit values
line_adjustments     {revenue: 0.0, cogs: 0.0, opex: 0.0, depreciation: 0.0}
line_overrides       {revenue: null|float, cogs: null|float,
                       opex: null|float, depreciation: null|float}
author_user_id       str
saved_at             str (ISO datetime)
note                 str
```

Indexes (created idempotently on first router call):
- `(tenant_id, range_from, range_to, version desc)` → `ebit_tenant_range_version_desc`
- `(tenant_id, saved_at desc)` → `ebit_tenant_saved_desc`

### 2. Compute service — `services/finance/ebit.py`
- `resolve_range(range_kind, from, to)` — accepts profit_report-compatible
  presets plus 53a additions `monthly` / `quarterly`. Custom-range guard
  rejects inverted ranges and windows > 366 days.
- `compute_ebit(db, tenant_id, range_from, range_to, revenue_basis)` —
  pulls invoices from `db.quotes` (cash: `payment_status=paid` on
  `paid_at`; accrual: `status ∈ {paid,partial,sent,overdue}` on
  `created_at`), non-voided `db.checks` in range with LLM-override
  categorization, and a wages-by-role diagnostic from
  `db.time_entries × db.users.hourly_rate`. Returns the shape above
  with EBIT identity holding.
- `apply_edits(live, adjustments, overrides)` — pure function that
  produces the EFFECTIVE snapshot payload from the live compute + edits.
  Override replaces value entirely; otherwise `effective = live + adjustment`.
  EBIT is recomputed from effective values so a single override
  propagates cleanly.

### 3. REST endpoints — `routers/ebit.py`
All gated to `super_admin + admin`. Everyone else → 403.

| # | Method | Path | Purpose |
|---|---|---|---|
| 1 | GET  | `/api/ebit/compute` | Live compute; no save. `?range`, `?from`, `?to`, `?revenue_basis` |
| 2 | GET  | `/api/ebit/snapshots` | List versioned history. `?range_from`, `?range_to`, `?limit` |
| 3 | GET  | `/api/ebit/snapshots/{id}` | Fetch a single snapshot |
| 4 | POST | `/api/ebit/snapshots` | Save a new version (v1 or v+1) |
| 5 | PATCH| `/api/ebit/snapshots/{id}/adjustments` | Merge deltas → NEW version |
| 6 | PATCH| `/api/ebit/snapshots/{id}/overrides` | Merge absolutes → NEW version |

PATCH semantics: incoming `line_adjustments` / `line_overrides` are
MERGED into the prior version's values (missing keys inherit). Result is
written as a new version doc — the prior doc is bit-for-bit unchanged in
Mongo.

### 4. Test coverage — `tests/test_phase53a_ebit_backend.py`
21 tests, all green (`1.62s` wall-clock).

- **Role gate** (7): compute + snapshots list + save all return 403 for
  manager / technician / customer; 200 for super_admin + admin.
- **Compute correctness** (5): hand-seeded fixture (2016-03) validates
  cash-basis (revenue=1500, cogs=300, opex=900, dep=200, ebit=100) AND
  accrual-basis (revenue=2300, cogs=300, opex=900, dep=200, ebit=900);
  breakdown shape asserted; invalid basis + inverted range → 422.
- **Save + version increment** (3): first POST returns v1, second POST
  same range returns v2 with a new `id`; list returns versions in desc.
  order; GET-by-id returns exact snapshot; unknown id → 404.
- **Adjustments PATCH** (1): creates new version; EBIT reflects delta;
  prior version doc in Mongo is byte-identical (immutability confirmed
  via direct PyMongo re-read).
- **Overrides PATCH** (2): absolute override replaces computed value;
  setting override to `null` reverts to `live + adjustment`.
- **Auth on PATCH** (1): manager PATCH → 403.
- **Tenant isolation** (1): a directly-planted `ebit_snapshots` row for
  a different `tenant_id` is invisible in the list endpoint.

Fixture is autouse + module-scoped, cleaned up in teardown. Idempotent
across re-runs (uses `_p53a_tag` selector).

### 5. Server wiring
Router registered in `server.py` immediately after `profit_report`:
```python
from routers import ebit as _p53a_ebit  # noqa: E402
api_router.include_router(_p53a_ebit.router)
```

---

## Locked user picks honored

| Pick | Decision | Impl |
|---|---|---|
| 3D  | Extend EXISTING P&L | 53a is additive; ProfitReportPage untouched. 53b will wire the EBIT panel into the existing page. |
| 3D  | Time-range toggle (monthly/quarterly/custom) | `range_kind` accepts monthly/quarterly + all profit_report presets + custom. |
| 4B  | super_admin + admin only | `_ALLOWED_ROLES = frozenset({"admin", "super_admin"})` on every endpoint. |
| 5C  | Default adjustments; admin can flip to override | Both `line_adjustments` (delta) AND `line_overrides` (absolute) supported. Setting override → null reverts to adjustment behavior. |
| 6B  | Immutable version history | Every save/patch creates a NEW doc. Version = max(existing)+1. Prior docs never mutated. |
| 7D  | PDF + CSV export | **Deferred to 53b** per spec. |
| 8C  | Full web + mobile parity | **Deferred to 53b/53c/53d** per spec. |

---

## Invariants verified

| Invariant | Result |
|---|---|
| Vitest suite (`yarn test:unit`) | **1357 / 1357 green** (39.7s) |
| Frontend lint (`yarn lint`) | **exit 0** (5.8s) |
| Phase 53a backend tests | **21 / 21 green** (1.6s) |
| Existing walkie backend tests | Unaffected — pre-existing storage-timeout flake only. |
| Mobile jest | 204 / 206 (pre-existing walkie-UI regressions from Phase 51.6; **NOT** caused by 53a — 53a touches zero mobile code). |

---

## What did NOT change

- No changes to `routers/profit_report.py`, `routers/cfo.py`, or any
  other prior-phase file.
- No changes to any hotfix code path.
- No changes to frontend or mobile — this is a strict backend phase.
- No changes to Stripe / Mapbox / Time-Off / RingCentral runtime.
- No new dependencies.

---

## Files added / modified

**Added:**
- `backend/services/finance/__init__.py`
- `backend/services/finance/ebit.py`
- `backend/routers/ebit.py`
- `backend/tests/test_phase53a_ebit_backend.py`
- `memory/PHASE53A_EBIT_BACKEND.md` (this file)

**Modified:**
- `backend/server.py` (single 3-line wire-up block after `profit_report`)

---

## Handoff to Phase 53b (web UI)

The web UI must:
1. Extend `frontend/src/pages/admin/ProfitReportPage.jsx` (do NOT create
   a new page).
2. Add an EBIT panel/tab that consumes `GET /api/ebit/compute` for the
   live figure.
3. Surface the current selected range's snapshot history from
   `GET /api/ebit/snapshots?range_from&range_to`.
4. Expose inline editing (default: adjustments; toggle to override) that
   `POST /api/ebit/snapshots` on save. Subsequent edits use PATCH
   variants.
5. Include a version-history dropdown (each row = an immutable version).
6. Wire PDF + CSV export off the current effective snapshot (per pick 7D).
