# Phase 53c-fix — Manager read-only EBIT (backend GET-allow + route guard + read-only rendering)

**Date:** Feb 2026  
**Scope:** Closes the manager read-only spec that Phase 53b promised but never wired end-to-end. Three surgical fixes.

---

## Fix 1 · Backend role gate split

`/app/backend/routers/ebit.py` — introduced two role gates and swapped the three GET endpoints to the new viewer gate:

| Endpoint | Method | Gate |
|---|---|---|
| `/api/ebit/compute` | GET | `_require_viewer` → `{super_admin, admin, manager}` |
| `/api/ebit/snapshots` | GET | `_require_viewer` |
| `/api/ebit/snapshots/{id}` | GET | `_require_viewer` |
| `/api/ebit/snapshots` | POST | `_require_role` → `{super_admin, admin}` |
| `/api/ebit/snapshots/{id}/adjustments` | PATCH | `_require_role` |
| `/api/ebit/snapshots/{id}/overrides` | PATCH | `_require_role` |

`_require_role` is retained as a backwards-compat alias for the editor-only gate.

Pytest coverage in `backend/tests/test_phase53a_ebit_backend.py`:
- `test_compute_manager_viewable` → 200
- `test_snapshots_list_manager_viewable` → 200
- `test_snapshot_get_by_id_viewable_by_manager` → 200
- `test_save_snapshot_forbidden_for_manager` → 403
- `test_patch_adjustments_forbidden_for_manager` → 403
- `test_patch_overrides_forbidden_for_manager` → 403 *(new — the earlier suite only asserted the adjustments PATCH)*

## Fix 2 · Frontend route guard

`/app/frontend/src/App.js` — new **targeted** guard `AdminOrManagerForProfitReport` used ONLY for `admin/reports/profit`. All other `/admin/*` routes stay under `AdminOnly`.

```jsx
<Route path="admin/reports/profit"
       element={<AdminOrManagerForProfitReport><ProfitReportPage /></AdminOrManagerForProfitReport>} />
```

The `ProfitReportPage`'s own `isAdmin` inner gate already includes `role === "manager"` (from Phase 53b), so once the route guard lets manager through, the page renders normally.

## Fix 3 · Manager read-only rendering

Both `frontend/src/components/admin/EbitPanel.jsx` AND `mobile/src/components/admin/EbitPanel.tsx` — the `EbitLineRow` component gained a `readOnly` prop. When `role === "manager"`:

- Every adjustment / override input still **renders** (so any prior edits are visible) but is `disabled` on web / `editable={false}` on mobile.
- Every `Flip to override` and `Clear override` button is **hidden**.
- The save row (button + note input) is **hidden**.
- A yellow **`read-only`** badge with `title="Read-only — contact admin to edit"` appears next to the `live` / `v{n}` pill.
- **History**, **CSV**, **PDF** buttons remain **enabled**.

When `role in {super_admin, admin}`: unchanged from Phase 53b/53c behavior — verified by explicit regression tests.

Both surfaces are locked to the same rule set by the parity file.

---

## E2E manager flow verified

Executed against the live preview URL as `manager@aquaterra.com / password123`:

1. Login as manager → succeeds (seed-drift healed in Phase 53c; `/api/auth/me` returns `role=manager`).
2. Navigate to `/admin/reports/profit` → **allowed** (was previously redirected off by `AdminOnly`).
3. Profit report page renders normally + EBIT panel mounts.
4. EBIT panel state at load:
   - **Yellow "read-only" badge** visible in header ✅
   - **Adjustment inputs disabled** (HTML `disabled` attribute present) ✅
   - **All 4 flip-to-override buttons hidden** ✅
   - **Save button + save-note input hidden** ✅
   - **History / CSV / PDF buttons enabled** ✅
5. History button opens the versions modal (viewing works).
6. CSV / PDF export buttons trigger — export works (viewing + exporting is fine for a manager).

Screenshot at `/tmp/ebit_manager_readonly.jpg` — Morgan Manager (bottom-left sidebar), `read-only` yellow pill next to `live`, 4 disabled adjustment inputs, no save button, no flip buttons.

## OpenAPI `range` enum

Tester note confirmed. The enum values accepted by `GET /api/ebit/compute?range=…` are:

