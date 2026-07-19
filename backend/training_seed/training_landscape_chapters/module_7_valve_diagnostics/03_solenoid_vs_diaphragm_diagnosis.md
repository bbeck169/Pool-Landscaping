# Valve Diagnostics — Solenoid vs. Diaphragm Failure

**Original in-house authorship. Consult the OEM manual for model-specific torque and rebuild kit specs.**

When a zone valve misbehaves, the failure is almost always in one of two places: the solenoid (electrical/mechanical actuator) or the diaphragm (the rubber sealing element). Getting the right diagnosis before you rip the valve apart saves time, saves parts, and saves the customer from an unnecessary bill. This chapter is the decision tree we use in the field to isolate solenoid problems from diaphragm problems in the first five minutes of a service visit.

**Recap of how the valve opens.** The controller sends 24V AC to the solenoid coil. The solenoid's iron plunger lifts, opening a small bleed port. Water pressure on the upper side of the diaphragm can now escape through that bleed port faster than it's being refilled through the tiny pilot orifice. Pressure drops above the diaphragm; the higher pressure on the downstream side lifts the diaphragm; the main port opens; the zone runs. Understand this sequence and every failure mode maps to one of five specific components.

**Failure mode 1 — Zone won't turn on.** Manually run the zone from the controller. If it doesn't open, disconnect the solenoid leads at the valve and measure AC voltage between the two solenoid wires with a multimeter. Expected: about 24V AC while the controller is calling that zone.

- If you see 24V at the wires, the controller and wiring are good; the problem is at the valve. Remove the solenoid, look for debris in the seat, and check the plunger's free movement. Nine times out of ten this is a fouled solenoid — replace it. If the new solenoid also doesn't open the valve, suspect debris in the pilot orifice or a torn diaphragm holding pressure in place.
- If you don't see 24V, the problem is upstream. Test at the controller terminal, then at each junction working back toward the valve. Broken common wire is a very common cause and shows up as multiple zones affected on the same common.

**Failure mode 2 — Zone won't shut off.** The controller's off, but the zone keeps flowing. Two possibilities, distinguished by one quick field test.

- **Close the manual bleed screw fully.** If flow stops, the bleed port was being held open by debris — either debris in the bleed port itself or a solenoid that isn't seating. Clean or replace the solenoid.
- **If flow continues with the bleed fully closed,** the diaphragm's primary seal has failed. Either the diaphragm is torn or the body seat is scored. Rebuild the valve or replace the diaphragm assembly.

**Failure mode 3 — Zone weeps or runs at reduced volume.** Reduced flow is usually a debris issue upstream (main line, filter screen) or a partially seated diaphragm. Steady weeping with a low flow footprint is a diaphragm just at the edge of failure — it's not fully sealing but it's not fully open either. Rebuild is warranted; a partially failing diaphragm never gets better.

**Failure mode 4 — Zone chatters or hammers.** Rapid open-close cycling of the diaphragm, usually caused by a partially plugged pilot orifice. Very high inlet pressure combined with a marginally sized main line can also do this. First step: clean the pilot orifice and the underside of the solenoid seat. If chatter persists, check inlet pressure — anything over 80 psi at the zone valve is aggressive and often requires an in-line pressure regulator upstream.

**Failure mode 5 — Solenoid coil open (rare but hard to spot).** Coil resistance should read approximately 20-60 ohms depending on model. An open (infinite resistance) or shorted (near zero) reading confirms coil failure. Always measure resistance with the solenoid disconnected from the controller — never in-circuit.

Field tip: keep a bag of assorted OEM-compatible solenoids and diaphragms in the truck. Nine out of ten valve failures are solved by swapping one of these two parts on the same visit — coming back the next day for a $12 solenoid you didn't have on hand is what turns a good service call into a bad one.
