# Feature — Multi-industry · Phase D (Mobile Parity)

**Phase**: Sep-2026 · Phase D of D (final)
**Scope**: Mobile only (`/app/mobile/`). Backend + web unchanged.

## Summary

Mirrors the web multi-industry hook, nav gating, settings UI, and industry
badges onto the mobile Expo app. Reads from the same backend endpoints
(Phase A), uses the same 25-industry enum, and applies the same fail-open
nav-gating pattern (Phase C).

## 1. `useIndustries()` hook

**File**: `src/hooks/useIndustries.ts`

```ts
const { industries, hasIndustry, labels, loaded } = useIndustries();
```

- `industries: string[]` — tenant's active slugs (empty on cold mount)
- `hasIndustry(slug) => boolean` — safe on cold mount (returns false)
- `labels: Record<string, string>` — canonical label map
- `loaded: boolean` — true once tenant fetch settles

Module-scope cache: single fetch per session via `GET /api/tenants/current`.
`invalidateIndustries()` exported for settings save + tests.

## 2. Config module

**File**: `src/config/industries.ts`

Byte-parallel to `frontend/src/config/industries.js`:
- `INDUSTRIES` — 25-slug frozen array
- `INDUSTRY_LABELS` — slug→label map
- `DEFAULT_INDUSTRY` — `"pools"`
- `isValidIndustry(slug)` — predicate

## 3. Nav gating

**File**: `src/nav/adminNav.ts`

- Added `industry?: string` optional field to `NavEntry` type
- Tagged 2 entries:
  - `Pool Service` → `industry: "pools"`
  - `Landscape AI` → `industry: "landscaping"`
- Added `filterNavByIndustries(entries, industries)` helper
  - Fail-open: empty/non-array industries → all entries pass

**File**: `app/(app)/more.tsx` (drawer)

- Imported `useIndustries` + `filterNavByIndustries`
- `DrawerGroup` now chains `filterNavByIndustries(...)` before `canSeeEntry(...)` RBAC
- Union rule: multi-industry sees both; single-industry sees only its entries

## 4. Industries Settings screen

**Files**:
- `src/components/settings/IndustriesSettings.tsx` — 25-toggle list component
- `app/settings/industries.tsx` — full-page route screen

UX: auto-save on toggle via `PATCH /api/tenants/mine/settings`. Optimistic UI
with rollback on 422. Toast on success/error. Invalidates `useIndustries()`
cache after save.

Settings Hub (`app/settings/index.tsx`) updated with "Industries" link in the
General tab.

## 5. Industry badges

**File**: `src/components/tenant/TenantIndustryBadges.tsx`

- ≤4 industries → all chips inline
- >4 → first 3 + `+N more` chip that expands on press
- Mounted on tenant settings screen (`app/settings/tenant.tsx`)

## TestID map

### Industries Settings
| TestID | Element |
|--------|---------|
| `settings-industries-screen` | Screen root |
| `settings-industries-section` | Section root |
| `settings-industries-title` | Section title |
| `settings-industries-loading` | Loading spinner |
| `settings-industry-checkbox-<slug>` | Per-industry toggle (25×) |

### Industry Badges
| TestID | Element |
|--------|---------|
| `tenant-industry-badges` | Badge container |
| `tenant-industry-badge-<slug>` | Per-industry chip |
| `tenant-industry-badge-overflow` | "+N more" overflow chip |

## Coupling with web Phases A/B/C

- **Phase A** (backend): `GET /api/tenants/current` returns `industries[]`; `PATCH /api/tenants/mine/settings` accepts `industries[]`
- **Phase B** (web settings UI): mirrored as mobile `IndustriesSettings.tsx`
- **Phase C** (web nav gating): mirrored via `filterNavByIndustries()` + industry tags on `adminNav.ts`

## Files created
| File | Purpose |
|------|---------|
| `src/config/industries.ts` | Enum + labels (25 slugs) |
| `src/hooks/useIndustries.ts` | Hook + module-scope cache |
| `src/components/tenant/TenantIndustryBadges.tsx` | Badge strip component |
| `src/components/settings/IndustriesSettings.tsx` | Settings toggle list |
| `app/settings/industries.tsx` | Industries settings screen |
| `__tests__/multi-industry-phase-d.test.tsx` | 10 Jest tests |

## Files modified
| File | Change |
|------|--------|
| `src/nav/adminNav.ts` | Added `industry` field, tagged 2 entries, added `filterNavByIndustries` |
| `app/(app)/more.tsx` | Imported hook + filter, wired into `DrawerGroup` |
| `app/settings/index.tsx` | Added "Industries" link in General tab |
| `app/settings/tenant.tsx` | Mounted `TenantIndustryBadges` |

## Test coverage — 10 tests passing

- Config × 4: size, labels, isValidIndustry, default
- Nav gating × 4: hide pool entry on landscape-only, multi-industry union, fail-open empty, fail-open non-array
- Badges × 2: overflow renders "+N more", all inline when ≤ max

## Dependencies
None new.
