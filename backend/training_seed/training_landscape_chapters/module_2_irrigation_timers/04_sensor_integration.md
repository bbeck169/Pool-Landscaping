# Module 2 — Irrigation Timers/Controllers · Chapter 4: Sensor integration

*Original in-house authorship. Consult the OEM manual for wiring diagrams.*

Sensors that connect to a controller:

- **Rain sensor** — a small disc that swells with moisture and opens a switch. Standard normally-closed contact wired to the SEN terminals. When it rains, the switch opens, controller suspends watering. Cheap, dumb, effective.
- **Freeze sensor** — combined with rain sensor in most modern units. Opens the switch when temperature drops below a threshold (typically 37°F).
- **Soil-moisture sensor** — probe buried in the root zone reads volumetric water content. More accurate than rain sensors because it measures what actually reaches the roots.
- **Flow sensor** — inline turbine on the mainline reports actual GPM. Enables flow-based leak detection (see Chapter 5).
- **Wind sensor** — rare on residential; standard on commercial. Suspends watering when wind exceeds a threshold to prevent overspray.

**Wiring rules for switch-type sensors:**

- Two-wire connection to SEN terminals.
- Sensor bypass switch on the controller face — ALWAYS returned to "active" after any diagnostic work.
- Do not wire a sensor in series with a zone valve — it belongs on the SEN input, not in the zone loop.

**Common failure:** rain sensor stuck in the "wet" position after a heavy rain and never resets → all zones off indefinitely. Customer calls "my system is broken." Fix: replace the sensor cup, or (temporary) toggle the bypass switch until the sensor dries.

**Sensor testing:** with the sensor disconnected, jumper the SEN terminals with a paperclip. If the controller now runs zones, the sensor is faulty. Reconnect the paperclip test wire when you leave.
