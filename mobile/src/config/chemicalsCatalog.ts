/**
 * Phase 45 · Shared chemicals catalog (mobile + web mirror).
 *
 * MUST stay in sync with `/app/backend/config_chemicals.py`. Any
 * additions/removals should land in both files in the same commit.
 * A future phase can auto-generate one from the other; for now, both
 * copies are hand-maintained.
 */
export type ChemUnitKind = "integer" | "decimal";

export type ChemCatalogEntry = {
  slug: string;
  name: string;
  unit: string;
  unit_kind: ChemUnitKind;
  step_hint: number;
};

export const CHEMICALS_CATALOG: ChemCatalogEntry[] = [
  { slug: "chlorine_tabs",     name: "Chlorine Tabs",     unit: "tabs",     unit_kind: "integer", step_hint: 1 },
  { slug: "liquid_chlorine",   name: "Liquid Chlorine",   unit: "gal",      unit_kind: "decimal", step_hint: 0.5 },
  { slug: "muriatic_acid",     name: "Muriatic Acid",     unit: "gal",      unit_kind: "decimal", step_hint: 0.25 },
  { slug: "soda_ash",          name: "Soda Ash",          unit: "lbs",      unit_kind: "decimal", step_hint: 1 },
  { slug: "shock",             name: "Shock",             unit: "lbs",      unit_kind: "decimal", step_hint: 1 },
  { slug: "clarifier",         name: "Clarifier",         unit: "oz",       unit_kind: "decimal", step_hint: 1 },
  { slug: "phosphate_remover", name: "Phosphate Remover", unit: "oz",       unit_kind: "decimal", step_hint: 1 },
  { slug: "salt",              name: "Salt",              unit: "40lb bag", unit_kind: "integer", step_hint: 1 },
  { slug: "enzymes",           name: "Enzymes",           unit: "oz",       unit_kind: "decimal", step_hint: 1 },
];

export const CHEMICAL_BY_SLUG: Record<string, ChemCatalogEntry> =
  Object.fromEntries(CHEMICALS_CATALOG.map((c) => [c.slug, c]));

/**
 * Normalize a user-typed numeric string to the schema for the unit:
 * integer units get `Math.round`, decimals get 2dp. Negative → null so
 * autosave doesn't PATCH a bad value.
 */
export function normalizeChemQty(entry: ChemCatalogEntry, raw: string): number | null {
  if (raw === "" || raw == null) return null;
  const n = Number(raw);
  if (!isFinite(n) || n < 0) return null;
  if (entry.unit_kind === "integer") return Math.round(n);
  return Math.round(n * 100) / 100;
}
