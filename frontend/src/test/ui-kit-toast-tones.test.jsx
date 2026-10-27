/**
 * TT hotfix · Feb-2026 — ui-kit Toast tone coverage.
 *
 * Guards against the regression that reopened QQ: ``setToast({
 * tone: "warning" })`` would dereference an undefined palette and
 * throw ``Cannot read properties of undefined (reading 'bg')``,
 * crashing the crew-save flow before the toast could render.
 *
 * Locks three invariants on ``frontend/src/components/ui-kit.jsx``
 * ``Toast``:
 *
 *   1. ``warning`` tone renders with the kit's established
 *      ``colors.warning`` (amber-600, ``#CA8A04``) palette.
 *   2. An unknown / future tone (``tone="unknown-made-up-value"``)
 *      falls back to the ``info`` palette instead of throwing.
 *      Fallback target is ``info`` deliberately — see the inline
 *      comment at ui-kit.jsx::Toast for the rationale (``success``
 *      would falsely signal "all good"; ``error`` was explicitly
 *      flagged against reuse in the mobile parked TD at
 *      TD-qq-info-mobile-crew-editor-must-include-dropped-member-warning).
 *   3. Regression lock on ``success | error | info`` — the three
 *      pre-TT tones must still render with their original
 *      palettes (``colors.success``, ``colors.error``,
 *      ``colors.brand``).
 */
import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

import { Toast } from "@/components/ui-kit";
import { colors } from "@/theme";


afterEach(() => { cleanup(); });


// Convert any CSS color value Testing Library gives us back to its
// lowercase form so hex / rgb comparisons aren't case-sensitive.
// ``window.getComputedStyle`` normalises ``#CA8A04`` to
// ``rgb(202, 138, 4)`` on the jsdom backend, so we assert against
// both shapes.
const _rgb = (hex) => {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgb(${r}, ${g}, ${b})`;
};


describe("TT · Toast tone map", () => {
  it("renders the warning tone with colors.warning (amber-600)",
    () => {
      render(<Toast toast={{ tone: "warning", message: "x" }} />);
      const el = screen.getByTestId("toast");
      // ``data-tone`` is a stable selector hint for the operator —
      // lock it explicitly so a future refactor can't quietly drop
      // the attribute.
      expect(el.getAttribute("data-tone")).toBe("warning");
      expect(el.style.backgroundColor).toBe(_rgb(colors.warning));
      // Solid-fill pattern matches the sibling success / error /
      // info tones: white text on the full-color bg.
      expect(el.style.color).toBe("rgb(255, 255, 255)");
    });

  it("falls back to the info tone when the tone key is unknown "
     + "(and does NOT throw)", () => {
    // Pre-TT this would have thrown "Cannot read properties of
    // undefined (reading 'bg')" and the toast would never have
    // mounted.  Post-TT it falls back to the info palette.
    const _render = () => render(
      <Toast toast={{ tone: "unknown-made-up-value",
                      message: "fallback" }} />);
    expect(_render).not.toThrow();
    const el = screen.getByTestId("toast");
    expect(el.getAttribute("data-tone")).toBe("unknown-made-up-value");
    expect(el.style.backgroundColor).toBe(_rgb(colors.brand));
    expect(el.style.color).toBe("rgb(255, 255, 255)");
  });
});


describe("TT · Pre-TT regression lock on success | error | info",
  () => {
    it("success tone renders with colors.success", () => {
      render(<Toast toast={{ tone: "success", message: "ok" }} />);
      const el = screen.getByTestId("toast");
      expect(el.getAttribute("data-tone")).toBe("success");
      expect(el.style.backgroundColor).toBe(_rgb(colors.success));
      expect(el.style.color).toBe("rgb(255, 255, 255)");
    });

    it("error tone renders with colors.error", () => {
      render(<Toast toast={{ tone: "error", message: "boom" }} />);
      const el = screen.getByTestId("toast");
      expect(el.getAttribute("data-tone")).toBe("error");
      expect(el.style.backgroundColor).toBe(_rgb(colors.error));
      expect(el.style.color).toBe("rgb(255, 255, 255)");
    });

    it("info tone renders with colors.brand", () => {
      render(<Toast toast={{ tone: "info", message: "fyi" }} />);
      const el = screen.getByTestId("toast");
      expect(el.getAttribute("data-tone")).toBe("info");
      expect(el.style.backgroundColor).toBe(_rgb(colors.brand));
      expect(el.style.color).toBe("rgb(255, 255, 255)");
    });

    it("no tone passed → default 'success' tone (pre-TT contract)",
      () => {
        // ``toast.tone || "success"`` default is pre-TT behaviour
        // callers rely on — do NOT drift this to "info" even
        // though the fallback-for-unknown path uses "info".
        render(<Toast toast={{ message: "no-tone" }} />);
        const el = screen.getByTestId("toast");
        expect(el.getAttribute("data-tone")).toBe("success");
        expect(el.style.backgroundColor).toBe(_rgb(colors.success));
      });

    it("null / empty toast prop renders nothing", () => {
      const { container } = render(<Toast toast={null} />);
      expect(container.innerHTML).toBe("");
    });
  });
