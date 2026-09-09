# Iteration 77 — Fix Expo Web Schedule Map + Header Layout Bugs

## What was implemented
- **Bug 1 (Web Map Fallback)**: Verified that `DailyRouteMap.web.tsx` already had a complete Leaflet/OSM iframe implementation from the previous agent's final write. The file renders real map tiles with `circleMarker` pins colored by job status, uses `fitBounds` for multi-pin views, and falls back to a placeholder when no geocoded stops exist. No additional code changes needed.
- **Bug 2 (Offline Banner Header Layout)**: Fixed `widgets.tsx` Header component's flexbox layout:
  - Added `minWidth: 0` to both the outer left flex row and the inner title/subtitle View
  - Added `flexShrink: 1` to the title/subtitle View
  - Added `numberOfLines={1}` and `ellipsizeMode="tail"` to the subtitle `<Text>` element
  - These changes prevent the RN Web quirk where flex items refuse to shrink below content width

## Web-to-mobile mapping decisions
- The web map uses `iframe srcDoc` with Leaflet CDN (no API key needed) — this is the correct approach since `@rnmapbox/maps` doesn't support web
- The header fix is specific to React Native Web's flexbox behavior differences vs native

## Files modified
- `/app/mobile/src/components/widgets.tsx` (lines 93, 100, 104-108)

## Files referenced
- `/app/mobile/src/components/schedule/DailyRouteMap.web.tsx` (verified complete)
- `/app/mobile/src/components/OfflineBadge.tsx` (checked for width constraints)
- `/app/mobile/app/(app)/schedule/calendar.tsx` (checked OfflineBadge usage in Header right prop)

## Dependencies installed
- None

## Known issues
- None — both bugs verified fixed via screenshot
