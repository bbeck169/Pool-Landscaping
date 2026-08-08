# Phase 53d — Editable EBIT MVP closeout

**Date:** Feb 2026  
**Scope:** Docs-heavy closeout. No new features. Contract-lock tests + parity snapshots + PRD/CHANGELOG entries + tightened OpenAPI enum + `author_display_name` field.

---

## Files touched

| File | Kind | Purpose |
|---|---|---|
| `backend/routers/ebit.py` | modified | `range` + `revenue_basis` → `Literal[...]` types (OpenAPI enums surface + 422 on drift). `_save_new_version` now takes + stores `author_display_name`. |
| `backend/tests/test_phase53d_ebit_contract_lock.py` | **added** | 6 pytest response-shape locks. |
| `frontend/src/test/phase53d-web-mobile-ebit-parity.test.jsx` | **added** | 11 source-inspection assertions locking shared vocab. |
| `mobile/__tests__/phase51d-walkie-parity.test.ts` | modified | +10 new Phase 53d parity assertions appended (walkie assertions untouched). |
| `memory/PRD.md` | modified | Consolidated Phase 53 section prepended. |
| `CHANGELOG.md` | modified | Consolidated Phase 53 entry prepended. |
| `mobile/EXPO_GO_RUNBOOK.md` | **unchanged** | Already covers `expo-audio` (Phase 51). `expo-print` + `expo-sharing` + `expo-file-system` are pre-bundled and require no dev-client rebuild — verified. |
| `memory/PHASE53D_EBIT_CLOSEOUT.md` | **added** | This delivery doc. |

## Parity assertions added

### `phase53d-web-mobile-ebit-parity.test.jsx` (web vitest — 11 tests)

1. Both surfaces mount `<EbitPanel />` from the shared component path.
2. `ADJUSTMENT_KEYS = ["revenue","cogs","opex","depreciation"]` — exact array on both sides (parsed from `LINE_KEYS` declaration).
3. `EDITOR_ROLES = {super_admin, admin}` — `canEdit` uses the same OR expression.
4. `VIEWER_ROLES = {super_admin, admin, manager}` — `canView = canEdit || role === "manager"` on both.
5. `MANAGER_READONLY_TESTIDS` — `ebit-panel-readonly-badge` + `ebit-row-${lineKey}-adjustment-input` render on both.
6. `MANAGER_HIDDEN_TESTIDS` — `ebit-row-${lineKey}-flip-override`, `ebit-save-btn`, `ebit-save-note` all exist in both surfaces behind a `canEdit` gate.
7. Range-picker client-driven values `{monthly, quarterly, custom}` match the OpenAPI enum subset.
8. Revenue-basis toggle exposes exactly `{cash, accrual}` — and rejects `modified_cash | tax_adjusted | gaap` sneaking in.
9. EBIT total formula literal `out.ebit = out.revenue - out.cogs - out.opex - out.depreciation` present on both sides.
10. Both surfaces POST `/ebit/snapshots` (immutable) — no client PATCH.
11. Both surfaces consume the same 3 read-side endpoints (`/ebit/compute`, `/ebit/snapshots`).

### `phase51d-walkie-parity.test.ts` (mobile jest — +10 EBIT tests)

Mirrors the same rules on the mobile source parity file (already reads both web + mobile source files, so this is where source-inspection parity lives). New "Phase 53d · EBIT MVP closeout — shared vocab parity" block covers `ADJUSTMENT_KEYS`, `EDITOR_ROLES`, `VIEWER_ROLES`, `MANAGER_READONLY_KEYS`, `MANAGER_HIDDEN_KEYS`, range enum, basis toggle, EBIT formula, POST-only client contract, `author_display_name` field reference.

## Backend contract-lock test summary

`backend/tests/test_phase53d_ebit_contract_lock.py` — 6 tests, all against LIVE endpoints:

1. **`test_compute_response_shape_locked`** — asserts presence + type of every field returned by `GET /ebit/compute`: `revenue, cogs, opex, depreciation, ebit` (numbers) + EBIT identity holds; `range_from, range_to, range_kind, revenue_basis` (strings, expected values); `line_adjustments, line_overrides` (dicts with all 4 line keys); `breakdown` (dict with `invoice_count, line_count, opex_payroll, opex_other, opex_by_category, depreciation_by_category, wages_by_role`).
2. **`test_compute_rejects_invalid_range_via_openapi_literal`** — bogus `range=` returns 422 with all 7 accepted values listed in the error body. Confirms the `Literal` type drives validation.
3. **`test_compute_rejects_invalid_revenue_basis_via_openapi_literal`** — same for `revenue_basis`, listing `cash | accrual`.
4. **`test_snapshot_response_shape_locked`** — asserts presence + type for every field returned by `GET /ebit/snapshots/{id}`: `id, tenant_id` (strings), EBIT figures + identity, `range_kind, range_from, range_to, revenue_basis`, `version` (int ≥ 1), `line_adjustments, line_overrides, breakdown, author_user_id, author_display_name, saved_at` (ISO-8601), `note`.
5. **`test_snapshot_author_display_name_populates_from_user`** — new saves must populate `author_display_name` from `user.name || user.email`. Non-empty guarantee.
6. **`test_openapi_range_and_basis_enums_present`** — `openapi.json` schema check: `parameters[range].schema.enum == {this_month, last_month, qtd, ytd, monthly, quarterly, custom}` and `parameters[revenue_basis].schema.enum == {cash, accrual}`.

