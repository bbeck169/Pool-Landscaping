# Iteration 95 — Phase M1: Sitewide Custom Teardrop Map Pin

## What was implemented
- Created `/app/mobile/src/components/maps/TeardropPin.tsx` — SVG teardrop pin component with:
  - 36×48 px teardrop silhouette via `react-native-svg`
  - Hollow center (white circle cutout)
  - `deriveDarker()` for stroke color
  - `colorFromId()` — 12-color deterministic palette
  - Pulsing halo ring via `react-native-reanimated`
- Updated `LiveTechPinsMap.tsx` — teardrop pins with per-tech colors + pulse for fresh GPS
- Updated `DailyRouteMap.native.tsx` — teardrop pins preserving numbered overlay + status badges
- Updated `ScheduleMap.native.tsx` — teardrop pins replacing native `pinColor` markers

## Files Modified
- `/app/mobile/src/components/maps/TeardropPin.tsx` (NEW)
- `/app/mobile/src/components/dispatch/LiveTechPinsMap.tsx`
- `/app/mobile/src/components/schedule/DailyRouteMap.native.tsx`
- `/app/mobile/src/components/schedule/ScheduleMap.native.tsx`

## Dependencies
- None new (react-native-svg 15.12.1, react-native-reanimated 4.1.1, react-native-maps 1.20.1 already installed)

## Deferred Items
- None
