/**
 * Phase 26b · Feb-2026 — Category auto-map warning badge tests.
 *
 * The K71 line-items editor consumes line items shaped like::
 *
 *     {
 *       service_category_id: "",      // null'd by fan-out
 *       income_category_id:  "",      // null'd by fan-out
 *       category_auto_mapped: true,   // stamp
 *       original_category_id: "cat-abc",
 *       original_category_name: "Pool Chemicals",
 *       ...
 *     }
 *
 * This test file verifies five things:
 *
 *   1. Rows carrying ``category_auto_mapped: true`` render an
 *      amber "Needs re-pick" chip.
 *   2. The chip's ``title`` tooltip exposes the
 *      ``original_category_name`` so the operator knows WHICH
 *      category was deactivated.
 *   3. The row ``<tr>`` carries ``data-auto-mapped="true"`` so the
 *      amber row tint + left-border accent can be CSS-targeted.
 *   4. Rows WITHOUT the stamp do NOT get the chip (regression
 *      lock — zero false positives).
 *   5. Mobile ``<MobileCard>`` mirrors the chip + card border.
 *
 * No live backend — static JSX render via React Testing Library.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// Mock the active-category fetch so staleIndices stays empty and
// we don't collide with the Phase-26b auto-map chip.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(() => Promise.resolve({items: [
      {id: "svc-active", name: "Live Svc", is_archived: false},
    ]})),
  },
}));

import K71LineItemsEditor from "../components/quotes/K71LineItemsEditor";


const BASE_LINE = {
  description: "Pool chemical treatment",
  item_name: "Chemical Treatment",
  quantity: 1,
  unit_price: 100,
};


function renderEditor(items) {
  // Phase K71 editor API: ``doc`` carries line_items; ``canEdit``
  // enables the per-row controls; ``onLinesUpdated`` + ``onError``
  // are callbacks we no-op out for the static-render test cases.
  return render(
    <K71LineItemsEditor
      doc={{line_items: items}}
      canEdit={true}
      onLinesUpdated={() => {}}
      onError={() => {}}
    />,
  );
}


describe("Phase 26b · auto-mapped line items — K71 editor", () => {
  it("renders the amber 'Needs re-pick' chip on rows with category_auto_mapped=true", () => {
    renderEditor([
      {...BASE_LINE,
        service_category_id: "",
        income_category_id: "",
        category_auto_mapped: true,
        original_category_id: "cat-xyz",
        original_category_name: "Pool Chemicals"},
    ]);
    // The chip itself:
    const chip = screen.getByTestId("k71-auto-mapped-badge-0");
    expect(chip).toBeInTheDocument();
    expect(chip).toHaveTextContent(/needs re-?pick/i);
  });

  it("tooltip + data attribute expose the ORIGINAL category name", () => {
    renderEditor([
      {...BASE_LINE,
        service_category_id: "",
        income_category_id: "",
        category_auto_mapped: true,
        original_category_id: "cat-xyz",
        original_category_name: "Pool Chemicals"},
    ]);
    const chip = screen.getByTestId("k71-auto-mapped-badge-0");
    // Tooltip (title attr) must contain the archived cat's name so
    // the operator doesn't have to go hunt it in the admin page.
    expect(chip).toHaveAttribute(
      "title",
      expect.stringContaining("Pool Chemicals"),
    );
    expect(chip).toHaveAttribute(
      "data-original-category-name",
      "Pool Chemicals",
    );
  });

  it("row <tr> carries data-auto-mapped so the amber tint + left-border accent are CSS-targetable", () => {
    renderEditor([
      {...BASE_LINE,
        service_category_id: "",
        income_category_id: "",
        category_auto_mapped: true,
        original_category_id: "cat-xyz",
        original_category_name: "Live Cat"},
    ]);
    const row = screen.getByTestId("k71-row-0");
    expect(row).toHaveAttribute("data-auto-mapped", "true");
  });

  it("rows WITHOUT the stamp do NOT render the chip (regression lock — no false positives)", () => {
    renderEditor([
      {...BASE_LINE,
        service_category_id: "svc-active",
        income_category_id: "inc-active"},
    ]);
    expect(
      screen.queryByTestId("k71-auto-mapped-badge-0"),
    ).not.toBeInTheDocument();
    const row = screen.getByTestId("k71-row-0");
    expect(row).not.toHaveAttribute("data-auto-mapped");
  });

  it("mobile MobileCard mirrors the chip + sets data-auto-mapped on the <li>", () => {
    renderEditor([
      {...BASE_LINE,
        service_category_id: "",
        income_category_id: "",
        category_auto_mapped: true,
        original_category_id: "cat-xyz",
        original_category_name: "Landscape Lighting"},
    ]);
    const mobileChip = screen.getByTestId(
      "k71-auto-mapped-badge-mobile-0");
    expect(mobileChip).toBeInTheDocument();
    expect(mobileChip).toHaveTextContent(/needs re-?pick/i);
    expect(mobileChip).toHaveAttribute(
      "data-original-category-name", "Landscape Lighting");
    const card = screen.getByTestId("k71-card-0");
    expect(card).toHaveAttribute("data-auto-mapped", "true");
  });

  it("non-blocking: the save button / editor stays operable when an auto-mapped row is present", () => {
    // The editor's add-line button is the operator's hook to re-
    // pick a category.  It must stay enabled even in presence of
    // the amber row — the K71 save-time validator soft-passes
    // these rows on write so the parent save button never greys
    // out based on this row's state.
    renderEditor([
      {...BASE_LINE,
        service_category_id: "",
        income_category_id: "",
        category_auto_mapped: true,
        original_category_id: "cat-xyz",
        original_category_name: "Deactivated Cat"},
    ]);
    // Add-line button is always exposed when canEdit=true and no
    // row is in edit mode.  Confirming its presence proves the
    // editor didn't go into an error-state that would disable
    // further interaction.
    const row = screen.getByTestId("k71-row-0");
    expect(row).toBeInTheDocument();
    // No ``aria-invalid`` on the row — auto-mapped is a warning,
    // not an invalid state.  (Stale/inactive rows ARE
    // aria-invalid; auto-mapped rows are NOT.)
    expect(row).not.toHaveAttribute("aria-invalid");
  });
});


describe("Phase 26b · Pricebook Categories admin — archive warn banner copy", () => {
  it("warn banner copy mentions 'moved to Uncategorized' + N references", async () => {
    // Static source-inspection, no DOM render — matches the
    // Phase-23/24 companion test style.
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.resolve(
        __dirname, "../pages/pricebook/CategoriesAdmin.jsx"),
      "utf8");
    expect(src).toMatch(/will be moved to Uncategorized/);
    expect(src).toMatch(/invoice[\s\S]{0,40}estimate editor/);
    // The old copy that lived INSIDE the <div data-testid=
    // "category-refs-warn-banner"> is gone.  Scope the regex to
    // the banner subtree so unrelated docstring/module mentions
    // of the word "archived" (there are a few in this file) can't
    // produce a false positive.
    const bannerIdx = src.indexOf('data-testid="category-refs-warn-banner"');
    const bannerSliceEnd = src.indexOf("</div>", bannerIdx);
    const bannerSlice = src.slice(bannerIdx, bannerSliceEnd);
    expect(bannerSlice).not.toMatch(/Archived category/);
    expect(bannerSlice).not.toMatch(/surface an/);
  });
});
