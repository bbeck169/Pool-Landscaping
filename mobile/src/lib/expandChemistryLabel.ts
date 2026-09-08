/**
 * K60 · Feb-2026 — Chemistry reading label expander.
 *
 * The mobile Job Checklist and web Service Report render the Chemistry
 * Readings section using labels drawn from the backend service-report
 * template (``chemical_reading_fields``).  The DEFAULT template ships
 * short-form abbreviations (``FC``, ``TC``, ``TA``, ``CYA``, ``CH``,
 * ``TDS``, ``PO4``) which are meaningful to seasoned pool techs but
 * opaque to newer staff and to the customer-portal report.
 *
 * User adjudication (K60): expand the DEFAULT abbreviations to their
 * full names on the display surface.  Data keys (``FC``, ``TC``, …) —
 * used by the backend, the water-analyzer, and the persisted
 * ``chemical_readings`` payload — remain UNCHANGED.  Only the visible
 * label is transformed.
 *
 * Tenant-customised labels are respected: if the template's ``name``
 * field is anything OTHER than one of the documented default
 * abbreviations, it passes through untouched.  The lookup is
 * case-insensitive + whitespace-trimmed so ``"fc"`` / ``"FC "`` all
 * resolve, but a bespoke ``"Free Cl (deep end)"`` is left as-is (not
 * in the map, so no transform).
 *
 * See /app/memory/PHASE_K60_CHEMISTRY_LABELS.md for the ship story.
 */

const _K60_LABEL_MAP: Readonly<Record<string, string>> = Object.freeze({
  fc:         "Free Chlorine",
  tc:         "Total Chlorine",
  cc:         "Combined Chlorine",
  ph:         "pH",
  ta:         "Total Alkalinity",
  cya:        "Cyanuric Acid",
  ch:         "Calcium Hardness",
  salt:       "Salt",
  tds:        "Total Dissolved Solids",
  po4:        "Phosphates",
  water_temp: "Water Temp",
});

/**
 * ``expandChemistryLabel`` — display-only transform.  Input MUST be the
 * template ``name`` value (what the render surface currently prints).
 * Returns the full-name expansion when the input matches a documented
 * default abbreviation (case-insensitive + trimmed), otherwise returns
 * the input unchanged so tenant customisations are preserved.
 *
 * Never mutates or normalises the reading's data key.
 */
export function expandChemistryLabel(raw: unknown): string {
  if (raw == null) return "";
  const s = String(raw).trim();
  if (!s) return "";
  const hit = _K60_LABEL_MAP[s.toLowerCase()];
  return hit ?? s;
}
