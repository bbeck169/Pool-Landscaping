/**
 * CUS-Marketing-Form-Builder · Feb-2026 — Phase 2.
 *
 * Locks the gradient + overlay extensions added to:
 *   - ``frontend/src/lib/formThemes.js`` (coerceTheme, themeToCssVars)
 *   - ``frontend/src/components/formBuilder/ThemePanel.jsx`` (UI)
 *   - ``frontend/src/components/formBuilder/ThemedFormShell.jsx`` (renderer)
 *
 * Contract locked:
 *   1. ``coerceTheme(null)`` returns a full-shape default with
 *      ``gradient: null, overlay_opacity: null``.
 *   2. Every K34 curated preset round-trips byte-identical (both
 *      new fields default to null so ``themeToCssVars`` does not
 *      emit the two new keys).
 *   3. Gradient sub-object validation — well-formed input persists;
 *      out-of-range angle clamps into ``[0, 360]``.
 *   4. Overlay integer validation — 0-100 accepted; > 100 clamps.
 *   5. ``themeToCssVars`` emits ``--form-bg-gradient`` and
 *      ``--form-overlay-opacity`` ONLY when set, with the exact
 *      CSS-ready shape.
 *   6. ``<ThemePanel>`` renders the advanced gradient controls
 *      only when the toggle is on.
 *   7. ``<ThemedFormShell>`` composes background-image from the
 *      gradient var; overlay stacks above the gradient.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

import {
  coerceTheme,
  themeToCssVars,
  FORM_THEME_PRESETS,
  DEFAULT_THEME_KEY,
  presetByKey,
} from "@/lib/formThemes";
import ThemePanel from "@/components/formBuilder/ThemePanel";
import ThemedFormShell from "@/components/formBuilder/ThemedFormShell";


// ═══════════════════════════════════════════════════════════════
// 1) coerceTheme — defaults + K34 round-trip
// ═══════════════════════════════════════════════════════════════
describe("Phase 2 · coerceTheme defaults + K34 round-trip", () => {
  it("coerceTheme(null) returns the default preset with null gradient + overlay",
      () => {
    const t = coerceTheme(null);
    expect(t.preset).toBe(DEFAULT_THEME_KEY);
    expect(t.gradient).toBeNull();
    expect(t.overlay_opacity).toBeNull();
    // Sanity — 5 role colors + font_family still populated.
    expect(t.colors.primary).toMatch(/^#/);
    expect(t.colors.background).toMatch(/^#/);
    expect(t.font_family).toBeTruthy();
  });

  it("every K34 curated preset round-trips byte-identical (gradient + overlay stay null)",
      () => {
    for (const preset of FORM_THEME_PRESETS) {
      const raw = {
        preset: preset.key,
        colors: { ...preset.colors },
        font_family: coerceTheme({ preset: preset.key }).font_family,
      };
      const t = coerceTheme(raw);
      expect(t.preset).toBe(preset.key);
      expect(t.colors).toEqual(preset.colors);
      expect(t.gradient).toBeNull();
      expect(t.overlay_opacity).toBeNull();
    }
  });
});


// ═══════════════════════════════════════════════════════════════
// 2) Gradient sub-object validation + clamping
// ═══════════════════════════════════════════════════════════════
describe("Phase 2 · gradient sub-object validation", () => {
  it("well-formed gradient persists with all three fields", () => {
    const t = coerceTheme({
      gradient: { angle_deg: 135, from: "#ffffff", to: "#000000" },
    });
    expect(t.gradient).toEqual({
      angle_deg: 135, from: "#ffffff", to: "#000000",
    });
  });

  it("negative angle clamps to 0 (not nullified — from + to were valid)",
      () => {
    const t = coerceTheme({
      gradient: { angle_deg: -50, from: "#ffffff", to: "#000000" },
    });
    expect(t.gradient).toEqual({
      angle_deg: 0, from: "#ffffff", to: "#000000",
    });
  });

  it("angle above 360 clamps to 360", () => {
    const t = coerceTheme({
      gradient: { angle_deg: 900, from: "#fff", to: "#000" },
    });
    expect(t.gradient.angle_deg).toBe(360);
  });

  it("missing from/to nullifies the gradient (no half-shape leaks through)",
      () => {
    const t = coerceTheme({
      gradient: { angle_deg: 135, from: "", to: "#000" },
    });
    expect(t.gradient).toBeNull();
  });

  it("garbage (non-object) nullifies the gradient", () => {
    expect(coerceTheme({ gradient: "linear-gradient(...)" }).gradient)
      .toBeNull();
    expect(coerceTheme({ gradient: 42 }).gradient).toBeNull();
    expect(coerceTheme({ gradient: [] }).gradient).toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════
// 3) Overlay integer validation + clamping
// ═══════════════════════════════════════════════════════════════
describe("Phase 2 · overlay_opacity validation", () => {
  it("integer 30 persists", () => {
    expect(coerceTheme({ overlay_opacity: 30 }).overlay_opacity).toBe(30);
  });

  it("integer > 100 clamps to 100", () => {
    expect(coerceTheme({ overlay_opacity: 150 }).overlay_opacity).toBe(100);
  });

  it("negative clamps to 0", () => {
    expect(coerceTheme({ overlay_opacity: -20 }).overlay_opacity).toBe(0);
  });

  it("non-numeric returns null (invalid input, not silent 0)", () => {
    expect(coerceTheme({ overlay_opacity: "bad" }).overlay_opacity)
      .toBeNull();
    expect(coerceTheme({ overlay_opacity: null }).overlay_opacity)
      .toBeNull();
    expect(coerceTheme({}).overlay_opacity).toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════
// 4) themeToCssVars — conditional emission of the 2 new keys
// ═══════════════════════════════════════════════════════════════
describe("Phase 2 · themeToCssVars conditional emission", () => {
  it("emits --form-bg-gradient with the exact linear-gradient(...) string",
      () => {
    const vars = themeToCssVars({
      gradient: { angle_deg: 135, from: "#ffffff", to: "#000000" },
    });
    expect(vars["--form-bg-gradient"]).toBe(
      "linear-gradient(135deg, #ffffff 0%, #000000 100%)",
    );
  });

  it("emits --form-overlay-opacity as a 2-decimal string (30 -> '0.30')",
      () => {
    const vars = themeToCssVars({ overlay_opacity: 30 });
    expect(vars["--form-overlay-opacity"]).toBe("0.30");
  });

  it("emits --form-overlay-opacity even without gradient (Phase-3 hero re-consumes it)",
      () => {
    const vars = themeToCssVars({ overlay_opacity: 50 });
    expect(vars["--form-overlay-opacity"]).toBe("0.50");
    expect(vars["--form-bg-gradient"]).toBeUndefined();
  });

  it("omits both new keys entirely when null (K34 shape preserved byte-identically)",
      () => {
    const vars = themeToCssVars(presetByKey("modern_blue"));
    expect(vars["--form-bg-gradient"]).toBeUndefined();
    expect(vars["--form-overlay-opacity"]).toBeUndefined();
    // Legacy K34 keys still present.
    expect(vars["--form-primary"]).toBe("#2563eb");
    expect(vars["--form-background"]).toBe("#ffffff");
    expect(vars["--form-text"]).toBe("#111827");
    expect(vars["--form-border"]).toBe("#e5e7eb");
    expect(vars["--form-accent"]).toBe("#3b82f6");
    expect(vars.backgroundColor).toBe("#ffffff");
    expect(vars.color).toBe("#111827");
    expect(vars.fontFamily).toBeTruthy();
  });
});


// ═══════════════════════════════════════════════════════════════
// 5) <ThemePanel> — advanced UI rendering
// ═══════════════════════════════════════════════════════════════
describe("Phase 2 · <ThemePanel> advanced gradient controls", () => {
  it("renders the advanced-panel toggle and expands to show gradient controls",
      () => {
    const theme = {
      preset: "custom",
      colors: {
        primary: "#2563eb", background: "#ffffff", text: "#111827",
        border: "#e5e7eb", accent: "#3b82f6",
      },
      font_family: "system-ui",
      gradient: { angle_deg: 135, from: "#fff", to: "#000" },
      overlay_opacity: 30,
    };
    render(<ThemePanel value={theme} onChange={() => {}} />);
    // Advanced panel is auto-open when either new field is set.
    expect(screen.getByTestId("theme-advanced-panel")).toBeTruthy();
    expect(screen.getByTestId("theme-gradient-toggle")).toBeTruthy();
    // Gradient controls visible because toggle is checked.
    expect(screen.getByTestId("theme-gradient-controls")).toBeTruthy();
    expect(screen.getByTestId("theme-gradient-angle")).toBeTruthy();
    expect(screen.getByTestId("theme-gradient-from")).toBeTruthy();
    expect(screen.getByTestId("theme-gradient-to")).toBeTruthy();
    // Overlay slider present.
    expect(screen.getByTestId("theme-overlay-slider")).toBeTruthy();
    cleanup();
  });

  it("gradient controls are HIDDEN when the toggle is off (theme.gradient null)",
      () => {
    render(
      <ThemePanel
        value={presetByKey("modern_blue")}
        onChange={() => {}}
      />,
    );
    // Panel is closed by default when both fields are null.
    expect(screen.queryByTestId("theme-advanced-panel")).toBeNull();
    // Click the toggle to open the panel.
    fireEvent.click(screen.getByTestId("theme-advanced-toggle"));
    // Now the toggle checkbox is visible but the controls under it are not.
    expect(screen.getByTestId("theme-gradient-toggle")).toBeTruthy();
    expect(screen.queryByTestId("theme-gradient-controls")).toBeNull();
    cleanup();
  });

  it("toggling the gradient checkbox emits a theme with a seeded gradient",
      () => {
    let captured = null;
    render(
      <ThemePanel
        value={presetByKey("modern_blue")}
        onChange={(t) => { captured = t; }}
      />,
    );
    fireEvent.click(screen.getByTestId("theme-advanced-toggle"));
    fireEvent.click(screen.getByTestId("theme-gradient-toggle"));
    expect(captured).not.toBeNull();
    expect(captured.preset).toBe("custom");
    expect(captured.gradient).toMatchObject({
      angle_deg: 135,
      from: expect.stringMatching(/^#/),
      to:   expect.stringMatching(/^#/),
    });
    cleanup();
  });

  it("switching to a curated preset resets gradient + overlay to null",
      () => {
    // Ruling R7 backwards-compat — swapping presets nukes advanced
    // settings so the preset renders exactly as its K34 shape.
    let captured = null;
    const start = {
      preset: "custom",
      colors: { ...presetByKey("modern_blue").colors },
      font_family: "system-ui",
      gradient: { angle_deg: 135, from: "#fff", to: "#000" },
      overlay_opacity: 30,
    };
    render(
      <ThemePanel
        value={start}
        onChange={(t) => { captured = t; }}
      />,
    );
    fireEvent.click(screen.getByTestId("theme-preset-warm_earth"));
    expect(captured.preset).toBe("warm_earth");
    expect(captured.gradient).toBeNull();
    expect(captured.overlay_opacity).toBeNull();
    cleanup();
  });
});


// ═══════════════════════════════════════════════════════════════
// 6) <ThemedFormShell> — background-image composition
// ═══════════════════════════════════════════════════════════════
describe("Phase 2 · <ThemedFormShell> gradient + overlay composition", () => {
  it("no-theme → renders wrapper WITHOUT emitting the 2 new CSS vars", () => {
    render(<ThemedFormShell testid="shell-a">child</ThemedFormShell>);
    const wrap = screen.getByTestId("shell-a");
    const styleAttr = wrap.getAttribute("style") || "";
    expect(styleAttr).not.toMatch(/--form-bg-gradient/);
    expect(styleAttr).not.toMatch(/--form-overlay-opacity/);
    expect(wrap.getAttribute("data-themed")).toBe("false");
    cleanup();
  });

  it("gradient set → background-image is the composed gradient string", () => {
    render(
      <ThemedFormShell
        testid="shell-b"
        theme={{
          gradient: { angle_deg: 135, from: "#111", to: "#222" },
        }}
      >x</ThemedFormShell>,
    );
    const wrap = screen.getByTestId("shell-b");
    const styleAttr = wrap.getAttribute("style") || "";
    expect(styleAttr).toMatch(/background-image:\s*linear-gradient\(135deg, #111 0%, #222 100%\)/);
    expect(styleAttr).toMatch(/--form-bg-gradient:\s*linear-gradient\(135deg/);
    cleanup();
  });

  it("gradient + overlay set → overlay stacks ABOVE gradient in background-image",
      () => {
    render(
      <ThemedFormShell
        testid="shell-c"
        theme={{
          gradient: { angle_deg: 45, from: "#aaa", to: "#bbb" },
          overlay_opacity: 40,
        }}
      >x</ThemedFormShell>,
    );
    const wrap = screen.getByTestId("shell-c");
    const styleAttr = wrap.getAttribute("style") || "";
    // Overlay layer FIRST (top of the stack), gradient SECOND.
    expect(styleAttr).toMatch(
      /background-image:\s*linear-gradient\(rgba\(0,\s*0,\s*0,\s*0\.40\),\s*rgba\(0,\s*0,\s*0,\s*0\.40\)\),\s*linear-gradient\(45deg, #aaa 0%, #bbb 100%\)/,
    );
    expect(styleAttr).toMatch(/--form-overlay-opacity:\s*0\.40/);
    cleanup();
  });

  it("overlay ONLY (no gradient) → no background-image composed, but the CSS var is still emitted",
      () => {
    // Phase 3 hero image will re-consume --form-overlay-opacity;
    // for now (no image path yet) ThemedFormShell doesn't have a
    // rich background to darken, so it stays solid.
    render(
      <ThemedFormShell
        testid="shell-d"
        theme={{ overlay_opacity: 50 }}
      >x</ThemedFormShell>,
    );
    const wrap = screen.getByTestId("shell-d");
    const styleAttr = wrap.getAttribute("style") || "";
    expect(styleAttr).toMatch(/--form-overlay-opacity:\s*0\.50/);
    expect(styleAttr).not.toMatch(/background-image:/);
    cleanup();
  });

  it("legacy K34 preset → renders EXACTLY as pre-Phase-2 (byte-identical style)",
      () => {
    render(
      <ThemedFormShell
        testid="shell-legacy"
        theme={presetByKey("modern_blue")}
      >x</ThemedFormShell>,
    );
    const wrap = screen.getByTestId("shell-legacy");
    const styleAttr = wrap.getAttribute("style") || "";
    // 5 K34 CSS vars + fontFamily + backgroundColor + color present.
    expect(styleAttr).toMatch(/--form-primary:\s*#2563eb/);
    expect(styleAttr).toMatch(/--form-background:\s*#ffffff/);
    // Neither new key emitted.
    expect(styleAttr).not.toMatch(/--form-bg-gradient/);
    expect(styleAttr).not.toMatch(/--form-overlay-opacity/);
    // No background-image composed.
    expect(styleAttr).not.toMatch(/background-image:/);
    cleanup();
  });
});
