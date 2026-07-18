# Module E — VSP Programming · Chapter 6: Automation-controller integration

*Original in-house authorship. Refer to the OEM manuals of the specific controller and pump for the exact keystrokes.*

When the pool has an automation controller (any brand), the VSP is usually **slaved to the controller** via a low-voltage signal cable or the manufacturer's proprietary bus. The pump's on-board schedule is disabled and the controller becomes the source of truth. This is the correct configuration — do not run both schedules simultaneously, or the controller and the pump will fight each other and confuse the customer.

Two integration modes to know:

**Mode 1 — On/off relay.** The controller triggers the pump like a fixed-speed pump; the pump internally decides its own RPM from a static schedule programmed into it. Cheapest, dumbest, works.

**Mode 2 — Speed request.** The controller directly tells the pump what RPM to run for each duty (spa mode, cleaner mode, floor cleaner, etc.). This is the setup that enables per-duty speed optimization. Requires a specific cable that varies by controller brand — reference the controller's install manual for the correct wiring diagram.

**Common problem:** the pump keeps returning to a default RPM after a power flick or controller reboot. Fix path: check the pump's "control source" setting — it should be "external" (not "internal / local"). The exact menu label varies by brand and model; use the OEM manual.

**Salt cell integration.** Many salt cells share the same low-voltage bus. Verify the pump doesn't drop below the cell's flow switch minimum during any programmed window. If the cell is turning off + on unexpectedly, the schedule is dipping the pump below the cell's flow floor.
