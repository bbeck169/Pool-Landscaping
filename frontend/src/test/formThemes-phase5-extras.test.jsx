/**
 * Feb-2026 · CUS-Marketing-Form-Builder Phase 5 (α-delta) — vitest
 * for ``coerceTheme`` + ``themeToCssVars`` on the four new fields.
 *
 * Companion to the BE pytest at
 * ``backend/tests/test_marketing_forms_phase5_theme_extras.py``.
 * Both suites together guarantee the FE pad + BE normaliser never
 * drift. Pattern mirrors the shipped
 * ``k34-form-theme.test.jsx`` + ``marketing-forms-theme-gradient-
 * overlay.test.jsx`` sibling vitests.
 */
import { describe, it, expect } from "vitest";
import {
  coerceTheme, themeToCssVars,
  FORM_LAYOUT_CONTAINER_OPTIONS,
  FORM_LAYOUT_HEADER_OPTIONS,
  FORM_FONT_SIZE_SCALE_OPTIONS,
  FORM_FONT_SIZE_SCALE_MULTIPLIERS,
} from "../lib/formThemes";


describe("Phase 5 · coerceTheme", () => {
  it("pads null defaults for the four new fields when input omits them", () => {
    const t = coerceTheme({ preset: "modern_blue" });
    expect(t.layout).toEqual({ container: null, header: null });
    expect(t.font).toEqual({ size_scale: null });
    expect(t.wallpaper).toBeNull();
    expect(t.banner).toBeNull();
  });

  it("accepts valid enum values on layout + font", () => {
    const t = coerceTheme({
      preset: "modern_blue",
      layout: { container: "centered", header: "full_banner" },
      font: { size_scale: "lg" },
    });
    expect(t.layout).toEqual({ container: "centered", header: "full_banner" });
    expect(t.font).toEqual({ size_scale: "lg" });
  });

  it("coerces invalid enum values to null (no throw)", () => {
    const t = coerceTheme({
      preset: "modern_blue",
      layout: { container: "DIAGONAL_FLIP", header: "weird" },
      font: { size_scale: "cosmic" },
    });
    expect(t.layout).toEqual({ container: null, header: null });
    expect(t.font).toEqual({ size_scale: null });
  });

  it("accepts non-empty image URLs on wallpaper + banner slots", () => {
    const t = coerceTheme({
      wallpaper: { image_url: "https://cdn.test/wall.jpg" },
      banner:    { image_url: "https://cdn.test/band.jpg" },
    });
    expect(t.wallpaper).toEqual({ image_url: "https://cdn.test/wall.jpg" });
    expect(t.banner).toEqual({ image_url: "https://cdn.test/band.jpg" });
  });

  it("coerces malformed image slots to null", () => {
    const cases = [
      { wallpaper: { image_url: "" } },           // empty string
      { wallpaper: { image_url: "   " } },        // whitespace-only
      { wallpaper: { image_url: 42 } },           // non-string
      { wallpaper: {} },                           // missing key
      { wallpaper: null },                         // explicit null
      { wallpaper: "not-a-dict" },                 // scalar
    ];
    for (const c of cases) {
      expect(coerceTheme(c).wallpaper).toBeNull();
    }
  });

  it("trims whitespace on image URLs", () => {
    const t = coerceTheme({
      banner: { image_url: "  https://cdn.test/b.jpg  " },
    });
    expect(t.banner).toEqual({ image_url: "https://cdn.test/b.jpg" });
  });

  it("exposes stable enum option arrays for the pickers", () => {
    expect(FORM_LAYOUT_CONTAINER_OPTIONS).toEqual(["left", "centered", "mixed"]);
    expect(FORM_LAYOUT_HEADER_OPTIONS).toEqual(["left_title", "full_banner"]);
    expect(FORM_FONT_SIZE_SCALE_OPTIONS).toEqual(
      ["xs", "sm", "md", "lg", "xl", "xxl"],
    );
    // md bucket must be 1.0 — matches today's baseline so a form
    // that picks md renders identically to a legacy K34 form.
    expect(FORM_FONT_SIZE_SCALE_MULTIPLIERS.md).toBe(1.0);
    // Monotonic ordering is load-bearing for the A-letter picker.
    const vals = FORM_FONT_SIZE_SCALE_OPTIONS.map(
      k => FORM_FONT_SIZE_SCALE_MULTIPLIERS[k],
    );
    for (let i = 1; i < vals.length; i++) {
      expect(vals[i]).toBeGreaterThan(vals[i - 1]);
    }
  });
});


describe("Phase 5 · themeToCssVars", () => {
  it("omits the five new CSS vars when the Phase-5 fields are unset", () => {
    const style = themeToCssVars({ preset: "modern_blue" });
    expect(style["--form-layout-container"]).toBeUndefined();
    expect(style["--form-layout-header"]).toBeUndefined();
    expect(style["--form-font-size-scale"]).toBeUndefined();
    expect(style["--form-wallpaper-url"]).toBeUndefined();
    expect(style["--form-banner-url"]).toBeUndefined();
  });

  it("emits layout enum literals + font-size multiplier when set", () => {
    const style = themeToCssVars({
      preset: "modern_blue",
      layout: { container: "centered", header: "full_banner" },
      font: { size_scale: "xl" },
    });
    expect(style["--form-layout-container"]).toBe("centered");
    expect(style["--form-layout-header"]).toBe("full_banner");
    // ``xl`` bucket = 1.25.
    expect(style["--form-font-size-scale"]).toBe("1.25");
  });

  it("emits url() CSS values for wallpaper + banner slots", () => {
    const style = themeToCssVars({
      wallpaper: { image_url: "https://cdn.test/wall.jpg" },
      banner:    { image_url: "https://cdn.test/band.jpg" },
    });
    expect(style["--form-wallpaper-url"]).toBe('url("https://cdn.test/wall.jpg")');
    expect(style["--form-banner-url"]).toBe('url("https://cdn.test/band.jpg")');
  });

  it("K34 byte-identity — pre-Phase-5 themes emit no new vars", () => {
    // Load-bearing — this is the test that would trip if someone
    // moved any of the five new ``out["--form-*"] = ...`` writes
    // out of their guarded if-block.
    const style = themeToCssVars({
      preset: "warm_earth",
      colors: {
        primary: "#b45309", background: "#fdf8f2", text: "#292524",
        border: "#e7d9c4", accent: "#d97706",
      },
      font_family: "Georgia, serif",
    });
    const phase5Keys = [
      "--form-layout-container",
      "--form-layout-header",
      "--form-font-size-scale",
      "--form-wallpaper-url",
      "--form-banner-url",
    ];
    for (const k of phase5Keys) {
      expect(style[k]).toBeUndefined();
    }
    // K34 vars still present.
    expect(style["--form-primary"]).toBe("#b45309");
    expect(style.fontFamily).toBe("Georgia, serif");
  });
});
