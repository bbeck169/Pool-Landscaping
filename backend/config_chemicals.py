"""Phase 45 · Shared chemicals catalog.

Single source of truth for chemicals + units. Mirrored to
`/app/mobile/src/config/chemicalsCatalog.ts` and imported by the web
frontend via a small re-export. Any additions/removals here MUST also
update the mobile mirror; a follow-up phase can auto-generate one from
the other.

Fields:
    slug         — machine key.
    name         — human label rendered in the UI.
    unit         — user-visible unit label (gal, lbs, oz, tabs, "40lb bag").
    unit_kind    — "integer" (whole numbers only) or "decimal" (up to 2dp).
    step_hint    — optional stepper increment for the Quick-add sheet.
"""

CHEMICALS_CATALOG = [
    {"slug": "chlorine_tabs",     "name": "Chlorine Tabs",     "unit": "tabs",     "unit_kind": "integer", "step_hint": 1},
    {"slug": "liquid_chlorine",   "name": "Liquid Chlorine",   "unit": "gal",      "unit_kind": "decimal", "step_hint": 0.5},
    {"slug": "muriatic_acid",     "name": "Muriatic Acid",     "unit": "gal",      "unit_kind": "decimal", "step_hint": 0.25},
    {"slug": "soda_ash",          "name": "Soda Ash",          "unit": "lbs",      "unit_kind": "decimal", "step_hint": 1},
    {"slug": "shock",             "name": "Shock",             "unit": "lbs",      "unit_kind": "decimal", "step_hint": 1},
    {"slug": "clarifier",         "name": "Clarifier",         "unit": "oz",       "unit_kind": "decimal", "step_hint": 1},
    {"slug": "phosphate_remover", "name": "Phosphate Remover", "unit": "oz",       "unit_kind": "decimal", "step_hint": 1},
    {"slug": "salt",              "name": "Salt",              "unit": "40lb bag", "unit_kind": "integer", "step_hint": 1},
    {"slug": "enzymes",           "name": "Enzymes",           "unit": "oz",       "unit_kind": "decimal", "step_hint": 1},
]

CHEMICAL_BY_SLUG = {c["slug"]: c for c in CHEMICALS_CATALOG}
