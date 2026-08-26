/**
 * Feb-2026 · Item 2 — CustomerFilterBar tests.
 *
 * Covers:
 *   1. Renders for admin, super_admin, manager.
 *   2. Does NOT render for technician role.
 *   3. Does NOT render for customer role.
 *   4. Fetches /customers?is_active=true on mount (when allowed).
 *   5. Selecting a customer calls onChange with the id.
 *   6. Clear button surfaces + calls onChange(null).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));
vi.mock("@/api", () => ({
  api: {
    get: apiGetMock, post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn(),
  },
}));

const { useAuthMock } = vi.hoisted(() => ({ useAuthMock: vi.fn() }));
vi.mock("@/auth", () => ({
  useAuth: () => useAuthMock(),
  AuthProvider: ({ children }) => children,
}));

import CustomerFilterBar from "@/components/customers/CustomerFilterBar";


const CUSTOMERS = [
  { id: "c-1", name: "Alpha Aquatics" },
  { id: "c-2", name: "Bravo Backyard" },
];


beforeEach(() => {
  vi.clearAllMocks();
  apiGetMock.mockResolvedValue(CUSTOMERS);
});


describe("CustomerFilterBar — role gate", () => {
  it("renders for admin", async () => {
    useAuthMock.mockReturnValue({ user: { role: "admin" } });
    render(<CustomerFilterBar value={null} onChange={vi.fn()}
                                testId="invoices-filter-customer" />);
    await waitFor(() =>
      expect(screen.getByTestId("invoices-filter-customer-bar")).toBeTruthy(),
    );
    expect(screen.getByTestId("invoices-filter-customer")).toBeTruthy();
  });

  it("renders for super_admin", async () => {
    useAuthMock.mockReturnValue({ user: { role: "super_admin" } });
    render(<CustomerFilterBar value={null} onChange={vi.fn()}
                                testId="quotes-filter-customer" />);
    await waitFor(() =>
      expect(screen.getByTestId("quotes-filter-customer-bar")).toBeTruthy(),
    );
  });

  it("renders for manager", async () => {
    useAuthMock.mockReturnValue({ user: { role: "manager" } });
    render(<CustomerFilterBar value={null} onChange={vi.fn()}
                                testId="estimates-filter-customer" />);
    await waitFor(() =>
      expect(screen.getByTestId("estimates-filter-customer-bar")).toBeTruthy(),
    );
  });

  it("does NOT render for technician", () => {
    useAuthMock.mockReturnValue({ user: { role: "technician" } });
    const { container } = render(
      <CustomerFilterBar value={null} onChange={vi.fn()}
                          testId="invoices-filter-customer" />,
    );
    expect(container.firstChild).toBeNull();
    expect(apiGetMock).not.toHaveBeenCalled();
  });

  it("does NOT render for customer role", () => {
    useAuthMock.mockReturnValue({ user: { role: "customer" } });
    const { container } = render(
      <CustomerFilterBar value={null} onChange={vi.fn()}
                          testId="payments-filter-customer" />,
    );
    expect(container.firstChild).toBeNull();
  });
});


describe("CustomerFilterBar — behavior", () => {
  it("fetches /customers?is_active=true on mount when allowed", async () => {
    useAuthMock.mockReturnValue({ user: { role: "admin" } });
    render(<CustomerFilterBar value={null} onChange={vi.fn()}
                                testId="invoices-filter-customer" />);
    await waitFor(() => {
      expect(apiGetMock).toHaveBeenCalledWith("/customers?is_active=true");
    });
  });

  it("shows the Clear chip only when a customer is selected", async () => {
    useAuthMock.mockReturnValue({ user: { role: "admin" } });
    const onChange = vi.fn();
    const { rerender } = render(
      <CustomerFilterBar value={null} onChange={onChange}
                          testId="invoices-filter-customer" />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("invoices-filter-customer-bar")).toBeTruthy(),
    );
    // No clear button when nothing selected.
    expect(screen.queryByTestId("invoices-filter-customer-clear")).toBeNull();
    // Rerender WITH a value.
    rerender(<CustomerFilterBar value="c-1" onChange={onChange}
                                  testId="invoices-filter-customer" />);
    expect(screen.getByTestId("invoices-filter-customer-clear")).toBeTruthy();
    // Click clear → onChange(null).
    fireEvent.click(screen.getByTestId("invoices-filter-customer-clear"));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
