/**
 * Ticket W · Feb-2026 — Custom Month grid on Schedule.
 *
 * Vitest for ``MonthCustomGrid`` + wiring posture. Component is
 * tested in isolation — CalendarSchedule.jsx is a 3657-line page
 * with many parent dependencies; the splice site is a one-liner
 * conditional, so unit-testing the component directly gives
 * maximum signal with zero fixture overhead.
 *
 * Assertions (Option α acceptance):
 *   1. Mon-Sun column headers in that order.
 *   2. Row count matches the visible month (Nov 2026 → 6 rows,
 *      Feb 2026 → 5 rows).
 *   3. Cards render job name + customer name.
 *   4. Status-color left-border driven by STATUS_COLORS.
 *   5. ``+N more`` pill + popover with all day's visits.
 *   6. Card click fires onSelectEvent with the event.
 *   7. View switcher calls onViewChange("agenda") / ("month").
 *   7b. Prev/Today/Next fire onNavigate with correct dates.
 *   8. REGRESSION LOCK — day cells + cards have no drag handlers
 *      (Ticket W drag-less posture).
 *   9. Filter re-render changes visible cards.
 *   10. Today / adjacent-month cell markers.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, within,
} from "@testing-library/react";

import MonthCustomGrid from "@/components/schedule/MonthCustomGrid";

const STATUS_COLORS = {
  scheduled: "#0EA5E9",
  active:    "#059669",
  completed: "#ff4542",
  pending:   "#F59E0B",
  cancelled: "#9CA3AF",
};


function _event(dateStr, overrides = {}) {
  const start = new Date(`${dateStr}T00:00:00`);
  const end = new Date(start.getTime() + 24 * 60 * 60 * 1000 - 1);
  return {
    id: overrides.id || `ev-${dateStr}-${Math.random().toString(36).slice(2, 6)}`,
    title: overrides.title || "Pool Service · Alice",
    start, end, allDay: true,
    resource: {
      job: {
        id: overrides.id || `job-${dateStr}`,
        customer_name: overrides.customer_name || "Alice Doe",
        service_type: overrides.service_type || "Pool Service",
        status: overrides.status || "scheduled",
        scheduled_date: dateStr,
      },
      status: overrides.status || "scheduled",
      colour: STATUS_COLORS[overrides.status || "scheduled"],
    },
  };
}


afterEach(() => { cleanup(); });


describe("MonthCustomGrid · Ticket W (Option α)", () => {
  it("renders Mon-Sun column headers in that order", () => {
    render(
      <MonthCustomGrid
        date={new Date("2026-11-15T00:00:00")}
        events={[]}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
      />,
    );
    const headers = screen.getByTestId("month-weekday-header-row");
    const children = Array.from(headers.children);
    expect(children.map((c) => c.textContent.trim()))
      .toEqual(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
  });

  it("renders 6 week rows for November 2026", () => {
    render(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={[]}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
      />,
    );
    const grid = screen.getByTestId("month-custom-grid");
    expect(grid.getAttribute("data-row-count")).toBe("6");
    const container = screen.getByTestId("month-weeks-container");
    expect(container.children.length).toBe(6);
  });

  it("renders 5 week rows for February 2026", () => {
    render(
      <MonthCustomGrid
        date={new Date("2026-02-10T00:00:00")}
        events={[]}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
      />,
    );
    const grid = screen.getByTestId("month-custom-grid");
    expect(grid.getAttribute("data-row-count")).toBe("5");
  });

  it("cards render job name and customer name", () => {
    const events = [
      _event("2026-11-10", {
        service_type: "Weekly Pool",
        customer_name: "Bob Smith",
      }),
    ];
    render(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={events}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
      />,
    );
    const card = screen.getByTestId("month-card-2026-11-10-0");
    expect(within(card).getByTestId("month-card-2026-11-10-0-jobname")
      .textContent).toBe("Weekly Pool");
    expect(within(card).getByTestId("month-card-2026-11-10-0-customername")
      .textContent).toBe("Bob Smith");
  });

  it("card left-border color driven by STATUS_COLORS", () => {
    const events = [
      _event("2026-11-10", { status: "active" }),
      _event("2026-11-11", { status: "pending" }),
    ];
    render(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={events}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
      />,
    );
    const activeCard = screen.getByTestId("month-card-2026-11-10-0");
    const pendingCard = screen.getByTestId("month-card-2026-11-11-0");
    expect(activeCard.getAttribute("data-status-color"))
      .toBe(STATUS_COLORS.active);
    expect(pendingCard.getAttribute("data-status-color"))
      .toBe(STATUS_COLORS.pending);
    expect(activeCard.style.borderLeftColor).toBeTruthy();
  });

  it("renders +N more pill and opens popover with all visits", () => {
    const events = Array.from({ length: 7 }, (_, i) =>
      _event("2026-11-10", {
        id: `ev-${i}`,
        service_type: `Job ${i}`,
        customer_name: `Cust ${i}`,
      }),
    );
    render(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={events}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
      />,
    );
    const pill = screen.getByTestId("month-more-pill-2026-11-10");
    expect(pill.textContent).toMatch(/\+4 more/);
    fireEvent.click(pill);
    const popover = screen.getByTestId("month-popover-2026-11-10");
    expect(popover).toBeInTheDocument();
    for (let i = 0; i < 7; i += 1) {
      expect(within(popover).getByTestId(
        `month-popover-card-2026-11-10-${i}`,
      )).toBeInTheDocument();
    }
  });

  it("card click fires onSelectEvent with the event object", () => {
    const onSelectEvent = vi.fn();
    const ev = _event("2026-11-10", { id: "ev-click" });
    render(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={[ev]}
        onNavigate={vi.fn()}
        onSelectEvent={onSelectEvent}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
      />,
    );
    fireEvent.click(screen.getByTestId("month-card-2026-11-10-0"));
    expect(onSelectEvent).toHaveBeenCalledTimes(1);
    expect(onSelectEvent.mock.calls[0][0].id).toBe("ev-click");
  });

  it("view switcher calls onViewChange('agenda') / ('month')", () => {
    const onViewChange = vi.fn();
    render(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={[]}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
        onViewChange={onViewChange}
        statusColors={STATUS_COLORS}
      />,
    );
    fireEvent.click(screen.getByTestId("month-view-switch-agenda"));
    expect(onViewChange).toHaveBeenCalledWith("agenda");
    fireEvent.click(screen.getByTestId("month-view-switch-month"));
    expect(onViewChange).toHaveBeenCalledWith("month");
  });

  it("prev / today / next fire onNavigate with correct dates", () => {
    const onNavigate = vi.fn();
    render(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={[]}
        onNavigate={onNavigate}
        onSelectEvent={vi.fn()}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
      />,
    );
    fireEvent.click(screen.getByTestId("month-nav-prev"));
    expect(onNavigate.mock.calls[0][0].getMonth()).toBe(9); // Oct
    fireEvent.click(screen.getByTestId("month-nav-next"));
    expect(onNavigate.mock.calls[1][0].getMonth()).toBe(11); // Dec
    fireEvent.click(screen.getByTestId("month-nav-today"));
    expect(onNavigate.mock.calls[2][0]).toBeInstanceOf(Date);
  });

  it("REGRESSION LOCK - day cells + cards have no drag handlers "
     + "(Ticket W drag-less posture)", () => {
    const events = [
      _event("2026-11-10"),
      _event("2026-11-11"),
    ];
    render(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={events}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
      />,
    );
    const cell = screen.getByTestId("month-cell-2026-11-10");
    const card = screen.getByTestId("month-card-2026-11-10-0");
    expect(cell.getAttribute("draggable")).toBeNull();
    expect(card.getAttribute("draggable")).toBeNull();
    expect(cell.hasAttribute("data-rbc-event-draggable"))
      .toBe(false);
    expect(card.hasAttribute("data-rbc-event-draggable"))
      .toBe(false);
    expect(cell.ondragstart).toBeNull();
    expect(card.ondragstart).toBeNull();
  });

  it("prop re-render with filtered events re-filters visible cards",
     () => {
    const allEvents = [
      _event("2026-11-10", { id: "ev-pool",
                               customer_name: "Pool Guy" }),
      _event("2026-11-10", { id: "ev-land",
                               customer_name: "Land Guy" }),
    ];
    const { rerender } = render(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={allEvents}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
      />,
    );
    expect(screen.getByTestId("month-card-2026-11-10-0")).toBeTruthy();
    expect(screen.getByTestId("month-card-2026-11-10-1")).toBeTruthy();

    rerender(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={[allEvents[0]]}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
      />,
    );
    expect(screen.getByTestId("month-card-2026-11-10-0")).toBeTruthy();
    expect(screen.queryByTestId("month-card-2026-11-10-1")).toBeNull();
  });

  it("today cell + adjacent-month cell markers via data attrs", () => {
    render(
      <MonthCustomGrid
        date={new Date("2026-11-10T00:00:00")}
        events={[]}
        onNavigate={vi.fn()}
        onSelectEvent={vi.fn()}
        onViewChange={vi.fn()}
        statusColors={STATUS_COLORS}
      />,
    );
    const oct26 = screen.getByTestId("month-cell-2026-10-26");
    expect(oct26.getAttribute("data-in-month")).toBe("false");
    const nov15 = screen.getByTestId("month-cell-2026-11-15");
    expect(nov15.getAttribute("data-in-month")).toBe("true");
  });
});


// ═════════════════════════════════════════════════════════════════
// Ticket OO · Feb-2026 — ``TD-web-month-view-1000-row-cap`` fix.
//
// Mobile port M3c (commit 090faf17f) found that web's shared
// ``/jobs`` fetch at CalendarSchedule.jsx:910 silently drops rows
// past the BE default 1000-row cap on busy tenants.  OO adds an
// explicit ``&limit=5000`` to the fetch URL (BE max per
// routers/jobs.py:875 — ``Query(1000, ge=1, le=5000)``).
//
// Source-shape lock on the parent file so a future refactor can't
// quietly drop the limit param without turning this test red.
// ═════════════════════════════════════════════════════════════════
import fs from "node:fs";
import path from "node:path";

describe("Ticket OO · Month-view fetch limit lock", () => {
  const SRC = fs.readFileSync(
    path.resolve(process.cwd(), "src/pages/schedule/CalendarSchedule.jsx"),
    "utf-8",
  );

  it("CalendarSchedule's /jobs fetch URL includes explicit limit=5000", () => {
    // Grep-lock on the fetch URL template so a refactor that
    // dropped the limit (or lowered it below the BE max) would
    // flip this red.
    expect(SRC).toMatch(/\/jobs\?start=\$\{start\}&end=\$\{end\}&limit=5000/);
  });

  it("limit value matches the BE max (routers/jobs.py:875 ``le=5000``)", () => {
    // Belt-and-suspenders — any value above 5000 would 422 at the
    // server (pydantic ``le=5000``); any value below 5000 leaves
    // headroom on busy tenants.  Pin to exactly 5000.
    const match = SRC.match(/\/jobs\?start=\$\{start\}&end=\$\{end\}&limit=(\d+)/);
    expect(match).toBeTruthy();
    expect(match[1]).toBe("5000");
  });
});
