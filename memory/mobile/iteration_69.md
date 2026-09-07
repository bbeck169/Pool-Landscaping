# Iteration 69 — Hotfix M1 + M2: Schedule bulk-action authz + row styling

## What was done

### M1 — Bulk-action strip hidden for tech role
- Changed the gate on the Actions dropdown in `calendar.tsx` from `{canWrite ?` to `{isAdmin ?`
- This fully unmounts the entire "Actions" button + dropdown modal for tech users
- Per-job row actions (On my way, Could not service) remain fully visible for techs
- The rearrange mode sections are also indirectly hidden (tech can't trigger them)

### M2 — Schedule row styling (4 visual changes)
1. **OnMyWayButton** → navy fill (`#1B1F5C`), white text/icon (was mint-green `#ECFDF5`/`#065F46`)
   - Both `primary` and `compact` variants updated
2. **CouldNotServiceButton** → danger red fill (`#DC2626`), white text/icon (was amber `#FEF3C7`/`#78350F`)
   - Both `compact` and `detail` variants updated
3. **NavigateJobButton** → prominent filled navy pill, 44×44 min tap target (was faint 30×30 `#EFF6FF` circle)
   - Changed to `#1B1F5C` bg, `navigate` (filled) icon, white icon color
   - Disabled state: `#D1D5DB` bg, 35% opacity
4. **JobNotesCallout** → white bg `#FFFFFF` with 3px amber `#F59E0B` left-accent border (was amber `#FEF3C7` fill)
   - Icon + toggle text still amber for "this is a note" scanability

## Files modified
| File | Change |
|---|---|
| `app/(app)/schedule/calendar.tsx` | Line 867: gate changed from `canWrite` to `isAdmin` |
| `src/components/schedule/OnMyWayButton.tsx` | Navy bg + white text for both variants |
| `src/components/schedule/CouldNotServiceButton.tsx` | Red bg + white text for both variants |
| `src/components/schedule/NavigateJobButton.tsx` | 44×44 navy pill, filled icon, removed unused `colors` import |
| `src/components/schedule/JobNotesCallout.tsx` | White bg, neutral border, amber left-accent |
| `__tests__/hotfix-m1-m2-schedule.test.tsx` | 10 new tests |

## Constants added
- `OnMyWayButton.tsx`: `NAVY = "#1B1F5C"`
- `CouldNotServiceButton.tsx`: `DANGER_RED = "#DC2626"`
- `NavigateJobButton.tsx`: `NAV_NAVY = "#1B1F5C"`
- `JobNotesCallout.tsx`: `AMBER_BG = "#FFFFFF"`, `AMBER_BORDER = "#E5E7EB"`

## Test results
- 10/10 M1+M2 tests pass
- 6/6 K32 tests still pass (no regressions)

## Screenshots
- **Tech (Mike, Wed 9)**: 4 job cards — navy "On my way", red "Can't service", navy 44px nav arrow, white notes with amber accent. No Actions button, no crew filter.
- **Admin (Alex, Wed 9)**: Same styled cards + Actions button visible + "All crews" dropdown + checkboxes + edit icons. 117 jobs vs 7 scoped.

## Platform caveats
- Verified on web viewport (Expo web). iOS/Android native rendering uses same StyleSheet — expected identical appearance.
- No `useSafeAreaInsets` or keyboard changes needed (button-only style updates).
