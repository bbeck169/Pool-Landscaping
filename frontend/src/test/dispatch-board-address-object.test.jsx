// Feb-2026 · P0 regression test — Dispatch address-object render safety.
//
// Reproduces the React error #31 crash the user hit on the Dispatch Board
// ("Objects are not valid as a React child (found: object with keys
// {street, city, state, postal_code})") and locks in the frontend fix
// applied via `utils/formatAddress`.
//
// The failing surface was any Dispatch component rendering a customer /
// job `.address` field directly, because backend endpoints occasionally
// return that field as an OBJECT rather than a string (CSV-imported
// customers whose `service_address` was persisted as a nested block by
// `services/customer_import.py`).
//
// This test does two things:
//   1. Unit-tests `formatAddress` against every value shape the backend
//      can produce.
//   2. Renders each Dispatch component with an ADDRESS-OBJECT pin/stop
//      and asserts:
//        • no React #31 throw
//        • the assembled string appears in the DOM
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import formatAddress from "@/utils/formatAddress";
import UnroutedPanel from "@/pages/dispatch/UnroutedPanel";
import RouteDetailsList from "@/pages/dispatch/RouteDetailsList";

// The address shape the user actually hit in the wild.
const OBJECT_ADDR = {
  street: "1234 Palm Way",
  city: "Phoenix",
  state: "AZ",
  postal_code: "85001",
};

// Alternate shapes we also want to handle without crashing.
const OBJECT_ADDR_FORMATTED = {
  formatted: "56 Mesa Rd, Peoria, AZ 85383",
  street: "56 Mesa Rd",
  city: "Peoria",
};
const OBJECT_ADDR_LINE1 = {
  line1: "77 Cactus Blvd",
  city: "Scottsdale",
  state: "AZ",
  postcode: "85251",
};

describe("formatAddress helper", () => {
  it("returns empty string for null / undefined", () => {
    expect(formatAddress(null)).toBe("");
    expect(formatAddress(undefined)).toBe("");
  });

  it("passes through a plain string trimmed", () => {
    expect(formatAddress("  Foo Bar  ")).toBe("Foo Bar");
  });

  it("stringifies numbers / booleans defensively", () => {
    expect(formatAddress(0)).toBe("0");
    expect(formatAddress(false)).toBe("false");
  });

  it("assembles from {street, city, state, postal_code}", () => {
    expect(formatAddress(OBJECT_ADDR)).toBe(
      "1234 Palm Way, Phoenix, AZ, 85001",
    );
  });

  it("prefers `formatted` when present on the object", () => {
    expect(formatAddress(OBJECT_ADDR_FORMATTED)).toBe(
      "56 Mesa Rd, Peoria, AZ 85383",
    );
  });

  it("understands {line1, city, state, postcode}", () => {
    expect(formatAddress(OBJECT_ADDR_LINE1)).toBe(
      "77 Cactus Blvd, Scottsdale, AZ, 85251",
    );
  });

  it("de-dupes adjacent identical parts", () => {
    expect(
      formatAddress({ city: "PHOENIX", state: "PHOENIX" }),
    ).toBe("PHOENIX");
  });
});

describe("UnroutedPanel renders without React #31 on an address OBJECT", () => {
  it("renders the assembled address string, not the raw object", () => {
    const items = [
      {
        customer_id: "c-1",
        name: "Test Customer",
        // ⚠️  Object shape — this used to crash Dispatch.
        address: OBJECT_ADDR,
        reason: "no_service_day",
      },
    ];
    // Should NOT throw React #31.
    render(<UnroutedPanel items={items} />);
    // The formatter output is visible in the DOM.
    expect(
      screen.getByTestId("dispatch-unrouted-row-c-1").textContent,
    ).toContain("1234 Palm Way");
    expect(
      screen.getByTestId("dispatch-unrouted-row-c-1").textContent,
    ).toContain("Phoenix");
  });
});

describe("RouteDetailsList renders without React #31 on an address OBJECT", () => {
  it("renders the assembled address string for each stop", () => {
    const stops = [
      {
        customer_id: "c-1",
        name: "Test Stop",
        address: OBJECT_ADDR, // ⚠️  Object shape
      },
    ];
    // Should NOT throw React #31.
    render(<RouteDetailsList stops={stops} />);
    expect(
      screen.getByTestId("dispatch-route-stop-c-1").textContent,
    ).toContain("1234 Palm Way");
    expect(
      screen.getByTestId("dispatch-route-stop-c-1").textContent,
    ).toContain("85001");
  });
});
