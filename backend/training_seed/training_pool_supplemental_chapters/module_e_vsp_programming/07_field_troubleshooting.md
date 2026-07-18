# Module E — VSP Programming · Chapter 7: Field troubleshooting

*Original in-house authorship. Refer to the OEM manual for any specific fault code definitions — this chapter teaches diagnostic categories, not brand-specific codes.*

VSP fault categories (brand-agnostic):

**Overcurrent / drive faults.** The inverter drive detected a current spike. Common causes: seized impeller, low-voltage wiring shared with an inductive load like a heater igniter, or an actual motor winding fault. Cycle power and observe. If it faults immediately on restart, isolate the pump and consult the OEM.

**Communication faults.** The pump lost communication with the automation controller. Physical: check the low-voltage cable, terminal screws, and any inline splice. Logical: check that the controller and the pump are both set to the same protocol / speed setting mode.

**Flow / no-flow faults.** Reported by the salt cell or heater, not by the pump directly. Means the pump is running but the downstream device is seeing insufficient flow. Check filter pressure, salt cell scale, and the actual programmed RPM for the window in effect.

**Thermal / overheat.** The drive is inside the pump housing, so poor ventilation at the equipment pad drives thermal shutdowns. Verify the pump has clearance and isn't sun-baked at 115°F.

**Grounding / stray voltage.** Older pads that share ground with the salt cell can develop galvanic corrosion on the pump. Verify the equipotential bond is intact. A licensed electrician escalates if you find corroded lugs.

**When to escalate to the OEM.** Same repeated fault after 2 attempts, drive failure smell (electrical burn), physical damage to housing, or any suspected motor winding fault. Warranty claims on VSPs are usually handled by the OEM's authorized service network — not field-repairable.

**Customer education.** Homeowners frequently over-program their VSP into a fixed-speed pattern because they don't trust the low overnight setting. Take 5 minutes to explain the affinity-law arithmetic (Chapter 2). Once they understand a pump running at half speed uses 1/8 the electricity, they stop resetting it.
