## Iteration 105 — Phase M1 finish: Remaining items closeout

### What was implemented

1. **LiveTechPinsMap consumer migration** — Switched from wrapping `<Text>{initials}</Text>` as children to using the redesigned `label={initials}` prop. The initials now render inside the white disc via the pin's native SVG text-centering path. Removed the now-unused `pinText` style definition.

2. **ColorPicker integration on Technician detail page** — Full rewrite of `app/technician/[id].tsx`:
   - Admin-only collapsible "Map pin color" section with a color dot preview.
   - `<ColorPicker />` opens inline with presets, recents, freeform hex + hue slider, and contrast guard.
   - On Apply: PATCHes `/api/users/{user_id}` with `{display_color_hex: hex}`.
   - Server 400 `color_contrast_too_low` handled with a user-visible alert.
   - Fire-and-forget `POST /api/users/me/recent-colors` on success.
   - Refreshes the tech record in-memory to show the new color dot immediately.

3. **DailyRouteMap cleanup** — Removed unused `pinNumber` style (no longer needed since label is rendered by the pin itself).

4. **3 Jest test files (27 tests total, all passing)**:
   - `colorContrast.test.ts` (8 tests): pure white, near-white, primary blue, pure black, malformed hex, canonical normalization, NaN luminance.
   - `TeardropPin.test.tsx` (12 tests): default render, labeled pin, selected scale, custom color + a11y, pulse halo, helper exports (colorFromId, deriveDarker, mixWithWhite, formatPinLabel, pickLabelTextColor).
   - `ColorPicker.test.tsx` (7 tests): preset row from mock fetch, recently-used hydration, #FFFFFF blocks Apply + shows warning, valid dark hex enables Apply, save flow calls onChange + recent-colors POST, preset tap fires onChange, empty recents hides row.

### Dependencies added
- `@react-native-community/slider` — pure-JS Slider for the HSL hue picker. Zero new native modules (no autolinking). Chosen because it's the official React Native community slider, works on web/iOS/Android, and avoids adding any native color-picker library.

### Consumer update summary
| Consumer | Status | Change |
|---|---|---|
| DailyRouteMap.native.tsx | ✅ Done (iter 104) | children → `label={num}` |
| LiveTechPinsMap.tsx | ✅ Done (this iter) | children → `label={initials}` |
| ScheduleMap.native.tsx | ✅ No change needed | Already uses only `color` prop — compatible |
| MapCanvas.native.tsx (d2d) | ✅ No change needed | Uses native `Marker pinColor`, not TeardropPin |
| Technician detail | ✅ Done (this iter) | Added ColorPicker for admin crew-color editing |

### Known issues
- Pre-existing: `k61-checklist-contract.test.ts` still fails (unrelated to this work).
- Screenshot tool couldn't reach tech detail page directly (login + navigation required). Verified app boots clean with no red-box. Full screenshot verification of the pin on a map with numbered labels deferred to the testing agent.
