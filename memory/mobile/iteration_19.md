# Iteration 19 — WeekStrip + Colored Left-Border (Schedule Page Parity)

## What was implemented

### New Files (2)
1. **`src/components/schedule/WeekStrip.tsx`** — Native port of web's `WeekStrip.jsx`
   - 7-day Mon–Sun horizontal strip with `<` / `>` chevron week navigation
   - Selected day: filled blue circle with white text + shadow
   - Today: small dot marker below date number (visible on other weeks)
   - Auto-selects today on mount when no `selectedDate` provided
   - Uses `TouchableOpacity` for day buttons, `Ionicons` for chevrons
   - Styled with `StyleSheet.create()` using theme tokens

2. **`src/utils/scheduleStatus.ts`** — Status border color helper
   - `getStatusBorderColor(status)` → `#DC2626` (red) for completed, `#2563EB` (blue) for all other statuses
   - Direct port of web's exported `getStatusBorderColor` from `CalendarSchedule.jsx`

### Modified Files (1)
3. **`app/(app)/schedule/calendar.tsx`** — Schedule screen integration
   - Imported `WeekStrip` and `getStatusBorderColor`
   - WeekStrip placed between LandscapingClockWidget and mode switch
   - `onSelectDate` callback updates existing `focus` state (no new state needed — reuses existing date management)
   - `JobRow` card: added `borderLeftWidth: 4, borderLeftColor: statusBorder` to card style

## Web-to-Mobile Mapping

| Web Element | Mobile Element | Notes |
|-------------|---------------|-------|
| `WeekStrip.jsx` | `WeekStrip.tsx` | Same date math, different rendering (RN components) |
| `getStatusBorderColor()` | `getStatusBorderColor()` | Identical logic |
| `border-left: 4px solid ${color}` on job card | `borderLeftWidth: 4, borderLeftColor: color` on Pressable | Same visual |
| `lucide-react` ChevronLeft/Right | `@expo/vector-icons` Ionicons | Same visual meaning |
| `date-fns` helpers | Raw `Date` math | Already used in existing schedule code |

## API Endpoints
No API changes — same endpoints as before. Client-side only.

## Divergence from Web
- The web page has the WeekStrip feeding into both Calendar and Grid mode. On mobile, it feeds into the shared `focus` state which drives both modes identically.
- The web's `focusISO` is computed from `format(date, "yyyy-MM-dd")` using date-fns. Mobile uses `d.toISOString().slice(0,10)`. Same result.

## Testing
- No Jest/Testing Library infra exists in the mobile project. Tests skipped; noted in report.
- Visual verification done via 5+ screenshots across admin and tech roles.

## Dependencies
None new — all dependencies already present.
