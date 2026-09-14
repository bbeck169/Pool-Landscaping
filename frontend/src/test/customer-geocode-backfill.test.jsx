/**
 * Feb-2026 · Phase — Customer geocoding on save + one-time backfill.
 *
 * Cases:
 *   1. CustomersList admin toolbar has the backfill button + POSTs
 *      to /admin/customers/backfill-geocoding on click.
 *   2. Inline-response toast copy: "Backfill complete: N updated…"
 *   3. Enqueued-response toast copy: "Backfill running in
 *      background…"
 *   4. CustomerGeocodeInfo exposes the spec ``customer-location-
 *      display`` testid alongside the legacy handle.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const { getSpy, postSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: vi.fn(),
    del: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  }),
}));

vi.mock("@/theme", async (importOriginal) => {
  // Partial mock — pull the real theme in so any exported key we
  // don't override (``gradients``, ``spacing``, etc.) still
  // resolves. Only ``colors.background`` is overridden here to
  // pin a stable value in the smoke.
  const actual = await importOriginal();
  return { ...actual };
});


// ─── CustomerGeocodeInfo dual-testid smoke ────────────────────────

import CustomerGeocodeInfo from "@/components/customers/CustomerGeocodeInfo";

describe("CustomerGeocodeInfo · dual-testid convention", () => {
  it("exposes ``customer-location-display`` alongside the legacy testid", () => {
    render(<CustomerGeocodeInfo customer={{
      id: "c-1",
      latitude: 33.7801,
      longitude: -112.3428,
      geocoded_at: "2026-02-14T15:00:00Z",
    }} user={{ role: "admin" }} />);

    // Legacy testid still resolves.
    expect(screen.getByTestId("customer-geocode-coords")).toBeTruthy();
    // Spec testid (Feb-2026 phase — auto-geocode + backfill).
    expect(screen.getByTestId("customer-location-display")).toBeTruthy();
    // The visible copy still reads the 4-decimal coords per spec.
    expect(screen.getByTestId("customer-geocode-coords").textContent)
      .toMatch(/33\.7801.*-112\.3428/);
  });
});


// ─── CustomersList backfill button + toast branches ───────────────

import CustomersList from "@/pages/customers/CustomersList";
import { toast } from "sonner";

describe("CustomersList · Backfill missing GPS button", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSpy.mockImplementation((path) => {
      if (path === "/auth/me") {
        return Promise.resolve({ id: "u", role: "super_admin" });
      }
      if (path.startsWith("/customers")) {
        return Promise.resolve({ items: [], total: 0 });
      }
      if (path.startsWith("/customer-tags")) {
        return Promise.resolve({ items: [] });
      }
      return Promise.resolve({ items: [] });
    });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("renders the button for admin users and fires POST on click", async () => {
    render(<MemoryRouter><CustomersList /></MemoryRouter>);
    // The button carries the spec testid.
    const btn = await screen.findByTestId(
      "admin-customers-backfill-geocoding-btn");
    expect(btn).toBeTruthy();
    postSpy.mockResolvedValueOnce({
      enqueued: false, scanned: 5, updated: 4, failed: 1,
      skipped_no_address: 0,
    });
    fireEvent.click(btn);
    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        "/admin/customers/backfill-geocoding", {});
    });
    // Inline-response toast copy.
    await waitFor(() => {
      const calls = toast.success.mock.calls.map((c) => c[0]);
      expect(calls.find((c) =>
        /Backfill complete: 4 customers updated, 1 failed, 0 skipped/
          .test(c))).toBeTruthy();
    });
  });

  it("shows the enqueued-response toast when the backend hands off to background", async () => {
    render(<MemoryRouter><CustomersList /></MemoryRouter>);
    const btn = await screen.findByTestId(
      "admin-customers-backfill-geocoding-btn");
    postSpy.mockResolvedValueOnce({
      enqueued: true, queue_size: 47, estimated_seconds: 28,
      skipped_no_address: 2,
      message: "Backfill running in background — refresh in a few minutes to see updates (47 rows)",
    });
    fireEvent.click(btn);
    await waitFor(() => {
      const calls = toast.mock.calls.map((c) => c[0]);
      expect(calls.find((c) =>
        /Backfill running in background/.test(c))).toBeTruthy();
    });
  });
});
