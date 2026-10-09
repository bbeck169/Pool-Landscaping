/**
 * Phase P53 tail · Feb-2026 — Fix C · Customer stats tile swap.
 *
 * Phase 9b · Feb-2026 — Invited card + Chase button were removed.
 * The P53 tail contracts that are still LIVE are the Cards-on-file
 * card shape (label, subtitle, testid, count binding). This file
 * keeps those live assertions and drops the ones Phase 9b retired
 * (card cardinality 4, Chase disabled/enabled). The paired Phase
 * 9b suite (``customers-tile-filters.test.jsx``) locks the new
 * 3-card toggle semantics.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { api } from "@/api";
import PortalOnboardingHealthTile from
  "@/components/customers/PortalOnboardingHealthTile";


describe("P53 tail · Cards-on-file card survives Phase 9b", () => {
  const asyncFlush = () => new Promise((r) => setTimeout(r, 0));

  beforeEach(() => {
    api.get.mockResolvedValue({
      as_of: "2026-02-14T00:00:00Z",
      window_days: 30,
      cohorts: {
        // Phase 9b — ``invited`` + ``never_logged_in`` blocks stay
        // in the backend response. The tile just no longer consumes
        // them; the test payload reflects reality.
        invited:                    { count: 12, delta_30d: null },
        activated:                  { count: 9,  delta_30d: 3 },
        signed_in:                  { count: 7,  delta_30d: 2 },
        never_logged_in:            { count: 2,  delta_30d: null },
        active_with_card_on_file:   { count: 5,  delta_30d: null },
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders exactly 3 cohort cards (Phase 9b cardinality)", async () => {
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await asyncFlush();
    await asyncFlush();

    const shell = await screen.findByTestId("onboarding-health-tile");
    const firstGenWrappers = shell.querySelectorAll(":scope > div");
    expect(firstGenWrappers.length).toBe(3);
  });

  it("Cards-on-file card renders with user-approved copy + testid", async () => {
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await asyncFlush();
    await asyncFlush();

    const card = await screen.findByTestId(
      "portal-onboarding-cards-on-file-tile",
    );
    expect(card).toBeTruthy();
    expect(card.textContent).toContain("Cards on file");
    const subtitle = await screen.findByTestId(
      "portal-onboarding-cards-on-file-tile-subtitle",
    );
    expect(subtitle.textContent).toBe(
      "Active customers with a saved payment method",
    );
  });

  it("count on the Cards-on-file card comes from cohorts.active_with_card_on_file.count", async () => {
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await asyncFlush();
    await asyncFlush();

    const card = await screen.findByTestId(
      "portal-onboarding-cards-on-file-tile",
    );
    const countNode = card.querySelector(".tabular-nums");
    expect(countNode).toBeTruthy();
    expect(countNode.textContent.trim()).toBe("5");
  });

  it("Cards-on-file CTA testid is still present (anchor + data-cta-testid)", async () => {
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await asyncFlush();
    await asyncFlush();

    const card = await screen.findByTestId(
      "portal-onboarding-cards-on-file-tile",
    );
    expect(card.getAttribute("data-cta-testid")).toBe(
      "onboarding-tile-cards-on-file-cta",
    );
    const anchor = await screen.findByTestId(
      "onboarding-tile-cards-on-file-cta",
    );
    expect(anchor).toBeTruthy();
  });

  it("retired Never-logged-in testids are absent from the DOM", async () => {
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await asyncFlush();
    await asyncFlush();

    expect(screen.queryByTestId("onboarding-cohort-never")).toBeNull();
    expect(screen.queryByTestId("onboarding-tile-never-cta")).toBeNull();
  });

  it("Phase 9b · retired Invited + Chase testids are absent from the DOM", async () => {
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await asyncFlush();
    await asyncFlush();

    expect(screen.queryByTestId("onboarding-cohort-invited")).toBeNull();
    expect(screen.queryByTestId("onboarding-tile-invited-cta")).toBeNull();
    expect(
      screen.queryByTestId("onboarding-tile-invited-chase-cta"),
    ).toBeNull();
  });
});
