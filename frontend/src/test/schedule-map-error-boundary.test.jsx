/**
 * Feb-2026 · P0 defensive · ScheduleMap error boundary vitest.
 *
 * Guards the P0 "schedule freezes if any day has a job scheduled"
 * class of bug: a Google Maps SDK render-throw MUST NOT cascade
 * beyond ``<ScheduleMapErrorBoundary>``.
 *
 * Cases covered:
 *   1. When the child renders normally, the boundary is transparent.
 *   2. When the child throws (simulating
 *      ``BillingNotEnabledMapError`` /
 *      ``ApiNotActivatedMapError`` from
 *      ``@vis.gl/react-google-maps``), the boundary swallows the
 *      throw and renders the ``schedule-map-fallback`` tile.
 *   3. The fallback tile carries a
 *      ``data-map-fallback-reason`` attribute so ops can grep for
 *      the underlying reason without spelunking the console.
 *   4. Siblings mounted OUTSIDE the boundary (representing the
 *      job-list, bulk actions, reorder controls in
 *      ``CalendarSchedule.jsx``) keep rendering — no cascading
 *      crash.
 */
/* eslint-disable no-console */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";

import ScheduleMapErrorBoundary from
  "../components/schedule/ScheduleMapErrorBoundary";


function _Boom({ message = "BillingNotEnabledMapError" }) {
  throw new Error(message);
  // eslint-disable-next-line no-unreachable
  return null;
}


function _Good() {
  return <div data-testid="good-map-child">map ok</div>;
}


describe("<ScheduleMapErrorBoundary>", () => {
  beforeEach(() => {
    // Silence React's noisy "The above error occurred in the
    // <Boom> component" console output — the boundary itself
    // logs a friendlier warn we DO care about, but React's
    // default noise adds ~10 lines per test.
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  it("passes children through when nothing throws", () => {
    render(
      <ScheduleMapErrorBoundary>
        <_Good />
      </ScheduleMapErrorBoundary>,
    );
    expect(screen.getByTestId("good-map-child")).toBeInTheDocument();
    expect(screen.queryByTestId("schedule-map-fallback")).toBeNull();
  });

  it("renders the fallback tile when the child throws " +
       "BillingNotEnabledMapError (matches P0 repro)", () => {
    render(
      <ScheduleMapErrorBoundary>
        <_Boom message="BillingNotEnabledMapError" />
      </ScheduleMapErrorBoundary>,
    );
    const fallback = screen.getByTestId("schedule-map-fallback");
    expect(fallback).toBeInTheDocument();
    expect(fallback).toHaveAttribute(
      "data-map-fallback-reason",
      "BillingNotEnabledMapError",
    );
    expect(fallback).toHaveTextContent(/temporarily unavailable/i);
    expect(fallback).toHaveTextContent(/integration settings/i);
  });

  it("renders the fallback tile when the child throws " +
       "ApiNotActivatedMapError (key-rotation class)", () => {
    render(
      <ScheduleMapErrorBoundary>
        <_Boom message="ApiNotActivatedMapError" />
      </ScheduleMapErrorBoundary>,
    );
    expect(
      screen.getByTestId("schedule-map-fallback"),
    ).toHaveAttribute("data-map-fallback-reason", "ApiNotActivatedMapError");
  });

  it("logs the crash to console.warn (ops observability, no toast)",
     () => {
    const warn = vi.spyOn(console, "warn");
    render(
      <ScheduleMapErrorBoundary>
        <_Boom message="something exploded" />
      </ScheduleMapErrorBoundary>,
    );
    // At least one warn should mention the boundary name.
    const calls = warn.mock.calls.map((c) => JSON.stringify(c));
    expect(
      calls.some((c) => /ScheduleMapErrorBoundary/.test(c)),
    ).toBe(true);
  });

  it("does NOT cascade: siblings mounted next to the boundary " +
       "keep rendering (this is the P0 root guarantee)", () => {
    render(
      <div>
        <ScheduleMapErrorBoundary>
          <_Boom />
        </ScheduleMapErrorBoundary>
        <div data-testid="schedule-day-cards">jobs here</div>
        <div data-testid="schedule-bulk-actions">bulk here</div>
      </div>,
    );
    expect(screen.getByTestId("schedule-map-fallback"))
      .toBeInTheDocument();
    // These represent the rest of CalendarSchedule.jsx's day
    // panel — they MUST NOT be swallowed by the throw.
    expect(screen.getByTestId("schedule-day-cards"))
      .toBeInTheDocument();
    expect(screen.getByTestId("schedule-bulk-actions"))
      .toBeInTheDocument();
  });
});
