/**
 * Feb-2026 · Portal onboarding health tile — behaviour tests.
 *
 * Contracts asserted:
 *   1. Loading skeleton renders while the fetch is in flight.
 *   2. All four cohort cards render with counts + delta arrows.
 *   3. Feb-2026 · Onboarding-tile clickable ship — every one of
 *      the four cohort cards navigates to the correct filtered
 *      URL on both click AND Enter/Space keyboard activation:
 *        Invited   → /customers?portal_invited=any
 *        Activated → /customers?portal_activated=1
 *        Signed in → /customers?first_access=any
 *        Never     → /customers?first_access=never   (preserved)
 *   4. Fetch failure surfaces toast.error and the tile does NOT
 *      render (skeleton removed, error state hidden — the tile is
 *      non-fatal).
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
    apiGetImpl.mockReturnValue(new Promise(() => {}));
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    expect(
      await screen.findByTestId("onboarding-health-tile-skeleton"),
    ).toBeTruthy();
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
    expect(screen.getByTestId("onboarding-cohort-invited")).toBeTruthy();
    expect(screen.getByTestId("onboarding-cohort-activated")).toBeTruthy();
    expect(screen.getByTestId("onboarding-cohort-signed-in")).toBeTruthy();
    expect(screen.getByTestId("onboarding-cohort-never")).toBeTruthy();
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
    expect(
      screen.getByTestId("onboarding-cohort-invited-delta"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("onboarding-cohort-activated-delta").textContent,
    ).toContain("4");
    expect(
      screen.getByTestId("onboarding-cohort-signed-in-delta").textContent,
    ).toContain("3");
    expect(
      screen.getByTestId("onboarding-cohort-invited-delta").textContent,
    ).toContain("vs last 30d");
    expect(
      screen.getByTestId("onboarding-cohort-never-delta").textContent,
    ).toContain("vs last 30d");
    expect(apiGetImpl).toHaveBeenCalledWith(
      "/reports/portal-onboarding-health?window_days=30",
    );
  });

  // Table-driven test — one assertion per cohort card, one for
  // click, one for Enter, one for Space. Matches the change-1 spec.
  const _COHORT_CASES = [
    { testid: "onboarding-tile-invited-cta",   href: "/customers?portal_invited=any" },
    { testid: "onboarding-tile-activated-cta", href: "/customers?portal_activated=1" },
    { testid: "onboarding-tile-signed-in-cta", href: "/customers?first_access=any" },
    { testid: "onboarding-tile-never-cta",     href: "/customers?first_access=never" },
  ];

  for (const c of _COHORT_CASES) {
    it(`${c.testid} click navigates to ${c.href}`, async () => {
      apiGetImpl.mockResolvedValue(_payload());
      render(
        <MemoryRouter>
          <PortalOnboardingHealthTile />
        </MemoryRouter>,
      );
      const cta = await screen.findByTestId(c.testid);
      fireEvent.click(cta);
      expect(navigateMock).toHaveBeenCalledWith(c.href);
    });
  }

  it("all four cohort cards support Enter/Space keyboard activation", async () => {
    apiGetImpl.mockResolvedValue(_payload());
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-health-tile")).toBeTruthy(),
    );
    for (const c of _COHORT_CASES) {
      navigateMock.mockReset();
      // The outer <div> with role="button" is the block card; the
      // ``data-cta-testid`` attribute makes each cohort card
      // discoverable in the DOM.
      const card = document.querySelector(
        `[data-cta-testid="${c.testid}"]`,
      );
      expect(card).toBeTruthy();
      expect(card.getAttribute("role")).toBe("button");
      expect(card.getAttribute("tabindex")).toBe("0");
      // Enter key
      fireEvent.keyDown(card, { key: "Enter" });
      expect(navigateMock).toHaveBeenCalledWith(c.href);
      navigateMock.mockReset();
      // Space key
      fireEvent.keyDown(card, { key: " " });
      expect(navigateMock).toHaveBeenCalledWith(c.href);
    }
  });

  it("fetch failure surfaces toast.error and hides the tile", async () => {
    apiGetImpl.mockRejectedValue(new Error("boom"));
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(
      screen.queryByTestId("onboarding-health-tile"),
    ).toBeNull();
    expect(
      screen.queryByTestId("onboarding-health-tile-skeleton"),
    ).toBeNull();
  });
});
