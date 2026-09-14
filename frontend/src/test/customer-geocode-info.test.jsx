/**
 * Feb-2026 · Customer profile — CustomerGeocodeInfo component tests.
 *
 * Feature scope note — Phase 17 already auto-geocodes on save. This
 * component is only the UI observability layer + escape hatch. See
 * /app/memory/FEATURE_CUSTOMER_MANUAL_REGEOCODE_UI.md.
 *
 * Contracts asserted:
 *   1. Populated state renders "Location: <lat>, <lng> · (geocoded YYYY-MM-DD)"
 *      with the correct test IDs.
 *   2. Null-coords state renders "Location: unavailable" + the
 *      Re-geocode button (admin role); click POSTs to
 *      /customers/:id/geocode?force=true, calls onRefetch, and
 *      surfaces a success toast.
 *   3. Non-admin roles (technician / customer) see the null-state
 *      line but the Re-geocode button is hidden.
 */
import React from "react";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";


let apiPostImpl = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get:  (...a) => Promise.resolve(null),
    post: (...a) => apiPostImpl(...a),
  },
}));


import CustomerGeocodeInfo from "@/components/customers/CustomerGeocodeInfo";


describe("CustomerGeocodeInfo (Feb-2026)", () => {
  beforeEach(() => {
    apiPostImpl = vi.fn();
  });
  afterEach(() => {
    cleanup();
  });

  it("renders coords + geocoded stamp when populated", () => {
    const customer = {
      id: "cust_1",
      latitude: 33.7245678,
      longitude: -112.1234567,
      geocoded_at: "2026-02-05T14:30:00+00:00",
    };
    render(
      <CustomerGeocodeInfo
        customer={customer}
        role="admin"
        onRefetch={vi.fn()}
        onToast={vi.fn()}
      />,
    );
    const info = screen.getByTestId("customer-geocode-info");
    expect(info).toBeTruthy();
    // Coords are rendered rounded to 4 decimals (component contract).
    expect(
      screen.getByTestId("customer-geocode-coords").textContent,
    ).toContain("33.7246");
    expect(
      screen.getByTestId("customer-geocode-coords").textContent,
    ).toContain("-112.1235");
    // Timestamp rendered as YYYY-MM-DD (matches TenantsAdminPage pattern).
    expect(
      screen.getByTestId("customer-geocode-stamp").textContent,
    ).toContain("2026-02-05");
    // Re-geocode button MUST NOT render when coords are present.
    expect(screen.queryByTestId("customer-regeocode-btn")).toBeNull();
  });

  it("renders 'unavailable' + Re-geocode button (admin) — click posts and refetches", async () => {
    const customer = {
      id: "cust_2",
      // No latitude/longitude/geocoded_at. Feb-2026 · Re-geocode
      // fix — the button short-circuits without a POST when the
      // customer has NO address anywhere on the doc, so the
      // happy-path click test must seed a resolvable address.
      address: "5542 W Big Oak St, Phoenix, AZ 85083",
    };
    apiPostImpl.mockResolvedValue({
      ok: true,
      lat: 33.99,
      lng: -112.01,
      geocoded_at: "2026-02-10T22:00:00+00:00",
    });
    const onRefetch = vi.fn();
    const onToast   = vi.fn();
    render(
      <CustomerGeocodeInfo
        customer={customer}
        role="admin"
        onRefetch={onRefetch}
        onToast={onToast}
      />,
    );
    expect(
      screen.getByTestId("customer-geocode-unavailable"),
    ).toBeTruthy();
    const btn = screen.getByTestId("customer-regeocode-btn");
    expect(btn).toBeTruthy();

    fireEvent.click(btn);

    await waitFor(() => {
      expect(apiPostImpl).toHaveBeenCalledWith(
        "/customers/cust_2/geocode?force=true",
      );
    });
    await waitFor(() => {
      expect(onRefetch).toHaveBeenCalledTimes(1);
    });
    // Success toast surfaced.
    expect(onToast).toHaveBeenCalled();
    const toastArgs = onToast.mock.calls[0][0];
    expect(toastArgs.tone).toBe("success");
  });

  it("hides the Re-geocode button for non-admin roles (technician)", () => {
    const customer = { id: "cust_3" }; // No coords.
    render(
      <CustomerGeocodeInfo
        customer={customer}
        role="technician"
        onRefetch={vi.fn()}
        onToast={vi.fn()}
      />,
    );
    // Line still renders.
    expect(
      screen.getByTestId("customer-geocode-unavailable"),
    ).toBeTruthy();
    // Button is gated.
    expect(screen.queryByTestId("customer-regeocode-btn")).toBeNull();
  });
});
