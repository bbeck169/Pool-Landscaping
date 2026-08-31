# Iteration 48 — Schedule NavigateJobButton (Mobile Parity)

## Date: 2026-08-30

## What was implemented

### 1. Maps Deep-Link Helper
- `src/services/navigation/mapsDeepLink.ts` (84 LOC):
  - `resolveDestination(job)` — coords (finite, non-0,0) > address > null
  - `buildGoogleMapsUrl(dest)` — universal `https://www.google.com/maps/dir/...` URL
  - `openMaps(dest)` — platform-specific routing:
    - iOS: `comgooglemaps://` → `maps://` fallback (Apple Maps)
    - Android: `google.navigation:q=` → https fallback
    - Web: always `https://www.google.com/maps/dir/...`

### 2. NavigateJobButton Component
- `src/components/schedule/NavigateJobButton.tsx` (89 LOC):
  - Props: `job` with `id`, `latitude`, `longitude`, `address`, `customer_name`
  - Renders 30x30 Pressable with `navigate-outline` Ionicon
  - Animated scale on press (spring 0.85 → 1.0)
  - Disabled: greyed out, tap shows Alert "No address on file"
  - testID: `schedule-job-nav-{job_id}` (web parity)
  - Accessibility: `accessibilityRole="button"`, `accessibilityLabel="Navigate to {name}"`, `accessibilityHint`

### 3. Mount Point
- Added to `app/(app)/schedule/calendar.tsx` JobRow, after CouldNotServiceButton and before status pill
- Separate Pressable — doesn't bubble to parent row tap (React Native's touch system handles this naturally via separate Pressable boundaries)

### 4. No New Dependencies
- `expo-linking` already installed (8.0.12)
- `expo-web-browser` already installed (15.0.11)

## Test results
| Suite | Tests | Status |
|-------|-------|--------|
| navigate-job-button.test.tsx | 12/12 | ✅ |
| mapsDeepLink.test.ts | 7/7 | ✅ |
| **Full regression** | **745/766** | 8 pre-existing, 0 new |

## Web-to-Mobile mapping
| Web | Mobile | Notes |
|-----|--------|-------|
| `NavigateJobButton.jsx` | `NavigateJobButton.tsx` | Same props, testID, disabled logic |
| `window.open(url, "_blank")` | `openMaps(dest)` via Linking | Native maps preferred on iOS/Android |
| `stopPropagation()` | Separate `Pressable` boundary | RN touch system naturally isolates |
| Tooltip "No address" | `Alert.alert("No address on file")` | Mobile equivalent |
| `lucide-react` Navigation icon | `Ionicons navigate-outline` | Matches app convention |
