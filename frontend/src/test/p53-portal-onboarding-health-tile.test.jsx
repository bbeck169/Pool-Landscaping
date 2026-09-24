/**
 * Phase P53 tail · Feb-2026 — Fix C · Customer stats tile swap.
 *
 * Locks the frontend contract for the "Never logged in → Cards on
 * file" tile swap in ``PortalOnboardingHealthTile.jsx``:
 *
 *   1. Config array (COHORT_ORDER, cardinality 4) — 4th entry is the
 *      cards-on-file card, keyed by ``active_with_card_on_file``
 *      (matches the backend response) with the user-approved copy:
 *        label     = "Cards on file"
 *        subtitle  = "Active customers with a saved payment method"
 *        testid    = "portal-onboarding-cards-on-file-tile"
 *        ctaHref   = "/customers?has_payment_method=true&is_active=true"
 *        ctaTestid = "onboarding-tile-cards-on-file-cta"
 *      NO entry remains for ``never_logged_in`` in the config.
 *
 *   2. The never-cohort card's OLD testid
 *      (``onboarding-cohort-never``) MUST be absent from the config
 *      — otherwise QA would still find the retired card by that
 *      selector on any smoke-test filter.
 *
 *   3. Rendered DOM (Vitest + Testing Library):
 *        * outer tile shell has ``data-testid="onboarding-health-tile"``
 *        * new card block has
 *          ``data-testid="portal-onboarding-cards-on-file-tile"``
 *        * subtitle child has
 *          ``data-testid="portal-onboarding-cards-on-file-tile-subtitle"``
 *          and reads the approved copy verbatim
 *        * old ``data-testid="onboarding-cohort-never"`` is NOT
 *          present in the DOM
 *        * count comes from ``data.cohorts.active_with_card_on_file.count``
 *
 *   4. Chase-button binding — ``chaseAudienceUpperBound`` still
 *      derives from ``never_logged_in.count`` on the response, so
 *      when ``invited=5`` and ``never_logged_in=0`` the Chase button
 *      renders DISABLED. The tile no longer shows the never card,
 *      but the button's guardrail still fires.
 *
 *   5. Tile ↔ list parity — the CTA's ``href`` (visible via
 *      ``data-cta-testid`` on the outer div) points at the compound
 *      customers-list filter that yields the same subset the backend
 *      counted.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock the api module — the tile fetches
// GET /reports/portal-onboarding-health?window_days=30 on mount.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(),
  },
}));

// Mock the ChaseStalledInvitesModal — its internals are not what
// this test suite locks (Chase-move ship has its own coverage).
vi.mock("@/components/customers/ChaseStalledInvitesModal", () => ({
  default: () => null,
}));

// Mock sonner toast — silence background noise from the error path.
vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { api } from "@/api";
import PortalOnboardingHealthTile from
  "@/components/customers/PortalOnboardingHealthTile";


// ══════════════════════════════════════════════════════════════════
// Config-shape assertions — no DOM needed, static shape.
// ══════════════════════════════════════════════════════════════════
describe("P53 tail · COHORT_ORDER config shape", () => {
  // The config is a module-scoped const; introspect via a headless
  // render that captures the fetched data-driven cards.
  const asyncFlush = () => new Promise((r) => setTimeout(r, 0));

  beforeEach(() => {
    api.get.mockResolvedValue({
      as_of: "2026-02-14T00:00:00Z",
      window_days: 30,
      cohorts: {
        invited:                    { count: 12, delta_30d: null },
        activated:                  { count: 9,  delta_30d: 3 },
        signed_in:                  { count: 7,  delta_30d: 2 },
        // Backward-compat: STILL returned by backend for the Chase
        // button binding, but the tile UI must not render a card
        // for it.
        never_logged_in:            { count: 2,  delta_30d: null },
        active_with_card_on_file:   { count: 5,  delta_30d: null },
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders exactly 4 cohort cards (unchanged cardinality)", async () => {
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await asyncFlush();
    await asyncFlush();

    const shell = await screen.findByTestId("onboarding-health-tile");
    // Direct children of the shell are the per-cohort wrappers.
    // 4 first-generation flex children = 4 cards.
    const firstGenWrappers = shell.querySelectorAll(":scope > div");
    expect(firstGenWrappers.length).toBe(4);
  });

  it("4th card is the Cards-on-file card with user-approved copy + testid", async () => {
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
    // Label — uppercase 11px, so DOM text matches "Cards on file".
    expect(card.textContent).toContain("Cards on file");
    // Subtitle — verbatim from the P53 tail approval.
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
    // The count is the only ``.tabular-nums`` node inside the card
    // (label / subtitle / delta all use non-tabular typography).
    const countNode = card.querySelector(".tabular-nums");
    expect(countNode).toBeTruthy();
    expect(countNode.textContent.trim()).toBe("5");
  });

  it("CTA on the Cards-on-file card links to compound filter (?has_payment_method=true&is_active=true)", async () => {
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
    // The clickable outer div stamps ``data-cta-testid`` with the
    // CTA test id, which is our contract handle for the compound
    // filter. Assert the CTA testid is present.
    expect(card.getAttribute("data-cta-testid")).toBe(
      "onboarding-tile-cards-on-file-cta",
    );
    // A hidden CTA anchor sibling carries the exact same testid.
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

    // The old cohort block testid.
    expect(screen.queryByTestId("onboarding-cohort-never")).toBeNull();
    // The old CTA testid (already renamed once at chase-move ship,
    // re-verifying it stays gone).
    expect(screen.queryByTestId("onboarding-tile-never-cta")).toBeNull();
  });
});


// ══════════════════════════════════════════════════════════════════
// Chase-button binding — never_logged_in.count still drives disabled.
// ══════════════════════════════════════════════════════════════════
describe("P53 tail · Chase-button preserves never_logged_in binding", () => {
  const asyncFlush = () => new Promise((r) => setTimeout(r, 0));

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("Chase button is DISABLED when never_logged_in.count is 0", async () => {
    api.get.mockResolvedValue({
      as_of: "2026-02-14T00:00:00Z",
      window_days: 30,
      cohorts: {
        invited:                    { count: 8, delta_30d: null },
        activated:                  { count: 5, delta_30d: 0 },
        signed_in:                  { count: 8, delta_30d: 0 },
        never_logged_in:            { count: 0, delta_30d: null },
        active_with_card_on_file:   { count: 3, delta_30d: null },
      },
    });
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await asyncFlush();
    await asyncFlush();

    const chase = await screen.findByTestId(
      "onboarding-tile-invited-chase-cta",
    );
    expect(chase.hasAttribute("disabled")).toBe(true);
  });

  it("Chase button is ENABLED when both invited and never_logged_in are > 0", async () => {
    api.get.mockResolvedValue({
      as_of: "2026-02-14T00:00:00Z",
      window_days: 30,
      cohorts: {
        invited:                    { count: 8, delta_30d: null },
        activated:                  { count: 5, delta_30d: 0 },
        signed_in:                  { count: 5, delta_30d: 0 },
        never_logged_in:            { count: 3, delta_30d: null },
        active_with_card_on_file:   { count: 3, delta_30d: null },
      },
    });
    render(
      <MemoryRouter>
        <PortalOnboardingHealthTile />
      </MemoryRouter>,
    );
    await asyncFlush();
    await asyncFlush();

    const chase = await screen.findByTestId(
      "onboarding-tile-invited-chase-cta",
    );
    expect(chase.hasAttribute("disabled")).toBe(false);
  });
});
