/**
 * Feb-2026 · TD-form-builder-accordion-ux-polish — vitest for the
 * accordion UX wrap added to the Phase-5 ThemePanel sections.
 *
 * Operator spec:
 *   * Each section header is a ``<button>`` with ``aria-expanded``.
 *   * Default state: ``Style`` expanded, others collapsed.
 *   * Section toggles on click.
 *   * Keyboard (Enter / Space) toggles via the button role.
 *   * Shipped Phase 5 UX byte-identical when sections are expanded.
 *   * All existing data-testids preserved.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";

import ThemePanel from "../components/formBuilder/ThemePanel";


const TP_SRC = fs.readFileSync(
  path.resolve(
    __dirname, "..", "components", "formBuilder", "ThemePanel.jsx",
  ),
  "utf8",
);


describe("Accordion UX · structure (source-inspect)", () => {
  it("Phase 5 sections wrapped in <AccordionSection> helper", () => {
    expect(TP_SRC).toContain("function AccordionSection(");
    // All four Phase-5 accordions mounted.
    expect(TP_SRC).toContain('sectionKey="style"');
    expect(TP_SRC).toContain('sectionKey="font"');
    expect(TP_SRC).toContain('sectionKey="wallpaper"');
    expect(TP_SRC).toContain('sectionKey="banner"');
  });

  it("default open state — Style expanded, others collapsed", () => {
    // The useState initialiser carries the operator-spec defaults.
    const normalised = TP_SRC.replace(/\s+/g, " ");
    expect(normalised).toContain(
      "style: true, font: false, wallpaper: false, banner: false,",
    );
  });

  it("Phase 5 testids preserved — shipped selectors still work", () => {
    // Load-bearing: previously-shipped Phase 5 vitest selectors
    // (`form-builder-phase5-ui-renderer.test.jsx`) must still find
    // these section testids.
    expect(TP_SRC).toContain('data-testid="theme-layout-container-section"');
    expect(TP_SRC).toContain('data-testid="theme-layout-header-section"');
    expect(TP_SRC).toContain('data-testid="theme-font-size-scale-section"');
    expect(TP_SRC).toContain('testid="theme-wallpaper"');
    expect(TP_SRC).toContain('testid="theme-banner"');
  });

  it("AccordionSection headers are <button> with aria-expanded + aria-controls", () => {
    const normalised = TP_SRC.replace(/\s+/g, " ");
    expect(normalised).toContain('aria-expanded={isOpen}');
    expect(normalised).toContain('aria-controls={contentId}');
    // Content region is linked back via aria-labelledby.
    expect(normalised).toContain('aria-labelledby={headerId}');
    expect(normalised).toContain('role="region"');
  });

  it("collapsed content uses ``hidden`` not conditional render", () => {
    // Operator risk-flag mitigation (from the original TD stub):
    // avoid re-mount on collapse so MediaLibraryPicker state +
    // selected values survive the collapse/expand cycle.
    expect(TP_SRC).toContain("hidden={!isOpen}");
    // No conditional render pattern that would re-mount children.
    expect(TP_SRC).not.toMatch(
      /isOpen \? <ImageSlotRow|isOpen && <ImageSlotRow/,
    );
  });
});


describe("Accordion UX · DOM behaviour", () => {
  const mountPanel = () =>
    render(<ThemePanel value={{ preset: "modern_blue" }} onChange={() => {}} />);

  it("Style content visible on mount, others hidden", () => {
    const { getByTestId } = mountPanel();
    expect(getByTestId("theme-accordion-style-content").hidden).toBe(false);
    expect(getByTestId("theme-accordion-font-content").hidden).toBe(true);
    expect(getByTestId("theme-accordion-wallpaper-content").hidden).toBe(true);
    expect(getByTestId("theme-accordion-banner-content").hidden).toBe(true);
  });

  it("aria-expanded reflects open state on each header", () => {
    const { getByTestId } = mountPanel();
    expect(getByTestId("theme-accordion-style-header")
      .getAttribute("aria-expanded")).toBe("true");
    expect(getByTestId("theme-accordion-font-header")
      .getAttribute("aria-expanded")).toBe("false");
  });

  it("clicking a collapsed header expands it", () => {
    const { getByTestId } = mountPanel();
    const fontHeader = getByTestId("theme-accordion-font-header");
    fireEvent.click(fontHeader);
    expect(fontHeader.getAttribute("aria-expanded")).toBe("true");
    expect(getByTestId("theme-accordion-font-content").hidden).toBe(false);
    // Font-size bucket controls now reachable.
    expect(getByTestId("theme-font-size-scale-xs")).toBeTruthy();
  });

  it("clicking an expanded header collapses it", () => {
    const { getByTestId } = mountPanel();
    const styleHeader = getByTestId("theme-accordion-style-header");
    expect(styleHeader.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(styleHeader);
    expect(styleHeader.getAttribute("aria-expanded")).toBe("false");
    expect(getByTestId("theme-accordion-style-content").hidden).toBe(true);
  });

  it("sections toggle independently — expanding Font doesn't collapse Style", () => {
    const { getByTestId } = mountPanel();
    fireEvent.click(getByTestId("theme-accordion-font-header"));
    expect(getByTestId("theme-accordion-style-header")
      .getAttribute("aria-expanded")).toBe("true");
    expect(getByTestId("theme-accordion-font-header")
      .getAttribute("aria-expanded")).toBe("true");
  });

  it("buttons are keyboard-reachable (focusable, button role)", () => {
    const { getByTestId } = mountPanel();
    const h = getByTestId("theme-accordion-wallpaper-header");
    // ``<button type="button">`` is inherently focusable + Enter/
    // Space trigger onClick — the browser's native button role.
    expect(h.tagName).toBe("BUTTON");
    expect(h.getAttribute("type")).toBe("button");
  });
});
