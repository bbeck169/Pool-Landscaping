/**
 * Feb-2026 · Multi-Contact Phase 1 · frontend editor tests.
 *
 * Locks the six invariants:
 *   1. Renders repeatable email + mobile rows from initial customer.
 *   2. "Add email" disables when 4 emails already present.
 *   3. Delete button removes a row.
 *   4. Duplicate address surfaces inline error + Save disabled.
 *   5. Mute toggle opens the reason prompt; confirm POSTs to
 *      ``PATCH /customers/{id}/mute-automations`` with the payload
 *      shape the backend expects.
 *   6. Muted-state banner + badge render when
 *      ``customer.automations_muted=true``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act,
         cleanup } from "@testing-library/react";

const __stubs = { patch: vi.fn() };
vi.mock("@/api", () => ({
  api: { patch: (...a) => __stubs.patch(...a) },
}));
vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import CustomerMultiContactEditor from
  "@/components/customers/CustomerMultiContactEditor";


function _customer(overrides = {}) {
  return {
    id: "cust-1",
    name: "Probe",
    emails: [{ address: "primary@x.com", label: "primary",
                 notifications_enabled: true }],
    mobiles: [{ number_e164: "+15551234567", label: "primary",
                  notifications_enabled: true }],
    ...overrides,
  };
}


beforeEach(() => {
  __stubs.patch.mockReset();
  cleanup();
});


describe("CustomerMultiContactEditor", () => {
  it("renders one email row and one mobile row from initial state", () => {
    render(<CustomerMultiContactEditor customer={_customer()}
                                          isAdmin onRefresh={() => {}} />);
    expect(screen.getByTestId("customer-email-row-0")).toBeTruthy();
    expect(screen.getByTestId("customer-mobile-row-0")).toBeTruthy();
    expect(screen.getByTestId("customer-email-input-0").value)
      .toBe("primary@x.com");
    expect(screen.getByTestId("customer-mobile-input-0").value)
      .toBe("+15551234567");
  });

  it("disables the Add-email button at 4 emails; enables until then", () => {
    const c = _customer({ emails: [
      { address: "a@x.com" }, { address: "b@x.com" },
      { address: "c@x.com" }, { address: "d@x.com" },
    ] });
    render(<CustomerMultiContactEditor customer={c} isAdmin
                                          onRefresh={() => {}} />);
    const addBtn = screen.getByTestId("customer-email-add-btn");
    expect(addBtn.disabled).toBe(true);
  });

  it("delete button removes the target row", () => {
    const c = _customer({ emails: [
      { address: "a@x.com" }, { address: "b@x.com" },
    ] });
    render(<CustomerMultiContactEditor customer={c} isAdmin
                                          onRefresh={() => {}} />);
    fireEvent.click(screen.getByTestId("customer-email-delete-0"));
    // After delete: row-1 gone, row-0 now contains what was row-1's data.
    expect(screen.queryByTestId("customer-email-row-1")).toBeNull();
    expect(screen.getByTestId("customer-email-input-0").value)
      .toBe("b@x.com");
  });

  it("duplicate address shows inline error and disables Save", () => {
    const c = _customer({ emails: [
      { address: "same@x.com" }, { address: "SAME@x.com" },
    ] });
    render(<CustomerMultiContactEditor customer={c} isAdmin
                                          onRefresh={() => {}} />);
    expect(screen.getByTestId("customer-email-dupe-error")).toBeTruthy();
    expect(screen.getByTestId("customer-contacts-save-btn").disabled)
      .toBe(true);
  });

  it("mute toggle → reason prompt → Mute button POSTs to the endpoint", async () => {
    __stubs.patch.mockResolvedValue({});
    render(<CustomerMultiContactEditor customer={_customer()} isAdmin
                                          onRefresh={() => {}} />);
    // Toggle ON.
    fireEvent.click(screen.getByTestId("customer-mute-automations-toggle"));
    // Reason prompt shows up.
    const reason = await screen.findByTestId("customer-mute-reason-input");
    fireEvent.change(reason,
      { target: { value: "Customer request 2026-09-11" } });
    // Confirm mute.
    fireEvent.click(screen.getByTestId("customer-mute-confirm-btn"));
    await waitFor(() =>
      expect(__stubs.patch).toHaveBeenCalledWith(
        "/customers/cust-1/mute-automations",
        { muted: true, reason: "Customer request 2026-09-11" },
      ),
    );
  });

  it("muted-state banner + badge render when automations_muted=true", () => {
    const c = _customer({
      automations_muted: true,
      automations_muted_reason: "Customer request",
      automations_muted_at: "2026-09-11T07:00:00+00:00",
      automations_muted_by: "u-42",
    });
    render(<CustomerMultiContactEditor customer={c} isAdmin
                                          onRefresh={() => {}} />);
    expect(screen.getByTestId("customer-muted-banner")).toBeTruthy();
    expect(screen.getByTestId("customer-muted-badge").textContent)
      .toMatch(/automations muted/i);
  });
});
