/**
 * Phase 15b · Feb-2026 — CustomerTagPicker unit tests.
 *
 *   1. Renders the inline "+ Add new tag" option when the typed
 *      string has zero exact matches.
 *   2. Hides the "+ Add new tag" option when the typed string
 *      matches an existing registry tag exactly.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { apiGetMock, apiPatchMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPatchMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: apiGetMock,
    patch: apiPatchMock,
  },
}));

import CustomerTagPicker from
  "@/components/customers/CustomerTagPicker";

beforeEach(() => {
  apiGetMock.mockReset();
  apiPatchMock.mockReset();
  apiGetMock.mockResolvedValue({
    items: [
      { id: "t1", name: "VIP", color: "#DBEAFE", usage_count: 4 },
      { id: "t2", name: "Waitlist", color: "#FEE2E2", usage_count: 2 },
    ],
    total: 2,
  });
});

function openPicker() {
  fireEvent.click(screen.getByTestId("customer-tag-picker-trigger"));
}

describe("CustomerTagPicker inline add-new", () => {
  it("shows '+ Add new tag' option when the typed string has no exact match", async () => {
    render(
      <CustomerTagPicker
        customerId="cust-1"
        value={[]}
        onChange={() => {}}
      />
    );
    openPicker();
    // Wait for registry fetch.
    await waitFor(() =>
      expect(screen.getByTestId("customer-tag-picker-search")).toBeInTheDocument()
    );
    // Type a string that doesn't match VIP or Waitlist.
    fireEvent.change(
      screen.getByTestId("customer-tag-picker-search"),
      { target: { value: "Preferred" } }
    );
    await waitFor(() =>
      expect(screen.getByTestId("customer-tag-add-new")).toBeInTheDocument()
    );
    const addRow = screen.getByTestId("customer-tag-add-new");
    expect(addRow.textContent).toMatch(/Add new tag/);
    expect(addRow.textContent).toContain("Preferred");
  });

  it("hides '+ Add new tag' when the typed string exactly matches an existing tag (case-insensitive)", async () => {
    render(
      <CustomerTagPicker
        customerId="cust-1"
        value={[]}
        onChange={() => {}}
      />
    );
    openPicker();
    await waitFor(() =>
      expect(screen.getByTestId("customer-tag-picker-search")).toBeInTheDocument()
    );
    // Type "vip" — same as "VIP" ignoring case.
    fireEvent.change(
      screen.getByTestId("customer-tag-picker-search"),
      { target: { value: "vip" } }
    );
    // The existing VIP option is still visible…
    await waitFor(() =>
      expect(screen.getByTestId("customer-tag-option-VIP")).toBeInTheDocument()
    );
    // …but the "add new" affordance is gone.
    expect(screen.queryByTestId("customer-tag-add-new")).not.toBeInTheDocument();
  });

  it("adding a new tag PATCHes the customer with the new tag list", async () => {
    apiPatchMock.mockResolvedValue({ ok: true, tags: ["Preferred"] });
    const onChange = vi.fn();
    render(
      <CustomerTagPicker
        customerId="cust-9"
        value={[]}
        onChange={onChange}
      />
    );
    openPicker();
    await waitFor(() =>
      expect(screen.getByTestId("customer-tag-picker-search")).toBeInTheDocument()
    );
    fireEvent.change(
      screen.getByTestId("customer-tag-picker-search"),
      { target: { value: "Preferred" } }
    );
    await waitFor(() =>
      expect(screen.getByTestId("customer-tag-add-new")).toBeInTheDocument()
    );
    fireEvent.click(screen.getByTestId("customer-tag-add-new"));
    await waitFor(() => expect(apiPatchMock).toHaveBeenCalled());
    // Confirm the PATCH included the new tag.
    const [url, payload] = apiPatchMock.mock.calls[0];
    expect(url).toBe("/customers/cust-9/tags");
    expect(payload).toEqual({ tags: ["Preferred"] });
    // The parent's onChange must be invoked with the server's tag list.
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(["Preferred"]));
  });

  it("shows selected chips with remove buttons", () => {
    render(
      <CustomerTagPicker
        customerId="cust-1"
        value={["VIP", "Repeat"]}
        onChange={() => {}}
      />
    );
    expect(screen.getByTestId("customer-tag-chip-VIP")).toBeInTheDocument();
    expect(screen.getByTestId("customer-tag-chip-Repeat")).toBeInTheDocument();
    expect(screen.getByTestId("customer-tag-remove-VIP")).toBeInTheDocument();
  });
});
