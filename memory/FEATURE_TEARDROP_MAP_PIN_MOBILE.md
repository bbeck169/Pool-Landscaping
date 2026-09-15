# Phase M1 — Sitewide Custom Teardrop Map Pin (Mobile)

## What was implemented

### New Component: `TeardropPin.tsx`
- **Location**: `/app/mobile/src/components/maps/TeardropPin.tsx`
- SVG teardrop silhouette (36×48 px) using `react-native-svg` `<Path>` + `<Circle>`
- Hollow center (white circular cutout in the pin head)
- Solid fill via `color` prop with 1px darker stroke via `deriveDarker()`
- Pulsing halo ring via `react-native-reanimated` `Animated.View` for "fresh GPS" state
- **Exports**: `<TeardropPin />`, `colorFromId(id)`, `deriveDarker(hex, pct)`
- `colorFromId()` uses a 12-color deterministic palette (expanded from the previous 8-color one)

### Updated: `LiveTechPinsMap.tsx`
- Replaced circular `<View>` pins with `<TeardropPin>`
- Uses `colorFromId(user_id)` for per-technician coloring
- Pulsing halo enabled on fresh (non-stale) pins
- Anchor set to bottom tip `{ x: 0.5, y: 1.0 }`
- Initials text overlaid inside the pin head

### Updated: `DailyRouteMap.native.tsx`
- `RoutePinView` now wraps `<TeardropPin>` instead of circular View
- Keeps numbered text overlay + status badges (completed checkmark, CNS warning)
- Status color semantics preserved (blue=pending, gray=completed, amber=CNS)
- Anchor set to bottom tip

### Updated: `ScheduleMap.native.tsx`
- Replaced native `pinColor` prop with custom `<TeardropPin>` child markers
- Status color semantics preserved
- Added `tracksViewChanges={false}` and anchor at bottom tip

## Web-to-Mobile Mapping
| Web Implementation | Mobile Implementation |
|---|---|
| Web has colored dots for live tech pins | Mobile now has teardrop pins with same color palette |
| Web uses staleness-based coloring | Mobile uses `colorFromId` + pulse for freshness |
| N/A (new mobile-only feature) | Pulsing halo ring for fresh GPS state |

## Dependencies
- No new dependencies needed (react-native-svg, react-native-reanimated, react-native-maps already installed)

## Known Issues
- None — app compiles cleanly with 2341 modules
