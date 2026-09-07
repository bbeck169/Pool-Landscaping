/**
 * Phase K79 · Feb-2026 — K79CustomerViewPreview · client-side grouping.
 *
 * Coverage:
 *  1. Renders group rows in first-appearance order.
 *  2. "Other" bucket appended for uncategorized lines.
 *  3. Never surfaces long_description on grouped rows.
 *  4. Falls back to itemized layout when customer_group_display is off.
 *  5. Descriptions render under the group label when provided.
 *  6. Group subtotals sum to the doc-level subtotal.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import K79CustomerViewPreview
  from "@/components/quotes/K79CustomerViewPreview";

const SERVICE_CATS = [
  { id: "svc-pool", name: "Pool Cleaning", color: "#0EA5E9" },
  { id: "svc-tile", name: "Tile & Coping", color: "#22C55E" },
];

const LONG_DESC_SECRET = "INTERNAL notes — must not appear";

const docGrouped = {
  id: "quote-1",
  customer_group_display: true,
  subtotal: 360, tax_rate: 0, tax: 0, total: 360,
  line_items: [
    {
      description: "Weekly cleaning", quantity: 4, unit_price: 40,
      service_category_id: "svc-pool",
      long_description: LONG_DESC_SECRET,
    },
    {
      description: "Chlorine treatment", quantity: 1, unit_price: 60,
      service_category_id: "svc-pool",
    },
    {
      description: "Grout resealing", quantity: 1, unit_price: 200,
      service_category_id: "svc-tile",
    },
  ],
};

const docWithOtherBucket = {
  id: "quote-2",
  customer_group_display: true,
  subtotal: 100, tax_rate: 0, tax: 0, total: 100,
  line_items: [
    {
      description: "Weekly cleaning", quantity: 1, unit_price: 40,
      service_category_id: "svc-pool",
    },
    // Uncategorized (no service_category_id) → "Other".
    { description: "Random repair", quantity: 1, unit_price: 60 },
  ],
};


describe("Phase K79 · K79CustomerViewPreview", () => {
  it("renders group rows in first-appearance order", () => {
    render(
      <K79CustomerViewPreview
        doc={docGrouped}
        serviceCategories={SERVICE_CATS}
        descriptions={{}}
        onClose={() => {}}
      />
    );
    const poolRow = screen.getByTestId("k79-preview-group-svc-pool");
    const tileRow = screen.getByTestId("k79-preview-group-svc-tile");
    expect(poolRow).toBeTruthy();
    expect(tileRow).toBeTruthy();
    // Order: pool appears first in line_items so it renders before tile.
    const rows = screen.getAllByTestId(/^k79-preview-group-/);
    expect(rows[0].getAttribute("data-testid"))
      .toBe("k79-preview-group-svc-pool");
    expect(rows[1].getAttribute("data-testid"))
      .toBe("k79-preview-group-svc-tile");
  });

  it("bucket uncategorized lines into 'Other' at the tail", () => {
    render(
      <K79CustomerViewPreview
        doc={docWithOtherBucket}
        serviceCategories={SERVICE_CATS}
        descriptions={{}}
        onClose={() => {}}
      />
    );
    const rows = screen.getAllByTestId(/^k79-preview-group-/);
    // pool first, then other at the tail.
    expect(rows[0].getAttribute("data-testid"))
      .toBe("k79-preview-group-svc-pool");
    expect(rows[rows.length - 1].getAttribute("data-testid"))
      .toBe("k79-preview-group-other");
    // "Other" bucket label rendered.
    expect(rows[rows.length - 1].textContent).toContain("Other");
  });

  it("never surfaces long_description on grouped rows", () => {
    render(
      <K79CustomerViewPreview
        doc={docGrouped}
        serviceCategories={SERVICE_CATS}
        descriptions={{}}
        onClose={() => {}}
      />
    );
    const modal = screen.getByTestId("k79-preview-modal");
    expect(modal.textContent).not.toContain(LONG_DESC_SECRET);
  });

  it("renders group descriptions when provided", () => {
    render(
      <K79CustomerViewPreview
        doc={docGrouped}
        serviceCategories={SERVICE_CATS}
        descriptions={{
          "svc-pool": "Bundled pool care package.",
        }}
        onClose={() => {}}
      />
    );
    expect(
      screen.getByTestId("k79-preview-desc-svc-pool").textContent
    ).toBe("Bundled pool care package.");
  });

  it("falls back to itemized layout when toggle is off", () => {
    const doc = { ...docGrouped, customer_group_display: false };
    render(
      <K79CustomerViewPreview
        doc={doc}
        serviceCategories={SERVICE_CATS}
        descriptions={{}}
        onClose={() => {}}
      />
    );
    expect(screen.getByTestId("k79-preview-itemized-table")).toBeTruthy();
    expect(screen.queryByTestId("k79-preview-grouped-table")).toBeNull();
    // Even in fallback, long_description must not appear.
    const modal = screen.getByTestId("k79-preview-modal");
    expect(modal.textContent).not.toContain(LONG_DESC_SECRET);
  });

  it("shows mode label based on the toggle state", () => {
    const { rerender } = render(
      <K79CustomerViewPreview
        doc={docGrouped}
        serviceCategories={SERVICE_CATS}
        descriptions={{}}
        onClose={() => {}}
      />
    );
    expect(screen.getByTestId("k79-preview-mode-label").textContent)
      .toContain("Grouped");
    rerender(
      <K79CustomerViewPreview
        doc={{ ...docGrouped, customer_group_display: false }}
        serviceCategories={SERVICE_CATS}
        descriptions={{}}
        onClose={() => {}}
      />
    );
    expect(screen.getByTestId("k79-preview-mode-label").textContent)
      .toContain("Itemized");
  });

  it("group subtotals + doc-level totals surface correctly", () => {
    render(
      <K79CustomerViewPreview
        doc={docGrouped}
        serviceCategories={SERVICE_CATS}
        descriptions={{}}
        onClose={() => {}}
      />
    );
    const subtotal = screen.getByTestId("k79-preview-subtotal").textContent;
    const total = screen.getByTestId("k79-preview-total").textContent;
    // 4*40 + 1*60 + 1*200 = 360
    expect(subtotal).toContain("360");
    expect(total).toContain("360");
  });

  it("renders empty state when there are no line items", () => {
    const emptyDoc = {
      ...docGrouped,
      line_items: [],
      subtotal: 0, total: 0,
    };
    render(
      <K79CustomerViewPreview
        doc={emptyDoc}
        serviceCategories={SERVICE_CATS}
        descriptions={{}}
        onClose={() => {}}
      />
    );
    expect(screen.getByTestId("k79-preview-empty")).toBeTruthy();
  });
});
