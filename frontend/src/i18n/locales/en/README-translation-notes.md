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
