/**
 * Feb-2026 · Portal onboarding health tile — behaviour tests.
 *
 * Phase 9b · Feb-2026 — the tile now renders THREE cards (down
 * from four). Invited + Chase were removed. Each card is a
 * TOGGLE whose active state is derived from the URL and whose
 * click handler preserves every OTHER URL filter the user has
 * applied.
 *
 * This suite pins the surviving contracts:
 *   1. Loading skeleton renders while the fetch is in flight.
 *   2. Three cohort cards render with counts + delta arrows.
 *   3. Each card toggles the correct URL param on click AND on
 *      Enter / Space keyboard activation.
 *   4. Fetch failure surfaces toast.error and the tile does NOT
 *      render (skeleton removed, error state hidden — the tile
 *      is non-fatal).
 *   5. REGRESSION — Invited testids + Chase button testid stay
 *      removed from the DOM. If a future refactor accidentally
 *      re-introduces them, CI trips here.
 */
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
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
      // Phase 9b — ``invited`` + ``never_logged_in`` blocks are
      // DELIBERATELY retained in the server payload so the backend
      // response contract stays stable. The tile UI must ignore
      // them (regression test below asserts the retired cohort-
      // card testids never render).
      invited:                  { count: 42, delta_30d: null },
      activated:                { count: 30, delta_30d: 4 },
      signed_in:                { count: 18, delta_30d: 3 },
      never_logged_in:          { count: 12, delta_30d: null },
      active_with_card_on_file: { count: 25, delta_30d: null },
      ...(overrides.cohorts || {}),
    },
    assumptions: {},
    ...overrides,
  };
}


describe("PortalOnboardingHealthTile (Phase 9b · 3-card shape)", () => {
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

  it("renders 3 cohort cards with counts + delta arrows", async () => {
    apiGetImpl.mockResolvedValue(_payload());
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-health-tile")).toBeTruthy(),
    );
    expect(screen.getByTestId("onboarding-cohort-activated")).toBeTruthy();
    expect(screen.getByTestId("onboarding-cohort-signed-in")).toBeTruthy();
    expect(
      screen.getByTestId("portal-onboarding-cards-on-file-tile"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("onboarding-cohort-activated").textContent,
    ).toContain("30");
    expect(
      screen.getByTestId("onboarding-cohort-signed-in").textContent,
    ).toContain("18");
    expect(
      screen.getByTestId("portal-onboarding-cards-on-file-tile")
        .textContent,
    ).toContain("25");
    expect(
      screen.getByTestId("onboarding-cohort-activated-delta").textContent,
    ).toContain("4");
    expect(
      screen.getByTestId("onboarding-cohort-signed-in-delta").textContent,
    ).toContain("3");
    expect(
      screen.getByTestId("portal-onboarding-cards-on-file-tile-delta")
        .textContent,
    ).toContain("vs last 30d");
    expect(apiGetImpl).toHaveBeenCalledWith(
      "/reports/portal-onboarding-health?window_days=30",
    );
  });

  it("REGRESSION · retired Invited + Chase testids are absent from the DOM", async () => {
    apiGetImpl.mockResolvedValue(_payload());
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-health-tile")).toBeTruthy(),
    );
    // Phase 9b removal locks — these three testids must NEVER
    // return. If a refactor accidentally re-wires the Invited
    // card or Chase button, CI trips here before preview.
    expect(screen.queryByTestId("onboarding-cohort-invited")).toBeNull();
    expect(screen.queryByTestId("onboarding-tile-invited-cta")).toBeNull();
    expect(
      screen.queryByTestId("onboarding-tile-invited-chase-cta"),
    ).toBeNull();
  });

  // Phase 9b · toggle semantics — click an inactive card ⇒ activate
  // its filter. The exact URL assertion is covered more thoroughly
  // in ``customers-tile-filters.test.jsx`` (the 11-case Phase 9b
  // spec); here we just prove each CTA wires through to navigate.
  const _COHORT_CASES = [
    { testid: "onboarding-tile-activated-cta",     expect: "portal_activated=1" },
    { testid: "onboarding-tile-signed-in-cta",     expect: "first_access=any" },
    { testid: "onboarding-tile-cards-on-file-cta", expect: "has_payment_method=true" },
  ];

  for (const c of _COHORT_CASES) {
    it(`${c.testid} click navigates with ${c.expect}`, async () => {
      apiGetImpl.mockResolvedValue(_payload());
      render(
        <MemoryRouter initialEntries={["/customers"]}>
          <PortalOnboardingHealthTile />
        </MemoryRouter>,
      );
      const cta = await screen.findByTestId(c.testid);
      fireEvent.click(cta);
      expect(navigateMock).toHaveBeenCalled();
      const navigatedTo = navigateMock.mock.calls[0][0];
      expect(navigatedTo).toContain(c.expect);
    });
  }

  it("all three cohort cards support Enter/Space keyboard activation", async () => {
    apiGetImpl.mockResolvedValue(_payload());
    render(
      <MemoryRouter initialEntries={["/customers"]}>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("onboarding-health-tile")).toBeTruthy(),
    );
    for (const c of _COHORT_CASES) {
      navigateMock.mockReset();
      const card = document.querySelector(
        `[data-cta-testid="${c.testid}"]`,
      );
      expect(card).toBeTruthy();
      expect(card.getAttribute("role")).toBe("button");
      expect(card.getAttribute("tabindex")).toBe("0");
      fireEvent.keyDown(card, { key: "Enter" });
      expect(navigateMock).toHaveBeenCalled();
      navigateMock.mockReset();
      fireEvent.keyDown(card, { key: " " });
      expect(navigateMock).toHaveBeenCalled();
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
