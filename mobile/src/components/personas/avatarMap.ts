/**
 * Task RR/SS Phase 2 follow-on · Feb 2026 — Expo static avatar map.
 *
 * Metro's static require() cannot take a dynamic argument, so a
 * literal lookup table is the standard Expo idiom for asset-by-key
 * resolution. Every persona_id must appear here; unknown keys
 * resolve to ``undefined`` and the component falls back to
 * ``avatar_emoji``.
 */
export const PERSONA_AVATARS: Record<string, number> = {
  casey:  require("../../../assets/personas/casey.jpg"),
  emmie:  require("../../../assets/personas/emmie.jpg"),
  buddy:  require("../../../assets/personas/buddy.jpg"),
  vizzy:  require("../../../assets/personas/vizzy.jpg"),
  dexter: require("../../../assets/personas/dexter.jpg"),
  soshie: require("../../../assets/personas/soshie.jpg"),
  scouty: require("../../../assets/personas/scouty.jpg"),
  commet: require("../../../assets/personas/commet.jpg"),
  skedra: require("../../../assets/personas/skedra.jpg"),
  billy:  require("../../../assets/personas/billy.jpg"),
};
