# Module 2 — Irrigation Timers/Controllers · Chapter 3: ETo and smart controllers

*Original in-house authorship. Consult the OEM manual for exact ETo configuration on your specific model.*

**ETo (Evapotranspiration Reference)** is the amount of water — in inches per day — that a well-watered grass reference crop loses through evaporation + transpiration under the local weather. Higher temperature, wind, and solar radiation → higher ETo → plants need more water. Cloudy/cool/humid → lower ETo.

Smart controllers (Hunter Hydrawise, Rain Bird ESP-Me3 with LNK, Rachio, B-hyve, and others) subscribe to local weather stations or use on-site sensors, calculate a daily ETo value, and adjust each zone's runtime to replace exactly what evaporated. In practice this cuts water use 20–40% vs. a fixed schedule.

**Zone-specific parameters** the tech configures once at install:

- **Plant type** (turf, shrub, tree, garden, drip)
- **Soil type** (sand, loam, clay) — determines how fast water infiltrates
- **Sprinkler type** (spray, rotor, drip) — determines precipitation rate
- **Slope** — steep slopes need cycle-and-soak
- **Sun exposure** (full, partial, shade)

The controller uses these + daily ETo to compute a runtime. Wrong parameters → wrong runtime → dead grass or waterlogged garden. Configure carefully.

**Rain skip + saturation skip** are standard smart-controller features. They should be enabled by default and only disabled when troubleshooting.

**Manual override.** Every smart controller has a manual "run this zone now" that bypasses the schedule. Use this to visually verify heads after any repair.
