/**
 * Phase D4 · Feb 2026 — translation-pending badge.
 *
 * When a row's ``label_i18n_available`` list does NOT contain the
 * active locale, we render a small "EN" chip with the English
 * label as the tooltip so techs know the visible text isn't in
 * their language yet.
 */
import { describe, it, expect, beforeAll, beforeEach, vi } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";


const apiGet = vi.fn(async (_url) => ({
  industry: "hvac",
  items: [
    // ES translation missing — should show the pending badge.
    { key: "replaced_air_filter",
      label: "Replaced air filter",                 // fallback to en
      label_en: "Replaced air filter",
      label_i18n_available: ["en"],
      required: true },
    // ES translation present — should NOT show the badge.
    { key: "checked_thermostat",
      label: "Calibración del termostato verificada",
      label_en: "Checked thermostat calibration",
      label_i18n_available: ["en", "es"],
      required: true },
  ],
  source: "default",
  locale: "es",
}));

vi.mock("@/api", () => ({ api: { get: apiGet } }));


let i18n;
let IndustryChecklistForm;

beforeAll(async () => {
  const modI18n = await import("../i18n");
  i18n = modI18n.default;
  const mod = await import("../components/checklist/IndustryChecklistForm");
  IndustryChecklistForm = mod.default;
});

beforeEach(async () => {
  apiGet.mockClear();
  cleanup();
});


describe("Phase D4 · translation-pending badge", () => {
  it("renders the badge on rows where the active locale is not available", async () => {
    await i18n.changeLanguage("es");
    render(<IndustryChecklistForm industry="hvac" checklistItems={[]}
                                     notes="" onChange={() => {}} />);
    const badge = await waitFor(
      () => screen.getByTestId(
        "industry-check-translation-pending-replaced_air_filter",
      ),
    );
    expect(badge.textContent).toBe("EN");
    const title = badge.getAttribute("title") || "";
    expect(title).toContain("Este ítem aún no ha sido traducido");
    expect(title).toContain("Replaced air filter");
  });

  it("does NOT render the badge on rows where the active locale IS available", async () => {
    await i18n.changeLanguage("es");
    render(<IndustryChecklistForm industry="hvac" checklistItems={[]}
                                     notes="" onChange={() => {}} />);
    await waitFor(() => {
      // Wait until at least one row is rendered.
      expect(
        screen.getByTestId("industry-check-checked_thermostat"),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByTestId(
        "industry-check-translation-pending-checked_thermostat",
      ),
    ).not.toBeInTheDocument();
  });

  it("under English locale, no row gets the badge", async () => {
    await i18n.changeLanguage("en");
    render(<IndustryChecklistForm industry="hvac" checklistItems={[]}
                                     notes="" onChange={() => {}} />);
    await waitFor(() => {
      expect(
        screen.getByTestId("industry-check-replaced_air_filter"),
      ).toBeInTheDocument();
    });
    // Row has ``["en"]`` in ``label_i18n_available`` — locale is en
    // → no badge.
    expect(
      screen.queryByTestId(
        "industry-check-translation-pending-replaced_air_filter",
      ),
    ).not.toBeInTheDocument();
  });
});
