# Valve Diagnostics — Controller-Side vs. Field-Side Isolation

**Original in-house authorship. Consult the OEM manual for model-specific torque and rebuild kit specs.**

When multiple zones misbehave at once, or a single zone acts inconsistently across days, the field question is always: is the problem at the controller, or out at the valve? Getting that isolation right is the difference between a fifteen-minute fix at the controller and a two-hour dig-and-splice in the field. This chapter is the walkthrough we use to answer that question before we ever pick up a shovel.

**Symptoms that suggest the controller side.**
- Multiple zones affected at once (independent valves rarely fail simultaneously — a shared cause is upstream)
- Behavior changes when the controller is reset or reprogrammed
- Zones run at unscheduled times or don't run when scheduled
- Common wire connection at the controller shows corrosion or looseness

**Symptoms that suggest the field side.**
- A single zone is affected while all others work normally
- Behavior is consistent with a mechanical failure (e.g., weep with the controller off is nearly always a diaphragm/bleed issue at the valve, not a controller issue)
- Recent digging, new landscaping, or trench work near the valve or between the controller and valve
- Visible corrosion, water intrusion, or damage at the valve box

**Isolation test 1 — Manual bleed at the valve.** Every zone valve has a manual bleed screw. Turning it a quarter turn open should open the valve mechanically, independent of the controller. If manual bleed opens the zone and it flows normally, the valve mechanics are fine — the problem is on the electrical side (controller, wire, or solenoid coil). If manual bleed does not open the zone, or the flow is weak, the problem is mechanical (diaphragm, debris, or supply pressure).

**Isolation test 2 — 24V at the solenoid wires.** With the controller commanded to run the failing zone, disconnect the solenoid leads and measure AC voltage between them. 24V present with correct behavior mismatched means the electrical signal is arriving fine; the failure is at the solenoid or downstream. No voltage means the failure is upstream — controller output, station terminal, junction splice, or common wire.

**Isolation test 3 — Substitute a known-good zone at the controller.** Move the failing zone's field wire to a controller terminal that you know works. Run the same test again from the controller's UI. If the zone now behaves correctly, the original controller terminal is failing (bad triac, corroded terminal, or open output). If the zone still fails, the problem is downstream from the controller — in the wire or at the valve.

**Isolation test 4 — Substitute a known-good valve at the field end.** Move the failing zone's wire to a valve that you know works. If the "borrowed" valve responds correctly, the original valve has the failure. If it doesn't, the wire between the controller and that valve position is compromised.

**Common controller-side failure modes.**
- **Bad output on one terminal.** Triac failure inside the controller — replace or swap channel wiring to a working terminal.
- **Corroded common connection.** Corrosion at the common terminal affects every zone using that common. Clean and tighten, or move the common to a fresh terminal on the barrier strip.
- **Failed backup battery (dry contact controllers).** Loses programming after every power blip; symptom is inconsistent scheduling and settings that "reset themselves."
- **Water intrusion inside the controller enclosure.** Silent killer — check for stains, salt whiskers, or ants around terminals. If the enclosure is compromised, you're diagnosing symptoms of a controller that's already been damaged.

**Common field-side failure modes.**
- **Cut or nicked wire in the trench.** Digging, tree roots, or rodents. Test with a wire tracer if you can't visually locate the damage. Splices must use gel-filled waterproof connectors, never indoor wire nuts.
- **Corroded splice inside the valve box.** Old wire nuts corrode within a season or two of valve-box submersion. Cut back the corroded copper and re-splice with waterproof connectors.
- **Broken common at a junction box.** The common wire is shared across the entire system. A break in the common shows up as every zone downstream of the break dropping out at the same time.

**When both sides look fine.** If controller-side and field-side both test clean but the zone still misbehaves, the intermittent culprit is usually one of three things: a marginal solenoid coil that only fails when hot, a partially plugged pilot orifice, or a common wire that flexes and opens under thermal expansion. Replace the solenoid, clean the pilot, and inspect any common splice point. In stubborn cases, a temporary in-line wire tester left in place for a run cycle catches intermittent opens that a static resistance measurement will miss.

Field tip: sketch the system on a scrap of paper before you start testing. The value of a diagnostic is knowing what you've eliminated. On complex systems (twelve or more zones, multiple valve boxes) it's easy to lose track of what you've tested, and running the same test twice while missing an entire branch is how afternoons disappear.
