# Iteration 12 — Timeclock Admin-Hide Parity

## What was implemented
- Hid the `LandscapingClockWidget` for `admin` and `super_admin` roles on mobile, matching the web frontend.

## Changes made
1. **`/app/mobile/src/components/LandscapingClockWidget.tsx`** (line 54):
   - Changed: `const isLandscaper = isAdminLike || hasLandscapeDept;`
   - To: `const isLandscaper = !isAdminLike && hasLandscapeDept;`
   - This means admins no longer pass the landscaper check, so the component returns `null`.

2. **Mount-site guards** (defense-in-depth):
   - `/app/mobile/app/(app)/index.tsx` (line 66): Wrapped `<LandscapingClockWidget />` in `{user?.role !== "admin" && user?.role !== "super_admin" && ...}`
   - `/app/mobile/app/(app)/schedule/calendar.tsx` (line 275): Same guard applied.

## Verification
- Admin login: No timeclock widget on dashboard ✅
- Landscape tech (carlos): Timeclock widget visible on schedule page ✅

## Dependencies installed
- None

## Known issues
- None introduced by this change.
