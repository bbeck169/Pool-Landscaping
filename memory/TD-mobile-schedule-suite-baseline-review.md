# TD-mobile-schedule-suite-baseline-review (P2 · Mobile · operator triage)

Filed 2026-10-25. This is a pre-existing Jest baseline problem; the sprint commits e49e39cb9, 49e246ebd, 4abc2707a, db938fb7c, 0f3fe6c91 and 94b10f310 did not cause it. No root-cause investigation was done. Each likely cause below comes only from the failure message seen in this session.

| Suite | Failure | Likely root cause |
|---|---|---|
| `schedule-card-notes-visibility.test.tsx` | JobNotesCallout bg expected `#FEF3C7`, got `#FFFFFF` | The callout colour changed after the test was written |
| `hotfix-m1-m2-schedule.test.tsx` | NavigateJobButton bg expected `#1B1F5C`, got `#F97316` | The button colour changed after the test was written |
| `s1-schedule-tech-filter.test.tsx` | 2 source-string checks (tech default filter; dayJobs/weekCounts/jobsByDay use `filteredJobs`) | Source drift: the code now uses `resolvedTechId` (K43) and `visibleJobs` |
| `phase-schedule-tech-filter-technician-id.test.tsx` | techScope check expects `user.technician_id` | Source drift: the code now uses `resolvedTechId` (K43) |
| `schedule-select-all.test.tsx` | Pattern `/canWrite\s*\?/` not found | The gate variable was renamed (`canWriteJobs`) or the gating pattern changed |
| `schedule-map-toggle.test.tsx` | Suite fails to load: `Cannot find native module 'ExpoTaskManager'` | `expo-task-manager` is not mocked in the test |
| `schedule-daily-route-map.test.tsx` | 3 failures: `schedule-daily-route-map-pin-num-j1` testID not found, plus a pin colour check | DailyRouteMap pin markup or colours changed |
| `k32-tech-scoped-schedule.test.tsx` | Suite fails to load: `Cannot read properties of undefined (reading 'bg')` in `StyleSheet.create` | A theme token is missing from the test's theme mock |

The 9th failing schedule suite, `schedule-sync-route.test.tsx`, is filed separately as `TD-mobile-schedule-sync-route-oom.md`.
