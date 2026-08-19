/**
 * Feb-2026 · Dispatch Board · db.jobs fallback (web).
 *
 * Covers:
 *   1. `fetchBoard({ date })` includes `date=YYYY-MM-DD` in the URL.
 *   2. `RouteDetailsList` renders the "not geocoded" chip on stops
 *      whose backend row carries `not_geocoded: true`.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";


const mockGet = vi.fn(async () => ({ pins: [], route_stops: [] }));
vi.mock("@/api", () => ({ api: { get: (...a) => mockGet(...a) } }));

// eslint-disable-next-line import/first
import { fetchBoard } from "@/pages/dispatch/dispatchBoardApi";
// eslint-disable-next-line import/first
import RouteDetailsList from "@/pages/dispatch/RouteDetailsList";


beforeEach(() => { mockGet.mockClear(); });


describe("fetchBoard · date param", () => {
  it("appends date=YYYY-MM-DD when supplied", async () => {
    await fetchBoard({ day: "mon", tech_user_id: "tech-A",
                       date: "2026-05-04" });
    const url = mockGet.mock.calls[0][0];
    expect(url).toMatch(/day=mon/);
    expect(url).toMatch(/tech_user_id=tech-A/);
    expect(url).toMatch(/date=2026-05-04/);
  });

  it("omits the date param when null / undefined (backwards compat)", async () => {
    await fetchBoard({ day: "all", tech_user_id: "tech-A", date: null });
    const url = mockGet.mock.calls[0][0];
    expect(url).not.toMatch(/date=/);
  });
});


describe("RouteDetailsList · not-geocoded chip", () => {
  const stops = [
    { customer_id: "c1", name: "Alice",
      address: "1 Test Ln", not_geocoded: false, lat: 1, lng: 2 },
    { customer_id: "c2", name: "Bob",
      address: "no map data", not_geocoded: true, lat: null, lng: null },
  ];

  it("renders chip only on rows where not_geocoded === true", () => {
    render(
      <RouteDetailsList
        stops={stops}
        activeCustomerId={null}
        onSelect={() => {}}
        onReorder={() => {}}
        onRemove={() => {}}
      />,
    );
    expect(screen.queryByTestId("dispatch-route-nogeo-c1")).toBeNull();
    expect(screen.getByTestId("dispatch-route-nogeo-c2")).toBeInTheDocument();
    expect(screen.getByTestId("dispatch-route-nogeo-c2")).toHaveTextContent(/not geocoded/i);
  });
});
