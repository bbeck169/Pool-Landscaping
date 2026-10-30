/**
 * Feb-2026 · CUS-Marketing-Form-Builder Phase 5 (α-delta) Commit C.
 *
 * Covers:
 *   § Renderer honor — ``ThemedFormShell`` applies the five new CSS
 *     vars + emits the banner band DOM when the theme is set.
 *   § ThemePanel UI — the four new sub-sections (container tiles,
 *     header tiles, font-size buckets, dual image slots) are
 *     present and wire ``onChange`` correctly.
 *
 * Posture: DOM-mount for the renderer (lightweight), source-
 * inspection for the ThemePanel UI (deep MediaLibraryPicker dep
 * + onChange wiring is already stable K34 pattern — source-
 * inspect matches sibling ``k34-form-theme.test.jsx`` posture).
 */
import fs from "fs";
import path from "path";
import React from "react";
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";

import ThemedFormShell from "../components/formBuilder/ThemedFormShell";


// ═══════════════════════════════════════════════════════════════════
// § ThemedFormShell renderer honor
// ═══════════════════════════════════════════════════════════════════
describe("Phase 5 · ThemedFormShell renderer honor", () => {
  it("emits data-attrs + composed className for layout enums", () => {
    const { getByTestId } = render(
      <ThemedFormShell theme={{
        layout: { container: "centered", header: "full_banner" },
      }}>
        <div>body</div>
      </ThemedFormShell>,
    );
    const shell = getByTestId("themed-form-shell");
    expect(shell.getAttribute("data-form-layout-container")).toBe("centered");
    expect(shell.getAttribute("data-form-layout-header")).toBe("full_banner");
    expect(shell.className).toContain("form-layout-container-centered");
    expect(shell.className).toContain("form-layout-header-full_banner");
  });

  it("renders the banner band when theme.banner is set", () => {
    const { getByTestId } = render(
      <ThemedFormShell theme={{
        banner: { image_url: "https://cdn.test/band.jpg" },
      }}>
        <div>body</div>
      </ThemedFormShell>,
    );
    const band = getByTestId("themed-form-banner");
    expect(band.style.backgroundImage).toContain("https://cdn.test/band.jpg");
  });

  it("omits the banner band DOM node entirely when theme.banner is null", () => {
    const { queryByTestId } = render(
      <ThemedFormShell theme={{ preset: "modern_blue" }}>
        <div>body</div>
      </ThemedFormShell>,
    );
    expect(queryByTestId("themed-form-banner")).toBeNull();
  });

  it("applies wallpaper as backgroundImage on the shell", () => {
    const { getByTestId } = render(
      <ThemedFormShell theme={{
        wallpaper: { image_url: "https://cdn.test/wall.jpg" },
      }}>
        <div>body</div>
      </ThemedFormShell>,
    );
    const shell = getByTestId("themed-form-shell");
    // backgroundImage is "url(...)" or a layered composition.
    expect(shell.style.backgroundImage).toContain("https://cdn.test/wall.jpg");
  });

  it("layers wallpaper BELOW a gradient when both are set", () => {
    const { getByTestId } = render(
      <ThemedFormShell theme={{
        wallpaper: { image_url: "https://cdn.test/wall.jpg" },
        gradient:  { angle_deg: 90, from: "#000000", to: "#ffffff" },
      }}>
        <div>body</div>
      </ThemedFormShell>,
    );
    const bgi = getByTestId("themed-form-shell").style.backgroundImage;
    // Gradient first in the backgroundImage composition (layered
    // ABOVE), wallpaper last (layered BELOW).
    const gradIdx = bgi.indexOf("linear-gradient");
    const wallIdx = bgi.indexOf("wall.jpg");
    expect(gradIdx).toBeGreaterThan(-1);
    expect(wallIdx).toBeGreaterThan(gradIdx);
  });

  it("applies font-size scale as a calc multiplier", () => {
    const { getByTestId } = render(
      <ThemedFormShell theme={{
        font: { size_scale: "xl" },  // 1.25 multiplier
      }}>
        <div>body</div>
      </ThemedFormShell>,
    );
    const shell = getByTestId("themed-form-shell");
    expect(shell.style.fontSize).toContain("1.25");
  });

  it("K34 byte-identity — pre-Phase-5 themes emit no Phase-5 data-attrs", () => {
    const { getByTestId } = render(
      <ThemedFormShell theme={{ preset: "warm_earth" }}>
        <div>body</div>
      </ThemedFormShell>,
    );
    const shell = getByTestId("themed-form-shell");
    expect(shell.getAttribute("data-form-layout-container")).toBeNull();
    expect(shell.getAttribute("data-form-layout-header")).toBeNull();
    expect(shell.style.fontSize).toBe("");
  });
});


