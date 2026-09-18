/**
 * Feb-2026 · Sprint 1 · Section D — TeardropPin direction chevron.
 *
 * Guardrails locked here:
 *   1. When ``headingDegrees`` is a finite number, a
 *      ``${testid}-chevron`` group renders with the correct
 *      ``rotate(<deg> 12 10)`` transform around the head centre.
 *   2. The chevron path (``${testid}-chevron-tip``) is filled with
 *      the pin's fill colour + stroked with the derived darker
 *      stroke so the tip reads against light + dark map tiles.
 *   3. The SVG root exposes the heading via ``data-heading`` so
 *      map consumers can assert without walking the inner tree.
 *   4. Missing / ``null`` / ``undefined`` / ``NaN`` heading
 *      suppress the chevron completely (byte-compat with pre-D
 *      TeardropPin consumers).
 *   5. ``pointerEvents: none`` on the chevron group so click
 *      handlers on the pin body still fire through the arrow.
 *   6. Numbered pins (``label``) + direction chevron coexist —
 *      chevron sits above the head, label inside the head.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import TeardropPin from "@/components/maps/TeardropPin";


describe("<TeardropPin headingDegrees>", () => {
  it("renders a rotated chevron when headingDegrees is finite", () => {
    const { container } = render(
      <TeardropPin color="#22C55E" headingDegrees={90} testid="dir-pin" />,
    );
    const svg = container.querySelector("svg[data-testid='dir-pin']");
    expect(svg).toBeTruthy();
    expect(svg.getAttribute("data-heading")).toBe("90");

    const chev = container.querySelector("g[data-testid='dir-pin-chevron']");
    expect(chev).toBeTruthy();
    // Rotation must orbit the head centre (12, 10) so ANY heading
    // stays anchored to the pin.
    expect(chev.getAttribute("transform")).toBe("rotate(90 12 10)");
    // Decorative — click surface stays on the pin body.
    expect(chev.getAttribute("style") || "").toMatch(/pointer-events\s*:\s*none/);
  });

  it("colours the chevron with the pin fill + derived stroke", () => {
    const { container } = render(
      <TeardropPin color="#EF4444" headingDegrees={0} testid="dir-red" />,
    );
    const tip = container.querySelector("path[data-testid='dir-red-chevron-tip']");
    expect(tip).toBeTruthy();
    expect((tip.getAttribute("fill") || "").toUpperCase()).toBe("#EF4444");
    // Stroke should be the perceptibly-darker variant, NOT the raw
    // fill (otherwise the tip disappears against light backgrounds).
    const stroke = (tip.getAttribute("stroke") || "").toUpperCase();
    expect(stroke).not.toBe("#EF4444");
    expect(stroke).toMatch(/^#[0-9A-F]{6}$/);
  });

  it("suppresses the chevron when headingDegrees is missing", () => {
    const { container } = render(
      <TeardropPin color="#22C55E" testid="no-dir" />,
    );
    expect(container.querySelector("g[data-testid='no-dir-chevron']")).toBeNull();
    // Root SVG's data-heading is absent → attribute is null.
    const svg = container.querySelector("svg[data-testid='no-dir']");
    expect(svg.getAttribute("data-heading")).toBeNull();
  });

  it("suppresses the chevron for null / undefined / NaN heading", () => {
    const cases = [null, undefined, NaN];
    for (const v of cases) {
      const { container } = render(
        <TeardropPin color="#22C55E" headingDegrees={v} testid={`bad-${String(v)}`} />,
      );
      expect(container.querySelector(`g[data-testid='bad-${String(v)}-chevron']`)).toBeNull();
    }
  });

  it("supports the full 0..360 range without breaking placement", () => {
    for (const deg of [0, 45, 90, 135, 180, 225, 270, 315, 360]) {
      const { container } = render(
        <TeardropPin color="#3B82F6" headingDegrees={deg} testid={`d-${deg}`} />,
      );
      const chev = container.querySelector(`g[data-testid='d-${deg}-chevron']`);
      expect(chev).toBeTruthy();
      expect(chev.getAttribute("transform")).toBe(`rotate(${deg} 12 10)`);
    }
  });

  it("coexists with numbered label — chevron + label both render", () => {
    const { container } = render(
      <TeardropPin
        color="#1E3A8A"
        label={7}
        headingDegrees={270}
        testid="combo"
      />,
    );
    expect(container.querySelector("g[data-testid='combo-chevron']")).toBeTruthy();
    expect(container.querySelector("text[data-testid='combo-label']")).toBeTruthy();
    expect(container.querySelector("circle[data-testid='combo-disc']")).toBeTruthy();
  });
});
