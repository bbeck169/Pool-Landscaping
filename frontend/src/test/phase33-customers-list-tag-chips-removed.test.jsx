/**
 * Feb-2026 · P33 — CustomersList row rendering & tag-catalog filter.
 *
 * Pins:
 *   1. Row-level tag chips are REMOVED. A row with
 *      ``tags: ["Landscaping", "Pool"]`` renders no ``TagChip`` and
 *      contains no visible text for those tag labels.
 *   2. VIP badge + Mark Muted button + Inactive pill still render
 *      exactly as before — the removal is scoped strictly to the
 *      free-text tag chips.
 *   3. The top-of-list "All tags" filter is populated from the
 *      tenant catalog (``GET /api/customer-tags``), not from the
 *      currently rendered rows — so a tag that exists in the
 *      catalog but on ZERO visible rows still shows up as an option.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ── Mocks ────────────────────────────────────────────────────────────
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: "admin", effectiveRole: "admin",
    isAdmin: true, isAdminOrManager: true, canDo: () => true,
  }),
}));

const mockGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(), warning: vi.fn(),
  }),
}));


import CustomersList from "@/pages/customers/CustomersList";


function _mount() {
  return render(
    <MemoryRouter initialEntries={["/customers"]}>
      <CustomersList />
    </MemoryRouter>,
  );
}


function _installGetRouter({ catalogTags = [], rows = [] } = {}) {
  mockGet.mockImplementation((path) => {
    if (path.startsWith("/customer-tags")) {
      return Promise.resolve({ items: catalogTags });
    }
    if (path.includes("count_only=true")) {
      return Promise.resolve({ count: rows.length });
    }
    if (path.startsWith("/customers")) {
      return Promise.resolve(rows);
    }
    return Promise.resolve({});
  });
}


beforeEach(() => {
  mockGet.mockClear();
});


describe("CustomersList · P33 row-chip removal + catalog filter", () => {
  it("renders NO tag chip on a row that has tags", async () => {
    _installGetRouter({
      catalogTags: [
        { id: "t-land", name: "Landscaping", usage_count: 4 },
        { id: "t-pool", name: "Pool",        usage_count: 12 },
      ],
      rows: [
        { id: "c-1", name: "Landscape + Pool Combo",
          is_active: true, is_vip: true,
          tags: ["Landscaping", "Pool"] },
      ],
    });
    _mount();
    await waitFor(() => expect(screen.getByTestId("customer-row-c-1"))
      .toBeTruthy());
    const row = screen.getByTestId("customer-row-c-1");

    // The removed testids MUST NOT be present on the row.
    expect(within(row).queryByTestId("row-c-1-tag-Landscaping")).toBeNull();
    expect(within(row).queryByTestId("row-c-1-tag-Pool")).toBeNull();

    // Free-text scan of the row — no visible "Landscaping" / "Pool"
    // chip label inside the row. (The customer name may match "Pool"
    // via substring, so we look for exact chip-text semantics: any
    // element whose textContent is EXACTLY the tag label.)
    const tagLabels = ["Landscaping", "Pool"];
    for (const label of tagLabels) {
      const exact = within(row).queryAllByText(
        (_content, el) => el.textContent === label && el.children.length === 0,
      );
      expect(exact.length).toBe(0);
    }

    // Positive: VIP badge is still on the row.
    expect(within(row).queryByTestId("row-c-1-vip-badge")).toBeTruthy();
  });

  it("Inactive pill still renders (unrelated to tag chips)", async () => {
    _installGetRouter({
      catalogTags: [],
      rows: [
        { id: "c-2", name: "Inactive Ivan",
          is_active: false, tags: ["Landscaping"] },
      ],
    });
    _mount();
    await waitFor(() => expect(screen.getByTestId("customer-row-c-2"))
      .toBeTruthy());
    const row = screen.getByTestId("customer-row-c-2");
    expect(within(row).queryByTestId("row-c-2-inactive-pill")).toBeTruthy();
    // Tag chip removed even though the row has tags.
    expect(within(row).queryByTestId("row-c-2-tag-Landscaping")).toBeNull();
  });

  it("catalog-only tags surface in the top-of-list filter dropdown", async () => {
    // ``Ghost tag`` exists in the tenant catalog but NO visible row
    // carries it. Pre-P33 the filter derived from visible rows and
    // this tag would be missing. Post-P33 the filter is sourced from
    // ``GET /customer-tags`` so it MUST appear as an option once the
    // dropdown is opened.
    _installGetRouter({
      catalogTags: [
        { id: "t-ghost", name: "Ghost tag", usage_count: 0 },
        { id: "t-real",  name: "Real tag",  usage_count: 1 },
      ],
      rows: [
        { id: "c-3", name: "Some customer",
          is_active: true, tags: ["Real tag"] },
      ],
    });
    _mount();

    // 1) Catalog fetch fired.
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      expect(calls.some((p) => p.startsWith("/customer-tags"))).toBe(true);
    });

    // 2) Open the tag-filter dropdown so the option list renders.
    const trigger = await screen.findByTestId("customers-tag-filter-button");
    trigger.click();

    // 3) The catalog-only "Ghost tag" appears as a selectable option
    //    inside the popover — matched by the locked testid.
    await waitFor(() => expect(
      screen.queryByTestId("customers-tag-filter-option-Ghost tag"),
    ).toBeTruthy());
    expect(screen.getByTestId("customers-tag-filter-option-Real tag"))
      .toBeTruthy();
  });
});
