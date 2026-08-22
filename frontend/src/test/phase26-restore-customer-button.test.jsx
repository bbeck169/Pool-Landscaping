/**
 * Feb-2026 · P26 — RestoreCustomerButton flow test.
 *
 * Pins the super_admin restore round-trip:
 *   1. Button renders with a data-testid keyed on the customer id.
 *   2. Clicking the button opens the confirmation modal.
 *   3. Anonymized customers surface a warning inside the modal.
 *   4. Confirm calls ``PATCH /customers/{cid}/restore`` and fires the
 *      ``onRestored`` callback with the API payload.
 *   5. API failures fire the ``onError`` callback with the message.
 *   6. Cancel closes the modal without calling the API.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: { patch: vi.fn() },
}));

import { api } from "@/api";
import RestoreCustomerButton from "@/components/customers/RestoreCustomerButton";


function _flush() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}


describe("RestoreCustomerButton (P26)", () => {
  it("renders the Restore pill with a stable testid", () => {
    const { getByTestId } = render(
      <RestoreCustomerButton customer={{ id: "cust-123" }} />,
    );
    const btn = getByTestId("restore-customer-btn-cust-123");
    expect(btn.textContent).toContain("Restore");
  });

  it("opens the confirmation modal on click", () => {
    const { getByTestId, queryByTestId } = render(
      <RestoreCustomerButton customer={{ id: "cust-123" }} />,
    );
    expect(queryByTestId("restore-customer-modal-cust-123")).toBeNull();
    fireEvent.click(getByTestId("restore-customer-btn-cust-123"));
    expect(getByTestId("restore-customer-modal-cust-123")).toBeTruthy();
  });

  it("shows the anonymized warning when the row was P11b-anonymized", () => {
    const { getByTestId, queryByTestId } = render(
      <RestoreCustomerButton customer={{
        id: "cust-a",
        anonymized_at: "2026-06-01T10:00:00Z",
      }} />,
    );
    fireEvent.click(getByTestId("restore-customer-btn-cust-a"));
    expect(getByTestId("restore-anonymized-warning-cust-a")).toBeTruthy();

    // A non-anonymized customer must NOT show the warning banner.
    const { getByTestId: g2, queryByTestId: q2 } = render(
      <RestoreCustomerButton customer={{ id: "cust-b" }} />,
    );
    fireEvent.click(g2("restore-customer-btn-cust-b"));
    expect(q2("restore-anonymized-warning-cust-b")).toBeNull();
  });

  it("confirms → calls PATCH → fires onRestored with the payload", async () => {
    api.patch.mockResolvedValueOnce({
      restored: true,
      customer_id: "cust-1",
      was_anonymized: false,
      restored_at: "2026-06-01T11:00:00Z",
    });
    const onRestored = vi.fn();
    const { getByTestId } = render(
      <RestoreCustomerButton
        customer={{ id: "cust-1" }}
        onRestored={onRestored}
      />,
    );
    fireEvent.click(getByTestId("restore-customer-btn-cust-1"));
    fireEvent.click(getByTestId("restore-customer-confirm-cust-1"));
    await _flush();
    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    expect(api.patch).toHaveBeenCalledWith("/customers/cust-1/restore", {});
    expect(onRestored).toHaveBeenCalledTimes(1);
    expect(onRestored.mock.calls[0][0].restored).toBe(true);
  });

  it("fires onError with the message on API failure", async () => {
    api.patch.mockRejectedValueOnce(new Error("Only super_admin can restore"));
    const onError = vi.fn();
    const { getByTestId } = render(
      <RestoreCustomerButton
        customer={{ id: "cust-x" }}
        onError={onError}
      />,
    );
    fireEvent.click(getByTestId("restore-customer-btn-cust-x"));
    fireEvent.click(getByTestId("restore-customer-confirm-cust-x"));
    await _flush();
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(onError.mock.calls[0][0]).toContain("Only super_admin can restore");
  });

  it("cancel closes the modal without calling the API", async () => {
    const onRestored = vi.fn();
    const { getByTestId, queryByTestId } = render(
      <RestoreCustomerButton
        customer={{ id: "cust-cancel" }}
        onRestored={onRestored}
      />,
    );
    fireEvent.click(getByTestId("restore-customer-btn-cust-cancel"));
    expect(getByTestId("restore-customer-modal-cust-cancel")).toBeTruthy();
    fireEvent.click(getByTestId("restore-customer-cancel-cust-cancel"));
    await _flush();
    expect(queryByTestId("restore-customer-modal-cust-cancel")).toBeNull();
    expect(api.patch).not.toHaveBeenCalled();
    expect(onRestored).not.toHaveBeenCalled();
  });
});
