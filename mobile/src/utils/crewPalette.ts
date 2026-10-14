/**
 * Per-tech pin colors — mobile port of `frontend/src/lib/crewPalette.js`
 * (crewHuedColor / crewHuedColorFromTech) + the CalendarSchedule
 * `techColorMap` builder. Same palette, hash, and HSL→hex math, so a
 * given tech gets the identical color on web and mobile.
 */
const CREW_HUES = [200, 30, 340, 90, 265, 175, 55, 315, 130, 285, 5, 220];
const SAT_LEVELS = [55, 75, 95];
const LIGHTNESS = 45;
const SOLO_SATURATION = 68;
export const UNASSIGNED_PIN_COLOR = "#94A3B8"; // slate-400 (web _UNASSIGNED_COLOR)

function hash(seed?: string | null): number {
  if (!seed) return 0;
  const s = String(seed);
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h) + s.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h);
}

function hslToHex(h: number, s: number, l: number): string {
  const S = s / 100, L = l / 100;
  const C = (1 - Math.abs(2 * L - 1)) * S;
  const H = ((h % 360) + 360) % 360;
  const X = C * (1 - Math.abs(((H / 60) % 2) - 1));
  const m = L - C / 2;
  let r = 0, g = 0, b = 0;
  if (H < 60) [r, g, b] = [C, X, 0];
  else if (H < 120) [r, g, b] = [X, C, 0];
  else if (H < 180) [r, g, b] = [0, C, X];
  else if (H < 240) [r, g, b] = [0, X, C];
  else if (H < 300) [r, g, b] = [X, 0, C];
  else [r, g, b] = [C, 0, X];
  const toByte = (v: number) => Math.round((v + m) * 255).toString(16).padStart(2, "0").toUpperCase();
  return `#${toByte(r)}${toByte(g)}${toByte(b)}`;
}

export function crewHuedColor({ techId, crewId }: { techId?: string | null; crewId?: string | null } = {}): string {
  if (!techId) return UNASSIGNED_PIN_COLOR;
  if (crewId) {
    const hue = CREW_HUES[hash(crewId) % CREW_HUES.length];
    const sat = SAT_LEVELS[hash(techId) % SAT_LEVELS.length];
    return hslToHex(hue, sat, LIGHTNESS);
  }
  return hslToHex(CREW_HUES[hash(techId) % CREW_HUES.length], SOLO_SATURATION, LIGHTNESS);
}

export function crewHuedColorFromTech(tech: any, crewId?: string | null): string {
  if (!tech) return UNASSIGNED_PIN_COLOR;
  if (tech.display_color_hex) return tech.display_color_hex;
  return crewHuedColor({ techId: tech.id || tech.user_id, crewId });
}

/** techId → color, mirroring web CalendarSchedule `techColorMap`. */
export function buildTechColorMap(techs: any[] = [], crews: any[] = []): Map<string, string> {
  const crewByTech = new Map<string, string>();
  for (const c of crews || []) for (const tid of c?.tech_ids || []) crewByTech.set(tid, c.id);
  const m = new Map<string, string>();
  for (const t of techs || []) {
    if (!t?.id) continue;
    m.set(t.id, crewHuedColorFromTech(t, crewByTech.get(t.id) || null));
  }
  return m;
}
