/**
 * Phase K73 · Feb-2026 — crewPalette unit tests.
 *
 * The palette is DETERMINISTIC: same ``(techId, crewId)`` MUST
 * yield the same hex across sessions. Techs in the same crew
 * share a hue slice; techs across crews sit on visually
 * distinct hue slices. ``display_color_hex`` on the tech record
 * still wins.
 */
import { describe, it, expect } from "vitest";
import {
  crewHuedColor,
  crewHuedColorFromTech,
  groupByCrewForLegend,
} from "../lib/crewPalette";

// Helper — pull the hue out of an ``#RRGGBB`` hex.
function _hueOf(hex) {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const d = max - min;
  if (d === 0) return 0;
  let h;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  h = h * 60;
  if (h < 0) h += 360;
  return h;
}

describe("crewHuedColor (K73)", () => {
  it("is deterministic — same inputs always return the same hex", () => {
    const a = crewHuedColor({ techId: "tech-1", crewId: "crew-a" });
    const b = crewHuedColor({ techId: "tech-1", crewId: "crew-a" });
    expect(a).toBe(b);
  });

  it("puts crewmates on the same hue slice, distinguishes by saturation", () => {
    const t1 = crewHuedColor({ techId: "tech-1", crewId: "crew-a" });
    const t2 = crewHuedColor({ techId: "tech-2", crewId: "crew-a" });
    // Hues must be within 5° of each other (identical slice).
    expect(Math.abs(_hueOf(t1) - _hueOf(t2))).toBeLessThan(5);
    // …but the two colours are not literally identical.
    expect(t1).not.toBe(t2);
  });

  it("puts techs in DIFFERENT crews on visually distinct hues", () => {
    const t1 = crewHuedColor({ techId: "tech-1", crewId: "crew-a" });
    const t2 = crewHuedColor({ techId: "tech-1", crewId: "crew-b" });
    // Different crew must land on a materially different hue.
    const delta = Math.abs(_hueOf(t1) - _hueOf(t2));
    expect(Math.min(delta, 360 - delta)).toBeGreaterThan(15);
  });

  it("falls back to a stable slate hex when techId is missing", () => {
    expect(crewHuedColor({})).toBe("#94A3B8");
  });

  it("solo techs (no crewId) still get a determined hex", () => {
    const a = crewHuedColor({ techId: "solo-1" });
    const b = crewHuedColor({ techId: "solo-1" });
    expect(a).toBe(b);
    expect(a).toMatch(/^#[0-9A-F]{6}$/);
  });
});

describe("crewHuedColorFromTech (K73)", () => {
  it("returns the tech.display_color_hex verbatim when set", () => {
    const tech = { id: "t", display_color_hex: "#123ABC" };
    expect(crewHuedColorFromTech(tech, "crew-x")).toBe("#123ABC");
  });

  it("uses the crew-hued palette when no explicit color is set", () => {
    const tech = { id: "t" };
    const hex = crewHuedColorFromTech(tech, "crew-x");
    expect(hex).toBe(crewHuedColor({ techId: "t", crewId: "crew-x" }));
  });
});

describe("groupByCrewForLegend (K73)", () => {
  it("groups techs by crew and appends a Solo bucket for leftovers", () => {
    const techs = [
      { id: "a", name: "Alice" },
      { id: "b", name: "Bob" },
      { id: "s", name: "Solo Sue" },
    ];
    const crews = [
      { id: "crew-a", name: "Blue Crew", tech_ids: ["a", "b"] },
    ];
    const groups = groupByCrewForLegend(techs, crews);
    expect(groups).toHaveLength(2);
    expect(groups[0].crewId).toBe("crew-a");
    expect(groups[0].techs.map((t) => t.id)).toEqual(["a", "b"]);
    expect(groups[1].crewId).toBeNull();
    expect(groups[1].crewName).toBe("Solo");
    expect(groups[1].techs.map((t) => t.id)).toEqual(["s"]);
  });

  it("omits the Solo group when every tech has a crew", () => {
    const techs = [
      { id: "a", name: "Alice" },
      { id: "b", name: "Bob" },
    ];
    const crews = [{ id: "c", name: "C", tech_ids: ["a", "b"] }];
    const groups = groupByCrewForLegend(techs, crews);
    expect(groups.map((g) => g.crewName)).toEqual(["C"]);
  });

  it("surfaces display_color_hex overrides via isExplicit", () => {
    const techs = [{ id: "a", name: "Alice", display_color_hex: "#FF00AA" }];
    const groups = groupByCrewForLegend(techs, []);
    expect(groups[0].techs[0].colorHex).toBe("#FF00AA");
    expect(groups[0].techs[0].isExplicit).toBe(true);
  });
});
