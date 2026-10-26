/**
 * M4 · web Ticket AA `_computeCombinedCategory` parity. Combined customer category
 * from ACTIVE properties, canonical order Pool → Landscaping → Both, joined " + ".
 * Returns null when nothing is set (badge renders "—").
 */
export const PROPERTY_CATEGORIES = ["pool", "landscaping", "both"] as const;
export type PropertyCategory = (typeof PROPERTY_CATEGORIES)[number];
export const PROPERTY_CATEGORY_LABEL: Record<PropertyCategory, string> = { pool: "Pool", landscaping: "Landscaping", both: "Both" };

export function computeCombinedCategory(properties: any[] | null | undefined): string | null {
  if (!Array.isArray(properties) || properties.length === 0) return null;
  const present = new Set<string>();
  for (const p of properties) {
    if (p?.active === false) continue; // web: dashboard aggregator excludes inactive
    const cat = String(p?.service_category || "").toLowerCase();
    if ((PROPERTY_CATEGORIES as readonly string[]).includes(cat)) present.add(cat);
  }
  if (present.size === 0) return null;
  return PROPERTY_CATEGORIES.filter((c) => present.has(c)).map((c) => PROPERTY_CATEGORY_LABEL[c]).join(" + ");
}
