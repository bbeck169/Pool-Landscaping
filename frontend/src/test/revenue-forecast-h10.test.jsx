/**
 * Phase H10 · Feb-2026 — RevenueForecastTile: recurring_jobs
 * contribution + This Month / Next Month toggles.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

const getMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...args) => getMock(...args) },
}));
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


const SAMPLE = {
  combined_total: 5300,
  booked: { amount: 0, job_count: 4 },
  recurring: {
    amount: 5300, subscription_count: 0, cycle_count: 0,
    recurring_job_count: 45, recurring_job_amount: 5300,
    active_template_count: 11,
  },
};


const RANGE = { start: "2026-02-01", end: "2026-02-28" };


beforeEach(() => {
  getMock.mockReset();
  getMock.mockResolvedValue(SAMPLE);
});


describe("H10 · RevenueForecastTile toggles + recurring_jobs", () => {
  it("renders all 5 tabs (Today | Tomorrow | This Week | This Month | Next Month)",
     async () => {
    render(<RevenueForecastTile range={RANGE} />);
    await waitFor(() => expect(screen.getByTestId(
      "revenue-forecast-tile")).toBeInTheDocument());
    // The new H10 tabs.
    expect(screen.getByTestId("revenue-forecast-tab-today"))
      .toBeInTheDocument();
    expect(screen.getByTestId("revenue-forecast-tab-tomorrow"))
      .toBeInTheDocument();
    expect(screen.getByTestId("revenue-forecast-tab-week"))
      .toBeInTheDocument();
    expect(screen.getByTestId("revenue-forecast-tab-this_month"))
      .toBeInTheDocument();
    expect(screen.getByTestId("revenue-forecast-tab-next_month"))
      .toBeInTheDocument();
  });

  it("clicking This Month fires a fetch spanning the current month",
     async () => {
    render(<RevenueForecastTile range={RANGE} />);
    await waitFor(() => expect(screen.getByTestId(
      "revenue-forecast-tab-this_month")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId(
      "revenue-forecast-tab-this_month"));
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
    const url = getMock.mock.calls[1][0];
    expect(url).toMatch(/start=\d{4}-\d{2}-01/);
    expect(url).toMatch(/end=\d{4}-\d{2}-\d{2}/);
  });

  it("clicking Next Month fires a fetch spanning the following month",
     async () => {
    render(<RevenueForecastTile range={RANGE} />);
    await waitFor(() => expect(screen.getByTestId(
      "revenue-forecast-tab-next_month")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId(
      "revenue-forecast-tab-next_month"));
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
    const url = getMock.mock.calls[1][0];
    expect(url).toMatch(/start=\d{4}-\d{2}-01/);
    const now = new Date();
    const thisMonth = String(now.getMonth() + 1).padStart(2, "0");
    expect(url).not.toMatch(new RegExp(`start=\\d{4}-${thisMonth}-01`));
  });

  it("RECURRING pill shows non-zero when recurring_job_amount > 0",
     async () => {
    render(<RevenueForecastTile range={RANGE} />);
    await waitFor(() => expect(screen.getByTestId(
      "revenue-forecast-recurring")).toBeInTheDocument());
    const recurringPill = screen.getByTestId(
      "revenue-forecast-recurring");
    expect(recurringPill.textContent).toMatch(/\$5,?300\.00/);
  });

  it("footer copy includes 'N recurring jobs' when count > 0",
     async () => {
    render(<RevenueForecastTile range={RANGE} />);
    const caption = await screen.findByTestId(
      "revenue-forecast-caption");
    expect(caption.textContent).toMatch(/4 booked jobs/);
    expect(caption.textContent).toMatch(/45 recurring jobs/);
    expect(caption.textContent).toMatch(/0 active subscription/);
    expect(caption.textContent).toMatch(/0 billing cycles/);
  });

  it("hides the 'N recurring jobs' clause when count is zero",
     async () => {
    getMock.mockResolvedValue({
      combined_total: 187,
      booked: { amount: 187, job_count: 72 },
      recurring: {
        amount: 0, subscription_count: 0, cycle_count: 0,
        recurring_job_count: 0, recurring_job_amount: 0,
        active_template_count: 0,
      },
    });
    render(<RevenueForecastTile range={RANGE} />);
    const caption = await screen.findByTestId(
      "revenue-forecast-caption");
    expect(caption.textContent).not.toMatch(/recurring job/);
    expect(caption.textContent).toMatch(/72 booked jobs/);
    expect(caption.textContent).toMatch(/0 billing cycles/);
  });
});
