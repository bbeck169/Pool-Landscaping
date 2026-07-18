# Module 2 — Irrigation Timers/Controllers · Chapter 2: Programs, start times, run times

*Original in-house authorship. Consult the OEM manual for exact programming steps.*

Every controller has three fundamental parameters for each zone:

- **Days** — which days of the week to water (or an interval like "every 3 days").
- **Start times** — the clock time(s) each day when the schedule begins.
- **Run time** — how long each zone runs when its turn arrives.

The controller cycles zones **in sequence**, one at a time — never simultaneously (residential controllers have insufficient current to run two 24 VAC solenoids at once, and hydraulic capacity usually can't support parallel flow anyway).

**Distinct programs exist so different zones can run on different schedules.** Example: turf zones on one program watering 3x/week; drip zones on a second program watering 2x/week for longer durations. Assigning every zone to the same program and hoping for the best is the mistake that shows up on the callback list.

**Multiple start times per day** are for zones that need long runtimes — split them into two shorter starts (dawn + late-morning) to reduce runoff on clay soil or sloped lawns. The concept is "cycle-and-soak": water 10 minutes → wait 30 → water 10 more, so the soil can absorb between cycles.

**Seasonal adjust (%)** is a global multiplier applied to every zone's runtime. 100% is summer; 60% is fall/spring; 20% or off for winter. Legacy controllers require manual seasonal adjustment; smart controllers do this automatically from local weather data.
