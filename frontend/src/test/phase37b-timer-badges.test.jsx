/**
 * Feb-2026 · P37b — Timer origin/termination badges.
 *
 * Show-only badges — verifies the field-driven contract so we never
 * synthesize a badge from client-side inference:
 *   1. ``timer_start_method="gps_arrival"`` → "Started HH:MM via GPS arrival".
 *   2. ``timer_start_method`` absent → no badge, no crash.
 *   3. ``timer_stop_method="service_report_submitted"`` → "Stopped via service report".
 *   4. ``timer_stop_method="job_completed"`` → "Stopped via job completion".
 *   5. Unknown ``timer_stop_method`` → no badge (fail-safe).
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import TimerBadges, {
  TimerStartBadge, TimerStopBadge,
} from "@/components/jobs/TimerBadges";


describe("TimerBadges · P37b", () => {
  it("renders the GPS-arrival start badge when timer_start_method matches", () => {
    render(<TimerStartBadge job={{
      id: "j-1",
      timer_started_at: "2026-06-15T14:14:00Z",
      timer_start_method: "gps_arrival",
    }} />);
    const badge = screen.getByTestId("timer-start-badge-j-1");
    expect(badge.textContent).toMatch(/via GPS arrival/);
    // Contains the HH:MM slice from the ISO input.
    expect(badge.textContent).toMatch(/\d{2}:\d{2}/);
  });

  it("renders NOTHING when timer_start_method is absent", () => {
    const { container } = render(
      <TimerStartBadge job={{ id: "j-2", timer_started_at: "2026-06-15T14:14:00Z" }} />
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("timer-start-badge-j-2")).toBeNull();
  });

  it("renders NOTHING when timer_start_method is a legacy/manual value", () => {
    const { container } = render(
      <TimerStartBadge job={{ id: "j-3", timer_started_at: "2026-06-15T14:14:00Z",
                                  timer_start_method: "manual" }} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the service-report-submitted stop badge", () => {
    render(<TimerStopBadge job={{ id: "j-4",
      timer_stop_method: "service_report_submitted",
    }} />);
    const badge = screen.getByTestId("timer-stop-badge-j-4");
    expect(badge.textContent).toMatch(/Stopped via service report/);
  });

  it("renders the job-completion stop badge", () => {
    render(<TimerStopBadge job={{ id: "j-5",
      timer_stop_method: "job_completed",
    }} />);
    const badge = screen.getByTestId("timer-stop-badge-j-5");
    expect(badge.textContent).toMatch(/Stopped via job completion/);
  });

  it("renders NOTHING for an unknown stop method (fail-safe)", () => {
    const { container } = render(
      <TimerStopBadge job={{ id: "j-6", timer_stop_method: "some_future_reason" }} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("composite <TimerBadges /> renders both start + stop when set", () => {
    render(<TimerBadges job={{
      id: "j-7",
      timer_started_at: "2026-06-15T14:14:00Z",
      timer_start_method: "gps_arrival",
      timer_stop_method: "service_report_submitted",
    }} />);
    expect(screen.getByTestId("timer-start-badge-j-7")).toBeTruthy();
    expect(screen.getByTestId("timer-stop-badge-j-7")).toBeTruthy();
  });

  it("composite <TimerBadges /> is safe with a null job", () => {
    const { container } = render(<TimerBadges job={null} />);
    expect(container.firstChild).toBeNull();
  });
});
