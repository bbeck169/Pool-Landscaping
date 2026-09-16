/**
 * Phase D4 · Feb 2026 — IndustryChecklistForm threads locale into
 * ``GET /api/checklists/industry/{industry}?locale=…`` and re-fetches
 * on ``i18n.language`` change.
 */
import { describe, it, expect, beforeAll, beforeEach, vi } from "vitest";
import { render, cleanup, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";


const apiGet = vi.fn(async (_url) => ({
  industry: "hvac",
  items: [
    { key: "replaced_air_filter",
      label: "Filtro de aire reemplazado",
      label_en: "Replaced air filter",
      label_i18n_available: ["en", "es", "fr"],
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
  await i18n.changeLanguage("en");
  cleanup();
});


describe("Phase D4 · IndustryChecklistForm locale threading", () => {
  it("fetches with ?locale=es when i18n.language is es", async () => {
    await i18n.changeLanguage("es");
    render(<IndustryChecklistForm industry="hvac" checklistItems={[]}
                                     notes="" onChange={() => {}} />);
    await waitFor(() => {
      expect(apiGet).toHaveBeenCalled();
    });
    const url = apiGet.mock.calls[0][0];
    expect(url).toBe("/checklists/industry/hvac?locale=es");
  });

  it("fetches with ?locale=fr when i18n.language is fr", async () => {
    await i18n.changeLanguage("fr");
    render(<IndustryChecklistForm industry="hvac" checklistItems={[]}
                                     notes="" onChange={() => {}} />);
    await waitFor(() => {
      expect(apiGet).toHaveBeenCalled();
    });
    expect(apiGet.mock.calls[0][0]).toBe(
      "/checklists/industry/hvac?locale=fr",
    );
  });

  it("re-fetches when i18n.language changes at runtime", async () => {
    await i18n.changeLanguage("en");
    render(<IndustryChecklistForm industry="hvac" checklistItems={[]}
                                     notes="" onChange={() => {}} />);
    await waitFor(() => {
      expect(apiGet.mock.calls[0][0]).toBe(
        "/checklists/industry/hvac?locale=en",
      );
    });
    // Switch language → second fetch fires.
    await i18n.changeLanguage("fr");
    await waitFor(() => {
      const urls = apiGet.mock.calls.map((c) => c[0]);
      expect(urls).toContain("/checklists/industry/hvac?locale=fr");
    });
  });

  it("pool industry short-circuits — no fetch at all", async () => {
    await i18n.changeLanguage("es");
    render(<IndustryChecklistForm industry="pool" poolProps={{}} />);
    // Give the effect a beat to (not) run.
    await new Promise((r) => setTimeout(r, 20));
    expect(apiGet).not.toHaveBeenCalled();
  });
});