## PRD Phase 53 section — diff summary

Prepended a single "## Phase 53 · Feb-2026 — Editable EBIT report MVP (a → d)" block covering:

- Feature scope + role gates (`EDITOR_ROLES`, `VIEWER_ROLES`) + manager read-only rendering rules
- All 6 endpoints under `/api/ebit/*` with method / gate / purpose
- OpenAPI `Literal` treatment (range + revenue_basis)
- Complete `EbitSnapshot` data-model shape + indexes
- Compute logic references (cash / accrual definitions, COGS from line items, depreciation category matching, wages-by-role diagnostic)
- Web + mobile surface paths (`ProfitReportPage.jsx` + `profit-report.tsx` + `EbitPanel.{jsx,tsx}`)
- Seed baseline (`seed_demo_manager`)
- Contract locks (53d)
- Non-goals: draft/publish workflow, external accounting sync, budget-vs-actual variance, consolidated multi-entity EBIT, automatic period lock
- Test coverage summary

## CHANGELOG Phase 53 entry — diff summary

Prepended a single "## 2026-02-XX — Phase 53 (a → d) · Editable EBIT report MVP" entry under Keep-a-Changelog format:

- **Added**: backend router + service + collection + web panel + mobile panel + route guard + manager read-only rendering + demo-manager seed repair + OpenAPI enum + `author_display_name` field + full test coverage + 6 per-phase memory docs + PRD section.
- **Changed**: `_require_role` → `_require_viewer` / `_require_editor` split (backwards-compat alias retained); mobile jest `setTimeout(15000)` batch accommodation; profit-report test mock URL-routing shim; `test_credentials.md` correction.
- **Fixed**: `manager@aquaterra.com` role drift; `/admin/reports/profit` route now allows manager (targeted rule).
- **Non-goals (deferred)**: matching the PRD list.

## OpenAPI `range` enum reconciliation

**Was:** `range: str = Query("this_month", description="this_month|last_month|qtd|ytd|monthly|quarterly|custom")` — description string only. Invalid values passed through to `resolve_range()` and returned 400 with a plain error message.

**Now (Phase 53d):** `range: RangeKind = Query("this_month", description=...)` where `RangeKind = Literal["this_month","last_month","qtd","ytd","monthly","quarterly","custom"]`. `openapi.json` now emits `parameters[range].schema.enum = [...]`. Invalid values return 422 with Pydantic's literal_error listing every accepted value. Same treatment for `revenue_basis: Literal["cash","accrual"]`.

**No live-behavior change beyond the tighter error code + full enum in the openapi schema.** All existing docs + tests already referenced the correct values — no downstream corrections required.

## Test count delta

| Suite | Before | After | Δ |
|---|---:|---:|---:|
| Backend pytest (53a + 53c-seed + 53d) | 25 | **31** | **+6** |
| Frontend vitest | 1378 | **1389** | **+11** |
| Mobile jest | 226 | **236** | **+10** |

## Suite verification (all green)

| Check | Result |
|---|---|
| `yarn lint` (frontend) | **exit 0** ✅ |
| `yarn test:unit` (frontend vitest) | **158 files · 1389 / 1389 green** ✅ |
| `yarn test` (mobile jest) | **29 suites · 236 / 236 green** ✅ |
| Backend Phase 53a + 53c + 53d pytest | **31 / 31 green** ✅ |
| `yarn lint` (mobile) | Pre-existing baseline (232 problems) unchanged — 53d added zero new problems. |
| Backend Phase 41.4 curated coverage gate | Untouched (only additive router changes). |

## Deviations

**None from spec.** Two implementation choices worth logging:

1. **`author_display_name` added to `ebit_snapshots`.** The brief listed it in the contract-lock assertion but the field didn't exist on the saved doc. Adding it was necessary for the contract-lock test to pass — treated as scope-included since the brief explicitly asked for it in the response-shape assertions. Backwards-compat: existing rows without the field still deserialize; the version-history modal falls back to `author_user_id`.
2. **Parity assertions were added into the existing `mobile/__tests__/phase51d-walkie-parity.test.ts`** (the source-inspection parity file that already reads both web + mobile source files) rather than creating a fresh mobile-side parity file. Rationale: keeps all mobile source-inspection parity in one canonical file. A new dedicated web vitest file (`phase53d-web-mobile-ebit-parity.test.jsx`) IS created — that file complements the mobile one from the web vitest side.

Phase 53 EBIT MVP is now complete. Ready for final sign-off. After sign-off, next candidates surface: Phase 47c/48b Stripe RBAC cluster + Phase 52.1 live-streaming walkie slicing plan.
