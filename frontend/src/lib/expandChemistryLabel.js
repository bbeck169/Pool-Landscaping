/**
 * K60 · Feb-2026 — Chemistry reading label expander (web parity).
 *
 * Web mirror of ``mobile/src/lib/expandChemistryLabel.ts``.  Kept in
 * lockstep with the mobile helper — the map contents MUST match byte-
 * for-byte so techs get the same label wherever they read the report.
 *
 * See /app/memory/PHASE_K60_CHEMISTRY_LABELS.md for the ship story.
 */

const _K60_LABEL_MAP = Object.freeze({
  fc:   "Free Chlorine",
  ph:   "pH",
  ta:   "Total Alkalinity",
  cya:  "Cyanuric Acid",
  ch:   "Calcium Hardness",
  salt: "Salt",
  tds:  "Total Dissolved Solids",
  po4:  "Phosphates",
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
export function expandChemistryLabel(raw) {
  if (raw == null) return "";
  const s = String(raw).trim();
  if (!s) return "";
  const hit = _K60_LABEL_MAP[s.toLowerCase()];
  return hit ?? s;
}
