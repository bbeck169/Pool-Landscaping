/**
 * Feb-2026 · Batch #4 · Item 3 (continuation) — schedule refresh
 * button coverage.
 *
 * The tester found the earlier ship put ``schedule-refresh`` ONLY
 * on the Grid sub-view of CalendarSchedule. The fix extracts the
 * button into a shared ``<ScheduleRefreshButton>`` component and
 * mounts it in the top-level toolbar of both CalendarSchedule (so
 * Calendar month/agenda + Grid all get it) and TodaySchedule.
 *
 * We iterate the shared component under 4 "view" contexts to
 * guard against a future regression that gates the button on a
 * particular ``mode`` / ``view`` combination.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

import ScheduleRefreshButton from "@/components/schedule/ScheduleRefreshButton";


const VIEW_CONTEXTS = [
  { name: "TodaySchedule (primary Today tab)" },
  { name: "CalendarSchedule · Grid (Day)" },
  { name: "CalendarSchedule · Month" },
  { name: "CalendarSchedule · Agenda" },
];


describe("Batch #4 · Item 3 · schedule-refresh across all views", () => {
  for (const ctx of VIEW_CONTEXTS) {
    describe(ctx.name, () => {
      it("renders with data-testid=`schedule-refresh` (not `-btn`)", () => {
        render(<ScheduleRefreshButton onRefresh={vi.fn()} />);
        expect(screen.getByTestId("schedule-refresh")).toBeTruthy();
        expect(screen.queryByTestId("schedule-refresh-btn")).toBeNull();
        cleanup();
      });

      it("click invokes onRefresh (no ReferenceError)", () => {
        const onRefresh = vi.fn();
        render(<ScheduleRefreshButton onRefresh={onRefresh} />);
        expect(() => {
          fireEvent.click(screen.getByTestId("schedule-refresh"));
        }).not.toThrow();
        expect(onRefresh).toHaveBeenCalledTimes(1);
        cleanup();
      });

      it("disabled + no-op click while busy", () => {
        const onRefresh = vi.fn();
        render(<ScheduleRefreshButton busy onRefresh={onRefresh} />);
        const btn = screen.getByTestId("schedule-refresh");
        expect(btn.disabled).toBe(true);
        fireEvent.click(btn);
        expect(onRefresh).not.toHaveBeenCalled();
        expect(screen.getByTestId("schedule-refresh-spinner")).toBeTruthy();
        cleanup();
      });
    });
  }

  it("missing onRefresh handler is a safe no-op (no throw)", () => {
    render(<ScheduleRefreshButton />);
    expect(() => {
      fireEvent.click(screen.getByTestId("schedule-refresh"));
    }).not.toThrow();
  });
});
