/**
 * RevenueForecastTile quick-view tabs · Feb-2026 tests.
 *
 * Covers:
 *   1. Tabs render (Today / Tomorrow / This Week).
 *   2. Clicking Today fires a second fetch with today's date range.
 *   3. Selected tab is visually highlighted (aria-pressed=true).
 *   4. Second fetch result renders as a small stat under the hero.
 *   5. Clicking the active tab again deselects.
 *   6. The tab click does NOT re-fire the hero fetch — shared range untouched.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";

// ── Mock the api module (must come before component import). ──
const getMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...args) => getMock(...args) },
}));

// ── Stub out theme + ui-kit so we don't need CSS vars in JSDOM. ──
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", border: "#eee", muted: "#666",
    onSurface: "#000", surfaceSecondary: "#fafafa",
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));
vi.mock("@/components/ui-kit", () => ({
  Skeleton: ({ children, ...p }) => <div {...p}>{children}</div>,
}));

import RevenueForecastTile from "@/components/dashboard/RevenueForecastTile";

// ── Fixed clock so today/tomorrow/week ranges are deterministic. ──
// We only check that a same-day fetch has start === end; we do NOT
// pin the exact date because vi.useFakeTimers breaks React's
// waitFor microtask queue.

beforeEach(() => {
  getMock.mockReset();
  // Default hero fetch response — used for the initial mount.
  getMock.mockResolvedValue({
    combined_total: 12345,
    booked: { amount: 8000, job_count: 3 },
    recurring: { amount: 4345, subscription_count: 2, cycle_count: 6 },
  });
});

afterEach(() => {
  cleanup();
});

const heroRange = { start: "2026-02-01", end: "2026-02-28" };

describe("RevenueForecastTile quick-view tabs", () => {
  it("renders three pill-tabs (Today / Tomorrow / This Week)", async () => {
    render(<RevenueForecastTile range={heroRange} />);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-forecast-combined"))
        .toBeInTheDocument();
    });
    expect(screen.getByTestId("revenue-forecast-tab-today")).toBeInTheDocument();
    expect(screen.getByTestId("revenue-forecast-tab-tomorrow"))
      .toBeInTheDocument();
    expect(screen.getByTestId("revenue-forecast-tab-week")).toBeInTheDocument();
  });

  // Feb-2026 — Next Week quick-view tab is present and sits between
  // "This Week" and "This Month" in render order (narrow→wide pill flow).
  it("renders a Next Week tab between This Week and This Month", async () => {
    render(<RevenueForecastTile range={heroRange} />);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-forecast-combined"))
        .toBeInTheDocument();
    });
    const next = screen.getByTestId("revenue-forecast-tab-next_week");
    expect(next).toBeInTheDocument();
    expect(next.textContent).toMatch(/Next Week/i);
    // Order: week → next_week → this_month.
    const quick = screen.getByTestId("revenue-forecast-quick-view");
    const buttons = Array.from(quick.querySelectorAll("button"))
      .map((b) => b.getAttribute("data-testid"));
    const iWeek = buttons.indexOf("revenue-forecast-tab-week");
    const iNextWeek = buttons.indexOf("revenue-forecast-tab-next_week");
    const iThisMonth = buttons.indexOf("revenue-forecast-tab-this_month");
    expect(iWeek).toBeGreaterThan(-1);
    expect(iNextWeek).toBe(iWeek + 1);
    expect(iThisMonth).toBe(iNextWeek + 1);
  });

  // Feb-2026 — clicking Next Week fires a tab-local fetch covering a
  // 7-day window one week ahead (start < end, exactly 6 days apart).
  it("clicking Next Week fires a fetch covering a 7-day forward window", async () => {
    render(<RevenueForecastTile range={heroRange} />);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-forecast-combined"))
        .toBeInTheDocument();
    });
    getMock.mockResolvedValueOnce({
      combined_total: 999,
      booked: { amount: 999, job_count: 2 },
      recurring: { amount: 0, subscription_count: 0, cycle_count: 0 },
    });
    fireEvent.click(screen.getByTestId("revenue-forecast-tab-next_week"));
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledTimes(2);
    });
    const secondCall = getMock.mock.calls[1][0];
    const m = secondCall.match(/start=([^&]+)&end=([^&]+)/);
    expect(m).not.toBeNull();
    const [, start, end] = m;
    // Window spans 6 inclusive days (Sun..Sat → 6-day delta).
    const sMs = new Date(`${start}T00:00:00`).getTime();
    const eMs = new Date(`${end}T00:00:00`).getTime();
    const dayMs = 24 * 60 * 60 * 1000;
    expect(Math.round((eMs - sMs) / dayMs)).toBe(6);
    // Window is strictly in the future vs today (start > today).
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    expect(sMs).toBeGreaterThan(today.getTime());
    // Rendered stat uses the Next Week label.
    await waitFor(() => {
      const stat = screen.getByTestId("revenue-forecast-tab-value");
      expect(stat.textContent).toMatch(/Next Week/i);
      expect(stat.textContent).toMatch(/\$999/);
    });
  });

  it("clicking Today fires a second fetch with today's date range", async () => {
    render(<RevenueForecastTile range={heroRange} />);
    // Wait for hero to settle.
    await waitFor(() => {
      expect(screen.getByTestId("revenue-forecast-combined"))
        .toBeInTheDocument();
    });
    // Prep a distinct response for the tab call.
    getMock.mockResolvedValueOnce({
      combined_total: 555,
      booked: { amount: 555, job_count: 1 },
      recurring: { amount: 0, subscription_count: 0, cycle_count: 0 },
    });
    fireEvent.click(screen.getByTestId("revenue-forecast-tab-today"));
    await waitFor(() => {
      // Two calls total: initial hero + tab click.
      expect(getMock).toHaveBeenCalledTimes(2);
    });
    // The 2nd call points at /admin/dashboard/revenue-forecast with
    // start === end === today's local ISO date.
    const secondCall = getMock.mock.calls[1][0];
    expect(secondCall).toMatch(/\/admin\/dashboard\/revenue-forecast\?start=\d{4}-\d{2}-\d{2}&end=\d{4}-\d{2}-\d{2}/);
    // Same-day today range → start === end.
    const m = secondCall.match(/start=([^&]+)&end=([^&]+)/);
    expect(m[1]).toBe(m[2]);
  });

  it("selected tab is highlighted via aria-pressed=true", async () => {
    render(<RevenueForecastTile range={heroRange} />);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-forecast-combined"))
        .toBeInTheDocument();
    });
    getMock.mockResolvedValueOnce({
      combined_total: 100,
      booked: { amount: 100, job_count: 1 },
      recurring: { amount: 0, subscription_count: 0, cycle_count: 0 },
    });
    const btn = screen.getByTestId("revenue-forecast-tab-tomorrow");
    expect(btn).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(btn);
    await waitFor(() => {
      expect(btn).toHaveAttribute("aria-pressed", "true");
    });
  });

  it("second fetch result renders as a small stat under hero", async () => {
    render(<RevenueForecastTile range={heroRange} />);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-forecast-combined"))
        .toBeInTheDocument();
    });
    getMock.mockResolvedValueOnce({
      combined_total: 777,
      booked: { amount: 777, job_count: 1 },
      recurring: { amount: 0, subscription_count: 0, cycle_count: 0 },
    });
    fireEvent.click(screen.getByTestId("revenue-forecast-tab-week"));
    await waitFor(() => {
      const stat = screen.getByTestId("revenue-forecast-tab-value");
      expect(stat.textContent).toMatch(/This Week/i);
      expect(stat.textContent).toMatch(/\$777/);
    });
  });

  it("clicking the active tab again deselects it (aria-pressed → false)", async () => {
    render(<RevenueForecastTile range={heroRange} />);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-forecast-combined"))
        .toBeInTheDocument();
    });
    getMock.mockResolvedValueOnce({
      combined_total: 1, booked: { amount: 1, job_count: 1 },
      recurring: { amount: 0, subscription_count: 0, cycle_count: 0 },
    });
    const btn = screen.getByTestId("revenue-forecast-tab-today");
    fireEvent.click(btn);
    await waitFor(() => {
      expect(btn).toHaveAttribute("aria-pressed", "true");
    });
    fireEvent.click(btn);
    await waitFor(() => {
      expect(btn).toHaveAttribute("aria-pressed", "false");
    });
    // After deselect, the tab-value stat is gone.
    expect(screen.queryByTestId("revenue-forecast-tab-value"))
      .not.toBeInTheDocument();
  });

  it("tab click does NOT re-fire the hero fetch (shared range untouched)", async () => {
    render(<RevenueForecastTile range={heroRange} />);
    await waitFor(() => {
      expect(screen.getByTestId("revenue-forecast-combined"))
        .toBeInTheDocument();
    });
    // Initial hero fetch.
    expect(getMock).toHaveBeenCalledTimes(1);
    expect(getMock.mock.calls[0][0])
      .toContain(`start=${heroRange.start}&end=${heroRange.end}`);
    getMock.mockResolvedValueOnce({
      combined_total: 42, booked: { amount: 42, job_count: 1 },
      recurring: { amount: 0, subscription_count: 0, cycle_count: 0 },
    });
    fireEvent.click(screen.getByTestId("revenue-forecast-tab-today"));
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledTimes(2);
    });
    // Hero URL (index 0) is unchanged.
    expect(getMock.mock.calls[0][0])
      .toContain(`start=${heroRange.start}&end=${heroRange.end}`);
  });
});
