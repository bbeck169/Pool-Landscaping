# Module 2 — Irrigation Timers/Controllers · Chapter 1: Controller anatomy

*Original in-house authorship. Hunter, Rain Bird, Toro, Rachio, B-hyve cited by name + external OEM manual link only. Consult the OEM manual for exact keypad/app procedures — this course teaches concepts, not menus.*

Every irrigation controller has the same architectural pieces regardless of brand or era:

- **Power supply** — 120 VAC in, 24 VAC out to the valves.
- **Common terminal (C)** — the return path shared by every zone.
- **Zone terminals (1, 2, 3, …)** — one per station.
- **Master valve / pump start terminal (MV or P)** — optional; energized whenever any zone runs.
- **Rain sensor terminals (SEN or SN)** — normally-closed inputs that suspend watering when tripped.
- **Program memory** — where the schedule lives. Older units use a physical dial; modern smart controllers use Wi-Fi + cloud.

A controller's job is exactly one thing: send 24 VAC to the correct zone terminal for the correct duration on the correct day, subject to sensor overrides. Everything else — programs, ETo lookups, mobile apps, weather adjust — is a wrapper around that primitive.

**Teaching philosophy.** This module teaches the concepts: how zones map to schedules, how ETo drives smart-controller adjustments, how sensor inputs work. For the exact keypad steps on any specific brand + model, consult the OEM manual. Menu paths differ between manufacturers and firmware versions — memorizing them is a fool's errand.
