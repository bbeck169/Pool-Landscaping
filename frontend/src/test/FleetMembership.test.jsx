/**
 * FLEET-A · Feb-2026 — FleetMembership page tests.
 *
 * Locks the membership manager's contract:
 *   1. Fetches ``/api/fleet/membership`` on mount and renders one
 *      row per technician.
 *   2. Toggle button flips the in/out state and POSTs to the API
 *      with the new value.
 *   3. Optimistic UI — the row shows the new state before the API
 *      resolves.
 *   4. API failure reverts the toggle and surfaces a toast.
 *   5. Search filters rows by name / email / role.
 *   6. Empty state renders when no rows match the filter.
 */
import React from "react";
import {
  render, screen, fireEvent, waitFor,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
  },
}));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

import FleetMembership from "@/pages/admin/FleetMembership";


function _fixture() {
  return {
    count: 2,
    items: [
      {
        tech_user_id: "u1", tech_name: "Alice Angler",
        email: "alice@aquaterra.com", role: "technician",
        in_fleet: true, notes: "primary rig",
        enabled_by_email: "admin@t1", enabled_at: "2026-02-01T00:00:00Z",
      },
      {
        tech_user_id: "u2", tech_name: "Bob Bailey",
        email: "bob@aquaterra.com", role: "technician",
        in_fleet: false, notes: null,
      },
    ],
  };
}


describe("FLEET-A · FleetMembership", () => {
  beforeEach(() => {
    _apiMock.get.mockReset();
    _apiMock.post.mockReset();
  });

  it("fetches /fleet/membership on mount and renders every tech row",
    async () => {
      _apiMock.get.mockResolvedValueOnce(_fixture());
      render(<FleetMembership />);
      await waitFor(() =>
        expect(_apiMock.get).toHaveBeenCalledWith("/fleet/membership")
      );
      expect(await screen.findByTestId("fleet-membership-row-u1"))
        .toBeInTheDocument();
      expect(screen.getByTestId("fleet-membership-row-u2"))
        .toBeInTheDocument();
      expect(screen.getByTestId("fleet-membership-toggle-u1"))
        .toHaveTextContent(/In Fleet/i);
      expect(screen.getByTestId("fleet-membership-toggle-u2"))
        .toHaveTextContent(/Out/i);
    });

  it("toggles in→out with an API POST and optimistic UI", async () => {
    _apiMock.get.mockResolvedValueOnce(_fixture());
    // POST resolves slowly enough that the optimistic UI can be
    // observed BEFORE the resolution.
    _apiMock.post.mockResolvedValueOnce({ ok: true });
    render(<FleetMembership />);
    const btn = await screen.findByTestId("fleet-membership-toggle-u1");
    expect(btn).toHaveTextContent(/In Fleet/i);
    fireEvent.click(btn);
    // Optimistic flip.
    expect(btn).toHaveTextContent(/Out/i);
    await waitFor(() =>
      expect(_apiMock.post).toHaveBeenCalledWith(
        "/fleet/membership/u1",
        expect.objectContaining({ in_fleet: false }),
      )
    );
  });

  it("toggles out→in with an API POST", async () => {
    _apiMock.get.mockResolvedValueOnce(_fixture());
    _apiMock.post.mockResolvedValueOnce({ ok: true });
    render(<FleetMembership />);
    const btn = await screen.findByTestId("fleet-membership-toggle-u2");
    expect(btn).toHaveTextContent(/Out/i);
    fireEvent.click(btn);
    expect(btn).toHaveTextContent(/In Fleet/i);
    await waitFor(() =>
      expect(_apiMock.post).toHaveBeenCalledWith(
        "/fleet/membership/u2",
        expect.objectContaining({ in_fleet: true }),
      )
    );
  });

  it("reverts the toggle and toasts when the API fails", async () => {
    const { toast } = await import("sonner");
    _apiMock.get.mockResolvedValueOnce(_fixture());
    _apiMock.post.mockRejectedValueOnce(new Error("boom"));
    render(<FleetMembership />);
    const btn = await screen.findByTestId("fleet-membership-toggle-u1");
    fireEvent.click(btn);
    await waitFor(() => {
      expect(btn).toHaveTextContent(/In Fleet/i);      // reverted
    });
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining("Toggle failed")
    );
  });

  it("filters rows by the search term", async () => {
    _apiMock.get.mockResolvedValueOnce(_fixture());
    render(<FleetMembership />);
    await screen.findByTestId("fleet-membership-row-u1");
    const search = screen.getByTestId("admin-fleet-membership-search");
    fireEvent.change(search, { target: { value: "bob" } });
    await waitFor(() => {
      expect(screen.queryByTestId("fleet-membership-row-u1")).toBeNull();
    });
    expect(screen.getByTestId("fleet-membership-row-u2"))
      .toBeInTheDocument();
  });

  it("shows empty state when nothing matches the filter", async () => {
    _apiMock.get.mockResolvedValueOnce(_fixture());
    render(<FleetMembership />);
    await screen.findByTestId("fleet-membership-row-u1");
    fireEvent.change(
      screen.getByTestId("admin-fleet-membership-search"),
      { target: { value: "nomatch" } }
    );
    expect(await screen.findByTestId("admin-fleet-membership-empty"))
      .toBeInTheDocument();
  });

  it("reload button re-invokes the fetch", async () => {
    _apiMock.get.mockResolvedValueOnce(_fixture());
    render(<FleetMembership />);
    await screen.findByTestId("fleet-membership-row-u1");
    expect(_apiMock.get).toHaveBeenCalledTimes(1);
    _apiMock.get.mockResolvedValueOnce(_fixture());
    fireEvent.click(screen.getByTestId("admin-fleet-membership-reload"));
    await waitFor(() =>
      expect(_apiMock.get).toHaveBeenCalledTimes(2)
    );
  });
});
