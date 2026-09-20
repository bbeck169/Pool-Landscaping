# Iteration 111 — E3: Mobile Bottom Navigation

## What was implemented
- **5-tab persistent bottom navigation bar** replacing the previously hidden tab bar
- Tabs (in order): Schedule | Customers | Messages | (role-dependent) | More/Profile
- **Role gating**:
  - Admin slot 4: "Pipeline" → routes to `/(app)/quotes`
  - Tech slot 4: "Jobs" → routes to `/(app)/jobs`
  - Admin slot 5: "More" (ellipsis icon)
  - Tech slot 5: "Profile" (person icon)
- All 70 route files registered as `<Tabs.Screen>` — 5 visible, 65 hidden (`href: null`)
- AI Dock FAB repositioned above tab bar

## Web-to-Mobile mapping decisions
- Schedule → `schedule/calendar` (same for both roles)
- Customers → `customers` (enabled for techs; previously admin-only)
- Messages → `huddle` (Daily Huddle; center position in bar)
- Pipeline (admin) → `quotes` (Quotes & Invoices — most active admin workflow)
- Jobs (tech) → `jobs` (Workstream list)
- More/Profile → `more` (overflow menu with all navigation links)

## Key changes in `_layout.tsx`
1. Removed `tabBarStyle: { display: "none" }` → tab bar now visible
2. Added `tabBarHideOnKeyboard: true`
3. Added shadow/elevation styling to tab bar
4. Reordered all `<Tabs.Screen>` — 5 visible tabs FIRST (determines tab bar order)
5. Fixed `name="assets"` → `name="assets/index"` (prevented phantom 6th tab)
6. Fixed dead `name="onboarding"` → `name="onboarding/mine"`
7. Added 22 previously-unregistered route files (all hidden)
8. FAB bottom position uses `TAB_BAR_HEIGHT + 16` constant

## Known issues / deferred items
- `tabBarTestID` works on native but NOT on web-preview (Playwright can't find `data-testid`; this is a React Navigation web limitation)
- No unread message badge on Messages tab (no existing API endpoint for unread count)
- Admin initially lands on Dashboard (index) with no tab highlighted — acceptable behavior since Dashboard is accessible but not a tab
- Tech's Customers screen shows a simplified view (no bulk actions) — existing behavior, not a bug

## Dependencies installed
- None (no new packages needed)

## Screens verified
- Admin: Schedule ✓, Customers ✓, Messages ✓, Pipeline (registered), More ✓
- Tech: Schedule ✓, Customers ✓, Messages (registered), Jobs ✓, Profile (registered)
