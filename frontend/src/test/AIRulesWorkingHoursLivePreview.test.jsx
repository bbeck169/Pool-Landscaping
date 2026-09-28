/**
 * MTH-D · Feb-2026 — WorkingHoursCard live preview.
 *
 * Locks:
 *   1. Debounced fetch fires on mount + on edit.
 *   2. Server-summary text replaces the client-computed strip
 *      when the fetch succeeds.
 *   3. Timezone edit → new fetch.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(), success: vi.fn(),
    info: vi.fn(), warning: vi.fn(),
  },
}));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: { post: vi.fn(), put: vi.fn(), get: vi.fn() },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

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

import WorkingHoursCard from "@/components/ai-rules/WorkingHoursCard";

const VALUE = {
  enabled: true,
  timezone: "America/Los_Angeles",
  windows: [{ day: "mon", start: "08:00", end: "17:00" }],
};

describe("MTH-D · WorkingHoursCard live preview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.post.mockResolvedValue({
      preview_kind: "working_hours_status",
      output: {
        inside_window: true,
        current_window: { day: "mon", start: "08:00", end: "17:00" },
        next_window_start: null,
        timezone_used: "America/Los_Angeles",
        summary: "Inside window (08:00–17:00 mon, America/Los_Angeles).",
        enabled: true,
      },
      warnings: [],
    });
  });

  it("debounced fetch fires after 500ms and updates summary", async () => {
    vi.useFakeTimers();
    render(
      <WorkingHoursCard
        value={VALUE}
        overrideMap={{}}
        platformValue={VALUE}
      />,
    );
    // Advance debounce window.
    await vi.advanceTimersByTimeAsync(600);
    vi.useRealTimers();
    await waitFor(() => {
      expect(_apiMock.post).toHaveBeenCalledWith(
        "/tenant-ai-rules/preview",
        expect.objectContaining({
          category: "working_hours",
          preview_kind: "working_hours_status",
        }),
      );
    });
    await waitFor(() =>
      expect(
        screen.getByTestId("ai-rules-working-hours-preview-summary")
          .textContent,
      ).toMatch(/Inside window/),
    );
  });

  it("timezone edit triggers a fresh preview fetch", async () => {
    vi.useFakeTimers();
    render(
      <WorkingHoursCard value={VALUE} overrideMap={{}} platformValue={VALUE} />,
    );
    await vi.advanceTimersByTimeAsync(600);
    _apiMock.post.mockClear();
    fireEvent.change(
      screen.getByTestId("ai-rules-working-hours-timezone"),
      { target: { value: "America/New_York" } },
    );
    await vi.advanceTimersByTimeAsync(600);
    vi.useRealTimers();
    await waitFor(() =>
      expect(_apiMock.post).toHaveBeenCalledWith(
        "/tenant-ai-rules/preview",
        expect.objectContaining({
          pending_value: expect.objectContaining({
            timezone: "America/New_York",
          }),
        }),
      ),
    );
  });

  it("probe datetime input threads into preview_input", async () => {
    vi.useFakeTimers();
    render(
      <WorkingHoursCard value={VALUE} overrideMap={{}} platformValue={VALUE} />,
    );
    await vi.advanceTimersByTimeAsync(600);
    _apiMock.post.mockClear();
    fireEvent.change(
      screen.getByTestId("ai-rules-working-hours-preview-probe"),
      { target: { value: "2026-02-15T09:00" } },
    );
    await vi.advanceTimersByTimeAsync(600);
    vi.useRealTimers();
    await waitFor(() =>
      expect(_apiMock.post).toHaveBeenCalledWith(
        "/tenant-ai-rules/preview",
        expect.objectContaining({
          preview_input: expect.objectContaining({
            probe_datetime: "2026-02-15T09:00",
          }),
        }),
      ),
    );
  });
});
