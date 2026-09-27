/**
 * Feb-2026 · Pool Service PS-C — tracker List/Calendar toggle.
 *
 * Pins the four behaviour invariants from the brief:
 *   (a) Default view is List (existing users see zero change on
 *       first paint).
 *   (b) Clicking the Calendar toggle switches views + renders the
 *       month grid + weekday header + navigation.
 *   (c) Rows with a ``due_at`` inside the currently-visible month
 *       render as event dots on the correct day cell, keyed by
 *       ``tracker-calendar-event-{id}``.
 *   (d) The view preference persists to localStorage under
 *       ``tracker_view_pref:{trackerType}`` — a re-mount of the
 *       page picks up the stored preference.
 *   (e) Empty month → the "No maintenance scheduled this month"
 *       overlay renders.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  act, cleanup, fireEvent, render, screen, waitFor,
} from "@testing-library/react";


const _getSpy = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => _getSpy(...a), post: vi.fn(),
           patch: vi.fn(), del: vi.fn() },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  Link: ({ children, ...props }) => (
    // eslint-disable-next-line jsx-a11y/anchor-is-valid
    <a {...props}>{children}</a>
  ),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
    warning: vi.fn(), info: vi.fn(),
  }),
}));

vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/components/customers/CustomerCombobox", () => ({
  default: () => null,
}));

// eslint-disable-next-line import/first
import { EquipmentTrackerListPage } from "@/pages/tracking/EquipmentTrackerPages";


// _FIXED_NOW must match the CI clock in this suite — vitest uses
// vi.setSystemTime to freeze ``new Date()``.  Feb 11 2026 lands us
// mid-month so a scheduled row on the 15th is same-month.
const _FIXED_NOW = new Date("2026-02-11T12:00:00Z");


beforeEach(() => {
  _getSpy.mockReset();
  window.localStorage.clear();
  vi.setSystemTime(_FIXED_NOW);
});


function _seedRows(rows) {
  _getSpy.mockResolvedValue({
    trackers: rows,
    counts_by_status: { current: 1, coming_due: 1, past_due: 0 },
  });
}


// ═══════════════════════════════════════════════════════════════════
// (a) Default view is List.
// ═══════════════════════════════════════════════════════════════════
describe("PS-C · tracker List/Calendar toggle · default view", () => {
  it("mounts in List mode with no stored preference", async () => {
    _seedRows([{
      id: "trk-1", customer_name: "Alice",
      interval_months: 6, due_at: "2026-02-15",
      status_computed: "coming_due", property_address: "1 Pool Ln",
    }]);
    render(<EquipmentTrackerListPage trackerType="filter" />);
    await waitFor(() => expect(_getSpy).toHaveBeenCalled());

    // Toggle exists.
    expect(screen.getByTestId("tracker-view-toggle")).toBeInTheDocument();
    expect(screen.getByTestId("tracker-view-list"))
      .toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("tracker-view-calendar"))
      .toHaveAttribute("aria-pressed", "false");

    // The list row is rendered (list mode).
    expect(await screen.findByTestId("tracker-row-trk-1"))
      .toBeInTheDocument();
    // Calendar body NOT rendered.
    expect(screen.queryByTestId("tracker-calendar-filter"))
      .toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════════
// (b) Toggle to Calendar renders grid + events on correct days.
// ═══════════════════════════════════════════════════════════════════
describe("PS-C · tracker List/Calendar toggle · switch to calendar", () => {
  it("renders month grid + event dots when Calendar clicked", async () => {
    _seedRows([
      { id: "trk-A", customer_name: "Alice",
        interval_months: 6, due_at: "2026-02-15",
        status_computed: "coming_due",
        property_address: "1 Pool Ln" },
      { id: "trk-B", customer_name: "Bob",
        interval_months: 6, due_at: "2026-02-20",
        status_computed: "current",
        property_address: "2 Pool Ln" },
    ]);
    render(<EquipmentTrackerListPage trackerType="filter" />);
    await waitFor(() => expect(_getSpy).toHaveBeenCalled());
    // Wait for at least one list row before flipping (ensures the
    // page finished its initial load).
    await screen.findByTestId("tracker-row-trk-A");

    // Flip to Calendar.
    await act(async () => {
      fireEvent.click(screen.getByTestId("tracker-view-calendar"));
    });

    // Grid + header rendered.
    expect(await screen.findByTestId("tracker-calendar-filter"))
      .toBeInTheDocument();
    expect(screen.getByTestId("tracker-calendar-grid"))
      .toBeInTheDocument();
    // Month label reads February 2026 (from _FIXED_NOW).
    expect(screen.getByTestId("tracker-calendar-month-label")
      .textContent).toMatch(/February 2026/);

    // Events landed on their day cells.
    const cell15 = screen.getByTestId("tracker-calendar-day-2026-02-15");
    expect(cell15).toHaveAttribute("data-event-count", "1");
    expect(cell15).toHaveAttribute("data-in-month", "true");
    const cell20 = screen.getByTestId("tracker-calendar-day-2026-02-20");
    expect(cell20).toHaveAttribute("data-event-count", "1");

    // Event dots keyed by tracker id.
    expect(screen.getByTestId("tracker-calendar-event-trk-A"))
      .toBeInTheDocument();
    expect(screen.getByTestId("tracker-calendar-event-trk-B"))
      .toBeInTheDocument();

    // Toggle state flipped.
    expect(screen.getByTestId("tracker-view-list"))
      .toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("tracker-view-calendar"))
      .toHaveAttribute("aria-pressed", "true");
  });
});


// ═══════════════════════════════════════════════════════════════════
// (c) LocalStorage persistence.
// ═══════════════════════════════════════════════════════════════════
describe("PS-C · tracker List/Calendar toggle · localStorage persistence", () => {
  it("persists the choice per tracker and re-hydrates on re-mount", async () => {
    _seedRows([]);

    // Round 1 — mount filter tracker, flip to Calendar.
    render(<EquipmentTrackerListPage trackerType="filter" />);
    await waitFor(() => expect(_getSpy).toHaveBeenCalled());
    await act(async () => {
      fireEvent.click(screen.getByTestId("tracker-view-calendar"));
    });
    expect(window.localStorage.getItem(
      "tracker_view_pref:filter",
    )).toBe("calendar");

    cleanup();

    // Round 2 — re-mount same tracker; picks up stored preference.
    _getSpy.mockReset();
    _seedRows([]);
    render(<EquipmentTrackerListPage trackerType="filter" />);
    await waitFor(() => expect(_getSpy).toHaveBeenCalled());
    expect(await screen.findByTestId("tracker-calendar-filter"))
      .toBeInTheDocument();
    expect(screen.getByTestId("tracker-view-calendar"))
      .toHaveAttribute("aria-pressed", "true");

    cleanup();

    // Round 3 — different tracker (salt_cell) → SEPARATE key,
    // defaults to List because we never set salt_cell to Calendar.
    _getSpy.mockReset();
    _seedRows([]);
    render(<EquipmentTrackerListPage trackerType="salt_cell" />);
    await waitFor(() => expect(_getSpy).toHaveBeenCalled());
    expect(screen.getByTestId("tracker-view-list"))
      .toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByTestId("tracker-calendar-salt_cell"))
      .toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════════
// (d) Empty month → overlay renders.
// ═══════════════════════════════════════════════════════════════════
describe("PS-C · tracker List/Calendar toggle · empty month", () => {
  it("shows 'No maintenance scheduled this month' overlay when no rows", async () => {
    _seedRows([]);
    render(<EquipmentTrackerListPage trackerType="salt_cell" />);
    await waitFor(() => expect(_getSpy).toHaveBeenCalled());
    // Manually flip because localStorage was cleared in beforeEach.
    await act(async () => {
      fireEvent.click(screen.getByTestId("tracker-view-calendar"));
    });

    expect(await screen.findByTestId("tracker-calendar-empty-salt_cell"))
      .toBeInTheDocument();
    expect(screen.getByTestId("tracker-calendar-empty-salt_cell")
      .textContent).toMatch(/No maintenance scheduled this month/);
  });

  it("hides the overlay once at least one event lands in the current month", async () => {
    _seedRows([{
      id: "trk-here", customer_name: "Charlie",
      interval_months: 6, due_at: "2026-02-07",
      status_computed: "current", property_address: "7 Pool Ln",
    }]);
    render(<EquipmentTrackerListPage trackerType="salt_cell" />);
    await waitFor(() => expect(_getSpy).toHaveBeenCalled());
    await act(async () => {
      fireEvent.click(screen.getByTestId("tracker-view-calendar"));
    });
    await screen.findByTestId("tracker-calendar-salt_cell");
    expect(screen.queryByTestId("tracker-calendar-empty-salt_cell"))
      .toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════════
// (e) Month navigation shifts events out of view.
// ═══════════════════════════════════════════════════════════════════
describe("PS-C · tracker List/Calendar toggle · month navigation", () => {
  it("advancing to March hides February events + shows March overlay", async () => {
    _seedRows([{
      id: "trk-feb", customer_name: "Alice",
      interval_months: 6, due_at: "2026-02-15",
      status_computed: "current", property_address: "1 Pool Ln",
    }]);
    render(<EquipmentTrackerListPage trackerType="filter" />);
    await waitFor(() => expect(_getSpy).toHaveBeenCalled());
    await act(async () => {
      fireEvent.click(screen.getByTestId("tracker-view-calendar"));
    });

    // Feb → March.
    await act(async () => {
      fireEvent.click(screen.getByTestId("tracker-calendar-next-month"));
    });
    expect(screen.getByTestId("tracker-calendar-month-label")
      .textContent).toMatch(/March 2026/);
    // Feb day cell is gone from the DOM (grid is March-anchored now).
    expect(screen.queryByTestId("tracker-calendar-day-2026-02-15"))
      .toBeNull();
    // Empty overlay for March (the Feb event doesn't cross over).
    expect(screen.getByTestId("tracker-calendar-empty-filter"))
      .toBeInTheDocument();

    // "Today" button jumps back to Feb.
    await act(async () => {
      fireEvent.click(screen.getByTestId("tracker-calendar-today-btn"));
    });
    expect(screen.getByTestId("tracker-calendar-month-label")
      .textContent).toMatch(/February 2026/);
    expect(screen.getByTestId("tracker-calendar-day-2026-02-15"))
      .toBeInTheDocument();
  });
});
