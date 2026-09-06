/**
 * Feb-2026 · UncategorizedItemsReport — Vitest spec.
 *
 * Locks the frontend behaviour of the ``/reports/uncategorized-items``
 * page including the two-taxonomy scope-addendum:
 *
 *   1. Page renders with the expected header count and the
 *      shared testids (report container, count, filter bar).
 *   2. Missing-side toggle switches the ``?missing=`` URL param
 *      between income / service / either / both.
 *   3. Row highlighting — a row with ``missing_income=true`` shows
 *      the Income control highlighted (data-missing-income="true");
 *      row with ``missing_service=true`` shows the Service control
 *      highlighted; row missing both shows both highlighted.
 *   4. Row lifecycle — assigning Income to a row missing both
 *      clears the Income highlight but keeps the row visible with
 *      Service still highlighted.
 *   5. Row lifecycle — dismissing a partially-categorized row via
 *      the X button removes it from the visible list.
 *   6. Empty state — count 0 renders the success card.
 *   7. Filter URL persistence — clicking the "Missing Both" chip
 *      writes ``?missing=both`` to the URL.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor, within,
} from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";


// ── shared mocks ─────────────────────────────────────────────
const _apiGet = vi.fn();
const _apiPost = vi.fn();
const _apiDel = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...a) => _apiGet(...a),
    post: (...a) => _apiPost(...a),
    del: (...a) => _apiDel(...a),
    patch: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(), info: vi.fn(),
  }),
}));


import UncategorizedItemsReport from "@/pages/reports/UncategorizedItemsReport";


// ── fixtures ─────────────────────────────────────────────────
const _rowMissingBoth = {
  invoice_id: "inv-A", invoice_number: "INV-001",
  customer_name: "Ada Lovelace", customer_id: "c-1",
  created_at: "2026-02-15T10:00:00Z",
  line_item_index: 0,
  description: "Weekly pool service",
  quantity: 1, unit_price: 100, amount: 100,
  income_category_id: "", income_category_name: "",
  service_category_id: "", service_category_name: "",
  missing_income: true, missing_service: true,
};
const _rowMissingIncome = {
  invoice_id: "inv-B", invoice_number: "INV-002",
  customer_name: "Grace Hopper", customer_id: "c-2",
  created_at: "2026-02-14T10:00:00Z",
  line_item_index: 0,
  description: "Chemicals",
  quantity: 1, unit_price: 40, amount: 40,
  income_category_id: "", income_category_name: "",
  service_category_id: "svc-pool", service_category_name: "Pool Service",
  missing_income: true, missing_service: false,
};
const _rowMissingService = {
  invoice_id: "inv-C", invoice_number: "INV-003",
  customer_name: "Alan Turing", customer_id: "c-3",
  created_at: "2026-02-13T10:00:00Z",
  line_item_index: 0,
  description: "Emergency call",
  quantity: 1, unit_price: 200, amount: 200,
  income_category_id: "inc-pool", income_category_name: "Pool",
  service_category_id: "", service_category_name: "",
  missing_income: false, missing_service: true,
};

const _fixtureRows = [_rowMissingBoth, _rowMissingIncome, _rowMissingService];


function _defaultApiImpl(path) {
  if (path.startsWith("/income-categories")) {
    return Promise.resolve({ items: [
      { id: "inc-pool", name: "Pool", color: "#123456" },
      { id: "inc-chem", name: "Chemicals", color: "#654321" },
    ]});
  }
  if (path.startsWith("/service-categories")) {
    return Promise.resolve({ items: [
      { id: "svc-pool", name: "Pool Service", color: "#abcdef" },
      { id: "svc-lawn", name: "Landscaping", color: "#fedcba" },
    ]});
  }
  if (path.startsWith("/reports/uncategorized-items")) {
    return Promise.resolve({
      items: _fixtureRows,
      total: _fixtureRows.length,
      range: "all", missing: "either",
    });
  }
  return Promise.resolve({ items: [], total: 0 });
}


// Location observer — captures the current URL so tests can assert
// on ``?missing=`` persistence.
function LocationObserver({ onChange }) {
  const loc = useLocation();
  React.useEffect(() => { onChange(loc); }, [loc, onChange]);
  return null;
}


function _mount(url = "/reports/uncategorized-items") {
  const locations = [];
  const view = render(
    <MemoryRouter initialEntries={[url]}>
      <UncategorizedItemsReport />
      <LocationObserver onChange={(l) => locations.push(l)} />
    </MemoryRouter>,
  );
  return { ...view, locations };
}


beforeEach(() => {
  _apiGet.mockReset();
  _apiPost.mockReset();
  _apiDel.mockReset();
  _apiGet.mockImplementation(_defaultApiImpl);
});
afterEach(() => cleanup());


describe("UncategorizedItemsReport · header + fixtures", () => {
  it("renders the count with '3 of 3 uncategorized line items'", async () => {
    _mount();
    const count = await screen.findByTestId("uncategorized-items-count");
    await waitFor(() =>
      expect(count.textContent).toMatch(/3 of 3/));
  });

  it("shows all three fixture rows in the table", async () => {
    _mount();
    await screen.findByTestId("uncategorized-items-report");
    // Wait for the rows to hydrate.
    await waitFor(() =>
      expect(screen.getByTestId("uncategorized-row-inv-A::0")).toBeTruthy());
    expect(screen.getByTestId("uncategorized-row-inv-B::0")).toBeTruthy();
    expect(screen.getByTestId("uncategorized-row-inv-C::0")).toBeTruthy();
  });
});


describe("UncategorizedItemsReport · missing-side highlighting", () => {
  it("row missing both shows BOTH Income + Service highlighted", async () => {
    _mount();
    await screen.findByTestId("uncategorized-row-inv-A::0");
    const incCell = screen.getByTestId("uncategorized-income-cell-inv-A::0");
    const svcCell = screen.getByTestId("uncategorized-service-cell-inv-A::0");
    expect(incCell.getAttribute("data-missing-income")).toBe("true");
    expect(svcCell.getAttribute("data-missing-service")).toBe("true");
    // Both pickers rendered inside the cells.
    expect(within(incCell).getByTestId("uncategorized-income-picker-inv-A::0")).toBeTruthy();
    expect(within(svcCell).getByTestId("uncategorized-service-picker-inv-A::0")).toBeTruthy();
  });

  it("row missing only Income shows Income highlighted, Service as chip", async () => {
    _mount();
    await screen.findByTestId("uncategorized-row-inv-B::0");
    const incCell = screen.getByTestId("uncategorized-income-cell-inv-B::0");
    const svcCell = screen.getByTestId("uncategorized-service-cell-inv-B::0");
    expect(incCell.getAttribute("data-missing-income")).toBe("true");
    expect(svcCell.getAttribute("data-missing-service")).toBe("false");
    // Service chip carries the existing category name.
    expect(
      within(svcCell).getByTestId("uncategorized-service-chip-inv-B::0").textContent,
    ).toContain("Pool Service");
  });

  it("row missing only Service shows Service highlighted, Income as chip", async () => {
    _mount();
    await screen.findByTestId("uncategorized-row-inv-C::0");
    const incCell = screen.getByTestId("uncategorized-income-cell-inv-C::0");
    const svcCell = screen.getByTestId("uncategorized-service-cell-inv-C::0");
    expect(incCell.getAttribute("data-missing-income")).toBe("false");
    expect(svcCell.getAttribute("data-missing-service")).toBe("true");
    expect(
      within(incCell).getByTestId("uncategorized-income-chip-inv-C::0").textContent,
    ).toContain("Pool");
  });
});


describe("UncategorizedItemsReport · missing-filter toggle URL persistence", () => {
  it("clicking 'Missing Both' persists ?missing=both in the URL", async () => {
    const { locations } = _mount();
    await screen.findByTestId("uncategorized-missing-toggle");
    const bothBtn = screen.getByTestId("uncategorized-missing-both");
    fireEvent.click(bothBtn);
    await waitFor(() => {
      const url = locations[locations.length - 1].search;
      expect(url).toContain("missing=both");
    });
  });

  it("clicking 'Missing Income' persists ?missing=income", async () => {
    const { locations } = _mount();
    await screen.findByTestId("uncategorized-missing-toggle");
    fireEvent.click(screen.getByTestId("uncategorized-missing-income"));
    await waitFor(() => {
      const url = locations[locations.length - 1].search;
      expect(url).toContain("missing=income");
    });
  });

  it("landing on ?missing=service preselects that chip", async () => {
    _mount("/reports/uncategorized-items?missing=service");
    const chip = await screen.findByTestId("uncategorized-missing-service");
    expect(chip.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("uncategorized-missing-either").getAttribute("aria-pressed"))
      .toBe("false");
  });
});


describe("UncategorizedItemsReport · row lifecycle — assign one taxonomy", () => {
  it("assigning Income on a missing-both row clears Income highlight but keeps the row visible with Service still highlighted", async () => {
    _apiPost.mockImplementation((path, body) => {
      if (path.includes("/assign")) {
        return Promise.resolve({
          ok: true, changed: true,
          invoice_id: "inv-A", line_item_index: 0,
          income_category: { id: "inc-pool", name: "Pool", color: "#123456" },
          service_category: null,
        });
      }
      return Promise.resolve({});
    });
    _mount();
    // Wait for hydration.
    await screen.findByTestId("uncategorized-row-inv-A::0");
    const picker = screen.getByTestId("uncategorized-income-picker-inv-A::0");
    // Open the picker + pick "Pool" from the list.
    fireEvent.click(within(picker).getByTestId("uncategorized-income-picker-inv-A::0-button"));
    const opt = await within(picker).findByTestId("uncategorized-income-picker-inv-A::0-option-inc-pool");
    fireEvent.click(opt);

    await waitFor(() => {
      // Income cell now shows a chip (not the picker) → highlight cleared.
      const incCell = screen.getByTestId("uncategorized-income-cell-inv-A::0");
      expect(incCell.getAttribute("data-missing-income")).toBe("false");
      // Row is STILL rendered — Service is still missing so row can't leave yet.
      expect(screen.getByTestId("uncategorized-row-inv-A::0")).toBeTruthy();
      // Service cell still highlighted.
      const svcCell = screen.getByTestId("uncategorized-service-cell-inv-A::0");
      expect(svcCell.getAttribute("data-missing-service")).toBe("true");
    });
  });
});


describe("UncategorizedItemsReport · row dismiss (Mark done)", () => {
  it("clicking the dismiss X removes the row from the visible list", async () => {
    _mount();
    await screen.findByTestId("uncategorized-row-inv-B::0");
    fireEvent.click(screen.getByTestId("uncategorized-dismiss-inv-B::0"));
    await waitFor(() =>
      expect(screen.queryByTestId("uncategorized-row-inv-B::0")).toBeNull());
    // Others still there.
    expect(screen.getByTestId("uncategorized-row-inv-A::0")).toBeTruthy();
    expect(screen.getByTestId("uncategorized-row-inv-C::0")).toBeTruthy();
  });
});


describe("UncategorizedItemsReport · empty state", () => {
  it("total=0 renders the success card and no table", async () => {
    _apiGet.mockImplementation((path) => {
      if (path.startsWith("/reports/uncategorized-items")) {
        return Promise.resolve({ items: [], total: 0,
                                 range: "all", missing: "either" });
      }
      return _defaultApiImpl(path);
    });
    _mount();
    await screen.findByTestId("uncategorized-empty-state");
    expect(screen.queryByTestId("uncategorized-table")).toBeNull();
  });
});
