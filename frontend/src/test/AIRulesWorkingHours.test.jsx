/**
 * MTH-B · Feb-2026 — Working Hours card tests.
 *
 * Locks:
 *   1. Timezone selector + 7 day rows render.
 *   2. "+ Add window" adds a new window under the day.
 *   3. Preview strip shows "inside window" vs "outside window"
 *      based on the tenant tz + windows against a fixed ``nowRef``.
 *   4. Save PUTs ``{enabled, timezone, windows}`` with reason.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: { put: vi.fn(), post: vi.fn(), get: vi.fn() },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

// TimezoneSelect makes a network call on mount — stub to a simple
// controlled select that just renders the current value.
vi.mock("@/components/settings/TimezoneSelect", () => ({
  TimezoneSelect: ({ value, onChange, testid }) => (
    <select
      data-testid={testid || "tenant-timezone-picker"}
      value={value}
      onChange={(e) => onChange && onChange(e.target.value)}
    >
      <option value="America/Los_Angeles">Pacific</option>
      <option value="America/New_York">Eastern</option>
    </select>
  ),
}));

import WorkingHoursCard, {
  isInsideWindow,
} from "@/components/ai-rules/WorkingHoursCard";

const VALUE = {
  enabled: true,
  timezone: "America/Los_Angeles",
  windows: [
    { day: "mon", start: "08:00", end: "17:00" },
    { day: "tue", start: "08:00", end: "17:00" },
  ],
};

describe("MTH-B · WorkingHoursCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.put.mockResolvedValue({ ok: true });
  });

  it("renders 7 day rows and the timezone picker", () => {
    render(
      <WorkingHoursCard
        value={VALUE}
        overrideMap={{}}
        platformValue={VALUE}
      />,
    );
    ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].forEach((d) => {
      expect(
        screen.getByTestId(`ai-rules-working-hours-day-${d}`),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("ai-rules-working-hours-timezone"),
    ).toBeInTheDocument();
  });

  it("+ Add window adds a new window under the day", () => {
    render(
      <WorkingHoursCard value={VALUE} overrideMap={{}} platformValue={VALUE} />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-working-hours-day-wed-add"));
    expect(
      screen.getByTestId("ai-rules-working-hours-day-wed-window-0"),
    ).toBeInTheDocument();
  });

  it("preview marks Mon 10:00 PT as inside window", () => {
    // Fixed date — Monday 2026-02-02 10:15 PT.
    const monday = new Date("2026-02-02T18:15:00Z"); // 10:15 PT (UTC-8 in Feb).
    render(
      <WorkingHoursCard
        value={VALUE}
        overrideMap={{}}
        platformValue={VALUE}
        nowRef={monday}
      />,
    );
    expect(
      screen.getByTestId("ai-rules-working-hours-preview-status").textContent,
    ).toMatch(/inside/);
  });

  it("preview marks Sunday as outside window (no windows on sun)", () => {
    const sunday = new Date("2026-02-01T18:15:00Z"); // 10:15 PT Sun.
    render(
      <WorkingHoursCard
        value={VALUE}
        overrideMap={{}}
        platformValue={VALUE}
        nowRef={sunday}
      />,
    );
    expect(
      screen.getByTestId("ai-rules-working-hours-preview-status").textContent,
    ).toMatch(/outside/);
  });

  it("save PUTs the current draft with reason", async () => {
    render(
      <WorkingHoursCard value={VALUE} overrideMap={{}} platformValue={VALUE} />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-working-hours-save"));
    fireEvent.change(
      screen.getByTestId("ai-rules-working-hours-save-reason-input"),
      { target: { value: "expanded coverage" } },
    );
    fireEvent.click(
      screen.getByTestId("ai-rules-working-hours-save-reason-confirm"),
    );
    await waitFor(() => {
      expect(_apiMock.put).toHaveBeenCalledWith(
        "/tenant-ai-rules/working_hours",
        expect.objectContaining({
          value: expect.objectContaining({
            enabled: true,
            timezone: "America/Los_Angeles",
          }),
          reason: "expanded coverage",
        }),
      );
    });
  });

  it("isInsideWindow pure helper — Mon 10:00 PT in Mon 08–17 window is inside", () => {
    const monday = new Date("2026-02-02T18:15:00Z");
    const res = isInsideWindow(monday, "America/Los_Angeles", [
      { day: "mon", start: "08:00", end: "17:00" },
    ]);
    expect(res.inside).toBe(true);
  });
});
