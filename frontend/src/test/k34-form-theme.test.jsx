/**
 * Phase K34 · Feb-2026 — vitest coverage for the shared theme
 * toolkit (registry + coerce + panel + shell).
 */
import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import React from "react";

import {
  FORM_THEME_PRESETS, FORM_FONT_STACKS, DEFAULT_THEME_KEY,
  coerceTheme, presetByKey, themeToCssVars, fontStackById,
} from "../lib/formThemes";
import ThemePanel from "../components/formBuilder/ThemePanel";
import ThemedFormShell from "../components/formBuilder/ThemedFormShell";


describe("formThemes registry", () => {
  it("exposes at least 5 curated presets", () => {
    expect(FORM_THEME_PRESETS.length).toBeGreaterThanOrEqual(5);
  });

  it("exposes system-font-only stacks (no Google Fonts import URLs)", () => {
    for (const f of FORM_FONT_STACKS) {
      expect(f.stack).not.toMatch(/fonts\.google/);
      expect(f.stack).not.toMatch(/@import/);
    }
  });

  it("coerceTheme fills defaults for missing fields", () => {
    const t = coerceTheme({});
    expect(t.preset).toBe(DEFAULT_THEME_KEY);
    expect(t.colors.primary).toBeTruthy();
    expect(t.colors.background).toBeTruthy();
    expect(t.colors.text).toBeTruthy();
    expect(t.colors.border).toBeTruthy();
    expect(t.colors.accent).toBeTruthy();
    expect(t.font_family).toBeTruthy();
  });

  it("coerceTheme preserves a valid preset key", () => {
    const t = coerceTheme({ preset: "warm_earth" });
    expect(t.preset).toBe("warm_earth");
    expect(t.colors.primary).toBe(presetByKey("warm_earth").colors.primary);
  });

  it("coerceTheme downgrades an unknown preset to 'custom'", () => {
    const t = coerceTheme({ preset: "does_not_exist" });
    expect(t.preset).toBe("custom");
  });

  it("themeToCssVars emits every --form-* variable", () => {
    const vars = themeToCssVars({ preset: "modern_blue" });
    expect(vars["--form-primary"]).toBeTruthy();
    expect(vars["--form-background"]).toBeTruthy();
    expect(vars["--form-text"]).toBeTruthy();
    expect(vars["--form-border"]).toBeTruthy();
    expect(vars["--form-accent"]).toBeTruthy();
    expect(vars.fontFamily).toBeTruthy();
    expect(vars.backgroundColor).toBeTruthy();
  });
});


describe("<ThemePanel />", () => {
  const noop = () => {};

  it("renders every preset swatch", () => {
    const { getByTestId } = render(<ThemePanel value={null} onChange={noop} />);
    for (const p of FORM_THEME_PRESETS) {
      expect(getByTestId(`theme-preset-${p.key}`)).toBeTruthy();
    }
    expect(getByTestId("theme-preset-custom")).toBeTruthy();
  });

  it("preset click emits the full preset colors via onChange", () => {
    const seen = [];
    const { getByTestId } = render(
      <ThemePanel value={null} onChange={(t) => seen.push(t)} />,
    );
    fireEvent.click(getByTestId("theme-preset-bold_green"));
    expect(seen).toHaveLength(1);
    expect(seen[0].preset).toBe("bold_green");
    expect(seen[0].colors.primary).toBe(
      presetByKey("bold_green").colors.primary,
    );
    expect(seen[0].font_family).toBe(fontStackById("modern_sans"));
  });

  it("Customize expand toggle reveals hex pickers", () => {
    const { getByTestId, queryByTestId } = render(
      <ThemePanel value={{ preset: "modern_blue" }} onChange={noop} />,
    );
    expect(queryByTestId("theme-color-pickers")).toBeNull();
    fireEvent.click(getByTestId("theme-expand-toggle"));
    expect(getByTestId("theme-color-pickers")).toBeTruthy();
    // The 5 role hex-pickers are all mounted.
    for (const r of ["primary","background","text","border","accent"]) {
      expect(getByTestId(`theme-color-${r}`)).toBeTruthy();
    }
  });

  it("editing a hex color flips preset to 'custom' and emits change", () => {
    const seen = [];
    const { getByTestId } = render(
      <ThemePanel value={{ preset: "modern_blue" }}
                    onChange={(t) => seen.push(t)} />,
    );
    fireEvent.click(getByTestId("theme-expand-toggle"));
    fireEvent.change(getByTestId("theme-color-primary"), {
      target: { value: "#ff00aa" },
    });
    expect(seen).toHaveLength(1);
    expect(seen[0].preset).toBe("custom");
    expect(seen[0].colors.primary).toBe("#ff00aa");
  });

  it("font dropdown emits the resolved stack via onChange", () => {
    const seen = [];
    const { getByTestId } = render(
      <ThemePanel value={{ preset: "modern_blue" }}
                    onChange={(t) => seen.push(t)} />,
    );
    fireEvent.change(getByTestId("theme-font-select"), {
      target: { value: "editorial_serif" },
    });
    expect(seen).toHaveLength(1);
    expect(seen[0].font_family).toBe(fontStackById("editorial_serif"));
  });
});


describe("<ThemedFormShell />", () => {
  it("emits --form-* CSS variables when theme is present", () => {
    const { getByTestId } = render(
      <ThemedFormShell theme={{ preset: "warm_earth" }} testid="shell-a">
        <span>hi</span>
      </ThemedFormShell>,
    );
    const el = getByTestId("shell-a");
    expect(el.getAttribute("data-themed")).toBe("true");
    expect(el.style.getPropertyValue("--form-primary")).toBeTruthy();
    expect(el.style.getPropertyValue("--form-background")).toBeTruthy();
    expect(el.style.fontFamily).toBeTruthy();
  });

  it("emits no CSS variables when theme is null (backwards compat)", () => {
    const { getByTestId } = render(
      <ThemedFormShell theme={null} testid="shell-b">
        <span>hi</span>
      </ThemedFormShell>,
    );
    const el = getByTestId("shell-b");
    expect(el.getAttribute("data-themed")).toBe("false");
    expect(el.style.getPropertyValue("--form-primary")).toBe("");
  });
});
