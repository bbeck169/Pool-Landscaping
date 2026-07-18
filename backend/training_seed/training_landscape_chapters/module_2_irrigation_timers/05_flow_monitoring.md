# Module 2 — Irrigation Timers/Controllers · Chapter 5: Flow monitoring + leak alerts

*Original in-house authorship. Consult the OEM manual for flow-sensor calibration procedures.*

An **inline flow sensor** on the mainline reports GPM to the controller. High-end smart controllers use this for three things:

**Baseline flow per zone.** On the first run of each zone, the controller measures actual GPM at steady state. That becomes the "expected flow" for that zone.

**Leak detection.** If GPM during a subsequent zone run exceeds the baseline by more than a configured tolerance (e.g., 130%), a broken lateral is dumping water into the ground. The controller can shut the zone off automatically and email/text the customer.

**No-flow detection.** If GPM drops below the baseline by a large margin, either the valve failed to open or the mainline is empty (upstream problem).

**Broken-head detection.** Some smart controllers distinguish "small over-flow" (5–20% over baseline, likely one broken head) from "large over-flow" (>50% over baseline, likely a broken lateral). Reporting these separately helps the tech prioritize.

**Calibration.** Every flow sensor has a K-factor tied to pipe diameter. Wrong K-factor = wrong GPM reading = wrong leak thresholds. Verify at install per the sensor's manual.

**Escalation.** Repeated leak alerts on the same zone with no visible above-ground leak = subterranean lateral leak. Dig, don't guess. The alert threshold is not the problem.

**Customer value.** Flow monitoring pays for itself in one detected leak — a single broken lateral running 5 GPM for 24 hours = 7,200 gallons. Water bill + landscape damage typically exceeds the sensor cost within the first year.
