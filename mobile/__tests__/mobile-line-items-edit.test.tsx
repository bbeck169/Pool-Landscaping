/**
 * __tests__/mobile-line-items-edit.test.tsx
 * Tests: row tap opens sheet prefilled, PATCH fires with changed fields.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockUpdateLI = jest.fn();
const mockGetLI = jest.fn();

jest.mock("@/src/api/lineItems", () => ({
  getLineItems: (...a: any[]) => mockGetLI(...a),
  addLineItem: jest.fn(),
  updateLineItem: (...a: any[]) => mockUpdateLI(...a),
  deleteLineItem: jest.fn(),
  getPricebookItems: jest.fn(async () => ({ items: [] })),
  getCategories: jest.fn(async () => []),
  parseLineItemError: jest.fn(() => null),
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}));
jest.mock("@/src/offline", () => ({ useOnline: () => true }));
jest.spyOn(require("react-native").Alert, "alert").mockImplementation(() => {});

import LineItemsSection from "@/src/components/jobs/LineItemsSection";

const LI_ROW = {
  id: "li_edit",
  name: "Chlorine Tabs",
  description: "Chlorine Tabs",
  quantity: 2,
  unit_price: 15,
  subtotal: 30,
  category: "Chemicals",
  pricebook_writeback_flag: false,
};

describe("LineItems Mobile Edit", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetLI.mockResolvedValue({ line_items: [LI_ROW], job_totals: null });
    mockUpdateLI.mockResolvedValue({});
  });

  it("row tap opens edit sheet with prefilled values", async () => {
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-li_edit")).toBeTruthy(),
    );
    fireEvent.press(tree.getByTestId("job-lineitem-li_edit"));
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-edit-sheet")).toBeTruthy(),
    );
    const qtyInput = tree.getByTestId("job-lineitem-qty");
    expect(qtyInput.props.value).toBe("2");
    const priceInput = tree.getByTestId("job-lineitem-unit-price");
    expect(priceInput.props.value).toBe("15");
    console.log("✅ LIE-T1: edit sheet opens with prefilled values");
  });

  it("PATCH fires with changed fields", async () => {
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-li_edit")).toBeTruthy(),
    );
    fireEvent.press(tree.getByTestId("job-lineitem-li_edit"));
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-edit-sheet")).toBeTruthy(),
    );
    fireEvent.changeText(tree.getByTestId("job-lineitem-qty"), "5");
    fireEvent.changeText(tree.getByTestId("job-lineitem-unit-price"), "20");
    await act(async () => {
      fireEvent.press(tree.getByTestId("job-lineitem-sheet-submit"));
    });
    await waitFor(() => {
      expect(mockUpdateLI).toHaveBeenCalledWith(
        "job-1",
        "li_edit",
        expect.objectContaining({
          quantity: 5,
          unit_price: 20,
        }),
      );
    });
    console.log("✅ LIE-T2: PATCH fires with changed fields");
  });

  it("description is read-only in edit mode", async () => {
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-li_edit")).toBeTruthy(),
    );
    fireEvent.press(tree.getByTestId("job-lineitem-li_edit"));
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-edit-sheet")).toBeTruthy(),
    );
    const descInput = tree.getByTestId("job-lineitem-desc");
    expect(descInput.props.editable).toBe(false);
    console.log("✅ LIE-T3: description is read-only in edit mode");
  });
});
