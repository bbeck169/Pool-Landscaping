/**
 * Phase 41.5c · Feb-2026 — Mobile Chemical Products admin render test.
 *
 * Boots ``app/admin/chemicals.tsx`` with every native dep mocked.
 * Covers:
 *   1. Admin sees the list pre-populated from GET /chemical-products.
 *   2. Search input + button re-hits the endpoint with q= param.
 *   3. Show-inactive toggle drops the ``active=true`` query param.
 *   4. Tapping a row opens the edit modal with fields pre-filled.
 *   5. Editing + Save fires PATCH /chemical-products/{slug} with the
 *      full payload shape (name/sku/unit/unit_cost_cents/active).
 *   6. New-product flow fires POST /chemical-products.
 *   7. Deactivate row fires DELETE /chemical-products/{slug}.
 *   8. Technician + customer hit the role gate — no fetch runs.
 */
import React from "react";
import { render, waitFor, act, fireEvent } from "@testing-library/react-native";

jest.setTimeout(15000);

// ── Mocks ────────────────────────────────────────────────────────────
const mockApiGet = jest.fn();
const mockApiPost = jest.fn();
const mockApiPatch = jest.fn();
const mockApiDel = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get:   (...a: any[]) => mockApiGet(...a),
    post:  (...a: any[]) => mockApiPost(...a),
    patch: (...a: any[]) => mockApiPatch(...a),
    del:   (...a: any[]) => mockApiDel(...a),
  },
}));

let mockUserRole: any = { id: "u_admin", role: "admin", email: "a@ex.com" };
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: mockUserRole }),
}));

jest.mock("@/src/components/widgets", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactMock = require("react");
  const RN = jest.requireActual("react-native");
  return {
    Header: ({ title }: { title: string }) =>
      ReactMock.createElement(RN.Text, { testID: "test-header" }, title),
  };
});

// eslint-disable-next-line import/first
import { Alert as RNAlert } from "react-native";
const mockAlert = jest.spyOn(RNAlert, "alert").mockImplementation(() => {});

// eslint-disable-next-line import/first
import ChemicalsScreen from "@/app/admin/chemicals";

const PRODUCTS = [
  { id: "p1", slug: "chlorine-3in", name: "Chlorine tablet 3-inch",
    sku: "CT3", unit: "lb", unit_cost_cents: 350, active: true },
  { id: "p2", slug: "muriatic-acid", name: "Muriatic acid",
    sku: "MA1", unit: "gal", unit_cost_cents: 899, active: true },
];

beforeEach(() => {
  mockApiGet.mockReset();
  mockApiPost.mockReset();
  mockApiPatch.mockReset();
  mockApiDel.mockReset();
  mockAlert.mockReset();
  mockUserRole = { id: "u_admin", role: "admin", email: "a@ex.com" };
});

