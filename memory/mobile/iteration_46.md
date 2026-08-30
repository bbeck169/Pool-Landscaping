# Iteration 46 — Settings Hub + Sprocket + Typed-Confirm Removal

## Date: 2026-08-30

## What was implemented

### Part 1 — Settings Hub (4-tab screen)
- `app/settings/index.tsx` (471 LOC) — tabbed hub at `/settings` with:
  - **General** tab: 8 quick-link rows to existing settings sub-pages (tenant, business-card, terms, late-fees, legal, notifications, promo-codes, service-categories, income-categories)
  - **Branding** tab: Read-only display of current tenant logo via `BrandLogo` component + info note ("Manage branding from the web app for now")
  - **Integrations** tab: Fetches `/api/settings/integrations`, renders 7 integration cards (Emergent LLM, Google, Resend, Stripe, Stripe Webhook, GBP, RingCentral) with connected/not-connected status chips + "Manage from web" note
  - **Social** tab: Mounts the extracted `PlatformGrid` component + "Open Soshie" link for Brand Brain/Autopilot/Review Queue access
- Role gate handled by existing `settings/_layout.tsx` (admin + super_admin only)
- Online-only with offline banner

### Part 2 — PlatformGrid component (extracted)
- `src/components/settings/PlatformGrid.tsx` (326 LOC) — extracted from `app/soshie/AutopilotTab.tsx`
- Contains: 8-platform connect grid with connection status badges, cadence controls, toggles
- Reddit toggle permanently disabled (manual only)
- Optimistic update + revert on API failure

### Part 3 — Settings sprocket in Header
- Added `SettingsSprocket` function inside `src/components/widgets.tsx`
- Renders `settings-outline` Ionicon, positioned left of existing right slot
- Only visible for admin/super_admin roles
- testID="header-settings-sprocket" (matches web for cross-platform test parity)
- On tap → navigates to `/settings`

### Part 4 — Typed-confirm removal
- `src/components/portal/DeleteAccountSection.tsx`: Removed `REQUIRED_PHRASE`, `phrase` state, `TextInput`, and `canConfirm` gate. Confirm button is now immediately enabled.
- No other mobile confirm dialogs had typed-confirm (`ConfirmModal`, `CustomerDeleteModal`, `BulkConfirmModal` were already single-click)
- No mobile bulk-delete surface exists that would need arm-and-execute (flagged in ship report)

### Part 5 — Soshie connect-grid deduplication
- Removed platform grid rendering from `app/soshie/AutopilotTab.tsx`
- AutopilotTab now shows: kill switch + "Manage connections on Settings → Social" message + recent actions feed
- Single source of truth for platform cadence management is now `/settings` → Social tab

## Web-to-Mobile mapping
| Web File | Mobile File | Notes |
|----------|-------------|-------|
| `layouts/SettingsHub.jsx` | `app/settings/index.tsx` | 4-tab segment control (vs web's sidebar nav) |
| `layouts/AdminTopBar.jsx` (sprocket) | `src/components/widgets.tsx` (SettingsSprocket) | Same testID, same role gate |
| `pages/settings/IntegrationsPages.jsx` | `app/settings/index.tsx` (IntegrationsTab) | Read-only status display |
| `pages/settings/SettingsSocial.jsx` | `app/settings/index.tsx` (SocialTab) + `PlatformGrid.tsx` | Extracted + deduplicated |
| `components/common/ConfirmDeleteDialog.jsx` | `portal/DeleteAccountSection.tsx` | Typed-confirm removed |

## Test results
| Suite | Tests | Status |
|-------|-------|--------|
| settings-hub-mobile.test.tsx | 6/6 | ✅ PASS |
| settings-sprocket-visibility.test.tsx | 5/5 | ✅ PASS |
| mobile-no-typed-confirm.test.tsx | 4/4 | ✅ PASS |
| phase11b-delete-account-section.test.tsx | 2/2 | ✅ PASS (updated) |
| soshie-hub.test.tsx | 7/7 | ✅ PASS (updated) |
| **Full regression** | **716/737** | 8 pre-existing failures, 0 new |

## Known issues
- Expo preview tunnel sleeping (CDN issue — not code)
- ~60 lint warnings (no-unused-vars) — deferred per user instructions
- No mobile bulk-delete surface → arm-and-execute UX not needed

## Deferred
- Mobile admin logo upload UI (Branding tab is read-only)
- In-app OAuth flows for integrations (links to web)
- No new dependencies installed
