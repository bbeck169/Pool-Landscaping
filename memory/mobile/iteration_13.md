# Iteration 13 — BUG H + BUG I Fix

## BUG H: Auto Clock-In page error
- **Root cause**: `src/background/autoClockin.ts:53` — `storage.get()` does not exist. The storage module exports `getItem()` / `setItem()`, not `get()` / `set()`.
- **Error message**: `_srcUtilsStorage.storage.get is not a function`
- **Stack trace**: `isAutoClockinEnabled` → `auto-clockin.tsx:26` (useEffect)
- **Fix**: Changed `storage.get` → `storage.getItem` and `storage.set` → `storage.setItem`
- **Additional**: Added `Tabs.Screen` entries for `settings/auto-clockin` and `settings/lidar` in `(app)/_layout.tsx`

## BUG I: Settings should be admin-only
- **Root cause**: `settings/_layout.tsx` was a bare `<Stack>` with no role guard. All `/settings/*` routes were accessible by URL to any role.
- **Fix**: Rewrote `settings/_layout.tsx` with `useAuth()` role check — non-admin/super_admin users see a "Not authorized" gate.
- **Also fixed**: `tenant.tsx` allowed `manager` role; removed per spec (settings = admin-only).

## LandscapingClockWidget
- Already correct: `isLandscaper = !isAdminLike && hasLandscapeDept` (fixed in Iteration 12)

## Files changed
- `src/background/autoClockin.ts` — storage API fix
- `app/settings/_layout.tsx` — admin role guard (rewritten)
- `app/settings/tenant.tsx` — removed manager from allowed
- `app/(app)/_layout.tsx` — added 2 hidden Tabs.Screen entries

## Known issues
- No mobile test suite (jest/detox) exists — all verification via screenshots.
- `GET /api/jobs/next` still 404 (deferred — backend issue).