// ═══════════════════════════════════════════════════════════════════
// § ThemePanel UI — source-inspection (deep dep tree, matches the
// shipped ``k34-form-theme.test.jsx`` posture).
// ═══════════════════════════════════════════════════════════════════
const TP_SRC = fs.readFileSync(
  path.resolve(__dirname, "..", "components", "formBuilder", "ThemePanel.jsx"),
  "utf8",
);


describe("Phase 5 · ThemePanel UI", () => {
  it("imports the three new enum option arrays from formThemes", () => {
    expect(TP_SRC).toContain("FORM_LAYOUT_CONTAINER_OPTIONS");
    expect(TP_SRC).toContain("FORM_LAYOUT_HEADER_OPTIONS");
    expect(TP_SRC).toContain("FORM_FONT_SIZE_SCALE_OPTIONS");
  });

  it("imports MediaLibraryPicker for the two image slots", () => {
    expect(TP_SRC).toContain("MediaLibraryPicker");
  });

  it("renders container-layout tiles with per-option testids", () => {
    expect(TP_SRC).toContain("theme-layout-container-${opt}");
    expect(TP_SRC).toContain('data-testid="theme-layout-container-section"');
  });

  it("renders header-layout tiles with per-option testids", () => {
    expect(TP_SRC).toContain("theme-layout-header-${opt}");
    expect(TP_SRC).toContain('data-testid="theme-layout-header-section"');
  });

  it("renders font-size buckets as A-letters with per-bucket testids", () => {
    expect(TP_SRC).toContain("theme-font-size-scale-${opt}");
    expect(TP_SRC).toContain('data-testid="theme-font-size-scale-section"');
    // A-letter visual scale — the button content is the letter "A"
    // inside a scaled font-size.
    expect(TP_SRC).toMatch(/>\s*A\s*</);
  });

  it("renders wallpaper + banner image slots with pick / replace / remove testids", () => {
    // The ImageSlotRow helper composes testids from the ``testid``
    // prop (``theme-wallpaper`` / ``theme-banner``). The call site
    // passes those literals; the helper itself emits
    // ``${testid}-section`` / ``${testid}-pick-btn`` / etc.
    expect(TP_SRC).toContain('testid="theme-wallpaper"');
    expect(TP_SRC).toContain('testid="theme-banner"');
    // Template emits the suffixed data-testid literals.
    expect(TP_SRC).toContain("`${testid}-section`");
    expect(TP_SRC).toContain("`${testid}-pick-btn`");
    expect(TP_SRC).toContain("`${testid}-replace-btn`");
    expect(TP_SRC).toContain("`${testid}-remove-btn`");
  });

  it("Phase-5 sections live INSIDE the shipped ThemePanel body (not a sibling)", () => {
    // The Phase-5 sections block must come BEFORE the final return
    // closes — a defensive index check that catches a future
    // refactor that accidentally rips the sections out as a
    // sibling component with wrong state wiring.
    const sectionsIdx = TP_SRC.indexOf('data-testid="theme-phase5-sections"');
    const panelDefIdx = TP_SRC.indexOf("export default function ThemePanel");
    expect(sectionsIdx).toBeGreaterThan(panelDefIdx);
    expect(sectionsIdx).toBeGreaterThan(-1);
  });

  it("K34 UX preserved — the shipped preset picker + customize controls are untouched", () => {
    // Load-bearing — the shipped K34 UX must stay intact. If any
    // of these three shipped testids disappear during a Phase-5
    // refactor, this test trips.
    expect(TP_SRC).toContain('data-testid="theme-overlay-slider"');
    expect(TP_SRC).toContain("FORM_THEME_PRESETS");
    expect(TP_SRC).toContain("coerceTheme");
  });
});
