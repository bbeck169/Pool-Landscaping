/**
 * Phase D3 · Feb 2026 — IndustryChecklistForm swaps the industry
 * display label per locale.
 *
 * Renders the form for ``industry="hvac"`` under each of the three
 * shipped locales and asserts the title text switches accordingly.
 * ``api.get`` is mocked so the fetch never leaves vitest.
 */
import { describe, it, expect, beforeAll, vi } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// Silence the network fetch — we only care about the title label.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async () => ({
      industry: "hvac",
      items: [
        { key: "replaced_air_filter", label: "Replaced air filter",
          required: true },
      ],
      source: "default",
    })),
  },
}));


let i18n;
let IndustryChecklistForm;

beforeAll(async () => {
  const modI18n = await import("../i18n");
  i18n = modI18n.default;
  const mod = await import(
    "../components/checklist/IndustryChecklistForm"
  );
  IndustryChecklistForm = mod.default;
});


async function renderIn(locale) {
  await i18n.changeLanguage(locale);
  cleanup();
  return render(
    <IndustryChecklistForm
      industry="hvac"
      checklistItems={[]}
      notes=""
      onChange={() => {}}
    />,
  );
}


describe("Phase D3 · IndustryChecklistForm respects the active locale", () => {
  it("renders the English HVAC label under en", async () => {
    await renderIn("en");
    const title = await waitFor(
      () => screen.getByTestId("industry-checklist-title-hvac"),
    );
    expect(title.textContent).toBe("HVAC");
  });

  it("renders the Spanish HVAC label under es", async () => {
    await renderIn("es");
    const title = await waitFor(
      () => screen.getByTestId("industry-checklist-title-hvac"),
    );
    // Spanish keeps the HVAC acronym per translator-notes README.
    expect(title.textContent).toBe("HVAC");
  });

  it("renders the French CVC label under fr", async () => {
    await renderIn("fr");
    const title = await waitFor(
      () => screen.getByTestId("industry-checklist-title-hvac"),
    );
    expect(title.textContent).toBe("CVC");
  });

  it("empty-state message localises correctly", async () => {
    // Re-mock the fetch to return zero items so the empty branch
    // renders.
    const { api } = await import("@/api");
    api.get.mockResolvedValueOnce({ industry: "hvac", items: [], source: "default" });
    await i18n.changeLanguage("es");
    cleanup();
    render(
      <IndustryChecklistForm
        industry="hvac" checklistItems={[]} notes="" onChange={() => {}}
      />,
    );
    const empty = await waitFor(
      () => screen.getByTestId("industry-checklist-empty"),
    );
    expect(empty.textContent).toContain(
      "Aún no hay elementos configurados",
    );
  });
});
