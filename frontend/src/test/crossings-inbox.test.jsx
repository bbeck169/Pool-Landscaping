// Phase G5a · Feb-2026 — Crossings Inbox page (Vitest).
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _events = {
  items: [
    { id: "e1", geofence_id: "g1", geofence_name: "Depot",
      user_id: "u1", user_name: "Ana Tech",
      crossing: "enter",
      detected_at: "2026-02-14T09:00:00Z",
      lat: 33.5, lon: -112.0, acknowledged: false },
    { id: "e2", geofence_id: "g2", geofence_name: "No-go Zone",
      user_id: "u2", user_name: "Ben Tech",
      crossing: "exit",
      detected_at: "2026-02-14T09:01:00Z",
      lat: 33.6, lon: -112.1, acknowledged: false },
    { id: "e3", geofence_id: "g1", geofence_name: "Depot",
      user_id: "u1", user_name: "Ana Tech",
      crossing: "enter",
      detected_at: "2026-02-14T09:02:00Z",
      lat: 33.5, lon: -112.0, acknowledged: true },
  ],
  total: 3,
};

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async () => _events),
    post: vi.fn(async () => ({ ok: true })),
    patch: vi.fn(), del: vi.fn(),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import CrossingsInbox from "@/pages/admin/CrossingsInbox";
import { api } from "@/api";

describe("CrossingsInbox · G5a", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders the crossing rows and column badges", async () => {
    render(<MemoryRouter><CrossingsInbox /></MemoryRouter>);
    expect(await screen.findByTestId("crossings-inbox-title"))
      .toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("crossings-inbox-row-e1")).toBeInTheDocument();
      expect(screen.getByTestId("crossings-inbox-row-e2")).toBeInTheDocument();
    });
    expect(screen.getByTestId("crossings-inbox-crossing-e1"))
      .toHaveTextContent(/enter/i);
    expect(screen.getByTestId("crossings-inbox-crossing-e2"))
      .toHaveTextContent(/exit/i);
  });

  it("acknowledge button POSTs and reloads", async () => {
    render(<MemoryRouter><CrossingsInbox /></MemoryRouter>);
    const btn = await screen.findByTestId("crossings-inbox-ack-btn-e1");
    fireEvent.click(btn);
    await waitFor(() => {
      const calls = api.post.mock.calls
        .filter((c) => c[0] === "/geofence-events/e1/acknowledge");
      expect(calls.length).toBe(1);
    });
  });

  it("acknowledged rows show label instead of action", async () => {
    render(<MemoryRouter><CrossingsInbox /></MemoryRouter>);
    await waitFor(() => {
      expect(screen.getByTestId("crossings-inbox-ack-e3"))
        .toBeInTheDocument();
    });
    expect(screen.queryByTestId("crossings-inbox-ack-btn-e3"))
      .not.toBeInTheDocument();
  });

  it("filter change refetches with query params", async () => {
    render(<MemoryRouter><CrossingsInbox /></MemoryRouter>);
    await screen.findByTestId("crossings-inbox-title");
    const filter = await screen.findByTestId("crossings-inbox-filter-crossing");
    fireEvent.change(filter, { target: { value: "exit" } });
    await waitFor(() => {
      const calls = api.get.mock.calls.map((c) => c[0]);
      expect(calls.some((p) => p.includes("crossing=exit"))).toBe(true);
    });
  });
});
