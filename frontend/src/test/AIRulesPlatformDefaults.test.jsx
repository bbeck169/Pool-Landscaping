/**
 * MTH-B · Feb-2026 — Platform Defaults tab tests.
 *
 * Locks:
 *   1. Non-super sees the "Requires super-admin" empty state; no
 *      /platform-ai-rules call.
 *   2. Super sees the platform tab, N-tenants banner with the fetched
 *      count, and mounts the reused category cards.
 *   3. Category card saves route to /platform-ai-rules/* (via
 *      the ``endpointPrefix`` prop).
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

vi.mock("@/components/settings/TimezoneSelect", () => ({
  TimezoneSelect: ({ value, testid }) => (
    <select data-testid={testid || "tenant-timezone-picker"} value={value} onChange={() => {}}>
      <option value={value}>{value}</option>
    </select>
  ),
}));

import PlatformDefaultsTab from "@/components/ai-rules/PlatformDefaultsTab";

const PLATFORM = {
  rules: {
    tone_voice: { style: "friendly", custom_directive: "" },
    auto_action_allowlist: { "marco.clock_in": "admin_approval" },
    employee_enable_disable: { marco_executive: true },
    working_hours: {
      enabled: true,
      timezone: "America/Los_Angeles",
      windows: [],
    },
    escalation_rules: [],
  },
  action_inventory: ["marco.clock_in"],
  employee_keys: ["marco_executive"],
  revision_number: 1,
};

describe("MTH-B · PlatformDefaultsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.get.mockImplementation((p) => {
      if (p === "/platform-ai-rules") return Promise.resolve(PLATFORM);
      if (p === "/tenants")
        return Promise.resolve([{ id: "a" }, { id: "b" }, { id: "c" }]);
      if (p === "/ai-employees") return Promise.resolve([]);
      return Promise.reject(new Error("not-mocked"));
    });
    _apiMock.put.mockResolvedValue({ ok: true });
  });

  it("non-super sees empty-state and does NOT fetch /platform-ai-rules", () => {
    render(<PlatformDefaultsTab isSuper={false} />);
    expect(
      screen.getByText(/requires super-admin/i),
    ).toBeInTheDocument();
    expect(_apiMock.get).not.toHaveBeenCalled();
  });

  it("super sees banner + tenant count + mounts category cards", async () => {
    render(<PlatformDefaultsTab isSuper />);
    await waitFor(() =>
      expect(
        screen.getByTestId("ai-rules-platform-defaults-banner"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("ai-rules-platform-defaults-tenant-count").textContent,
    ).toBe("3");
    expect(
      screen.getByTestId("ai-rules-tone-voice-card"),
    ).toBeInTheDocument();
  });

  it("tone_voice save routes to /platform-ai-rules/tone_voice", async () => {
    render(<PlatformDefaultsTab isSuper />);
    await waitFor(() =>
      expect(
        screen.getByTestId("ai-rules-tone-voice-card"),
      ).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("ai-rules-tone-voice-save"));
    fireEvent.change(
      screen.getByTestId("ai-rules-tone-voice-save-reason-input"),
      { target: { value: "platform bump" } },
    );
    fireEvent.click(
      screen.getByTestId("ai-rules-tone-voice-save-reason-confirm"),
    );
    await waitFor(() => {
      expect(_apiMock.put).toHaveBeenCalledWith(
        "/platform-ai-rules/tone_voice",
        expect.objectContaining({ reason: "platform bump" }),
      );
    });
  });

  it("reset button is hidden in platform tab (backend has no /reset)", async () => {
    render(<PlatformDefaultsTab isSuper />);
    await waitFor(() =>
      expect(
        screen.getByTestId("ai-rules-tone-voice-card"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("ai-rules-tone-voice-reset"),
    ).not.toBeInTheDocument();
  });
});
