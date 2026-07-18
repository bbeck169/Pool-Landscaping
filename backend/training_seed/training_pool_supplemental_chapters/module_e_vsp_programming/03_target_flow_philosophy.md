# Module E — VSP Programming · Chapter 3: Target-based programming philosophy

*Original in-house authorship. Concepts only — refer to the OEM manual for the specific keystrokes on the model in front of you.*

The programming philosophy that unifies every VSP brand is:

> Do not program to a fixed RPM. Program to a **target flow** (GPM) that meets the duty at hand.

For each equipment-pad duty, you calculate the flow needed and then choose the RPM that delivers it on this specific plumbing. Because head loss varies pool-to-pool with pipe size, valve count, filter type, and heater bypass, the same target GPM produces different RPMs on different pads. That's a feature, not a bug.

The duties and their target flow logic:

- **Turnover.** Pool volume divided by desired turnover hours × 60. E.g., a 20,000-gal pool with an 8-hour turnover target needs `20000 / (8 * 60) = 42` GPM average.
- **Skimming.** Requires enough surface flow to move debris to the skimmer. Rule of thumb: at least 15–20 GPM per skimmer.
- **Filter backwash.** Consult the filter label; sand backwash typically needs 15 GPM per sq ft of filter area.
- **Heater (gas or heat pump).** The unit label gives the minimum flow it needs to stop shutting off on flow switch. Typically 20–40 GPM.
- **Pressure-side cleaner (with booster pump).** Usually needs the main pump at moderate speed to prime the booster.
- **Suction-side cleaner.** Needs specific flow; the cleaner's manual states it.

Program the pump to the **lowest RPM that hits the target flow** for each duty. That RPM will be different from the pool next door, even at the same duty, because head loss differs.
