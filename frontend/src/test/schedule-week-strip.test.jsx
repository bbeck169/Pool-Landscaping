/**
 * Feb-2026 · Schedule-UI · WeekStrip vitest.
 *
 * Covers the 7-day toggle strip that lives at the top of the
 * ``/schedule`` page:
 *
 *   • Renders MON–SUN of the selected week + numbers 1–31.
 *   • ``selectedDate`` (or "today" as fallback) is drawn in the
 *     filled highlight circle.
 *   • "Today" always shows a subtle dot below its number so users
 *     don't get lost when navigating other weeks.
 *   • Left / right chevrons shift the visible week by ±7 days.
 *   • Clicking a day fires ``onSelectDate(iso)`` with the correct
 *     yyyy-mm-dd ISO string.
 *   • Auto-selects today on mount when the parent did not seed a
 *     ``selectedDate``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import WeekStrip from "@/components/schedule/WeekStrip";


// Pin the clock to Wednesday, 2026-02-11 so the Monday-anchored week
// resolves to 09..15 across all timezones the CI happens to run in.
const _FIXED = new Date(2026, 1, 11, 12, 0, 0);
beforeEach(() => { vi.useFakeTimers().setSystemTime(_FIXED); });
afterEach(() => { vi.useRealTimers(); cleanup(); });


describe("WeekStrip · rendering", () => {
  it("renders MON-SUN with the correct date numbers", () => {
    render(<WeekStrip selectedDate="2026-02-11" onSelectDate={() => {}} />);
    // Container present + day tabs are exactly 7.
    expect(screen.getByTestId("schedule-week-strip")).toBeInTheDocument();
    const tabs = screen
      .getByTestId("week-strip-days")
      .querySelectorAll('[data-testid^="week-strip-day-"]');
    expect(tabs).toHaveLength(7);
    // Monday 2026-02-09 through Sunday 2026-02-15.
    for (const iso of [
      "2026-02-09", "2026-02-10", "2026-02-11", "2026-02-12",
      "2026-02-13", "2026-02-14", "2026-02-15",
    ]) {
      expect(screen.getByTestId(`week-strip-day-${iso}`)).toBeInTheDocument();
    }
    // Text labels.
    expect(screen.getAllByText("MON")).not.toHaveLength(0);
    expect(screen.getAllByText("SUN")).not.toHaveLength(0);
  });

  it("marks today with the today-dot AND today's tab as data-today=true", () => {
    render(<WeekStrip selectedDate="2026-02-11" onSelectDate={() => {}} />);
    const todayTab = screen.getByTestId("week-strip-day-2026-02-11");
    expect(todayTab.getAttribute("data-today")).toBe("true");
    // Since today IS the selected date the dot is hidden — swap the
    // selection to another day to expose the dot.
    cleanup();
    render(<WeekStrip selectedDate="2026-02-13" onSelectDate={() => {}} />);
    expect(screen.getByTestId("week-strip-today-dot-2026-02-11"))
      .toBeInTheDocument();
    // Selected tab (Fri 2026-02-13) is marked accordingly.
    const selected = screen.getByTestId("week-strip-day-2026-02-13");
    expect(selected.getAttribute("data-selected")).toBe("true");
  });
});


describe("WeekStrip · navigation", () => {
  it("left chevron shifts the visible week by -7 days", () => {
    render(<WeekStrip selectedDate="2026-02-11" onSelectDate={() => {}} />);
    fireEvent.click(screen.getByTestId("week-strip-prev"));
    // After -7d anchor becomes 2026-02-02 (Mon) → 2026-02-08 (Sun).
    expect(screen.getByTestId("week-strip-day-2026-02-02")).toBeInTheDocument();
    expect(screen.getByTestId("week-strip-day-2026-02-08")).toBeInTheDocument();
    // Original week is no longer in view.
    expect(screen.queryByTestId("week-strip-day-2026-02-15")).toBeNull();
  });

  it("right chevron shifts the visible week by +7 days", () => {
    render(<WeekStrip selectedDate="2026-02-11" onSelectDate={() => {}} />);
    fireEvent.click(screen.getByTestId("week-strip-next"));
    // +7d anchor becomes 2026-02-16 (Mon) → 2026-02-22 (Sun).
    expect(screen.getByTestId("week-strip-day-2026-02-16")).toBeInTheDocument();
    expect(screen.getByTestId("week-strip-day-2026-02-22")).toBeInTheDocument();
  });

  it("fires onSelectDate with the correct ISO string when a day is clicked", () => {
    const onSelect = vi.fn();
    render(<WeekStrip selectedDate="2026-02-11" onSelectDate={onSelect} />);
    fireEvent.click(screen.getByTestId("week-strip-day-2026-02-13"));
    expect(onSelect).toHaveBeenCalledWith("2026-02-13");
  });

  it("auto-selects today on mount when the parent did not seed a date", () => {
    const onSelect = vi.fn();
    render(<WeekStrip onSelectDate={onSelect} />);
    expect(onSelect).toHaveBeenCalledWith("2026-02-11");
  });

  it("re-anchors when selectedDate jumps into a different week", () => {
    const { rerender } = render(
      <WeekStrip selectedDate="2026-02-11" onSelectDate={() => {}} />);
    // Sanity — current week visible.
    expect(screen.getByTestId("week-strip-day-2026-02-15")).toBeInTheDocument();
    // Parent updates selectedDate to a date 3 weeks later.
    rerender(<WeekStrip selectedDate="2026-03-04" onSelectDate={() => {}} />);
    // Strip should show the week of Mar 02-08 (Wednesday 04 is the sel).
    expect(screen.getByTestId("week-strip-day-2026-03-02")).toBeInTheDocument();
    expect(screen.getByTestId("week-strip-day-2026-03-08")).toBeInTheDocument();
  });
});


// ─── 3. Per-day count badges ─────────────────────────────────────────
describe("WeekStrip · per-day count badges", () => {
  it("renders a badge on every day that has counts > 0", () => {
    const counts = {
      "2026-02-09": 2,
      "2026-02-11": 4,
      "2026-02-13": 1,
    };
    render(
      <WeekStrip selectedDate="2026-02-11" counts={counts}
                    onSelectDate={() => {}} />,
    );
    expect(screen.getByTestId("week-strip-count-2026-02-09"))
      .toHaveTextContent("2");
    expect(screen.getByTestId("week-strip-count-2026-02-11"))
      .toHaveTextContent("4");
    expect(screen.getByTestId("week-strip-count-2026-02-13"))
      .toHaveTextContent("1");
  });

  it("hides the badge entirely on zero-count days", () => {
    const counts = { "2026-02-11": 4 };   // only Wed has jobs
    render(
      <WeekStrip selectedDate="2026-02-11" counts={counts}
                    onSelectDate={() => {}} />,
    );
    // Wed shows.
    expect(screen.getByTestId("week-strip-count-2026-02-11"))
      .toBeInTheDocument();
    // Every other day in the week — no badge node.
    for (const iso of [
      "2026-02-09", "2026-02-10", "2026-02-12",
      "2026-02-13", "2026-02-14", "2026-02-15",
    ]) {
      expect(screen.queryByTestId(`week-strip-count-${iso}`)).toBeNull();
    }
  });

  it("also hides the badge when the day is explicitly 0 in the counts map", () => {
    const counts = { "2026-02-11": 0, "2026-02-13": 3 };
    render(
      <WeekStrip selectedDate="2026-02-11" counts={counts}
                    onSelectDate={() => {}} />,
    );
    expect(screen.queryByTestId("week-strip-count-2026-02-11")).toBeNull();
    expect(screen.getByTestId("week-strip-count-2026-02-13"))
      .toHaveTextContent("3");
  });

  it("renders no badges at all when counts prop is undefined (backwards compat)", () => {
    render(<WeekStrip selectedDate="2026-02-11" onSelectDate={() => {}} />);
    for (const iso of [
      "2026-02-09", "2026-02-10", "2026-02-11", "2026-02-12",
      "2026-02-13", "2026-02-14", "2026-02-15",
    ]) {
      expect(screen.queryByTestId(`week-strip-count-${iso}`)).toBeNull();
    }
  });
});
