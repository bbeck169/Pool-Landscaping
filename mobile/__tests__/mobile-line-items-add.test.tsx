/**
 * __tests__/mobile-line-items-add.test.tsx
 * Tests: sheet opens, pricebook picker populates, submit fires POST with F7 fields.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockAddLI = jest.fn();
const mockGetPB = jest.fn();
const mockGetCats = jest.fn();

jest.mock("@/src/api/lineItems", () => ({
  getLineItems: jest.fn(async () => ({ line_items: [], job_totals: null })),
  addLineItem: (...a: any[]) => mockAddLI(...a),
  updateLineItem: jest.fn(),
  deleteLineItem: jest.fn(),
  getPricebookItems: (...a: any[]) => mockGetPB(...a),
  getCategories: (...a: any[]) => mockGetCats(...a),
  parseLineItemError: jest.fn(() => null),
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}));
jest.mock("@/src/offline", () => ({ useOnline: () => true }));
jest.spyOn(require("react-native").Alert, "alert").mockImplementation(() => {});

import LineItemsSection from "@/src/components/jobs/LineItemsSection";

describe("LineItems Mobile Add", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockAddLI.mockResolvedValue({});
    mockGetPB.mockResolvedValue({
      items: [
        { id: "pb_1", name: "Chlorine 10lb", unit_price: 24.99, category: "Chemicals" },
        { id: "pb_2", name: "Filter Cartridge", unit_price: 45, category: "Filters" },
      ],
    });
    mockGetCats.mockResolvedValue([
      { id: "cat_1", name: "Chemicals" },
      { id: "cat_2", name: "Filters" },
    ]);
  });

  it("add button opens sheet + pricebook populates", async () => {
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-add-button")).toBeTruthy(),
    );
    fireEvent.press(tree.getByTestId("job-lineitem-add-button"));
    await waitFor(() => {
      expect(tree.getByTestId("job-lineitem-add-sheet")).toBeTruthy();
      expect(tree.getByTestId("job-lineitem-pb-item-pb_1")).toBeTruthy();
      expect(tree.getByTestId("job-lineitem-pb-item-pb_2")).toBeTruthy();
    });
    console.log("✅ LIA-T1: sheet opens + pricebook populated");
  });

  it("selecting pb item fills form fields", async () => {
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-add-button")).toBeTruthy(),
    );
    fireEvent.press(tree.getByTestId("job-lineitem-add-button"));
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-pb-item-pb_1")).toBeTruthy(),
    );
    fireEvent.press(tree.getByTestId("job-lineitem-pb-item-pb_1"));
    const descInput = tree.getByTestId("job-lineitem-desc");
    expect(descInput.props.value).toBe("Chlorine 10lb");
    const priceInput = tree.getByTestId("job-lineitem-unit-price");
    expect(priceInput.props.value).toBe("24.99");
    console.log("✅ LIA-T2: pb item selection fills form");
  });

  it("submit fires POST with correct body incl. category + writeback", async () => {
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-add-button")).toBeTruthy(),
    );
    fireEvent.press(tree.getByTestId("job-lineitem-add-button"));
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-pb-item-pb_1")).toBeTruthy(),
    );
    // Pick item
    fireEvent.press(tree.getByTestId("job-lineitem-pb-item-pb_1"));
    // Change qty
    fireEvent.changeText(tree.getByTestId("job-lineitem-qty"), "2");
    // Toggle writeback
    const wbToggle = tree.getByTestId("job-lineitem-writeback-toggle");
    fireEvent(wbToggle, "valueChange", true);
    // Submit
    await act(async () => {
      fireEvent.press(tree.getByTestId("job-lineitem-sheet-submit"));
    });
    await waitFor(() => {
      expect(mockAddLI).toHaveBeenCalledWith(
        "job-1",
        expect.objectContaining({
          pricebook_item_id: "pb_1",
          description: "Chlorine 10lb",
          quantity: 2,
          category: "Chemicals",
          pricebook_writeback: true,
        }),
      );
    });
    console.log("✅ LIA-T3: POST fires with F7 fields (category, writeback)");
  });

  it("custom price hint appears when price diverges from pricebook", async () => {
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-add-button")).toBeTruthy(),
    );
    fireEvent.press(tree.getByTestId("job-lineitem-add-button"));
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-pb-item-pb_1")).toBeTruthy(),
    );
    fireEvent.press(tree.getByTestId("job-lineitem-pb-item-pb_1"));
    // Change price to a different value
    fireEvent.changeText(tree.getByTestId("job-lineitem-unit-price"), "30");
    await waitFor(() => {
      expect(tree.getByTestId("job-lineitem-custom-price-hint")).toBeTruthy();
    });
    console.log("✅ LIA-T4: custom price hint on divergence");
  });
});