describe("Phase 41.5c · mobile Chemical Products", () => {
  it("admin loads the list with active=true by default", async () => {
    mockApiGet.mockResolvedValueOnce({ count: 2, products: PRODUCTS });
    const { getByTestId } = render(<ChemicalsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    expect(mockApiGet.mock.calls[0][0]).toBe("/chemical-products?active=true");
    await waitFor(() =>
      expect(getByTestId("chem-product-row-chlorine-3in")).toBeTruthy());
    expect(getByTestId("chem-product-row-muriatic-acid")).toBeTruthy();
    expect(getByTestId("chem-product-status-chlorine-3in")).toBeTruthy();
  });

  it("search button re-hits endpoint with q= parameter", async () => {
    mockApiGet.mockResolvedValue({ count: 0, products: [] });
    const { getByTestId } = render(<ChemicalsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));

    await act(async () => {
      fireEvent.changeText(getByTestId("chem-product-search"), "chlorine");
    });
    await act(async () => {
      fireEvent.press(getByTestId("chem-product-search-btn"));
    });
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
    expect(mockApiGet.mock.calls[1][0]).toContain("q=chlorine");
    expect(mockApiGet.mock.calls[1][0]).toContain("active=true");
  });

  it("show-inactive toggle drops the active=true filter", async () => {
    mockApiGet.mockResolvedValue({ count: 0, products: [] });
    const { getByTestId } = render(<ChemicalsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));

    await act(async () => {
      fireEvent(getByTestId("chem-product-show-inactive"), "valueChange", true);
    });
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
    // No active=true when inactive-toggle is on.
    expect(mockApiGet.mock.calls[1][0]).toBe("/chemical-products?");
  });

  it("tapping a row opens the edit modal pre-populated", async () => {
    mockApiGet.mockResolvedValueOnce({ count: 2, products: PRODUCTS });
    const { getByTestId } = render(<ChemicalsScreen />);
    await waitFor(() =>
      expect(getByTestId("chem-product-row-chlorine-3in")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("chem-product-row-chlorine-3in"));
    });
    await waitFor(() => expect(getByTestId("chem-product-modal")).toBeTruthy());
    expect(getByTestId("chem-product-name").props.value).toBe("Chlorine tablet 3-inch");
    expect(getByTestId("chem-product-sku").props.value).toBe("CT3");
    expect(getByTestId("chem-product-unit").props.value).toBe("lb");
    expect(getByTestId("chem-product-cost").props.value).toBe("350");
  });

  it("edit + save fires PATCH /chemical-products/{slug} with the exact payload", async () => {
    mockApiGet.mockResolvedValueOnce({ count: 2, products: PRODUCTS });
    mockApiPatch.mockResolvedValueOnce({ ...PRODUCTS[0], unit_cost_cents: 425 });
    mockApiGet.mockResolvedValueOnce({ count: 2, products: PRODUCTS });
    const { getByTestId } = render(<ChemicalsScreen />);
    await waitFor(() =>
      expect(getByTestId("chem-product-row-chlorine-3in")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("chem-product-row-chlorine-3in"));
    });
    await waitFor(() => getByTestId("chem-product-modal"));

    await act(async () => {
      fireEvent.changeText(getByTestId("chem-product-cost"), "425");
    });
    await act(async () => {
      fireEvent.press(getByTestId("chem-product-save"));
    });
    await waitFor(() => expect(mockApiPatch).toHaveBeenCalledTimes(1));
    expect(mockApiPatch.mock.calls[0][0]).toBe("/chemical-products/chlorine-3in");
    const body = mockApiPatch.mock.calls[0][1];
    expect(body).toEqual({
      name: "Chlorine tablet 3-inch",
      sku: "CT3",
      unit: "lb",
      unit_cost_cents: 425,
      active: true,
    });
    // Toast + reload after save.
    await waitFor(() => expect(mockAlert).toHaveBeenCalledTimes(1));
    expect(mockAlert.mock.calls[0][0]).toBe("Saved");
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
  });

  it("new-product flow fires POST /chemical-products", async () => {
    mockApiGet.mockResolvedValueOnce({ count: 0, products: [] });
    mockApiPost.mockResolvedValueOnce({
      id: "p_new", slug: "algaecide", name: "Algaecide 60",
      sku: "", unit: "gal", unit_cost_cents: 1200, active: true,
    });
    mockApiGet.mockResolvedValueOnce({ count: 1, products: [] });
    const { getByTestId } = render(<ChemicalsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));

    await act(async () => {
      fireEvent.press(getByTestId("chem-product-new"));
    });
    await waitFor(() => getByTestId("chem-product-modal"));

    await act(async () => {
      fireEvent.changeText(getByTestId("chem-product-name"), "Algaecide 60");
    });
    await act(async () => {
      fireEvent.changeText(getByTestId("chem-product-unit"), "gal");
    });
    await act(async () => {
      fireEvent.changeText(getByTestId("chem-product-cost"), "1200");
    });
    await act(async () => {
      fireEvent.press(getByTestId("chem-product-save"));
    });
    await waitFor(() => expect(mockApiPost).toHaveBeenCalledTimes(1));
    expect(mockApiPost.mock.calls[0][0]).toBe("/chemical-products");
    expect(mockApiPost.mock.calls[0][1]).toEqual({
      name: "Algaecide 60",
      sku: "",
      unit: "gal",
      unit_cost_cents: 1200,
      active: true,
    });
  });

  it("save without name shows a validation alert and no HTTP fires", async () => {
    mockApiGet.mockResolvedValueOnce({ count: 0, products: [] });
    const { getByTestId } = render(<ChemicalsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));

    await act(async () => {
      fireEvent.press(getByTestId("chem-product-new"));
    });
    await waitFor(() => getByTestId("chem-product-modal"));
    await act(async () => {
      fireEvent.press(getByTestId("chem-product-save"));
    });
    expect(mockApiPost).not.toHaveBeenCalled();
    expect(mockApiPatch).not.toHaveBeenCalled();
    expect(mockAlert).toHaveBeenCalledWith("Missing field", expect.any(String));
  });

  it("deactivate row fires DELETE /chemical-products/{slug}", async () => {
    mockApiGet.mockResolvedValueOnce({ count: 2, products: PRODUCTS });
    mockApiDel.mockResolvedValueOnce(undefined);
    mockApiGet.mockResolvedValueOnce({ count: 1, products: [PRODUCTS[1]] });

    // Auto-confirm the RN Alert.alert() prompt by invoking the
    // "Deactivate" destructive button handler.
    mockAlert.mockImplementation((_title, _msg, buttons) => {
      const b = (buttons || []).find((x: any) => x.style === "destructive");
      if (b?.onPress) b.onPress();
    });

    const { getByTestId } = render(<ChemicalsScreen />);
    await waitFor(() =>
      expect(getByTestId("chem-product-row-muriatic-acid")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("chem-product-deactivate-muriatic-acid"));
    });
    await waitFor(() => expect(mockApiDel).toHaveBeenCalledTimes(1));
    expect(mockApiDel.mock.calls[0][0]).toBe("/chemical-products/muriatic-acid");
    // List reloads.
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
  });

  it("technician sees the role gate and no fetch runs", () => {
    mockUserRole = { id: "u_t", role: "technician", email: "t@ex.com" };
    const { getByTestId, queryByTestId } = render(<ChemicalsScreen />);
    expect(getByTestId("chemicals-admin-role-gate")).toBeTruthy();
    expect(queryByTestId("chemicals-admin-screen")).toBeNull();
    expect(mockApiGet).not.toHaveBeenCalled();
  });

  it("customer is blocked by the role gate too", () => {
    mockUserRole = { id: "u_c", role: "customer", email: "c@ex.com" };
    const { getByTestId } = render(<ChemicalsScreen />);
    expect(getByTestId("chemicals-admin-role-gate")).toBeTruthy();
    expect(mockApiGet).not.toHaveBeenCalled();
  });
});
