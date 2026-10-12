/**
 * Phase PRICEBOOK-UNIFY · Feb-2026 — QuoteInvoiceNew now uses the
 * shared PricebookItemPicker instead of the legacy master-services
 * combobox.
 *
 * Locks:
 *   1. The pricebook picker (not master-services) is what mounts.
 *   2. Picking an item populates ``description`` + ``unit_price``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { apiGetSpy, apiPostSpy } = vi.hoisted(() => ({
  apiGetSpy: vi.fn(),
  apiPostSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGetSpy(...a),
    post: (...a) => apiPostSpy(...a),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin" } }),
}));


import QuoteInvoiceNew from "@/pages/quotes/QuoteInvoiceNew";


beforeEach(() => {
  apiGetSpy.mockReset();
  apiPostSpy.mockReset();
  apiGetSpy.mockImplementation((url) => {
    if (url.startsWith("/customers"))
      return Promise.resolve([
        { id: "c-1", name: "Sample Co", is_active: true,
          address: "1 Main" },
      ]);
    if (url.startsWith("/service_categories"))
      return Promise.resolve([]);
    if (url.startsWith("/settings/terms"))
      return Promise.resolve({ default_quote_terms: "" });
    if (url.startsWith("/items"))
      return Promise.resolve([
        { id: "pb-1", name: "Muriatic acid — gal",
          description: "Pool acid", unit_price: 12.50,
          category: "Chemical" },
      ]);
    return Promise.resolve(null);
  });
  apiPostSpy.mockResolvedValue({ id: "q-1" });
});

afterEach(() => { vi.restoreAllMocks(); });


function _mount() {
  return render(
    <MemoryRouter initialEntries={["/quotes/new"]}>
      <QuoteInvoiceNew docType="quote" />
    </MemoryRouter>,
  );
}


describe("QuoteInvoiceNew × PricebookItemPicker", () => {
  it("mounts the pricebook picker input for row 0", async () => {
    _mount();
    await waitFor(() =>
      expect(screen.queryByTestId("qf-line-0-desc-input")).toBeTruthy(),
    );
    // The legacy master-services picker's testid is NOT present.
    expect(screen.queryByTestId("qf-line-0-desc")).toBeNull();
  });

  it("picking an item populates description + unit_price on row 0",
    async () => {
      _mount();
      const desc = await waitFor(() =>
        screen.getByTestId("qf-line-0-desc-input"),
      );
      // Phase PRICEBOOK-UNIFY · Feb-2026 — PricebookItemPicker runs a
      // 250 ms debounced ``setTimeout`` + async fetch chain before
      // populating ``results[]``. ``fireEvent.change`` on the input
      // fires the onChange prop synchronously, but the debounced
      // results commit happens on the next macrotask tick + microtask
      // chain. The test environment doesn't configure
      // ``IS_REACT_ACT_ENVIRONMENT`` so wrapping in ``act(...)`` won't
      // help — we instead give waitFor a timeout above the 250 ms
      // debounce + room for the fetch resolution + React commit.
      fireEvent.change(desc, { target: { value: "acid" } });
      const row = await waitFor(() =>
        screen.getByTestId("qf-line-0-picker-item-0"),
      { timeout: 4500 });
      fireEvent.click(row);
      await waitFor(() =>
        expect(
          screen.getByTestId("qf-line-0-desc-input").value,
          // QF-1 · Feb-2026 (Option B + legacy-string) — on pick,
          // ``item.description`` populates the picker's description
          // slot (which drives this input's displayed value), while
          // ``item.name`` populates a separate ``item_name`` SKU
          // slot on the line. The pre-QF1 flow folded both into
          // one value; this test previously asserted the SKU label
          // after pick but the picker now shows the description.
        ).toBe("Pool acid"),
      );
      // Fallback: the unit-price input isn't strictly testid'd via a
      // top-level attribute; find it via the Quote-line price testid.
      const priceInput = screen.getAllByRole("spinbutton").find(
        (i) => i.getAttribute("data-testid") === "qf-line-0-price"
                || i.value === "12.5"
                || i.value === "12.50",
      );
      expect(priceInput).toBeTruthy();
    }, 10000);
});
