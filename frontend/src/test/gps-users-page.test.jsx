import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _summary = {
  as_of: "2026-02-14T09:00:00Z",
  tenant_enabled: true, hr_agreement_ack: true,
  counts: { total_technicians: 3, opted_in: 2, opted_out: 1,
             clocked_in_now: 1, sending_pings_now: 1 },
  technicians: [
    { user_id: "u1", user_name: "Ana Tech", role: "technician",
      opted_out: false, retention_override_days: null,
      clocked_in: true, last_ping_at: "2026-02-14T08:59:00Z",
      last_ping_seconds_ago: 60, note: null },
    { user_id: "u2", user_name: "Ben Tech", role: "technician",
      opted_out: true, retention_override_days: 14,
      clocked_in: false, last_ping_at: null,
      last_ping_seconds_ago: null, note: "on vacation" },
  ],
};

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async () => _summary),
    patch: vi.fn(async () => ({ updated: true })),
    post: vi.fn(), del: vi.fn(),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import GpsUsersPage from "@/pages/admin/GpsUsersPage";
import { api } from "@/api";

describe("GpsUsersPage · G4", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders summary counts and technician rows", async () => {
    render(<MemoryRouter><GpsUsersPage /></MemoryRouter>);
    expect(await screen.findByTestId("gps-users-title"))
      .toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("gps-summary-total"))
        .toHaveTextContent("3");
      expect(screen.getByTestId("gps-summary-opted-in"))
        .toHaveTextContent("2");
      expect(screen.getByTestId("gps-summary-opted-out"))
        .toHaveTextContent("1");
      expect(screen.getByTestId("gps-user-row-u1")).toBeInTheDocument();
      expect(screen.getByTestId("gps-user-row-u2")).toBeInTheDocument();
    });
  });

  it("edit drawer PATCHes opt-out on save", async () => {
    render(<MemoryRouter><GpsUsersPage /></MemoryRouter>);
    fireEvent.click(await screen.findByTestId("gps-user-edit-u1"));
    const toggle = await screen.findByTestId("gps-user-opt-out-toggle");
    fireEvent.click(toggle);
    fireEvent.click(screen.getByTestId("gps-user-save-btn"));
    await waitFor(() => {
      const calls = api.patch.mock.calls
        .filter((c) => c[0] === "/admin/gps/users/u1");
      expect(calls.length).toBe(1);
      expect(calls[0][1].gps_tracking_opt_out).toBe(true);
    });
  });

  it("retention override sent when provided", async () => {
    render(<MemoryRouter><GpsUsersPage /></MemoryRouter>);
    fireEvent.click(await screen.findByTestId("gps-user-edit-u2"));
    const input = await screen.findByTestId("gps-user-retention-input");
    fireEvent.change(input, { target: { value: "30" } });
    fireEvent.click(screen.getByTestId("gps-user-save-btn"));
    await waitFor(() => {
      const calls = api.patch.mock.calls
        .filter((c) => c[0] === "/admin/gps/users/u2");
      expect(calls.length).toBe(1);
      expect(calls[0][1].gps_retention_override_days).toBe(30);
    });
  });
});
