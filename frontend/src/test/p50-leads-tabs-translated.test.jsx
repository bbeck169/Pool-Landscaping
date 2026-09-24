/**
 * Phase P50 · Feb-2026 — LeadsDashboardPage translation smoke.
 *
 * Mounts the real page in each of the three locales (EN/ES/FR)
 * and asserts the P50-scoped strings render the translated
 * literal AND the pre-existing data-testids are preserved:
 *
 *   * Tab labels (leads-tab-active / leads-tab-archive)
 *   * Search input placeholder (lead-search-input)
 *   * "All statuses" filter (lead-filter-status-select)
 *   * Status dropdown option (lead-status-option-new)
 *
 * Reuses the P48 mount pattern: MemoryRouter wrap for
 * useSearchParams, vi.mock for @/api / sonner / confirm-dialog.
 * Adds an eager import of ``@/i18n`` so the singleton is
 * initialised for this worker.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import i18n from "@/i18n";

const apiGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGet(...a),
    post: vi.fn().mockResolvedValue({}),
    del: vi.fn().mockResolvedValue({}),
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));
vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(() => Promise.resolve(true)),
}));

async function tick(n = 4) {
  await act(async () => {
    for (let i = 0; i < n; i += 1) await Promise.resolve();
  });
}


beforeAll(async () => {
  // Start every run at EN.  Individual tests flip.
  await i18n.changeLanguage("en");
});

beforeEach(() => {
  apiGet.mockReset();
  // Empty leads list → the empty-state block renders → we get the
  // tab-scoped "No active/archived leads yet" copy.
  apiGet.mockResolvedValue({ rows: [], total: 0, page: 1, page_size: 200 });
});


async function mountAt(initialEntry) {
  const { default: LeadsDashboardPage } =
    await import("@/pages/leads/LeadsDashboardPage");
  const utils = render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <LeadsDashboardPage />
    </MemoryRouter>,
  );
  await tick();
  return utils;
}


// ─── Expected translations (mirrors leads.json locale bundles) ──────
const T = {
  en: {
    active: "Active",
    archive: "Archive",
    search: "Search name, email, phone",
    allStatuses: "All statuses",
    statusNew: "New",
    emptyActiveTitle: "No active leads yet.",
    emptyArchiveTitle: "No archived leads yet.",
  },
  es: {
    active: "Activos",
    archive: "Archivados",
    search: "Buscar nombre, correo o teléfono",
    allStatuses: "Todos los estados",
    statusNew: "Nuevo",
    emptyActiveTitle: "Aún no hay clientes potenciales activos.",
    emptyArchiveTitle: "Aún no hay clientes potenciales archivados.",
  },
  fr: {
    active: "Actifs",
    archive: "Archivés",
    search: "Rechercher nom, e-mail, téléphone",
    allStatuses: "Tous les statuts",
    statusNew: "Nouveau",
    emptyActiveTitle: "Aucun prospect actif pour le moment.",
    emptyArchiveTitle: "Aucun prospect archivé pour le moment.",
  },
};


// One suite per locale — keeps the failure trace obvious ("ES failed
// on the status dropdown label" vs "one big test broke somewhere").
for (const locale of ["en", "es", "fr"]) {
  describe(`P50 · LeadsDashboardPage renders ${locale.toUpperCase()}`, () => {
    it(`tab labels, search placeholder, "All statuses", status ` +
       `dropdown option and empty states all render the ${locale} ` +
       `translation while every P48 data-testid is preserved`, async () => {
      await i18n.changeLanguage(locale);
      const { unmount } = await mountAt("/leads");
      const exp = T[locale];

      // ── Tab labels ──────────────────────────────────────────
      const active = screen.getByTestId("leads-tab-active");
      const archive = screen.getByTestId("leads-tab-archive");
      expect(active.textContent).toContain(exp.active);
      expect(archive.textContent).toContain(exp.archive);

      // ── Search input placeholder ────────────────────────────
      const search = screen.getByTestId("lead-search-input");
      expect(search.getAttribute("placeholder")).toBe(exp.search);

      // ── Status filter dropdown "All …" option (first <option>) ─
      const statusSelect = screen.getByTestId("lead-filter-status-select");
      const firstOpt = statusSelect.querySelector("option");
      expect(firstOpt.textContent).toBe(exp.allStatuses);

      // ── Status option "new" (the P48 tab-scoped dropdown) ───
      const newOpt = screen.getByTestId("lead-status-option-new");
      expect(newOpt.textContent).toBe(exp.statusNew);

      // ── Empty state · Active tab ────────────────────────────
      // Empty state title is inside the ``admin-leads-empty-active``
      // block; ``textContent`` includes both title + subtitle so
      // ``.toContain`` is sufficient (regex-avoidant).
      const emptyActive = screen.getByTestId("admin-leads-empty-active");
      expect(emptyActive.textContent).toContain(exp.emptyActiveTitle);

      unmount();
    });
  });
}


// ─── One extra smoke: locale switch mid-lifecycle re-renders ────────
describe("P50 · LeadsDashboardPage · runtime locale switch", () => {
  it("changing i18n.language from EN to ES flips the tab labels " +
     "in situ (re-render on the next paint)", async () => {
    await i18n.changeLanguage("en");
    const { unmount } = await mountAt("/leads");
    expect(screen.getByTestId("leads-tab-active").textContent)
      .toContain("Active");
    expect(screen.getByTestId("leads-tab-archive").textContent)
      .toContain("Archive");

    // Flip locale — react-i18next subscribes to i18n events so the
    // ``useTranslation`` hook re-renders on ``languageChanged``.
    await act(async () => {
      await i18n.changeLanguage("es");
    });
    await tick();

    expect(screen.getByTestId("leads-tab-active").textContent)
      .toContain("Activos");
    expect(screen.getByTestId("leads-tab-archive").textContent)
      .toContain("Archivados");

    // Restore for downstream tests.
    await i18n.changeLanguage("en");
    unmount();
  });
});
