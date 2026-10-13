/**
 * P2 #6 · Feb-2026 — ServiceCategoryControl (CustomerDetail dropdown) vitest.
 *
 * Locks four invariants on the admin-only service_category edit control:
 *   1. Admin role sees the control; non-admin (manager/technician/
 *      customer) sees nothing (component short-circuits to null).
 *   2. Changing the <select> fires PATCH /customers/{cid}/service-category
 *      with the chosen value AND optimistically updates the parent via
 *      ``onOptimisticSet``.
 *   3. Selecting the "Not set" option sends ``service_category: null``.
 *   4. API error path reverts the optimistic update to the previous value.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup }
  from "@testing-library/react";


const { apiPatchSpy, toastSuccessSpy, toastErrorSpy } = vi.hoisted(() => ({
  apiPatchSpy: vi.fn(),
  toastSuccessSpy: vi.fn(),
  toastErrorSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { patch: (...a) => apiPatchSpy(...a) },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: (...a) => toastSuccessSpy(...a),
    error: (...a) => toastErrorSpy(...a),
  }),
}));

const authMock = vi.hoisted(() => ({ user: { role: "admin" } }));
vi.mock("@/auth", () => ({ useAuth: () => authMock }));


import { ServiceCategoryControl }
  from "@/components/customers/ServiceCategoryControl";


beforeEach(() => {
  apiPatchSpy.mockReset();
  toastSuccessSpy.mockReset();
  toastErrorSpy.mockReset();
  authMock.user = { role: "admin" };
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });


function _mount({ customer, onOptimisticSet = vi.fn() }) {
  const r = render(
    <ServiceCategoryControl
      customer={customer}
      onOptimisticSet={onOptimisticSet}
    />,
  );
  return { ...r, onOptimisticSet };
}


describe("P2 #6 · ServiceCategoryControl", () => {
  it("renders for admin and PATCHes with the chosen value + optimistic update", async () => {
    apiPatchSpy.mockResolvedValue({});
    const { onOptimisticSet } = _mount({
      customer: { id: "c-1", service_category: null },
    });
    const sel = screen.getByTestId("customer-service-category-select");
    fireEvent.change(sel, { target: { value: "pool" } });
    expect(onOptimisticSet).toHaveBeenCalledWith("pool");
    await waitFor(() => {
      expect(apiPatchSpy).toHaveBeenCalledWith(
        "/customers/c-1/service-category",
        { service_category: "pool" },
      );
    });
    await waitFor(() => expect(toastSuccessSpy).toHaveBeenCalled());
  });

  it("Not set option PATCHes with null body", async () => {
    apiPatchSpy.mockResolvedValue({});
    const { onOptimisticSet } = _mount({
      customer: { id: "c-2", service_category: "both" },
    });
    const sel = screen.getByTestId("customer-service-category-select");
    fireEvent.change(sel, { target: { value: "" } });
    expect(onOptimisticSet).toHaveBeenCalledWith(null);
    await waitFor(() => {
      expect(apiPatchSpy).toHaveBeenCalledWith(
        "/customers/c-2/service-category",
        { service_category: null },
      );
    });
  });

  it("API error reverts the optimistic update + fires error toast", async () => {
    apiPatchSpy.mockRejectedValue(new Error("boom"));
    const { onOptimisticSet } = _mount({
      customer: { id: "c-3", service_category: "landscaping" },
    });
    const sel = screen.getByTestId("customer-service-category-select");
    fireEvent.change(sel, { target: { value: "pool" } });
    // Optimistic forward step.
    expect(onOptimisticSet).toHaveBeenNthCalledWith(1, "pool");
    await waitFor(() => expect(toastErrorSpy).toHaveBeenCalled());
    // Revert step with the prev value.
    expect(onOptimisticSet).toHaveBeenNthCalledWith(2, "landscaping");
  });

  it("hides the control for non-admin roles", () => {
    authMock.user = { role: "manager" };
    const { container } = _mount({
      customer: { id: "c-4", service_category: null },
    });
    expect(container.firstChild).toBeNull();
  });
});
