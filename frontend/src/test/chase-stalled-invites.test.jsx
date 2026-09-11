/**
 * Feb-2026 · Chase Stalled Invites — frontend behavior tests.
 *
 * Covers the four contracts the tile CTA + modal ship:
 *   1. "Chase" button renders under the Never card when count > 0,
 *      hidden/disabled when count === 0.
 *   2. Click opens the modal + fetches the stalest preview list.
 *   3. Confirm posts to the bulk endpoint with the id list, then
 *      swaps modal content to the summary state.
 *   4. Close triggers a refetch of
 *      /api/reports/portal-onboarding-health.
 */
import React from "react";
import {
  render, screen, fireEvent, waitFor, cleanup, within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";


let apiGetImpl  = vi.fn();
let apiPostImpl = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get:  (...a) => apiGetImpl(...a),
    post: (...a) => apiPostImpl(...a),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});


import PortalOnboardingHealthTile from "@/components/customers/PortalOnboardingHealthTile";


function _tilePayload(never_count) {
  return {
    as_of: "2026-02-10T10:00:00+00:00",
    window_days: 30,
    cohorts: {
      invited:         { count: 42, delta_30d: null },
      activated:       { count: 30, delta_30d: 4 },
      signed_in:       { count: 18, delta_30d: 3 },
      never_logged_in: { count: never_count, delta_30d: null },
    },
    assumptions: {},
  };
}


describe("Chase Stalled Invites (Feb-2026)", () => {
  beforeEach(() => {
    apiGetImpl  = vi.fn();
    apiPostImpl = vi.fn();
    navigateMock.mockReset();
  });
  afterEach(() => {
    cleanup();
  });

  it("renders the Chase button when never_logged_in count > 0 and disables it when count === 0", async () => {
    apiGetImpl.mockImplementation((url) => {
      if (String(url).startsWith("/reports/portal-onboarding-health")) {
        return Promise.resolve(_tilePayload(12));
      }
      return Promise.resolve([]);
    });
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    const btn = await screen.findByTestId("onboarding-tile-never-chase-cta");
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(false);

    cleanup();

    // count===0 → button still rendered but disabled (matches spec:
    // "Enabled only when count > 0"). We expose the same testid so
    // ops discovers the affordance even when there's nothing to
    // chase — hover title explains why.
    apiGetImpl = vi.fn().mockImplementation((url) => {
      if (String(url).startsWith("/reports/portal-onboarding-health")) {
        return Promise.resolve(_tilePayload(0));
      }
      return Promise.resolve([]);
    });
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    const btn2 = await screen.findByTestId("onboarding-tile-never-chase-cta");
    expect(btn2.disabled).toBe(true);
  });

  it("opens the modal on click and fetches the preview list", async () => {
    const previewCustomers = Array.from({ length: 10 }, (_, i) => ({
      id: `cust_${i}`,
      name: `Stale Customer ${i}`,
      email: `stale${i}@example.com`,
    }));
    apiGetImpl.mockImplementation((url) => {
      if (String(url).startsWith("/reports/portal-onboarding-health")) {
        return Promise.resolve(_tilePayload(12));
      }
      if (String(url).startsWith("/customers?first_access=never&sort=stalest_first")) {
        return Promise.resolve(previewCustomers);
      }
      return Promise.resolve([]);
    });
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    const btn = await screen.findByTestId("onboarding-tile-never-chase-cta");
    fireEvent.click(btn);
    // Modal opens.
    const modal = await screen.findByTestId("chase-stalled-invites-modal");
    expect(modal).toBeTruthy();
    // Preview list renders 10 rows.
    await waitFor(() => {
      const rows = screen.getAllByTestId("chase-invites-preview-row");
      expect(rows.length).toBe(10);
    });
    // The API was called with the correct query.
    expect(apiGetImpl).toHaveBeenCalledWith(
      "/customers?first_access=never&sort=stalest_first&limit=10",
    );
  });

  it("confirming posts to the bulk endpoint and swaps modal to summary state", async () => {
    const previewCustomers = [
      { id: "cust_A", name: "Alpha", email: "alpha@e.com" },
      { id: "cust_B", name: "Bravo", email: "bravo@e.com" },
    ];
    apiGetImpl.mockImplementation((url) => {
      if (String(url).startsWith("/reports/portal-onboarding-health")) {
        return Promise.resolve(_tilePayload(2));
      }
      if (String(url).startsWith("/customers?first_access=never&sort=stalest_first")) {
        return Promise.resolve(previewCustomers);
      }
      return Promise.resolve([]);
    });
    apiPostImpl.mockResolvedValue({
      enqueued: 2, rate_limited: [], failed: [],
      sent: 2, batch_id: "b1", failures: [],
    });
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    const btn = await screen.findByTestId("onboarding-tile-never-chase-cta");
    fireEvent.click(btn);
    await screen.findByTestId("chase-stalled-invites-modal");
    // Wait for preview.
    await waitFor(() => {
      expect(screen.getAllByTestId("chase-invites-preview-row").length).toBe(2);
    });
    const sendBtn = screen.getByTestId("chase-invites-send-btn");
    fireEvent.click(sendBtn);
    // POST body should carry the id list.
    await waitFor(() => {
      expect(apiPostImpl).toHaveBeenCalledWith(
        "/admin/customers/portal-invite/bulk",
        { customer_ids: ["cust_A", "cust_B"],
          reason: "chase_stalled_invites" },
      );
    });
    // Modal swaps to summary state.
    const summary = await screen.findByTestId("chase-invites-summary");
    expect(summary).toBeTruthy();
    expect(
      screen.getByTestId("chase-invites-summary-enqueued").textContent,
    ).toContain("2");
    expect(
      screen.getByTestId("chase-invites-summary-rate-limited").textContent,
    ).toContain("0");
    expect(
      screen.getByTestId("chase-invites-summary-failed").textContent,
    ).toContain("0");
  });

  it("close (via Done in summary) triggers a refetch of the health tile", async () => {
    const previewCustomers = [
      { id: "cust_X", name: "X", email: "x@e.com" },
    ];
    // Track health-tile refetches.
    let healthCalls = 0;
    apiGetImpl.mockImplementation((url) => {
      if (String(url).startsWith("/reports/portal-onboarding-health")) {
        healthCalls += 1;
        return Promise.resolve(_tilePayload(1));
      }
      if (String(url).startsWith("/customers?first_access=never&sort=stalest_first")) {
        return Promise.resolve(previewCustomers);
      }
      return Promise.resolve([]);
    });
    apiPostImpl.mockResolvedValue({
      enqueued: 1, rate_limited: [], failed: [],
      sent: 1, batch_id: "b1", failures: [],
    });
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await screen.findByTestId("onboarding-tile-never-chase-cta");
    expect(healthCalls).toBe(1); // initial mount
    fireEvent.click(screen.getByTestId("onboarding-tile-never-chase-cta"));
    await screen.findByTestId("chase-stalled-invites-modal");
    await waitFor(() => {
      expect(screen.getAllByTestId("chase-invites-preview-row").length).toBe(1);
    });
    fireEvent.click(screen.getByTestId("chase-invites-send-btn"));
    await screen.findByTestId("chase-invites-summary");
    // Click Done → close → triggers onSent → parent refetch.
    fireEvent.click(screen.getByTestId("chase-invites-done-btn"));
    await waitFor(() => {
      // Second health-tile fetch fired after Done.
      expect(healthCalls).toBeGreaterThanOrEqual(2);
    });
  });
});
