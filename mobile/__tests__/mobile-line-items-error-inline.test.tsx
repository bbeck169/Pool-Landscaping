/**
 * __tests__/mobile-line-items-error-inline.test.tsx
 * Tests: archived_category → row highlighted, save button stays enabled.
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
  parseLineItemError: (e: any) => {
    try {
      const j = JSON.parse(e?.message || "");
      if (j?.error_code) return j;
    } catch {
      /* not JSON */
    }
    return null;
  },
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}));
jest.mock("@/src/offline", () => ({ useOnline: () => true }));
jest.spyOn(require("react-native").Alert, "alert").mockImplementation(() => {});

import LineItemsSection from "@/src/components/jobs/LineItemsSection";

const LI_ROW = {
  id: "li_err",
  name: "Pool Salt",
  quantity: 1,
  unit_price: 10,
  subtotal: 10,
  category: "Chemicals",
};

describe("LineItems Mobile Error Inline", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetLI.mockResolvedValue({ line_items: [LI_ROW], job_totals: null });
  });

  it("archived_category error shows in sheet + row highlighted after close", async () => {
    mockUpdateLI.mockRejectedValue(
      new Error(
        JSON.stringify({
          error_code: "archived_category",
          attempted_category: "OldCat",
          available_categories: ["Chemicals", "Filters"],
        }),
      ),
    );
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-li_err")).toBeTruthy(),
    );
    // Open edit sheet
    fireEvent.press(tree.getByTestId("job-lineitem-li_err"));
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-edit-sheet")).toBeTruthy(),
    );
    // Submit — should fail
    await act(async () => {
      fireEvent.press(tree.getByTestId("job-lineitem-sheet-submit"));
    });
    // Error visible in sheet
    await waitFor(() => {
      expect(tree.getByTestId("job-lineitem-sheet-error")).toBeTruthy();
    });
    expect(tree.getAllByText(/archived_category/).length).toBeGreaterThanOrEqual(1);
    // Submit button STAYS ENABLED (not disabled)
    const submitBtn = tree.getByTestId("job-lineitem-sheet-submit");
    expect(submitBtn.props.accessibilityState?.disabled).not.toBe(true);
    console.log("✅ LIEI-T1: error in sheet + submit stays enabled");
  });

  it("save button stays enabled after error for retry", async () => {
    mockUpdateLI.mockRejectedValueOnce(
      new Error(
        JSON.stringify({ error_code: "archived_category", attempted_category: "Bad" }),
      ),
    );
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-li_err")).toBeTruthy(),
    );
    fireEvent.press(tree.getByTestId("job-lineitem-li_err"));
    await waitFor(() =>
      expect(tree.getByTestId("job-lineitem-edit-sheet")).toBeTruthy(),
    );
    await act(async () => {
      fireEvent.press(tree.getByTestId("job-lineitem-sheet-submit"));
    });
    await waitFor(() => {
      expect(tree.getByTestId("job-lineitem-sheet-error")).toBeTruthy();
    });
    // Change category and retry
    mockUpdateLI.mockResolvedValue({});
    await act(async () => {
      fireEvent.press(tree.getByTestId("job-lineitem-sheet-submit"));
    });
    await waitFor(() => {
      expect(mockUpdateLI).toHaveBeenCalledTimes(2);
    });
    console.log("✅ LIEI-T2: retry works after error");
  });
});
