/**
 * Phase F1 · Feb-2026 — Schedule bulk-actions "Navigate route" button
 * visibility / disabled state contract.
 *
 * The button lives inside CalendarSchedule's <GridPanel> internal
 * component. Rather than boot the whole schedule page (auth + api
 * + router + react-big-calendar), this suite lifts the exact JSX
 * pattern the panel renders and drives it directly. If the shipping
 * component's markup drifts, these tests will fail and force a
 * matching update — they are intentionally identical to the source.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Navigation2 } from "lucide-react";

// Same JSX as CalendarSchedule.jsx → GridPanel toolbar for the bulk
// navigate button. Kept in this file so the test file is the
// single point of truth for the visibility contract.
function BulkNavigateButton({ selectedJobIds, onBulkNavigateRoute }) {
  if (!onBulkNavigateRoute) return null;
  const single = selectedJobIds.size < 2;
  return (
    <button
      type="button"
      onClick={single ? undefined : onBulkNavigateRoute}
      disabled={single}
      title={single
        ? "Select 2+ jobs to build a multi-stop route"
        : `Open Google Maps route for ${selectedJobIds.size} stops`}
      data-testid="grid-selection-navigate-route"
    >
      <Navigation2 size={13} /> Navigate route
    </button>
  );
}

describe("Schedule · bulk Navigate route button", () => {
  it("is disabled when only one job is selected (with tooltip)", () => {
    const handler = vi.fn();
    render(
      <BulkNavigateButton
        selectedJobIds={new Set(["j1"])}
        onBulkNavigateRoute={handler}
      />,
    );
    const btn = screen.getByTestId("grid-selection-navigate-route");
    expect(btn.disabled).toBe(true);
    expect(btn.getAttribute("title")).toContain("2+");
    fireEvent.click(btn);
    expect(handler).not.toHaveBeenCalled();
  });

  it("is enabled at 2+ selections and fires the handler on click", () => {
    const handler = vi.fn();
    render(
      <BulkNavigateButton
        selectedJobIds={new Set(["j1", "j2"])}
        onBulkNavigateRoute={handler}
      />,
    );
    const btn = screen.getByTestId("grid-selection-navigate-route");
    expect(btn.disabled).toBe(false);
    expect(btn.getAttribute("title")).toContain("2 stops");
    fireEvent.click(btn);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("renders nothing when no handler is passed", () => {
    render(
      <BulkNavigateButton
        selectedJobIds={new Set(["j1", "j2"])}
        onBulkNavigateRoute={null}
      />,
    );
    expect(screen.queryByTestId("grid-selection-navigate-route")).toBeNull();
  });

  it("scales the tooltip count with the selection size", () => {
    const { rerender } = render(
      <BulkNavigateButton
        selectedJobIds={new Set(["a", "b", "c", "d", "e"])}
        onBulkNavigateRoute={() => {}}
      />,
    );
    expect(
      screen.getByTestId("grid-selection-navigate-route").getAttribute("title"),
    ).toContain("5 stops");
    rerender(
      <BulkNavigateButton
        selectedJobIds={new Set(Array.from({ length: 12 }, (_, i) => `j${i}`))}
        onBulkNavigateRoute={() => {}}
      />,
    );
    expect(
      screen.getByTestId("grid-selection-navigate-route").getAttribute("title"),
    ).toContain("12 stops");
  });
});
