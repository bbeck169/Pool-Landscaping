# Feature — Multi-industry · Phase B (Organization Settings multi-select UI + industry badges)

**Phase**: Feb-2026 · Phase B of D  
**Scope**: Frontend only.  Backend from Phase A is unchanged.  
**Deferred**: re-gating existing pool/landscape branches (Phase C),
mobile parity (Phase D).

## What shipped

1. **`Settings → Industries` page** — 25-checkbox multi-select grid keyed off `INDUSTRIES` + `INDUSTRY_LABELS`. Auto-saves on toggle via `PATCH /api/tenants/mine/settings`. Cache-invalidation call after each successful save so the `useIndustries()` hook re-fetches next mount.
2. **`TenantIndustryBadges` component** — compact chip strip surfacing the tenant's active industries.  Mounted on the SettingsHub header row alongside the "Settings" title.
3. **New sidebar entry** in `SettingsHub.jsx` between Business and Theme.

## Save UX decision — auto-save on toggle

Chose **auto-save** over a Save button because:

- Checkbox grids feel awkward with an explicit save gate ("did I click Save yet?").
- The PATCH endpoint already validates every request, so mistake tolerance is `422 → red toast → rollback` which is cheaper than blocking the UI on a diff-tracker.
- The visible feedback loop is < 200ms: optimistic UI updates, chip flips, success toast ("Saved") fades in ~1.5s.

Error path: 422 (invalid_industry / invalid_industries_shape) → red toast "Failed to save industries. Please refresh and try again." + local state rolled back to pre-click so the checkbox de-flips.

## Testid map

### `IndustriesSettings.jsx`

| Element | testid |
|--------|--------|
| Section root | `settings-industries-section` |
| Section title | `settings-industries-title` |
| Loading state | `settings-industries-loading` |
| Checkbox grid container | `settings-industries-grid` |
| Per-industry checkbox (25×) | `settings-industry-checkbox-<slug>` |
| Save toast (success or error) | `settings-industry-save-toast` |

### `TenantIndustryBadges.jsx`

| Element | testid |
|--------|--------|
| Chip container | `tenant-industry-badges` |
| Per-industry chip | `tenant-industry-badge-<slug>` |
| "+N more" overflow chip | `tenant-industry-badge-overflow` |

## Badge overflow behavior

- **≤ 4 industries** → all chips render inline.
- **> 4 industries** → first `max - 1` (3 by default) chips + a `+N more` chip that lists the hidden slugs in its `title` attribute.
- Clicking `+N more` expands the strip inline (no dropdown / no modal) — hidden chips flow into the same wrap layout so the surface never becomes visually dominant.
- The overflow chip vanishes once expanded; there's no re-collapse button because the natural "less" gesture is a page navigation away.

## Layout description

```
Settings                [Pools] [Landscaping] [+3 more]
┌──────────────────────────────────────────────────────────┐
│ General   |                                              │
│ Branding  |  Industries                                  │
│ Business  |  Select all industries your business serves. │
│ >Industries<                                             │
│ Theme     |  ┌──────┐ ┌──────────┐ ┌──────┐ ┌──────────┐│
│ Integr.   |  │ Pools│ │Landscape │ │ HVAC │ │ Plumbing ││
│ Social    |  └──────┘ └──────────┘ └──────┘ └──────────┘│
│           |  ... (grid: 2 cols <sm, 3 sm, 4 md+)         │
│           |  [ Saved ] (green pill, fades 1.5s)          │
└──────────────────────────────────────────────────────────┘
```

Grid breakpoints: `grid-cols-2 sm:grid-cols-3 md:grid-cols-4`.  
Chip enum order matches `INDUSTRIES` (backend source of truth) so the settings grid and the header badges always agree on ordering.

## Files touched

- **new**: `frontend/src/pages/settings/IndustriesSettings.jsx`
- **new**: `frontend/src/components/tenant/TenantIndustryBadges.jsx`
- **modified**: `frontend/src/layouts/SettingsHub.jsx` (new section link + header badge mount).
- **modified**: `frontend/src/App.js` (route + import).
- **new test**: `frontend/src/test/multi-industry-phase-b.test.jsx` (8 tests).

## Test coverage

Frontend Vitest — **8 new tests passing**:

- `IndustriesSettings` × 4: 25-checkbox render, PATCH-body assertion in canonical enum order, success toast, error toast + rollback on 422.
- `TenantIndustryBadges` × 4: N-chips per selected industry, hidden when empty, overflow behavior (>4 → 3 + "+N more"), all-inline behavior (≤ 4).

Existing Phase A + tenant / settings suites — **no regression**.  
**OpenAPI paths unchanged at 1747** (no backend surface touched).

## Out of scope (unchanged)

- Re-gating pool/landscape branches (Phase C — next dispatch).
- Mobile parity (Phase D — later, delegated to `e1_expo_frontend_dev`).
- Per-industry checklist / preset mappings.
- Any A–F backlog items.
