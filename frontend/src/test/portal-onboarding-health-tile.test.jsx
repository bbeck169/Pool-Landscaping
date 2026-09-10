/**
 * Feb-2026 · Portal onboarding health tile — behaviour tests.
 *
 * Contracts asserted:
 *   1. Loading skeleton renders while the fetch is in flight.
 *   2. All four cohort cards render with counts + delta arrows.
 *   3. Never-logged-in card click navigates to
 *      /customers?first_access=never.
 *   4. Fetch failure surfaces toast.error and the tile does NOT
 *      render (skeleton removed, error state hidden — the tile is
 *      non-fatal).
 *
 * Uses the same vitest style as reports-unpaid-invoice-reminder-
 * button.test.jsx so the whole `src/test` suite stays consistent.
 */
import React from "react";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";


let apiGetImpl = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => apiGetImpl(...a) },
}));
vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});

import { toast } from "sonner";
import PortalOnboardingHealthTile from "@/components/customers/PortalOnboardingHealthTile";


function _payload(overrides = {}) {
  return {
    as_of: "2026-02-10T10:00:00+00:00",
    window_days: 30,
    cohorts: {
      invited:         { count: 42, delta_30d: null },
      activated:       { count: 30, delta_30d: 4 },
      signed_in:       { count: 18, delta_30d: 3 },
      never_logged_in: { count: 12, delta_30d: null },
      ...(overrides.cohorts || {}),
    },
    assumptions: {},
    ...overrides,
  };
}


describe("PortalOnboardingHealthTile", () => {
  beforeEach(() => {
    apiGetImpl = vi.fn();
    navigateMock.mockReset();
    toast.error.mockReset();
    toast.success.mockReset();
  });

  it("renders the skeleton while the fetch is pending", async () => {
    // Never-resolving promise → we stay in loading state.
    apiGetImpl.mockReturnValue(new Promise(() => {}));
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    expect(
      await screen.findByTestId("onboarding-health-tile-skeleton"),
    ).toBeTruthy();
    // The tile itself must NOT render yet.
    expect(
      screen.queryByTestId("onboarding-health-tile"),
    ).toBeNull();
  });

  it("renders 4 cohort cards with counts + delta arrows", async () => {
    apiGetImpl.mockResolvedValue(_payload());
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-health-tile")).toBeTruthy(),
    );
    // All four cards.
    expect(screen.getByTestId("onboarding-cohort-invited")).toBeTruthy();
    expect(screen.getByTestId("onboarding-cohort-activated")).toBeTruthy();
    expect(screen.getByTestId("onboarding-cohort-signed-in")).toBeTruthy();
    expect(screen.getByTestId("onboarding-cohort-never")).toBeTruthy();
    // Counts rendered.
    expect(
      screen.getByTestId("onboarding-cohort-invited").textContent,
    ).toContain("42");
    expect(
      screen.getByTestId("onboarding-cohort-activated").textContent,
    ).toContain("30");
    expect(
      screen.getByTestId("onboarding-cohort-signed-in").textContent,
    ).toContain("18");
    expect(
      screen.getByTestId("onboarding-cohort-never").textContent,
    ).toContain("12");
    // Delta arrows present per-cohort.
    expect(
      screen.getByTestId("onboarding-cohort-invited-delta"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("onboarding-cohort-activated-delta").textContent,
    ).toContain("4");
    expect(
      screen.getByTestId("onboarding-cohort-signed-in-delta").textContent,
    ).toContain("3");
    // Null-delta cohorts render the dimmed dash.
    expect(
      screen.getByTestId("onboarding-cohort-invited-delta").textContent,
    ).toContain("vs last 30d");
    expect(
      screen.getByTestId("onboarding-cohort-never-delta").textContent,
    ).toContain("vs last 30d");
    // Fetch was made with the 30-day window.
    expect(apiGetImpl).toHaveBeenCalledWith(
      "/reports/portal-onboarding-health?window_days=30",
    );
  });

  it("never card click navigates to /customers?first_access=never", async () => {
    apiGetImpl.mockResolvedValue(_payload());
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    const neverCta = await screen.findByTestId("onboarding-tile-never-cta");
    fireEvent.click(neverCta);
    expect(navigateMock).toHaveBeenCalledWith(
      "/customers?first_access=never",
    );
    // The three other cards are NOT clickable — they must not
    // register a CTA testid.
    expect(
      screen.queryByTestId("onboarding-cohort-invited")
             .getAttribute("data-cta-testid"),
    ).toBeNull();
  });

  it("fetch failure surfaces toast.error and hides the tile", async () => {
    apiGetImpl.mockRejectedValue(new Error("boom"));
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    // Tile silently hides on error — no skeleton, no cards.
    expect(
      screen.queryByTestId("onboarding-health-tile"),
    ).toBeNull();
    expect(
      screen.queryByTestId("onboarding-health-tile-skeleton"),
    ).toBeNull();
  });
});