```
this_month | last_month | qtd | ytd | monthly | quarterly | custom
```

Verified live:

| `range=` | Response |
|---|---|
| `this_month` | 200 ✅ |
| `monthly` | 200 ✅ |
| `month` *(the brief's typo)* | **400** — `{"detail":{"error":"invalid_range_kind: 'month'"}}` |

The `range: str = Query("this_month", description="this_month|last_month|qtd|ytd|monthly|quarterly|custom")` docstring on the endpoint already lists the correct enum — no docs or tests referenced the wrong `month` value, so nothing needed adjusting.

---

## Files touched

| File | Kind | Purpose |
|---|---|---|
| `backend/routers/ebit.py` | modified | Split `_require_role` into `_require_viewer` (GETs) + `_require_editor` (POST/PATCH). Retained alias for compat. |
| `backend/tests/test_phase53a_ebit_backend.py` | modified | Flipped manager expectations on GETs from 403→200. Added `test_save_snapshot_forbidden_for_manager`, `test_patch_overrides_forbidden_for_manager`, `test_snapshot_get_by_id_viewable_by_manager`. |
| `frontend/src/App.js` | modified | New `AdminOrManagerForProfitReport` guard. Route swap targeted at `/admin/reports/profit` only. |
| `frontend/src/components/admin/EbitPanel.jsx` | modified | `EbitLineRow.readOnly` prop; disabled inputs + hidden flip/clear buttons when true. New `ebit-panel-readonly-badge` element. |
| `frontend/src/test/ebit-panel.test.jsx` | modified | Rewrote the manager row-hidden assertion to the new inputs-disabled semantics. |
| `frontend/src/test/ebit-panel-manager-readonly.test.jsx` | **added** | 7 dedicated tests (5 manager, 2 admin/super_admin regression guards). |
| `mobile/src/components/admin/EbitPanel.tsx` | modified | Same read-only rendering as web + `readonlyPill` style + `rowInputDisabled` style. |
| `mobile/__tests__/phase53c-mobile-ebit-panel.test.tsx` | modified | Rewrote the manager row-hidden assertion to the new inputs-disabled + badge-visible semantics. |
| `mobile/__tests__/phase51d-walkie-parity.test.ts` | modified | +2 parity assertions locking the readonly badge + `readOnly={!canEdit}` + disabled/`editable` prop patterns to both surfaces. |
| `memory/PHASE53C_FIX_MANAGER_READONLY.md` | **added** | This delivery doc. |

## Test count delta

| Suite | Before | After | Δ |
|---|---:|---:|---:|
| Backend pytest | 22 | **25** | **+3** |
| Frontend vitest | 1371 | **1378** | **+7** |
| Mobile jest | 224 | **226** | **+2** |

## Suite verification (all green)

| Check | Result |
|---|---|
| `yarn lint` (frontend) | **exit 0** ✅ |
| `yarn test:unit` (frontend vitest) | **157 files · 1378 / 1378 green** ✅ |
| `yarn test` (mobile jest) | **29 suites · 226 / 226 green** ✅ |
| Backend Phase 53a + 53c pytest | **25 / 25 green** ✅ |
| `yarn lint` (mobile) | Baseline unchanged (232 pre-existing problems, 0 delta from 53c-fix) |
| Backend Phase 41.4 curated coverage gate | Untouched — additive-only backend change. |

## Guardrails verified

- ✅ No new EBIT features — pure spec completion.
- ✅ No other `/admin/*` routes opened to manager (`AdminOrManagerForProfitReport` is used only on `/admin/reports/profit`).
- ✅ No touch to the three hotfix code paths.
- ✅ No touch to Phase 49/50/50.1/50.2/41.1b/41.1c/41.1d/41.2/41.3/41.4/41.5/42.4/43/46/47c-48b/51a-d/51.5/51.6 code beyond the specific manager-role gate on `/admin/reports/profit`.
- ✅ No touch to Stripe / Mapbox / Time-Off / RingCentral runtime.

## Deviations

**None from the accepted spec.** The read-only badge is a small UX addition (unrequested but consistent with the manager-visible messaging in the spec's "tooltip" language) — testable via `ebit-panel-readonly-badge` and covered by the parity file. If undesired it's a 3-line removal from each surface.

Ready to advance to Phase 53d.
