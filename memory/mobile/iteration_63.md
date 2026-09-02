## Iteration 63 — Phase K25: Schedule Crew filter + Active/Inactive customer filter
- **Commit**: 3db719aa9ac644e648795c72c3fcca26e69efb4f
- **Date**: 2026-09-02
- **Changes**:
  ### Grep inventory:
  - **Schedule crew filter**: Already fully implemented in prior phases:
    - `src/components/schedule/CrewFilterBar.tsx` — picker modal with crew color dots, member chips, "All crews" option
    - `app/(app)/schedule/calendar.tsx` — crew filter state, `crew_id` param in API fetch, K15 AbortController coordination
    - K25 addition: AsyncStorage persistence (`k25_schedule_crew_filter`) — reads on mount, writes on selection change
  - **Customers active/inactive filter**: Already fully implemented in prior phases:
    - `app/(app)/customers.tsx` — Active/Inactive/Waitlist/All segmented control (line 192-211)
    - `is_active` param mapped to API (line 78), persisted via `storage.setItem()` (line 199)
    - Portal activation filter also present (line 213-231)
    - **No changes needed** — already complete with persistence
  - `CrewFilterBar.tsx` **was available for reuse** ✅ — fully functional picker with modal, crew colors, member chips
  ### Files:
  - **Modified**: `app/(app)/schedule/calendar.tsx` (+9 lines — storage key, hydration in mount useEffect, persist in handleCrewSelect)
  - **Created**: `__tests__/scheduleCrewFilter.test.tsx` (7 tests — render, select, picker, empty)
  - **Created**: `__tests__/customersActiveFilter.test.tsx` (10 tests — query param mapping, persistence)
  - All 17 tests pass, metro bundles clean
  - Screenshots: app loads correctly at login (authenticated screens require login)
