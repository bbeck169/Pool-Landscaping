## Iteration 76 — Schedule map show/hide toggle

### What was implemented
- Collapsible map toggle bar in the Schedule Grid view (`calendar.tsx`)
- "Hide map" (blue icon, chevron-up) / "Show map" (grey icon, chevron-down) toggle
- When hidden: DailyRouteMap + List|Map segmented control are both removed from the render tree
- When map is hidden and user had "Map" sub-mode selected, the ScheduleMapLazy also stays hidden (forces list view)
- Preference stored under key `schedule.mapVisible` using existing `storage` utility (AsyncStorage on native, localStorage on web)
- Default: `true` (map visible)

### UX decision documented
- When map is hidden, the List|Map segmented control is hidden along with it (cleaner option per requirements)
- The toggle bar itself always remains visible so the user can restore the map
- The toggle doesn't affect the top-level Calendar|Grid mode switch — orthogonal concern

### Accessibility
- `accessibilityLabel` dynamically set: "Hide map" / "Show map"
- `accessibilityRole="button"`
- `testID="schedule-map-toggle"`

### Tests created
- `mobile/__tests__/schedule-map-toggle.test.tsx` — 8 tests, all passing:
  1. Toggle renders with correct initial state
  2. Shows "Hide map" when visible (default)
  3. Tapping hides map, shows "Show map"
  4. Tapping again restores map
  5. Persists `false` to storage on hide
  6. Persists `true` to storage on show
  7. Reads saved preference `false` on mount
  8. Reads saved preference `true` on mount
  9. Has correct accessibility props (label changes dynamically)

### Dependencies installed
- None (used existing `storage` utility, `Ionicons`, `Pressable`)

### Known issues
- None introduced. Pre-existing test failures in schedule-select-all and schedule-card-notes-visibility are unrelated.

### Deferred items
- None
