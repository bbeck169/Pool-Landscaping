/**
 * Feb-2026 · Re-geocode button — client-side address resolution
 * fallback chain. Locks the fix for the reported bug: customer's
 * ``address`` is populated (renderer reads it) but clicking
 * "Re-geocode" incorrectly toasted "No address on file" because
 * the old handler POSTed unconditionally and the backend fallback
 * only checked ``service_address`` + structured legacy fields.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { postSpy } = vi.hoisted(() => ({ postSpy: vi.fn() }));

vi.mock("@/api", () => ({
  api: {
    post:  (...a) => postSpy(...a),
    get:   vi.fn(),
    patch: vi.fn(),
    put:   vi.fn(),
    del:   vi.fn(),
  },
}));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f8fafc",
    border: "#e5e7eb", onSurface: "#111827", muted: "#6b7280",
  },
}));

import CustomerGeocodeInfo, { resolveCustomerAddress }
  from "@/components/customers/CustomerGeocodeInfo";


beforeEach(() => { postSpy.mockReset(); });


describe("resolveCustomerAddress · fallback chain", () => {
  it("prefers service_address when present", () => {
    expect(resolveCustomerAddress({
      service_address: "1 Canon Way",
      address:         "2 Loser Ave",
    })).toBe("1 Canon Way");
  });

  it("falls back to `address` when service_address is empty", () => {
    // The reported-bug repro — display renderer reads ``address``,
    // so re-geocode MUST also see it.
    expect(resolveCustomerAddress({
      service_address: "",
      address:         "5542 W Big Oak St, Phoenix, AZ 85083",
    })).toBe("5542 W Big Oak St, Phoenix, AZ 85083");
  });

  it("falls back to street_address / mailing_address in order", () => {
    expect(resolveCustomerAddress({
      street_address: "12 Alt Rd",
    })).toBe("12 Alt Rd");
    expect(resolveCustomerAddress({
      mailing_address: "PO Box 999, Peoria AZ",
    })).toBe("PO Box 999, Peoria AZ");
  });

  it("builds a composite from structured fields as last resort", () => {
    expect(resolveCustomerAddress({
      service_street: "1 Main St",
      service_city:   "Peoria",
      service_state:  "AZ",
      service_zip:    "85383",
    })).toBe("1 Main St Peoria AZ 85383");
    expect(resolveCustomerAddress({
      street: "42 Elm St", city: "Peoria",
      state: "AZ", zip: "85383",
    })).toBe("42 Elm St Peoria AZ 85383");
  });

  it("flattens dict-shape service_address", () => {
    expect(resolveCustomerAddress({ service_address: {
      street: "1 Main St", city: "Peoria",
      state: "AZ", postal_code: "85383",
    }})).toBe("1 Main St Peoria AZ 85383");
  });

  it("returns empty string when nothing is populated anywhere", () => {
    expect(resolveCustomerAddress(null)).toBe("");
    expect(resolveCustomerAddress({})).toBe("");
    expect(resolveCustomerAddress({
      service_address: "",
      address:         null,
      street_address:  "   ",
    })).toBe("");
  });
});


describe("Re-geocode button · resolution short-circuit", () => {
  const noCoords = { id: "cust_1", latitude: null, longitude: null };

  it("customer with only `address` populated → click fires POST (does NOT toast no_address)", async () => {
    const onToast = vi.fn();
    const onRefetch = vi.fn().mockResolvedValue(null);
    postSpy.mockResolvedValue({
      ok: true, lat: 33.7, lng: -112.2,
      geocoded_at: "2026-02-14T00:00:00Z",
    });
    render(<CustomerGeocodeInfo
      customer={{ ...noCoords,
                     address: "5542 W Big Oak St, Phoenix, AZ 85083" }}
      role="admin" onToast={onToast} onRefetch={onRefetch} />);
    fireEvent.click(screen.getByTestId("customer-regeocode-btn"));
    await waitFor(() => expect(postSpy).toHaveBeenCalled());
    expect(postSpy).toHaveBeenCalledWith(
      "/customers/cust_1/geocode?force=true",
    );
    // Success toast, NEVER the "No address on file" toast.
    await waitFor(() => expect(onToast).toHaveBeenCalled());
    const messages = onToast.mock.calls.map((c) => c[0].message);
    expect(messages.some((m) => /No address on file/i.test(m))).toBe(false);
  });

  it("customer with NO address anywhere → toast shows and NO POST fires", async () => {
    const onToast = vi.fn();
    render(<CustomerGeocodeInfo
      customer={{ ...noCoords,
                     service_address: "", address: null,
                     street_address: "", mailing_address: null }}
      role="admin" onToast={onToast} />);
    fireEvent.click(screen.getByTestId("customer-regeocode-btn"));
    // No round-trip.
    expect(postSpy).not.toHaveBeenCalled();
    // Toast contains the "No address on file" copy.
    expect(onToast).toHaveBeenCalledWith(expect.objectContaining({
      tone:    "error",
      message: expect.stringMatching(/No address on file/i),
    }));
  });

  it("customer with mailing_address only → click DOES fire POST", async () => {
    const onToast = vi.fn();
    const onRefetch = vi.fn().mockResolvedValue(null);
    postSpy.mockResolvedValue({ ok: true, lat: 1, lng: 2 });
    render(<CustomerGeocodeInfo
      customer={{ ...noCoords,
                     mailing_address: "PO Box 99, Peoria AZ" }}
      role="admin" onToast={onToast} onRefetch={onRefetch} />);
    fireEvent.click(screen.getByTestId("customer-regeocode-btn"));
    await waitFor(() => expect(postSpy).toHaveBeenCalled());
  });
});
