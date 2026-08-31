/**
 * __tests__/mobile-line-items-offline.test.tsx
 * Tests: offline banner + disabled actions when disconnected.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

let mockOnline = false;

jest.mock("@/src/api/lineItems", () => ({
  getLineItems: jest.fn(async () => ({
    line_items: [
      {
        id: "li_off",
        name: "Salt Bag",
        quantity: 1,
        unit_price: 8,
        subtotal: 8,
      },
    ],
    job_totals: null,
  })),
  addLineItem: jest.fn(),
  updateLineItem: jest.fn(),
  deleteLineItem: jest.fn(),
  getPricebookItems: jest.fn(async () => ({ items: [] })),
  getCategories: jest.fn(async () => []),
  parseLineItemError: jest.fn(() => null),
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}));

jest.mock("@/src/offline", () => ({
  useOnline: () => mockOnline,
}));

import LineItemsSection from "@/src/components/jobs/LineItemsSection";

describe("LineItems Mobile Offline", () => {
  beforeEach(() => {
    mockOnline = false;
    jest.clearAllMocks();
  });

  it("shows offline banner + disabled add button when offline", async () => {
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() => {
      expect(tree.getByTestId("job-lineitem-offline-banner")).toBeTruthy();
    });
    const addBtn = tree.getByTestId("job-lineitem-add-button");
    expect(addBtn.props.accessibilityState?.disabled).toBe(true);
    console.log("✅ LIO-T1: offline banner + disabled add button");
  });

  it("row edit + delete buttons disabled when offline", async () => {
    const tree = render(<LineItemsSection jobId="job-1" jobStatus="active" />);
    await waitFor(() => {
      expect(tree.getByTestId("job-lineitem-li_off")).toBeTruthy();
    });
    const row = tree.getByTestId("job-lineitem-li_off");
    expect(row.props.accessibilityState?.disabled).toBe(true);
    console.log("✅ LIO-T2: row edit/delete disabled when offline");
  });
});
