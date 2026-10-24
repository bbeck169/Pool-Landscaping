# TD-landscape-time-clock-unify-reads — P2

**Opened:** Feb-2026 (as part of `TD-timeclock-tech-clock-out-flow` sprint).
**Status:** NOT STARTED.
**Owner:** unassigned.

## Context

As of `TD-timeclock-tech-clock-out-flow` (Oct 2026 preview, Feb 2026 ticket cycle),
the hero-banner `LandscapingClockWidget` writes to `time_entries` via
`/api/workforce/clock-in` + `/api/workforce/clock-out`. Downstream display
surfaces — tech profile timecard (`/tech/time-clock`), admin
"Timesheets" (`/workforce/timesheets`), admin "Time Entries" bulk
list (`/admin/time-entries`), payroll runs, approval workflows,
`TimecardEditModal` — now surface widget-sourced shifts for free.

However, **`/landscape/time-clock`** (both the per-tech read side and the
admin team-aggregation panel) still reads from `timeclock_punches` via
`/api/timeclock/{mine-today,mine-summary,admin-summary}`. Mobile punches
continue to flow into `timeclock_punches` through `/api/timeclock/punch`.

### Resulting split

| Entry source | `/tech/time-clock` + admin Timesheets + admin Time Entries | `/landscape/time-clock` admin aggregation |
|---|---|---|
| Web widget | ✅ shows (after this ticket) | ❌ does NOT show (regression) |
| Mobile punch | ❌ does NOT show (same as before) | ✅ shows |
| TodaySchedule per-job clock-in | ✅ shows | ❌ does NOT show |

Net: the two admin review surfaces each see one of the two data sources, so
no single admin surface shows a landscape tech's complete day if they
clocked in on the web widget AND the mobile app on the same day.

## Fix shapes

Three options, pick one at ticket intake:

1. **Re-point `/landscape/time-clock` aggregation at `time_entries`.** Admin
   aggregation panel + `AdminPunchEditsPanel` read `time_entries` + synthesise
   the paired-shift shape `pairPunches.js` builds from `timeclock_punches`.
   Mobile punches stop appearing on `/landscape/time-clock` until the mobile
   app is also pivoted — mobile parity ticket required.
2. **Union both collections.** `GET /api/timeclock/admin-summary` returns rows
   from both collections normalised to the same shape. Lets both surfaces show
   both sources with no coordination work.
3. **Dual-write.** `/api/workforce/clock-in` additionally writes a mirror
   row to `timeclock_punches` (and vice versa for mobile punches). Simplest
   downstream, worst data-integrity footprint — two writes per shift, risk of
   divergence under partial-failure.

Recommended: option (2) union, with a 60-day migration window that then
flips mobile to `/workforce/clock-in` and retires `timeclock_punches`.

## Not blocking

The web clock-in/out flow and the standard admin timecard review surface
(`/workforce/timesheets`) are fully functional after
`TD-timeclock-tech-clock-out-flow`. This ticket covers the one secondary
admin surface (`/landscape/time-clock`) where web widget entries do not
appear until unification lands.
