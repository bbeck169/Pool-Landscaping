/**
 * Phase PRICEBOOK-UNIFY · Feb-2026 — Estimator + PricebookItemPicker
 * integration + $0-save-bug regression.
 *
 * Locks:
 *   1. Picking an item from the pricebook populates ``description``
 *      + ``unit_price`` on the CORRECT row (index isolation).
 *   2. The save payload maps UI ``unit_price`` → payload
 *      ``unit_cost`` — the root cause of the $0-save bug.
 *   3. The user can hand-edit description + price AFTER a pick.
 *   4. Round-trip regression: saving a non-zero ``unit_price`` and
 *      reloading (mocked ``GET /estimates/<id>``) retains the
 *      value.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";


const { apiGetSpy, apiPostSpy, apiPutSpy } = vi.hoisted(() => ({
  apiGetSpy: vi.fn(),
  apiPostSpy: vi.fn(),
  apiPutSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGetSpy(...a),
    post: (...a) => apiPostSpy(...a),
    put: (...a) => apiPutSpy(...a),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin" } }),
}));

// The Estimator page pulls a heavy media uploader we don't need
// to exercise here.
vi.mock("@/components/media/MediaUploader", () => ({
  __esModule: true,
  default: () => null,
}));


import { EstimatorEditor as Estimator } from "@/pages/estimator/Estimator";


function _mount({ path = "/estimator/new" } = {}) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/estimator/new" element={<Estimator />} />
        <Route path="/estimator/:id" element={<Estimator />} />
      </Routes>
    </MemoryRouter>,
  );
}


beforeEach(() => {
  apiGetSpy.mockReset();
  apiPostSpy.mockReset();
  apiPutSpy.mockReset();
  apiGetSpy.mockImplementation((url) => {
    if (url.startsWith("/customers")) {
      return Promise.resolve([
        { id: "c-1", name: "Sample Customer",
          is_active: true, address: "123 Main" },
      ]);
    }
    if (url.startsWith("/settings/terms")) {
      return Promise.resolve({ default_quote_terms: "Std terms." });
    }
    if (url.startsWith("/items")) {
      return Promise.resolve([
        { id: "it-A", name: "Muriatic acid — gal",
          description: "Pool acid",
          unit_price: 12.5, category: "Chemical" },
      ]);
    }
    return Promise.resolve(null);
  });
  apiPostSpy.mockResolvedValue({ id: "est-new" });
  apiPutSpy.mockResolvedValue({ id: "est-new" });
});

afterEach(() => { vi.restoreAllMocks(); });


describe("Estimator × PricebookItemPicker · pick populates the row", () => {
  it("picking an item auto-fills description + unit_price on row 0",
    async () => {
      _mount();
      // Bootstrap render.
      await waitFor(() => screen.getByTestId("est-editor"));
      const desc = screen.getByTestId("est-line-0-description");
      fireEvent.change(desc, { target: { value: "acid" } });
      // Debounce → GET /items → dropdown → click first result.
      const row = await waitFor(() =>
        screen.getByTestId("est-line-0-picker-item-0"),
      { timeout: 1500 });
      fireEvent.click(row);
      // Description populated with the item's ``name``.
      await waitFor(() => {
        const d = screen.getByTestId("est-line-0-description");
        expect(d.value).toBe("Muriatic acid — gal");
      });
      // Unit-price populated with the item's ``unit_price``.
      const up = screen.getByTestId("est-line-0-unit-price");
      expect(Number(up.value)).toBe(12.5);
    });

  it("the user can hand-edit description + price AFTER picking",
    async () => {
      _mount();
      await waitFor(() => screen.getByTestId("est-editor"));
      const desc = screen.getByTestId("est-line-0-description");
      fireEvent.change(desc, { target: { value: "acid" } });
      const row = await waitFor(() =>
        screen.getByTestId("est-line-0-picker-item-0"),
      { timeout: 1500 });
      fireEvent.click(row);
      // Now override the auto-filled fields.
      fireEvent.change(screen.getByTestId("est-line-0-description"),
        { target: { value: "Custom acid blend" } });
      fireEvent.change(screen.getByTestId("est-line-0-unit-price"),
        { target: { value: "17.25" } });
      expect(
        screen.getByTestId("est-line-0-description").value,
      ).toBe("Custom acid blend");
      expect(
        Number(screen.getByTestId("est-line-0-unit-price").value),
      ).toBe(17.25);
    });
});


describe("Estimator · $0-save-bug fix (unit_price → unit_cost)", () => {
  it("POST /estimates payload sends unit_cost with the UI's unit_price value",
    async () => {
      _mount();
      await waitFor(() => screen.getByTestId("est-editor"));
      // Directly set unit_price + qty (no pick, no debounce).
      fireEvent.change(screen.getByTestId("est-line-0-description"),
        { target: { value: "Manual line" } });
      fireEvent.change(screen.getByTestId("est-line-0-quantity"),
        { target: { value: "3" } });
      fireEvent.change(screen.getByTestId("est-line-0-unit-price"),
        { target: { value: "42.75" } });
      // Click Save.
      fireEvent.click(screen.getByRole("button", { name: /^save estimate$/i }));
      await waitFor(() => expect(apiPostSpy).toHaveBeenCalled());
      const [url, body] = apiPostSpy.mock.calls[0];
      expect(url).toBe("/estimates");
      const li = body.line_items[0];
      // The critical assertion: unit_cost lands with the non-zero
      // dollars value the operator typed.
      expect(li.unit_cost).toBe(42.75);
      // For backwards-compat we also still write unit_price on the
      // wire so any consumer still reading it works.
      expect(li.unit_price).toBe(42.75);
      // Quantity + description carry as usual.
      expect(li.quantity).toBe("3");
      expect(li.description).toBe("Manual line");
    });

  it("regression · load-then-save round-trip preserves non-zero unit_price",
    async () => {
      // Prime the GET to return a saved estimate whose
      // ``unit_cost`` carries a real dollars value (the shape the
      // backend actually persists post-fix).
      apiGetSpy.mockImplementation((url) => {
        if (url === "/estimates/est-1") {
          return Promise.resolve({
            id: "est-1", title: "Loaded", customer_id: "c-1",
            line_items: [
              { description: "Persisted item", quantity: 2,
                unit_cost: 33.10 },
            ],
            tax_rate: 0, notes: "", terms: "",
          });
        }
        if (url.startsWith("/customers")) {
          return Promise.resolve([
            { id: "c-1", name: "Sample Customer",
              is_active: true, address: "123 Main" },
          ]);
        }
        if (url.startsWith("/settings/terms")) {
          return Promise.resolve({ default_quote_terms: "" });
        }
        return Promise.resolve(null);
      });
      _mount({ path: "/estimator/est-1" });
      await waitFor(() =>
        expect(
          screen.getByTestId("est-line-0-description").value,
        ).toBe("Persisted item"),
      );
      // UI hydrates ``unit_price`` from the DB's ``unit_cost``.
      expect(
        Number(screen.getByTestId("est-line-0-unit-price").value),
      ).toBe(33.10);
      // Re-save without changing anything.
      fireEvent.click(screen.getByRole("button", { name: /^save estimate$/i }));
      await waitFor(() => expect(apiPutSpy).toHaveBeenCalled());
      const [url, body] = apiPutSpy.mock.calls[0];
      expect(url).toBe("/estimates/est-1");
      // Non-zero unit_cost lands on the wire.
      expect(body.line_items[0].unit_cost).toBe(33.10);
    });
});
