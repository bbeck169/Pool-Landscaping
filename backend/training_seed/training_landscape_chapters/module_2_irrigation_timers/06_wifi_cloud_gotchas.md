# Module 2 — Irrigation Timers/Controllers · Chapter 6: Wi-Fi + cloud gotchas

*Original in-house authorship. Consult the OEM manual + the customer's Wi-Fi provider for connectivity troubleshooting.*

Smart controllers depend on a persistent Wi-Fi connection to the OEM cloud for weather data + remote control. When something breaks in the customer's home network, the controller often surfaces vague symptoms — "schedule not running", "app can't connect", "showing offline."

**Diagnostic order:**

1. **Verify Wi-Fi is up at the equipment location.** Customer's router may be indoors while the controller is in the garage — signal strength drops through walls and metal doors. Bring a phone; if you can't connect to the Wi-Fi from where the controller is mounted, neither can it.
2. **Check for firmware updates.** OEMs push firmware silently; some updates require the customer to re-authorize the app.
3. **Check the OEM cloud status page.** If Rachio, Rain Bird, or B-hyve is having a service outage, the controller behaves as expected but the app doesn't respond. Not a repair item — wait it out.
4. **Router reboot.** The universal first fix. Ask the customer if they've rebooted their router; if not, ask them to.
5. **Guest network vs. main network confusion.** Customer changed their Wi-Fi password on the main network but the controller is still trying the old credentials. Reconnect via the app.

**Concept, not menu.** Every OEM's mobile app has a different reconfigure flow. Consult the app / OEM manual for the specific brand at hand — this chapter teaches the diagnostic order, not the exact taps.

**When to escalate.** If the controller repeatedly disconnects with no other Wi-Fi device having trouble, suspect the controller's Wi-Fi radio itself. Warranty-return per OEM procedure.

**Manual fallback.** Every smart controller has a physical "run zone now" option that works offline. Show the customer how to use it as backup on the day of install. Reduces future support calls.
