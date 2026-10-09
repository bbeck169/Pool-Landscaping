/**
 * Phase 9b · Feb-2026 — Customers page tile-filter contract tests.
 *
 * Covers the user-approved spec (1a / 2a / 3b):
 *   1. Invited tile is NOT rendered (removal lock).
 *   2. Top-cluster Portal Invite button is NOT rendered
 *      (removal lock on ``customers-toolbar-portal-invite-btn``).
 *   3. Filter-row Bulk Portal Invite button IS still rendered
 *      (regression lock on ``customers-filter-bulk-portal-invite-btn``).
 *   4-6. Clicking Activated / Signed-in / Cards-on-file tiles
 *        activates the correct URL filter. Clicking the active
 *        tile clears it. Clicking a different tile swaps it.
 *   7. Active tile carries the correct selected-state visual
 *      (``data-active="true"`` + aria-pressed="true" + brand
 *      border).
 *   8. Tile stacks AND with other URL params (status tab,
 *      ``q=`` search).
 *   9. (merged with 8).
 *  10. Tile filter is encoded in the URL and restored on refresh
 *      (deep-link lock).
 *  11. Semantic alignment — the three backend fields the tile
 *      counts against map 1:1 to the list-filter URL params the
 *      tile emits. (Static contract test — no DOM.)
 *
 * Scope: ``PortalOnboardingHealthTile.jsx`` + source-body check
 * on ``CustomersList.jsx``. The full customers-page mount is NOT
 * exercised here (its transitive dep graph is too heavy for the
 * vitest harness — see vitest.config.js Phase 41.5 note). Static
 * source-body checks cover the CustomersList removals, matching
 * the pattern used across the ``customers-list-*`` suite.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const CUSTOMERS_LIST_SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomersList.jsx"),
  "utf-8",
);
const TILE_SRC = fs.readFileSync(
  path.resolve(
    process.cwd(),
    "src/components/customers/PortalOnboardingHealthTile.jsx",
  ),
  "utf-8",
);


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

import PortalOnboardingHealthTile
  from "@/components/customers/PortalOnboardingHealthTile";


function _payload() {
  return {
    as_of: "2026-02-14T00:00:00Z",
    window_days: 30,
    cohorts: {
      invited:                  { count: 12, delta_30d: null },
      activated:                { count: 48, delta_30d: 2 },
      signed_in:                { count: 30, delta_30d: 1 },
      never_logged_in:          { count: 7,  delta_30d: null },
      active_with_card_on_file: { count: 25, delta_30d: null },
    },
  };
}


function renderTileAt(initialPath) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <PortalOnboardingHealthTile />
    </MemoryRouter>,
  );
}

async function waitForTile() {
  await waitFor(() =>
    expect(screen.getByTestId("onboarding-health-tile")).toBeTruthy(),
  );
}


// ═════════════════════════════════════════════════════════════
// 1-3 · Button + tile removal/retention locks (static grep)
// ═════════════════════════════════════════════════════════════
describe("Phase 9b · removal + retention locks", () => {
  it("1. Invited tile is NOT rendered — testid absent from the DOM", async () => {
    apiGetImpl = vi.fn().mockResolvedValue(_payload());
    renderTileAt("/customers");
    await waitForTile();
    expect(screen.queryByTestId("onboarding-cohort-invited")).toBeNull();
    expect(screen.queryByTestId("onboarding-tile-invited-cta")).toBeNull();
  });

  it("2. Top-cluster Portal Invite button is NOT rendered (removal lock)", () => {
    // Static source-body check: the JSX block that rendered the
    // top-cluster button (test-id ``customers-toolbar-portal-invite-btn``)
    // must be gone from CustomersList.jsx entirely.
    expect(CUSTOMERS_LIST_SRC).not.toContain(
      'testid="customers-toolbar-portal-invite-btn"',
    );
    expect(CUSTOMERS_LIST_SRC).not.toContain(
      'data-testid="customers-toolbar-portal-invite-btn"',
    );
  });

  it("3. Filter-row Bulk Portal Invite button IS still rendered (regression lock)", () => {
    // Static source-body check: the inline filter-bar button
    // (test-id ``customers-filter-bulk-portal-invite-btn``) must
    // still be present — different button, different flow.
    expect(CUSTOMERS_LIST_SRC).toContain(
      'data-testid="customers-filter-bulk-portal-invite-btn"',
    );
    // Its handler stays wired too.
    expect(CUSTOMERS_LIST_SRC).toMatch(
      /onClick=\{openBulkPortalInviteFromFilter\}/,
    );
  });

  it("3a. PortalInvite and BulkPortalInvite are DIFFERENT components (no shared code path)", () => {
    // The two surfaces use DIFFERENT modal components. The
    // selection-toolbar + (removed) top-cluster path share the H1
    // modal rendered inline. The filter-row path uses the dedicated
    // BulkPortalInviteConfirm component. They must not be aliased.
    expect(CUSTOMERS_LIST_SRC).toContain(
      "import BulkPortalInviteConfirm from",
    );
    expect(CUSTOMERS_LIST_SRC).toContain(
      "onConfirm={confirmBulkPortalInviteFromFilter}",
    );
    // The filter-row handler and the (preserved) toolbar handler
    // must be distinct symbols.
    expect(CUSTOMERS_LIST_SRC).toMatch(/const openBulkPortalInviteFromFilter\s*=/);
    expect(CUSTOMERS_LIST_SRC).toMatch(/const doBulkPortalInvite\s*=/);
  });
});


// ═════════════════════════════════════════════════════════════
// 4-6 · Toggle semantics
// ═════════════════════════════════════════════════════════════
describe("Phase 9b · tile toggle semantics", () => {
  beforeEach(() => {
    apiGetImpl = vi.fn().mockResolvedValue(_payload());
    navigateMock.mockReset();
  });
  afterEach(() => cleanup());

  it("4. Clicking Activated tile navigates with ?portal_activated=1", async () => {
    renderTileAt("/customers");
    await waitForTile();
    fireEvent.click(screen.getByTestId("onboarding-tile-activated-cta"));
    expect(navigateMock).toHaveBeenCalled();
    const url = navigateMock.mock.calls[0][0];
    expect(url).toContain("portal_activated=1");
    expect(url).not.toContain("first_access=");
    expect(url).not.toContain("has_payment_method=");
  });

  it("5. Clicking the SAME tile again clears the filter (toggle off)", async () => {
    // Start with the Activated tile already selected via URL.
    renderTileAt("/customers?portal_activated=1");
    await waitForTile();
    fireEvent.click(screen.getByTestId("onboarding-tile-activated-cta"));
    expect(navigateMock).toHaveBeenCalled();
    const url = navigateMock.mock.calls[0][0];
    // ``portal_activated`` must be stripped. The clean URL is just
    // ``/customers`` (no stale filter leaks).
    expect(url).not.toContain("portal_activated=");
    expect(url).toBe("/customers");
  });

  it("6. Clicking a DIFFERENT tile swaps the filter (previous deselects)", async () => {
    renderTileAt("/customers?portal_activated=1");
    await waitForTile();
    fireEvent.click(screen.getByTestId("onboarding-tile-signed-in-cta"));
    const url = navigateMock.mock.calls[0][0];
    expect(url).toContain("first_access=any");
    // Mutex guard — Activated's URL param must be stripped.
    expect(url).not.toContain("portal_activated=");
  });

  it("6a. Cards-on-file tile ALSO sets is_active=true on activate (cohort nudge)", async () => {
    renderTileAt("/customers");
    await waitForTile();
    fireEvent.click(screen.getByTestId("onboarding-tile-cards-on-file-cta"));
    const url = navigateMock.mock.calls[0][0];
    expect(url).toContain("has_payment_method=true");
    expect(url).toContain("is_active=true");
  });

  it("6b. Deactivating Cards-on-file leaves shared is_active param alone", async () => {
    renderTileAt("/customers?has_payment_method=true&is_active=true");
    await waitForTile();
    fireEvent.click(screen.getByTestId("onboarding-tile-cards-on-file-cta"));
    const url = navigateMock.mock.calls[0][0];
    expect(url).not.toContain("has_payment_method=");
    // ``is_active`` belongs to the status tab now — tile does not
    // own it on deactivate.
    expect(url).toContain("is_active=true");
  });
});


// ═════════════════════════════════════════════════════════════
// 7 · Active tile visual state
// ═════════════════════════════════════════════════════════════
describe("Phase 9b · active tile visual state", () => {
  beforeEach(() => {
    apiGetImpl = vi.fn().mockResolvedValue(_payload());
    navigateMock.mockReset();
  });
  afterEach(() => cleanup());

  it("7. Active tile exposes data-active=true + aria-pressed=true", async () => {
    renderTileAt("/customers?portal_activated=1");
    await waitForTile();
    const activated = screen.getByTestId("onboarding-cohort-activated");
    expect(activated.getAttribute("data-active")).toBe("true");
    expect(activated.getAttribute("aria-pressed")).toBe("true");
    // The other two tiles stay inactive.
    expect(
      screen.getByTestId("onboarding-cohort-signed-in")
        .getAttribute("data-active"),
    ).toBe("false");
    expect(
      screen.getByTestId("portal-onboarding-cards-on-file-tile")
        .getAttribute("data-active"),
    ).toBe("false");
  });

  it("7a. Signed-in URL marks the Signed-in tile active and clears others", async () => {
    renderTileAt("/customers?first_access=any");
    await waitForTile();
    expect(
      screen.getByTestId("onboarding-cohort-signed-in")
        .getAttribute("data-active"),
    ).toBe("true");
    expect(
      screen.getByTestId("onboarding-cohort-activated")
        .getAttribute("data-active"),
    ).toBe("false");
  });

  it("7b. Cards-on-file URL marks the Cards-on-file tile active", async () => {
    renderTileAt("/customers?has_payment_method=true");
    await waitForTile();
    expect(
      screen.getByTestId("portal-onboarding-cards-on-file-tile")
        .getAttribute("data-active"),
    ).toBe("true");
  });
});


// ═════════════════════════════════════════════════════════════
// 8-10 · AND stacking with other filters + URL deep-link
// ═════════════════════════════════════════════════════════════
describe("Phase 9b · AND stacking + URL deep-link", () => {
  beforeEach(() => {
    apiGetImpl = vi.fn().mockResolvedValue(_payload());
    navigateMock.mockReset();
  });
  afterEach(() => cleanup());

  it("8. Tile stacks AND with status-tab URL param (tab=active + tile=signed_in)", async () => {
    renderTileAt("/customers?tab=active");
    await waitForTile();
    fireEvent.click(screen.getByTestId("onboarding-tile-signed-in-cta"));
    const url = navigateMock.mock.calls[0][0];
    // Both the pre-existing tab param AND the new tile param
    // survive — AND semantics.
    expect(url).toContain("tab=active");
    expect(url).toContain("first_access=any");
  });

  it("9. Tile stacks AND with search input (q=jones + tile=activated)", async () => {
    renderTileAt("/customers?q=jones");
    await waitForTile();
    fireEvent.click(screen.getByTestId("onboarding-tile-activated-cta"));
    const url = navigateMock.mock.calls[0][0];
    expect(url).toContain("q=jones");
    expect(url).toContain("portal_activated=1");
  });

  it("9a. Tile toggle-OFF preserves other filters (clearing tile does NOT clear search)", async () => {
    renderTileAt("/customers?q=jones&portal_activated=1");
    await waitForTile();
    fireEvent.click(screen.getByTestId("onboarding-tile-activated-cta"));
    const url = navigateMock.mock.calls[0][0];
    expect(url).toContain("q=jones");
    expect(url).not.toContain("portal_activated=");
  });

  it("10. Tile filter encoded in URL and restored on refresh (deep-link lock)", async () => {
    // Mounting at the deep-link URL hydrates the correct active
    // tile without any extra client-side state — refresh survives
    // because the state source IS the URL.
    renderTileAt("/customers?portal_activated=1");
    await waitForTile();
    expect(
      screen.getByTestId("onboarding-cohort-activated")
        .getAttribute("aria-pressed"),
    ).toBe("true");
  });
});


// ═════════════════════════════════════════════════════════════
// 11 · Semantic alignment lock — backend field ⇄ URL filter
// ═════════════════════════════════════════════════════════════
describe("Phase 9b · semantic alignment (count ⇄ list filter)", () => {
  it("11. Each tile's backend count key maps to the correct URL filter param", () => {
    // The tile source is the single source of truth. Verify the
    // three COHORT_ORDER entries' ``urlParam`` keys match the
    // backend-aligned list-filter params the brief approved.
    //
    //   Activated       → cohorts.activated.count       → ?portal_activated=1
    //   Signed in       → cohorts.signed_in.count       → ?first_access=any
    //   Cards on file   → cohorts.active_with_card_on_file.count
    //                     → ?has_payment_method=true (+ is_active=true cohort nudge)
    //
    // Static grep against the component source keeps the mapping
    // honest even if someone edits the config array shape.
    expect(TILE_SRC).toMatch(
      /key:\s*"activated"[\s\S]{0,500}urlParam:\s*\{\s*key:\s*"portal_activated",\s*value:\s*"1"\s*\}/,
    );
    expect(TILE_SRC).toMatch(
      /key:\s*"signed_in"[\s\S]{0,500}urlParam:\s*\{\s*key:\s*"first_access",\s*value:\s*"any"\s*\}/,
    );
    expect(TILE_SRC).toMatch(
      /key:\s*"active_with_card_on_file"[\s\S]{0,900}urlParam:\s*\{\s*key:\s*"has_payment_method",\s*value:\s*"true"\s*\}/,
    );
    // The Cards-on-file cohort nudge param must be exactly
    // ``is_active=true`` so the list cohort matches the backend
    // predicate (``active AND NOT muted AND card on file``).
    expect(TILE_SRC).toMatch(
      /extraActivateParam:\s*\{\s*key:\s*"is_active",\s*value:\s*"true"\s*\}/,
    );
  });

  it("11a. Mutex param strip list includes every tile key + retired Invited key", () => {
    // The toggle strips all four tile-category URL params on
    // activation (defense-in-depth for pre-Phase-9b bookmarks that
    // might still carry ``portal_invited=any``).
    expect(TILE_SRC).toMatch(
      /_TILE_PARAM_KEYS\s*=\s*\[[\s\S]{0,200}"portal_activated"[\s\S]{0,200}"first_access"[\s\S]{0,200}"has_payment_method"[\s\S]{0,200}"portal_invited"[\s\S]{0,20}\]/,
    );
  });
});
