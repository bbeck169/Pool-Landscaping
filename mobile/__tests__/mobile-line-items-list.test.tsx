/**
 * __tests__/mobile-line-items-list.test.tsx
 * Tests: fetches and renders rows, empty state, tech sees read-only pricing.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

const mockGetLI = jest.fn();

jest.mock("@/src/api/lineItems", () => ({
  getLineItems: (...a: any[]) => mockGetLI(...a),
  addLineItem: jest.fn(),
  updateLineItem: jest.fn(),
  deleteLineItem: jest.fn(),
  getPricebookItems: jest.fn(async () => ({ items: [] })),
  getCategories: jest.fn(async () => []),
  parseLineItemError: jest.fn(() => null),
}));

let mockUser: any = { role: "admin" };
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: mockUser }),
}));
jest.mock("@/src/offline", () => ({ useOnline: () => true }));

import LineItemsSection from "@/src/components/jobs/LineItemsSection";

describe("LineItems Mobile List", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUser = { role: "admin" };
  });

  it("renders line item rows with name, qty, category", async () => {
    mockGetLI.mockResolvedValue({
      line_items: [
        {
          id: "li_1",
          name: "Chlorine Tablets",
          quantity: 3,
          unit_price: 12.5,
          subtotal: 37.5,
          category: "Chemicals",
        },
      ],
      job_totals: { subtotal: 37.5, total: 37.5 },
    });
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() => {
      expect(tree.getByTestId("job-lineitem-li_1")).toBeTruthy();
    });
    expect(tree.getByText("Chlorine Tablets")).toBeTruthy();
    expect(tree.getByText("Qty 3")).toBeTruthy();
    expect(tree.getByText("Chemicals")).toBeTruthy();
    console.log("✅ LIL-T1: rows render with name, qty, category");
  });

  it("shows empty state when no line items", async () => {
    mockGetLI.mockResolvedValue({ line_items: [], job_totals: null });
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() => {
      expect(tree.getByTestId("job-lineitem-empty")).toBeTruthy();
    });
    expect(tree.getByText("No line items yet")).toBeTruthy();
    console.log("✅ LIL-T2: empty state renders");
  });

  it("admin sees subtotal + total", async () => {
    mockGetLI.mockResolvedValue({
      line_items: [
        { id: "li_2", name: "Filter", quantity: 1, unit_price: 25, subtotal: 25 },
      ],
      job_totals: { subtotal: 25, tax: 2, total: 27 },
    });
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() => {
      expect(tree.getByTestId("job-lineitem-totals")).toBeTruthy();
    });
    expect(tree.getByTestId("job-lineitem-subtotal")).toBeTruthy();
    expect(tree.getByTestId("job-lineitem-total")).toBeTruthy();
    console.log("✅ LIL-T3: admin sees totals");
  });

  it("tech sees read-only pricing (no subtotal column)", async () => {
    mockUser = { role: "technician" };
    mockGetLI.mockResolvedValue({
      line_items: [
        { id: "li_3", name: "Pump O-Ring", quantity: 2, unit_price: 5, subtotal: 10, notes: "replaced" },
      ],
      job_totals: { subtotal: 10, total: 10 },
    });
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() => {
      expect(tree.getByTestId("job-lineitem-li_3")).toBeTruthy();
    });
    expect(tree.queryByTestId("job-lineitem-totals")).toBeNull();
    expect(tree.queryByTestId("job-lineitem-li_3-total")).toBeNull();
    console.log("✅ LIL-T4: tech sees read-only (no totals/price columns)");
  });

  it("custom price hint shown when flag is set", async () => {
    mockGetLI.mockResolvedValue({
      line_items: [
        {
          id: "li_cp",
          name: "Custom Widget",
          quantity: 1,
          unit_price: 99,
          subtotal: 99,
          custom_price_override_flag: true,
        },
      ],
      job_totals: null,
    });
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() => {
      expect(tree.getByTestId("job-lineitem-li_cp-custom-hint")).toBeTruthy();
    });
    expect(tree.getByText("Custom price")).toBeTruthy();
    console.log("✅ LIL-T5: custom price hint shown");
  });
});
