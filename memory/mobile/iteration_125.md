# Iteration 125 — Live Tech GPS pins + Multi-Property map pins (mobile Schedule map)

- Screen: app/(app)/schedule/calendar.tsx day view → ScheduleMapLazy → ScheduleMap.native (react-native-maps via @/src/lib/maps).
- Jobs: GET /api/jobs?start=&end= — backend already resolves coords into location_lat/lng and stamps coord_source/property_id/property_label.
- Role discriminator: `useAuth().user.role` (same user context as Clock-In gate); list = backend _GPS_READ_ROLES.
- Deviation: web renders the toggle for every role (default OFF for techs → 403 if turned on). Mobile hides it + never polls for non-GPS roles.
- Approximate pin = wrapper View (2px dashed deriveDarker ring + opacity 0.7); no <Circle> overlay (meters-based, wrong at zoom; also Circle absent in test mocks).
- Not ported: Expo-web ScheduleMap placeholder (no map there). Older dispatch board LiveTechPinsWrapper (/gps/live-positions) untouched.
- Deps: none.
