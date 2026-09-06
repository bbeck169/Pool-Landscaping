/**
 * Phase K73 · Feb-2026 — deterministic crew-hue + individual-
 * saturation palette for schedule map pins and calendar events.
 *
 * User adjudication for K73 asked for palette option ``c``:
 *   * Each crew gets its own base HUE.
 *   * Members within a crew are distinguished by SATURATION.
 *   * Solo techs (no crew) get their own hue from the same wheel
 *     at a neutral saturation level.
 *   * The map is deterministic: same ``(crewId, techId)`` always
 *     resolves to the same hex, across sessions and tenants.
 *   * ``display_color_hex`` on the tech record still wins when
 *     set (backward-compat with the pre-K73 admin picker).
 *
 * Colour math
 * -----------
 * A 12-slice HSL wheel gives crews visually distinct hues.
 * Within a crew, saturation cycles across 3 levels (55%, 75%,
 * 95%) — enough to differentiate individuals without breaking
 * the crew grouping. Lightness is fixed at 45% so pins stay
 * legible against the Google Maps light theme.
 *
 * Public surface: ``crewHuedColor({techId, crewId})`` +
 * ``crewHuedColorFromDisplayHex(tech, crewId)`` +
 * ``groupByCrewForLegend(techs, crewMap)``.
 */

// 12 hues around the wheel — offsets picked so adjacent crews
// never sit within 25° of each other (readability guardrail).
const CREW_HUES = [
  200,  30, 340,  90, 265, 175,
   55, 315, 130, 285,   5, 220,
];
const SAT_LEVELS = [55, 75, 95];
const LIGHTNESS = 45;
const SOLO_SATURATION = 68;

// Small deterministic 32-bit hash — matches the shape of the
// pre-K73 ``hashedTechColor`` so we don't introduce a new hash
// dependency and stay easy to reason about in tests.
function _hash(seed) {
  if (!seed) return 0;
  const s = String(seed);
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h) + s.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h);
}

function _hslToHex(h, s, l) {
  // Standard HSL → RGB → HEX. Everything is integer-clean.
  const S = s / 100, L = l / 100;
  const C = (1 - Math.abs(2 * L - 1)) * S;
  const H = ((h % 360) + 360) % 360;
  const X = C * (1 - Math.abs(((H / 60) % 2) - 1));
  const m = L - C / 2;
  let r = 0, g = 0, b = 0;
  if      (H <  60) [r, g, b] = [C, X, 0];
  else if (H < 120) [r, g, b] = [X, C, 0];
  else if (H < 180) [r, g, b] = [0, C, X];
  else if (H < 240) [r, g, b] = [0, X, C];
  else if (H < 300) [r, g, b] = [X, 0, C];
  else              [r, g, b] = [C, 0, X];
  const toByte = (v) => Math.round((v + m) * 255).toString(16).padStart(2, "0").toUpperCase();
  return `#${toByte(r)}${toByte(g)}${toByte(b)}`;
}

/**
 * Deterministic hex for ``(techId, crewId)`` under the K73
 * palette. Solo techs (no ``crewId``) get a hue from the same
 * wheel but a fixed neutral saturation so they read as a
 * separate "Solo" band in the legend.
 */
export function crewHuedColor({ techId, crewId } = {}) {
  if (!techId) return "#94A3B8"; // slate-400 · matches ScheduleMap unassigned fallback
  if (crewId) {
    const hue = CREW_HUES[_hash(crewId) % CREW_HUES.length];
    const sat = SAT_LEVELS[_hash(techId) % SAT_LEVELS.length];
    return _hslToHex(hue, sat, LIGHTNESS);
  }
  // Solo tech: hash the tech id into the same wheel, fixed sat.
  const hue = CREW_HUES[_hash(techId) % CREW_HUES.length];
  return _hslToHex(hue, SOLO_SATURATION, LIGHTNESS);
}

/**
 * Convenience wrapper — falls back to ``tech.display_color_hex``
 * if the admin has explicitly pinned a colour for this tech.
 *
 * Passing an explicit color preserves the K51 admin picker and
 * matches the pre-K73 ``hashedTechColor`` fallback chain.
 */
export function crewHuedColorFromTech(tech, crewId) {
  if (!tech) return "#94A3B8";
  if (tech.display_color_hex) return tech.display_color_hex;
  const id = tech.id || tech.user_id;
  return crewHuedColor({ techId: id, crewId });
}

/**
 * Given ``techs`` (list) and ``crews`` (list with ``id`` +
 * ``name`` + ``tech_ids``), return a shape suitable for
 * rendering the schedule map legend:
 *
 *     [
 *       { crewId, crewName, techs: [{id, name, colorHex, isExplicit}] },
 *       …
 *       { crewId: null, crewName: "Solo", techs: [...] },
 *     ]
 *
 * Explicit admin-picked colours are surfaced via ``isExplicit``
 * so the legend can render a small "pinned" glyph next to them.
 */
export function groupByCrewForLegend(techs = [], crews = []) {
  const techById = new Map();
  for (const t of techs) {
    const id = t.id || t.user_id;
    if (!id) continue;
    techById.set(id, t);
  }
  const groups = [];
  const seen = new Set();
  for (const c of crews) {
    const rows = [];
    for (const tid of c.tech_ids || []) {
      const t = techById.get(tid);
      if (!t) continue;
      rows.push({
        id: tid,
        name: t.name || t.display_name || tid.slice(0, 8),
        colorHex: crewHuedColorFromTech(t, c.id),
        isExplicit: !!t.display_color_hex,
      });
      seen.add(tid);
    }
    if (rows.length) {
      groups.push({ crewId: c.id, crewName: c.name || "Crew", techs: rows });
    }
  }
  const solo = [];
  for (const t of techs) {
    const id = t.id || t.user_id;
    if (!id || seen.has(id)) continue;
    solo.push({
      id,
      name: t.name || t.display_name || id.slice(0, 8),
      colorHex: crewHuedColorFromTech(t, null),
      isExplicit: !!t.display_color_hex,
    });
  }
  if (solo.length) {
    groups.push({ crewId: null, crewName: "Solo", techs: solo });
  }
  return groups;
}

// Named export bundle so callers can ``import { … } from "@/lib/crewPalette"``.
export default {
  crewHuedColor,
  crewHuedColorFromTech,
  groupByCrewForLegend,
};
