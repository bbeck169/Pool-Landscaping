/**
 * Feb-2026 · Chase Stalled Invites — frontend behavior tests.
 *
 * Covers the four contracts the tile CTA + modal ship:
 *   1. Feb-2026 · Chase-move ship — "Chase" button renders under
 *      the INVITED card (test-id ``onboarding-tile-invited-chase-cta``),
 *      enabled when there's a chase audience, disabled when either
 *      ``invited`` or ``never_logged_in`` cohort is empty (the
 *      audience is the intersection of the two).
 *   2. Click opens the modal + fetches the stalest preview list
 *      via ``?portal_invited=any&first_access=never&sort=stalest_first``
 *      so we only chase customers who were actually invited.
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

  it("renders the Chase button under the Invited card and enables it based on chase-audience size", async () => {
    // invited=42 AND never=12 → audience upper bound = 12 > 0 → enabled.
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
    const btn = await screen.findByTestId("onboarding-tile-invited-chase-cta");
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(false);
    // The old Never-card Chase testid must no longer exist —
    // Feb-2026 · Chase-move ship intentionally retires it.
    expect(
      screen.queryByTestId("onboarding-tile-never-chase-cta"),
    ).toBeNull();

    cleanup();

    // never=0 → chase audience upper bound = 0 → button disabled.
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
    const btn2 = await screen.findByTestId("onboarding-tile-invited-chase-cta");
    expect(btn2.disabled).toBe(true);
  });

  it("opens the modal on click and fetches the preview list with portal_invited=any", async () => {
    const previewCustomers = Array.from({ length: 10 }, (_, i) => ({
      id: `cust_${i}`,
      name: `Stale Customer ${i}`,
      email: `stale${i}@example.com`,
    }));
    apiGetImpl.mockImplementation((url) => {
      if (String(url).startsWith("/reports/portal-onboarding-health")) {
        return Promise.resolve(_tilePayload(12));
      }
      if (String(url).startsWith(
        "/customers?portal_invited=any&first_access=never&sort=stalest_first",
      )) {
        return Promise.resolve(previewCustomers);
      }
      return Promise.resolve([]);
    });
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    const btn = await screen.findByTestId("onboarding-tile-invited-chase-cta");
    fireEvent.click(btn);
    const modal = await screen.findByTestId("chase-stalled-invites-modal");
    expect(modal).toBeTruthy();
    await waitFor(() => {
      const rows = screen.getAllByTestId("chase-invites-preview-row");
      expect(rows.length).toBe(10);
    });
    // Feb-2026 · Chase-move — preview URL adds ``portal_invited=any``
    // so we only chase actually-invited customers.
    expect(apiGetImpl).toHaveBeenCalledWith(
      "/customers?portal_invited=any&first_access=never&sort=stalest_first&limit=10",
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
      if (String(url).startsWith(
        "/customers?portal_invited=any&first_access=never&sort=stalest_first",
      )) {
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
    const btn = await screen.findByTestId("onboarding-tile-invited-chase-cta");
    fireEvent.click(btn);
    await screen.findByTestId("chase-stalled-invites-modal");
    await waitFor(() => {
      expect(screen.getAllByTestId("chase-invites-preview-row").length).toBe(2);
    });
    const sendBtn = screen.getByTestId("chase-invites-send-btn");
    fireEvent.click(sendBtn);
    await waitFor(() => {
      expect(apiPostImpl).toHaveBeenCalledWith(
        "/admin/customers/portal-invite/bulk",
        { customer_ids: ["cust_A", "cust_B"],
          reason: "chase_stalled_invites" },
      );
    });
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
    let healthCalls = 0;
    apiGetImpl.mockImplementation((url) => {
      if (String(url).startsWith("/reports/portal-onboarding-health")) {
        healthCalls += 1;
        return Promise.resolve(_tilePayload(1));
      }
      if (String(url).startsWith(
        "/customers?portal_invited=any&first_access=never&sort=stalest_first",
      )) {
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
    await screen.findByTestId("onboarding-tile-invited-chase-cta");
    expect(healthCalls).toBe(1);
    fireEvent.click(screen.getByTestId("onboarding-tile-invited-chase-cta"));
    await screen.findByTestId("chase-stalled-invites-modal");
    await waitFor(() => {
      expect(screen.getAllByTestId("chase-invites-preview-row").length).toBe(1);
    });
    fireEvent.click(screen.getByTestId("chase-invites-send-btn"));
    await screen.findByTestId("chase-invites-summary");
    fireEvent.click(screen.getByTestId("chase-invites-done-btn"));
    await waitFor(() => {
      expect(healthCalls).toBeGreaterThanOrEqual(2);
    });
  });
});
