/**
 * Feb-2026 · Responsive Quote/Estimate follow-up — K71 line-items
 * editor stacked-card fallback for < sm (640 px). Admin
 * ``/quotes/:id`` + ``/invoices/:id`` are the sole consumers of
 * ``K71LineItemsEditor`` — they share this responsive treatment.
 *
 * The desktop ``<table data-testid="k71-line-items-table">`` stays
 * authoritative at ≥ sm; below sm we render a parallel stacked-card
 * ``<ul data-testid="k71-line-items-cards">`` with the same rows +
 * distinct ``-mobile`` testids so pre-existing table-based
 * assertions keep resolving.
 *
 * Coverage:
 *   1. Read mode: table has ``hidden sm:table`` and the mobile
 *      card list is present, exposing per-line cards with
 *      Edit + Delete buttons.
 *   2. Original ``k71-row-<i>`` testids still resolve — backwards
 *      compatibility with 4290 existing tests.
 *   3. Tapping the mobile Edit button routes to the same
 *      ``setEditIndex`` state as the desktop pencil, and while
 *      editing the ``sm:hidden`` mobile list is un-rendered so
 *      the ``EditableRow`` (which lives inside ``<tr>``) becomes
 *      the sole surface + owns focus.
 *   4. Legacy-badge duplication is resolved via a
 *      ``-mobile-<i>`` testid on the mobile card variant.
 *   5. Delete on mobile card enters the same pending-undo state
 *      and surfaces ``k71-undo-toast``.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0B4A6F",
    onBrand: "#FFFFFF",
    onSurface: "#111827",
    onSurfaceSecondary: "#6B7280",
    muted: "#6B7280",
    border: "#E5E7EB",
    divider: "#E5E7EB",
    surface: "#FFFFFF",
    surfaceSecondary: "#F8FAFC",
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));

// CategoryPicker is only mounted inside the edit form; a light
// stub is enough for this test file — every case here starts in
// read mode. K71LineItemsEditor also imports the ``loadCategories``
// helper from this module (Phase P40 — active-category id fetch),
// so the mock must export it too. Returning empty arrays exercises
// the P40 guard's "no active ids known" path, which correctly
// classifies every prefilled row as legacy/valid and never trips
// the stale-category banner — matching this suite's expectations.
vi.mock("@/components/income/CategoryPicker", () => ({
  default: () => null,
  loadCategories: async () => [],
  invalidateCategoryCache: () => {},
}));

import K71LineItemsEditor from "@/components/quotes/K71LineItemsEditor";


const _lines = [
  {
    description: "Design consult",
    long_description: "1-hour walkthrough",
    quantity: 1, unit_price: 125,
    service_category_id: "svc-design",
    income_category_id: "inc-design",
  },
  {
    description: "Backyard pavers",
    quantity: 200, unit_price: 12,
    service_category_id: "svc-hardscape",
    income_category_id: "inc-hardscape",
  },
];


function _renderK71(overrides = {}) {
  const doc = { line_items: _lines, ...overrides.doc };
  return render(
    <K71LineItemsEditor
      doc={doc}
      canEdit={overrides.canEdit ?? true}
      onLinesUpdated={overrides.onLinesUpdated ?? (() => {})}
      onError={overrides.onError ?? (() => {})}
    />,
  );
}


describe("K71LineItemsEditor · responsive mobile cards (< sm)", () => {
  it("read mode: table has 'hidden sm:table' and mobile card list is present", () => {
    _renderK71();
    const table = screen.getByTestId("k71-line-items-table");
    expect(table.className).toMatch(/\bhidden\b/);
    expect(table.className).toMatch(/\bsm:table\b/);
    const cards = screen.getByTestId("k71-line-items-cards");
    expect(cards.className).toMatch(/\bsm:hidden\b/);
    // One card per line, distinct testid namespace.
    expect(screen.getByTestId("k71-card-0")).toBeTruthy();
    expect(screen.getByTestId("k71-card-1")).toBeTruthy();
  });

  it("preserves the original ``k71-row-<i>`` desktop testids (backwards compat)", () => {
    _renderK71();
    expect(screen.getByTestId("k71-row-0")).toBeTruthy();
    expect(screen.getByTestId("k71-row-1")).toBeTruthy();
  });

  it("mobile Edit tap routes to the same edit state; mobile cards vanish while editing", () => {
    _renderK71();
    // Both surfaces present pre-edit.
    expect(screen.getByTestId("k71-line-items-cards")).toBeTruthy();
    // Tap Edit on card 0 via the mobile testid.
    fireEvent.click(screen.getByTestId("k71-card-edit-btn-0"));
    // Edit row is now the sole visible surface (EditableRow lives
    // in a <tr>, so the mobile list MUST unmount so the table can
    // render at every viewport).
    expect(screen.getByTestId("k71-row-edit-0")).toBeTruthy();
    expect(screen.queryByTestId("k71-line-items-cards")).toBeNull();
    // Table itself now renders unconditionally (no ``hidden``).
    const table = screen.getByTestId("k71-line-items-table");
    expect(table.className).not.toMatch(/\bhidden\b/);
    // Cancel returns to card mode.
    fireEvent.click(screen.getByTestId("k71-cancel-0"));
    expect(screen.getByTestId("k71-line-items-cards")).toBeTruthy();
    expect(screen.getByTestId("k71-line-items-table").className)
      .toMatch(/\bhidden sm:table\b/);
  });

  it("legacy badge testid is disambiguated on the mobile card variant", () => {
    _renderK71({
      doc: {
        line_items: [{
          description: "Legacy import",
          quantity: 1, unit_price: 50,
          // Neither category set → isLegacyLine === true.
        }],
      },
    });
    // Original desktop testid resolves uniquely.
    expect(screen.getByTestId("k71-uncategorized-badge")).toBeTruthy();
    // Mobile duplicate uses a distinct index-scoped testid.
    expect(screen.getByTestId("k71-uncategorized-badge-mobile-0")).toBeTruthy();
  });

  it("mobile Delete tap enters the pending-undo state and shows the undo toast", () => {
    _renderK71();
    fireEvent.click(screen.getByTestId("k71-card-delete-btn-0"));
    expect(screen.getByTestId("k71-undo-toast")).toBeTruthy();
    // Other mobile delete buttons are disabled while pending.
    const otherBtn = screen.getByTestId("k71-card-delete-btn-0")
      || screen.queryByTestId("k71-card-delete-btn-0");
    // The row itself was removed from local state; the remaining
    // card should retain its data-testid + disabled attr on its
    // delete button per the ``pendingDelete !== null`` gate.
    const remaining = screen.queryByTestId("k71-card-delete-btn-0");
    if (remaining) {
      expect(remaining.disabled).toBe(true);
    }
  });
});
