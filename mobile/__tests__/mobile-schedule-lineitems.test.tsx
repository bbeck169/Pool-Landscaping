/**
 * __tests__/mobile-schedule-lineitems.test.tsx
 * Tests: LineItemsSection is rendered inside ScheduleJobEditSheet.
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

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(async () => []),
    post: jest.fn(async () => ({})),
    put: jest.fn(async () => ({})),
    patch: jest.fn(async () => ({})),
    del: jest.fn(async () => ({})),
  },
}));
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}));
jest.mock("@/src/offline", () => ({ useOnline: () => true }));

import ScheduleJobEditSheet from "@/src/components/schedule/ScheduleJobEditSheet";

describe("Schedule Edit Sheet — Line Items", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetLI.mockResolvedValue({ line_items: [], job_totals: null });
  });

  it("renders line items section when editing a job", async () => {
    const job = {
      id: "job-123",
      title: "Pool Clean",
      status: "scheduled",
      service_type: "Pool Cleaning",
    };
    const tree = render(
      <ScheduleJobEditSheet
        open={true}
        job={job}
        onClose={() => {}}
        onSaved={() => {}}
        onDeleted={() => {}}
      />,
    );
    await waitFor(() => {
      expect(tree.getByTestId("job-line-items-section")).toBeTruthy();
    });
    expect(tree.getByTestId("job-line-items-title")).toBeTruthy();
    console.log("✅ SLI-T1: LineItemsSection rendered in schedule edit sheet");
  });

  it("passes correct jobId to LineItemsSection", async () => {
    const job = { id: "job-456", title: "Filter", status: "active" };
    render(
      <ScheduleJobEditSheet
        open={true}
        job={job}
        onClose={() => {}}
        onSaved={() => {}}
        onDeleted={() => {}}
      />,
    );
    await waitFor(() => {
      expect(mockGetLI).toHaveBeenCalledWith("job-456");
    });
    console.log("✅ SLI-T2: correct jobId passed to line items API");
  });
});
