/**
 * Feb-2026 · Batch #4 · Item 3 regression — schedule refresh button.
 *
 * Two invariants the tester flagged as broken:
 *   1. Test-id was ``schedule-refresh-btn``; required is
 *      ``schedule-refresh``. (Rename + no stale references.)
 *   2. Click threw ``ReferenceError: load is not defined`` because
 *      the button lived inside <GridPanel> but referenced the
 *      parent <CalendarSchedule>'s ``load`` symbol. The fix routes
 *      the handler through an ``onRefresh`` prop injected from the
 *      parent — this test guards against reintroduction.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// Some GridPanel deep imports pull in date-fns / motion / RN-web
// shims that aren't needed for this smoke test. Keep the render
// surface lean by stubbing the heavy components below to no-op.
vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
  useLocation: () => ({ pathname: "/schedule", search: "" }),
  Link: ({ children }) => children,
}));

import { GridPanel } from "@/pages/schedule/CalendarSchedule";


function _baseProps(overrides = {}) {
  return {
    date: new Date("2026-09-21T12:00:00Z"),
    setDate: vi.fn(),
    jobs: [],
    loading: false,
    checked: new Set(),
    onToggle: vi.fn(),
    canWrite: false,
    onBulkComplete: vi.fn(),
    onOpenMove: vi.fn(),
    moveOpen: false,
    setMoveOpen: vi.fn(),
    moveDate: new Date(),
    setMoveDate: vi.fn(),
    onConfirmMove: vi.fn(),
    busy: false,
    onOpenJob: vi.fn(),
    onNewJob: undefined,
    selectedJobIds: new Set(),
    onToggleSelect: vi.fn(),
    canMultiSelectDelete: false,
    onOpenBulkDelete: vi.fn(),
    onClearSelection: vi.fn(),
    onSelectAllInView: vi.fn(),
    onBulkNavigateRoute: vi.fn(),
    canMultiSelectAssign: false,
    onOpenBulkAssign: vi.fn(),
    techs: [],
    onOpenEdit: undefined,
    isAdminForCard: false,
    onOpenCouldNotService: vi.fn(),
    orderController: { setOrder: vi.fn(), getOrder: () => ({}) },
    onOpenBulkReorder: vi.fn(),
    reorderableJobIds: [],
    onOptimizeRoute: vi.fn(),
    optimizing: false,
    onRefresh: vi.fn(),
    ...overrides,
  };
}


describe("Batch #4 · Item 3 · GridPanel refresh button", () => {
  it("renders with test-id `schedule-refresh` (not `-btn`)", () => {
    render(<GridPanel {..._baseProps()} />);
    expect(screen.getByTestId("schedule-refresh")).toBeTruthy();
    expect(screen.queryByTestId("schedule-refresh-btn")).toBeNull();
  });

  it("click invokes the injected onRefresh handler (no ReferenceError)", () => {
    const onRefresh = vi.fn();
    render(<GridPanel {..._baseProps({ onRefresh })} />);
    // Zero-throw click — regression against the ``load is not
    // defined`` failure the tester reported.
    expect(() => {
      fireEvent.click(screen.getByTestId("schedule-refresh"));
    }).not.toThrow();
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("disabled while busy — click is a no-op", () => {
    const onRefresh = vi.fn();
    render(<GridPanel {..._baseProps({ busy: true, onRefresh })} />);
    const btn = screen.getByTestId("schedule-refresh");
    expect(btn.disabled).toBe(true);
    fireEvent.click(btn);
    expect(onRefresh).not.toHaveBeenCalled();
  });
});
