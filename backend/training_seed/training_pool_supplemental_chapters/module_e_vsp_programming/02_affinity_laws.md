# Module E — VSP Programming · Chapter 2: Affinity laws for pool techs

*Original in-house authorship. Concepts only — see OEM manuals for exact keypad procedures.*

The three affinity laws relate pump speed to flow, pressure, and power. For pool techs the most important consequence is this:

> Power draw scales with the cube of the speed ratio.

If a pump was running at full speed (call it 3450 RPM) and drawing (say) 2000 W, and you drop it to half speed (1725 RPM), the new power draw is roughly `2000 × (0.5)³ = 250 W`. That's an eight-fold reduction in electrical cost.

Two side laws come from the same math:

- **Flow scales linearly with speed.** Half-speed = half GPM.
- **Head (pressure) scales with the square of speed.** Half-speed = one-quarter head.

These are the reasons a well-programmed VSP saves money: most pool duties (routine turnover, water polishing, night circulation) don't need full-speed flow. Full-speed operation is reserved for **high-flow needs**: aggressive water polishing after a bloom, priming, backwash, and some pressure-side cleaners. Everything else runs at whatever reduced speed still delivers the flow the plumbing needs.

The single biggest programming mistake in the field is running full-speed 24/7 because the previous fixed-speed pump did. That's an $80–150/month utility bill for no additional benefit.
