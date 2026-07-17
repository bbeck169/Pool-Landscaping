# Chapter 9 — Pool Math and Calculations

*Original in-house authorship. External standards cited by name and link only.*

## Why the math matters

The technician who cannot compute a dose in the field will overshoot, undershoot, or reach for the wrong product. Pool math is not complicated — it is arithmetic — but the units are unforgiving. A confident operator carries a small set of formulas, verifies pool volume before dosing, and rounds up only for chemistry that is safe to over-apply. This chapter collects the calculations you will actually use on a service visit.

## Pool volume

The formula for volume is length × width × average depth × 7.48 for a rectangular pool with a flat bottom, where the result is in U.S. gallons. Real pools are seldom flat: they slope from a shallow end to a deep end. The average depth is the arithmetic average of the shallow-end and deep-end depths for a linearly sloped floor. For freeform pools, break the surface into geometric shapes, compute each area, multiply by average depth, and sum. For circular pools, the surface area is π × r². Keep pool volume in the customer record so it does not need to be re-derived on every visit.

## Dose to a target concentration

Once volume is known, dosing is a proportional problem. For every 10,000 gallons of pool water and every 1 ppm of concentration change, you need a specific weight or volume of a given product. Common field factors:

- 1 ppm free chlorine per 10,000 gal ≈ **2 oz** of trichlor (90 % strength)
- 1 ppm free chlorine per 10,000 gal ≈ **2.5 oz** of dichlor (56 % strength)
- 1 ppm free chlorine per 10,000 gal ≈ **1.9 oz** of cal-hypo (73 % strength)
- 10 ppm free chlorine per 10,000 gal ≈ **1 gal** of 10 % liquid chlorine
- 10 ppm total alkalinity per 10,000 gal ≈ **1.5 lb** of sodium bicarbonate
- 10 ppm calcium hardness per 10,000 gal ≈ **1.25 lb** of calcium chloride (77 % anhydrous)
- 10 ppm cyanuric acid per 10,000 gal ≈ **13 oz** of granular stabilizer
- 0.2 pH decrease per 10,000 gal in average-alkalinity water ≈ **10 oz** of 31.45 % muriatic acid or **20 oz** of dry sodium bisulfate

Product labels always take precedence over rules of thumb. Every product has trade strength printed on the container; compute against that.

## Dose scaling with volume

The rule of thumb factors above apply to 10,000 gallons. For a different volume, scale linearly: a pool holding 22,500 gallons uses 2.25 times the dose of a 10,000-gallon pool for the same ppm change. A common mistake is scaling from a memorized "residential" dose without checking volume.

## Langelier Saturation Index (LSI)

LSI is computed as:

    LSI = pH + T_f + C_f + A_f − 12.1

where T_f, C_f, and A_f are lookup factors for water temperature, calcium hardness, and total alkalinity. Positive LSI means scaling tendency; negative means corrosion. Field cards for the lookup factors are published in the operator's manual for most test kits.

## Chemical demand — free vs. combined chlorine

To reach breakpoint chlorination in the presence of combined chlorine, the target free chlorine is roughly 10 × CC. If a pool shows FAC 3.0 ppm and CC 1.0 ppm, breakpoint requires a raise to FAC 10 ppm (an additional 7 ppm above the current residual). Compute the dose against the additional ppm required, not the target ppm.

## Volume conversions

- 1 gallon of water ≈ **8.33 lb**
- 1 cubic foot of water ≈ **7.48 gal**
- 1 U.S. gallon = **128 fluid ounces**
- 1 pound = **16 ounces (weight)**

Volume in ounces is fluid; dosing granular product in ounces is weight. When a label says "oz," the industry convention for dry product is weight and for liquid product is volume.

## Ordering of adjustments

Because chlorine, alkalinity, and pH all interact, the operator must apply adjustments in a repeatable order. The industry rule of thumb: (1) adjust TA to target, (2) verify and adjust pH, (3) adjust CYA if needed by drain-and-refill, (4) adjust FAC last. Adjusting FAC first — a shock ahead of pH correction — wastes chlorine because much of it is present as the weakly-effective hypochlorite ion at a high pH.

## Sample field calculation

*Pool: 20 × 40, average depth 5 ft; test panel FAC 1.0, CC 0.6, pH 7.8, TA 90, CH 220, CYA 40; goal: breakpoint shock.*

- Volume = 20 × 40 × 5 × 7.48 = **29,920 gal**, call it 30,000.
- Target FAC for breakpoint = 10 × 0.6 = **6.0 ppm**; additional ppm needed = 6.0 − 1.0 = **5.0 ppm**.
- Using 10 % liquid chlorine: 10 ppm per 10,000 gal takes 1 gal. So 5 ppm per 30,000 gal = **1.5 gal**.
- pH is 7.8 — high enough that the shock will lose effectiveness. Drop pH to 7.4 first with about 30 oz of muriatic acid before shocking.

## Field practice

Carry a printed dose chart in the truck. Keep a calibrated scale for granular products. Always predissolve granular chlorine and always add acid to a large volume of water, never the reverse. Log actual doses in the service record so the next visit's operator inherits the math.

## External references
- ANSI/APSP/ICC-11 — Water Quality standard: https://www.phta.org
- CDC Model Aquatic Health Code (MAHC): https://www.cdc.gov/mahc
- Chemical product safety data sheets (per OSHA HCS): https://www.osha.gov
