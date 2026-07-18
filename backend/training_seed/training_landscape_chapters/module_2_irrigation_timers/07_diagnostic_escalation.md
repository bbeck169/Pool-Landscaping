# Module 2 — Irrigation Timers/Controllers · Chapter 7: Diagnostic + escalation

*Original in-house authorship. Consult the OEM manual for brand-specific fault codes.*

## Universal fault categories

- **Zone short-circuit.** The controller detected an over-current on one zone output. Cause: pinched wire, corroded splice, shorted solenoid. Isolate by disconnecting each zone wire at the controller and testing zones one at a time. When the fault clears, you found it.
- **Common wire fault.** Every zone fails simultaneously. Cause: cut common. Trace with a wire toner (Module 1 Chapter 6).
- **Program corruption.** Schedule appears to reset randomly. Cause: dead backup battery on older controllers, or firmware bug on smart controllers. Battery is a $2 fix.
- **Total non-response.** Nothing works. Cause: 120 VAC power lost (breaker tripped, wall wart unplugged), OR the internal 24 VAC transformer has failed.

## Test tools

- **Multimeter** — read the transformer output (24 VAC ± 3 V) at the controller terminals. Below 20 VAC = failing transformer, above 27 VAC = brand-new transformer running high (rare, usually harmless).
- **Solenoid activator / valve locator** — fires a solenoid directly, bypassing the controller, to isolate wire vs. controller faults.
- **Continuity tester** — cheap, sufficient for most zone-wire troubleshooting.

## Escalation triggers

- Any 120 VAC repair (transformer replacement, receptacle work) → licensed electrician.
- Repeated firmware corruption after 2 replacement backup batteries → controller EOL; recommend replacement.
- Persistent cloud connectivity issues after router + reauth → OEM warranty return.
- Sensor input reads 0 VAC when it should read 24 VAC → controller board fault, warranty return.

## Documentation

Every controller service call logs: brand + model, firmware version if smart, symptom category, parts replaced, controller test result after service. This is the audit trail that supports warranty claims + repeat-visit optimization.
