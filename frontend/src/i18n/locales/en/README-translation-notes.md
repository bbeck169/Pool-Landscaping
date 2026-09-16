# Phase D3 · Translator review checklist

The Spanish and French translations shipped in D3 use neutral,
industry-generic vocabulary suitable for the North American
service-business context. The following terms should be revisited
by a professional translator once the tenant base grows beyond
US-only English tenants:

## Spanish (`es/`)
- `industries.handyman` → "Reparaciones generales" — Latin American
  regional preference. Spain / Iberia may prefer "Manitas".
- `industries.hvac` → kept as **"HVAC"** (US-industry acronym).
  Iberian Spanish typically expands to "Climatización" and Latin
  American Spanish to "Aires acondicionados y calefacción". Left
  as HVAC pending translator review.
- `industries.pest_control` → "Control de plagas" — universal.
- `industries.pressure_washing` → "Lavado a presión" — universal.

## French (`fr/`)
- `industries.hvac` → **"CVC"** (Chauffage-Ventilation-Climatisation)
  — Quebec / European French standard. Confirm with US-Franco
  tenants which acronym their techs use.
- `industries.handyman` → "Bricolage" — Metropolitan French. Quebec
  French may prefer "Homme à tout faire" (formal) or
  "Petits travaux" (industry-standard).
- `industries.landscaping` → "Aménagement paysager" — Quebec
  standard. Metropolitan French might use "Jardinage".
- `industries.chimney_sweep` → "Ramonage" — universal.

## Notes on placeholders
- The `checklist.notes_placeholder` string in every locale uses the
  ellipsis character `…` (U+2026), NOT three ASCII dots. Please
  preserve this on any future translation edit.

_This file lives ONLY in `en/` because it's a translator briefing
document — not user-facing content. Delete or move to a `docs/`
folder if a docs infrastructure lands._

## Phase D4 · row-level translations needing pro review

The Phase D4 seeder ships neutral Spanish + French translations for
every row across all 23 industries. The following rows use
industry jargon or region-specific vocabulary that a pro translator
should confirm before we go live in a non-en-primary market:

### Kept as English acronyms (industry-domain)
- `hvac.replaced_air_filter`, `plumbing.water_pressure_checked`,
  `electrical.gfci_afci_tested`, `electrical.voltage_readings_recorded`,
  `pressure_washing.psi_setting_recorded`,
  `pest_control.documented_products_epa`,
  `solar.recorded_system_output` — trade-standard acronyms (HVAC,
  PSI, GFCI, AFCI, EPA, kWh). Localised copy expands them in the
  translator-review pass per-market.

### Region-sensitive terms
- Spanish `pest_control.documented_products_epa` → "n.º de registro
  EPA" — LatAm-neutral. Iberian markets may prefer "N.º de registro
  EPA sin punto".
- French `hvac.*` — Quebec uses "CVC" for HVAC; European French may
  prefer full expansion "Chauffage-Ventilation-Climatisation".
- Spanish `handyman.confirmed_scope` → "Alcance confirmado" —
  LatAm neutral. Iberian Spanish may prefer "Ámbito acordado".
- French `snow_removal.deicer_applied` → "Fondant appliqué" —
  Quebec-standard "fondant" (de-icer). Metropolitan French may
  prefer "produit de déverglaçage".

### Punctuation
Em-dash `—` (U+2014) and ellipsis `…` (U+2026) are preserved
verbatim across every locale. Please retain these on translator
edits.

_These notes accumulate — do NOT delete Phase D3 entries when
adding Phase D4 items. Both surfaces need pro review._
