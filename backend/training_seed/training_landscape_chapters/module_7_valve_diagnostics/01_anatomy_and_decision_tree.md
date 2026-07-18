# Valve Diagnostics — Anatomy and the Symptom-to-Cause Decision Tree

**Original in-house authorship. Consult the OEM manual for model-specific torque and rebuild kit specs.**

An irrigation zone valve is a normally-closed diaphragm valve opened by a small electric solenoid. When the controller sends 24V AC to the solenoid, the solenoid opens a bleed port; pressure differential across the diaphragm shifts; the diaphragm lifts and the valve opens. When the controller drops the signal, the bleed port closes, pressure re-seats the diaphragm, and the valve shuts. Understanding this sequence lets you narrow every field symptom to one of three subsystems.

The three subsystems are:
1. **Electrical** — controller, wire, and solenoid coil.
2. **Hydraulic** — diaphragm, bleed port, and body seat.
3. **Debris / mechanical** — foreign material, torn diaphragm, cracked body.

The symptom-to-cause decision tree:

**Symptom: valve won't open on schedule.**
- First test electrical continuity between the controller terminal and the solenoid. A 24V AC reading at the solenoid means electrical is good — the fault is hydraulic or debris.
- No 24V at the solenoid: check wire path for cuts, splices, or bad ground.
- Voltage at solenoid but valve doesn't open: manually bleed the valve using the built-in bleed screw. If manual bleed opens the valve, the solenoid is bad or its port is fouled. If manual bleed also fails, debris is preventing diaphragm lift.

**Symptom: valve won't close (weeps or runs continuously).**
- Manually cycle the bleed screw. If closing the bleed screw closes the valve, debris is trapped in the bleed port.
- If the valve still weeps with the bleed closed, the diaphragm is torn or the body seat is scored — a rebuild or replacement is needed.

**Symptom: valve hums but won't fully open.**
- Low system pressure or too much flow — check upstream pressure and downstream head count.
- Solenoid drawing but stuck partially open — replace the solenoid.

**Symptom: multiple zones acting up together.**
- Almost always a controller or common-wire problem. Check controller output and the common-wire connection at the valve box.

Field tip: carry a multimeter set to AC volts and a small flat-head screwdriver every time. Ninety percent of valve calls are diagnosed in three minutes by measuring voltage at the solenoid and manually bleeding the valve. Only after those two steps have failed do you need to open the valve body.
