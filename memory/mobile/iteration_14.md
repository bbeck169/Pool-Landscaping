# Iteration 14 — BUG H Regression + Default-ON Feature

## BUG H Regression
- Root cause: Metro bundler cache served stale code after file was fixed on disk.
- Fix: Cleared all caches (`rm -rf .metro-cache node_modules/.cache /tmp/metro-* /tmp/haste-map-*`) + `supervisorctl restart mobile`.
- Verification: Grepped entire codebase — zero `storage.get`/`storage.set` (non-Item) callsites.

## Auto Clock-In Default-ON Feature
- `isAutoClockinEnabled(role)` now uses a two-key system:
  - `auto_clockin_explicit` (boolean) — tracks if user has EVER toggled
  - `auto_clockin_enabled` (boolean) — the actual preference
  - If explicit is false → return `true` for techs, `false` for others (default-ON)
  - If explicit is true → return the saved preference
- Screen rewritten with:
  - Green/red ON/OFF status banner
  - Role gate for non-technicians
  - Info text explaining default-ON behavior
  - Status text showing Running/Stopped

## Backend Gaps (for web agent)
1. **Add `auto_clockin_enabled: bool` to user model** — default `true` for tech role
2. **Add support in `PATCH /api/users/{id}`** — accept `auto_clockin_enabled`
3. **Add self-PATCH for techs** — `PATCH /api/auth/me` or allow tech to patch own profile
4. **Backfill**: On boot, set `auto_clockin_enabled=true` for all existing tech users where field is missing
5. **Admin panel**: Add "Auto Clock-In enabled" column with toggle on the Team/Users page

## Files changed
- `src/background/autoClockin.ts` — default-ON logic
- `app/(app)/settings/auto-clockin.tsx` — full rewrite

## Known issues
- Preference is local-storage-only (doesn't survive app reinstall until backend support lands)
