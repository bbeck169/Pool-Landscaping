# Iteration 68 — Phase K32: Tech-scoped mobile Schedule

## What was done
- **Auto-scope tech schedule fetch**: When `role === "technician"` or `role === "tech"`, the `/api/jobs` request now includes `&technician_id=<user.id>` (defense in depth — even if server scopes, the client enforces).
- **Hidden CrewFilterBar for techs**: The `<CrewFilterBar>` component is wrapped in `{!isTech && crews.length > 0}` — techs never see crew filter controls.
- **Crew filter bypassed**: When isTech, `crew_id` is NOT appended to the URL even if `crewFilter` state has a leftover value.
- **Both role spellings handled**: `isTech = role === "technician" || role === "tech"` covers both K6 codebase spellings.
- **Admin/Manager/Dispatcher unchanged**: They still see all jobs + filters (no `technician_id` forced).
- **Nothing persisted**: The auto-scope is derived from role at render time, not stored.

## Changes
| File | Change |
|---|---|
| `calendar.tsx` line 152 | `isTech` now checks `"technician" \|\| "tech"` |
| `calendar.tsx` line 275-278 | `load()` appends `technician_id` for techs, skips `crew_id` for techs |
| `calendar.tsx` line 305 | Removed unused eslint-disable; added `isTech` to deps array |
| `calendar.tsx` line 634 | Pass `isTech` prop to GridView |
| `calendar.tsx` line 746 | GridView destructures `isTech` |
| `calendar.tsx` line 787 | CrewFilterBar hidden when `isTech` |
| `__tests__/k32-tech-scoped-schedule.test.tsx` | 6 tests covering all scenarios |

## API verification
- Admin (14 jobs in window) vs Tech with technician_id (3 jobs) — confirmed server-side filtering works

## Test results
- 6/6 K32 tests pass
- No regressions in existing tests

## Screenshots
- Tech schedule: No crew filter, "3 jobs in window", Navigate + Actions visible
- Admin schedule: Crew filter area present (no crews in demo data), "New job" button visible
