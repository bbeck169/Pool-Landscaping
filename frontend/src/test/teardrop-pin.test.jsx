/**
 * Phase M1 · Feb-2026 — TeardropPin component tests.
 *
 * Locks the acceptance contract from the phase brief:
 *   1. Renders with the given ``color`` prop as the body fill.
 *   2. ``pulse`` prop toggles the halo group / class.
 *   3. ``deriveDarker`` helper monotonically darkens hex / rgb
 *      inputs and hands back a neutral slate on garbage input.
 *   4. ``colorFromId`` is deterministic per id and always resolves
 *      to a member of the 12-color safe palette.
 *   5. ``toGoogleMapsIcon`` emits a data-URL SVG anchored at the
 *      bottom tip.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import TeardropPin, {
  deriveDarker,
  colorFromId,
  toGoogleMapsIcon,
  CANONICAL_WIDTH,
  CANONICAL_HEIGHT,
} from "@/components/maps/TeardropPin";


describe("TeardropPin · body", () => {
  it("renders with the given color as the body fill", () => {
    render(<TeardropPin color="#EF4444" testid="pin-red" />);
    const body = screen.getByTestId("pin-red-body");
    // Feb-2026 · Redesigned pin — body ``fill`` is now a gradient
    // reference (``url(#td-grad-…)``) so the glossy sheen renders.
    // The raw hex is preserved on ``data-color`` for assertions +
    // downstream tooling that needs the flat color.
    expect(body.getAttribute("data-color")).toBe("#EF4444");
    expect(body.getAttribute("fill")).toMatch(/^url\(#td-grad-/);
    // Stroke is auto-derived darker unless overridden.
    expect(body.getAttribute("stroke")).toBe(deriveDarker("#EF4444"));
    // Feb-2026 · The redesigned body uses the solid silhouette path
    // (no ``fill-rule=evenodd`` needed) because the "hollow" area
    // is now a stacked white disc — see the ``-disc`` element when
    // a ``label`` is present.
  });

  it("caller-supplied ``stroke`` prop overrides the auto-darker stroke", () => {
    render(<TeardropPin color="#EF4444" stroke="#000000" testid="pin-stroke" />);
    const body = screen.getByTestId("pin-stroke-body");
    expect(body.getAttribute("stroke")).toBe("#000000");
  });

  it("scales width + height together to preserve the 3:4 tear-drop ratio", () => {
    render(<TeardropPin color="#3B82F6" size={72} testid="pin-72" />);
    const svg = screen.getByTestId("pin-72");
    expect(Number(svg.getAttribute("width"))).toBe(72);
    // 72 * (48/36) = 96.
    expect(Number(svg.getAttribute("height"))).toBe(96);
  });

  it("default size matches the canonical 36x48 constants", () => {
    render(<TeardropPin color="#3B82F6" testid="pin-canon" />);
    const svg = screen.getByTestId("pin-canon");
    expect(Number(svg.getAttribute("width"))).toBe(CANONICAL_WIDTH);
    expect(Number(svg.getAttribute("height"))).toBe(CANONICAL_HEIGHT);
  });
});


describe("TeardropPin · pulse halo", () => {
  it("halo group is absent when ``pulse=false``", () => {
    render(<TeardropPin color="#22C55E" pulse={false} testid="pin-off" />);
    expect(screen.getByTestId("pin-off").getAttribute("data-pulse"))
      .toBe("false");
    expect(screen.queryByTestId("pin-off-halo")).toBeNull();
  });

  it("halo group renders when ``pulse=true`` and carries the pulse class", () => {
    render(<TeardropPin color="#22C55E" pulse={true} testid="pin-on" />);
    const svg = screen.getByTestId("pin-on");
    expect(svg.getAttribute("data-pulse")).toBe("true");
    const halo = screen.getByTestId("pin-on-halo");
    expect(halo).toBeTruthy();
    // ``className`` on an SVG element is a ``SVGAnimatedString`` in
    // the DOM but ``getAttribute("class")`` still returns the raw
    // value React set — that's the ``td-pulse-…`` scoped name.
    const cls = halo.getAttribute("class") || halo.className?.baseVal || "";
    expect(String(cls)).toMatch(/^td-pulse-/);
  });
});


describe("deriveDarker helper", () => {
  it("monotonically darkens a 6-digit hex input", () => {
    // #FFFFFF (255) → 0.72 * 255 ≈ 184 → #B8B8B8.
    expect(deriveDarker("#FFFFFF")).toBe("#b8b8b8");
    // Mid-range check.
    expect(deriveDarker("#808080")).toBe("#5c5c5c");
    // Fully dark stays fully dark.
    expect(deriveDarker("#000000")).toBe("#000000");
  });

  it("accepts a 3-digit hex shorthand", () => {
    // #F00 == #FF0000 → 0.72 * (255,0,0) = (184,0,0).
    expect(deriveDarker("#F00")).toBe("#b80000");
  });

  it("accepts rgb() input", () => {
    expect(deriveDarker("rgb(255,0,0)")).toBe("#b80000");
  });

  it("falls back to neutral slate on garbage input", () => {
    expect(deriveDarker("")).toBe("#334155");
    expect(deriveDarker(null)).toBe("#334155");
    expect(deriveDarker("not-a-color")).toBe("#334155");
    expect(deriveDarker("#zzzz")).toBe("#334155");
  });
});


describe("colorFromId helper", () => {
  it("is deterministic per id", () => {
    const a = colorFromId("tech-jenny");
    const b = colorFromId("tech-jenny");
    expect(a).toBe(b);
  });

  it("resolves to one of the 12 safe palette entries", () => {
    const _safe = new Set([
      "#EF4444", "#F97316", "#EAB308", "#22C55E", "#10B981", "#06B6D4",
      "#0EA5E9", "#3B82F6", "#6366F1", "#8B5CF6", "#EC4899", "#14B8A6",
    ]);
    for (const id of ["a", "b", "c", "d", "e", "f", "g", "h",
                        "tech-1", "tech-2", "customer-99", "long-id-string-x-y-z"]) {
      const c = colorFromId(id);
      expect(_safe.has(c), `${id} → ${c}`).toBe(true);
    }
  });

  it("different ids typically resolve to different colors", () => {
    // Not strictly true for every pair (12 buckets → collisions
    // exist) but across a wide corpus we must see at least 8
    // distinct palette entries used.
    const ids = Array.from({ length: 64 }).map((_, i) => `tech-${i}`);
    const distinct = new Set(ids.map(colorFromId));
    expect(distinct.size).toBeGreaterThanOrEqual(8);
  });

  it("handles empty / null id without crashing", () => {
    expect(typeof colorFromId(null)).toBe("string");
    expect(typeof colorFromId("")).toBe("string");
    expect(typeof colorFromId(undefined)).toBe("string");
  });
});


describe("toGoogleMapsIcon helper", () => {
  it("emits a data-URL SVG carrying the given color", () => {
    const icon = toGoogleMapsIcon({ color: "#22C55E" });
    expect(icon.url).toMatch(/^data:image\/svg\+xml;base64,/);
    // Decode + sanity-check the SVG bytes.
    const svg = Buffer.from(icon.url.split(",")[1], "base64").toString("utf-8");
    expect(svg).toContain("<svg");
    expect(svg).toContain('fill="#22C55E"');
    expect(svg).toContain('fill-rule="evenodd"');
  });

  it("static halo ring appears in the SVG only when ``pulse=true``", () => {
    const off = toGoogleMapsIcon({ color: "#22C55E", pulse: false });
    const on  = toGoogleMapsIcon({ color: "#22C55E", pulse: true });
    const svgOff = Buffer.from(off.url.split(",")[1], "base64").toString("utf-8");
    const svgOn  = Buffer.from(on.url.split(",")[1],  "base64").toString("utf-8");
    expect(svgOff).not.toContain("fill-opacity=\"0.30\"");
    expect(svgOn).toContain("fill-opacity=\"0.30\"");
  });

  it("anchors at the bottom tip of the pin", () => {
    const icon = toGoogleMapsIcon({ color: "#22C55E", size: 36 });
    // Plain-object anchor when the Google Maps SDK isn't loaded
    // (jsdom).  ``x = size/2`` = 18, ``y = height`` = 48.
    expect(icon.anchor).toEqual({ x: 18, y: 48 });
  });
});
