/**
 * Portal-Contrast · Feb-2026 — Portal Home ``portal-action-tile``
 * variant lock.
 *
 * Pre-fix state: Quick Actions (Service Reports, Invoices,
 * Estimates, Payment Method, Leave a Review, Photos, Videos,
 * Messages) and the Ask-a-Concierge inner buttons (Billy, Skedra)
 * rendered on ``colors.surfaceSecondary`` (``portalColors`` →
 * #0a0940) against a ``colors.surface`` (#03002e) page bg —
 * ≈12% luminance delta, invisible separation.
 *
 * Metric tiles (Balance Due / Past Due / Credit / Overdue /
 * Pending Estimates / Unread Messages) convey state via
 * dynamic ``bgColor`` overrides and MUST remain on
 * ``colors.surface`` — the Phase-23 contract locked in
 * ``portal-home-tiles-hover-glow-dynamic-colors.test.jsx``.
 *
 * This file locks:
 *   1. The shared ``.portal-dark .portal-action-tile`` CSS rule
 *      ships ``#1E3A5F`` as its background.
 *   2. The ``ActionTile`` component body carries
 *      ``portal-action-tile`` and NO ``colors.surfaceSecondary``
 *      inline bg.
 *   3. The AI employee buttons (Billy / Skedra) carry
 *      ``portal-action-tile`` and NO ``colors.surfaceSecondary``
 *      inline bg.
 *   4. The metric ``Tile`` component is unchanged — still ships
 *      ``colors.surface`` as its chassis bg and does NOT carry
 *      ``portal-action-tile``.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.join(process.cwd(), "src", rel), "utf-8");

const PH_SRC = read("pages/portal/PortalHome.jsx");
const PORTAL_DARK_CSS = read("styles/portal-dark.css");

// ───────────────────────────────────────────────────────────────
// Component-body slices (regex-indexed, matches the Phase-23
// test-file strategy).
// ───────────────────────────────────────────────────────────────
const ACTION_TILE_FN_IDX = PH_SRC.indexOf("function ActionTile(");
const TILE_FN_IDX = PH_SRC.indexOf("function Tile(");
const ACTION_TILE_BODY = PH_SRC.slice(ACTION_TILE_FN_IDX, TILE_FN_IDX);
const TILE_BODY = PH_SRC.slice(TILE_FN_IDX, TILE_FN_IDX + 2500);

describe("Portal-Contrast · ``portal-action-tile`` CSS variant", () => {
  it("portal-dark.css ships ``.portal-dark .portal-action-tile`` painted with ``#1E3A5F`` background", () => {
    const idx = PORTAL_DARK_CSS.indexOf(".portal-dark .portal-action-tile");
    expect(
      idx,
      "`.portal-dark .portal-action-tile` rule missing",
    ).toBeGreaterThan(-1);
    const block = PORTAL_DARK_CSS.slice(idx, idx + 400);
    expect(block).toMatch(/background-color:\s*#1E3A5F\s*!important/i);
  });

  it("hover state exists and lifts the tile above the rest state", () => {
    expect(PORTAL_DARK_CSS).toMatch(
      /\.portal-dark \.portal-action-tile:hover[\s\S]{0,200}background-color:\s*#(?:[0-9a-f]{6})\s*!important/i,
    );
  });
});

describe("Portal-Contrast · ActionTile component swaps ``surfaceSecondary`` for ``portal-action-tile``", () => {
  it("ActionTile className list carries ``portal-action-tile``", () => {
    expect(ACTION_TILE_BODY).toMatch(
      /className=["'][^"']*\bportal-action-tile\b/,
    );
  });

  it("ActionTile no longer ships the pre-fix ``backgroundColor: colors.surfaceSecondary`` inline bg", () => {
    // The dark-on-dark bg is retired.  The CSS variant provides
    // the (lighter) surface instead.
    expect(ACTION_TILE_BODY).not.toMatch(
      /backgroundColor:\s*colors\.surfaceSecondary/,
    );
  });

  it("ActionTile still ships the admin-side ``transition hover:brightness-95`` affordance (consistency)", () => {
    // The hover affordance remains — Portal-Contrast only swaps
    // the surface, not the hover language.
    expect(ACTION_TILE_BODY).toMatch(/transition hover:brightness-95/);
  });

  it("ActionTile preserves the Phase-24 white halo on hover", () => {
    expect(ACTION_TILE_BODY).toMatch(
      /hover:shadow-\[0_0_20px_rgba\(255,255,255,0\.6\)\]/,
    );
  });
});

describe("Portal-Contrast · AI concierge buttons (Billy / Skedra) swap ``surfaceSecondary`` for ``portal-action-tile``", () => {
  // Scope: the ``aiEmployees.map(...)`` block that renders the
  // two inner cards.  Starts at ``data-testid="portal-ai-section"``
  // and ends at the ``portal-referral-section`` sibling.
  const idx = PH_SRC.indexOf('data-testid="portal-ai-section"');
  const end = PH_SRC.indexOf("portal-referral-section", idx);
  const SECTION = PH_SRC.slice(idx, end > 0 ? end : idx + 3000);

  it("inner AI buttons ship ``portal-action-tile`` className", () => {
    expect(SECTION).toMatch(/className=["'][^"']*\bportal-action-tile\b/);
    // Must appear in a ``data-testid`` that targets an AI
    // employee card (billy / skedra).
    expect(SECTION).toMatch(/portal-ai-\$\{emp\.key\}-card/);
  });

  it("inner AI buttons no longer ship ``backgroundColor: colors.surfaceSecondary`` inline bg", () => {
    expect(SECTION).not.toMatch(/backgroundColor:\s*colors\.surfaceSecondary/);
  });
});

describe("Portal-Contrast · metric ``Tile`` component is UNCHANGED (Balance / Past Due / Credit / Overdue / Pending Estimates / Unread Messages)", () => {
  // The metric tiles convey state via dynamic ``bgColor``
  // overrides (dark red for past-due > 0, dark green for credit
  // > 0, etc.).  Hoisting them to ``portal-action-tile`` would
  // break the state-color contract locked by Phase 24.
  it("Tile body still ships ``backgroundColor: colors.surface`` as its chassis default", () => {
    expect(TILE_BODY).toMatch(/backgroundColor:\s*colors\.surface/);
  });

  it("Tile body does NOT carry the ``portal-action-tile`` className", () => {
    expect(TILE_BODY).not.toMatch(
      /className=["'][^"']*\bportal-action-tile\b/,
    );
  });

  it("Tile body still ships the dynamic ``bgColor`` spread override", () => {
    expect(TILE_BODY).toMatch(
      /\.\.\.\(bgColor \? \{ backgroundColor: bgColor \} : \{\}\)/,
    );
  });

  it("every Metric tile testid is still rendered via the ``Tile`` component (not ``ActionTile``)", () => {
    // These are the testids spec'd as "do NOT touch" in the
    // Portal-Contrast brief.  All six must render via ``<Tile``.
    const metricTestids = [
      "portal-balance-tile",
      "portal-past-due-tile",
      "portal-credit-tile",
      "portal-overdue-tile",
      "portal-pending-estimates-tile",
      "portal-unread-messages-tile",
    ];
    for (const tid of metricTestids) {
      const re = new RegExp(`<Tile[\\s\\S]{0,600}?testid=["']${tid}["']`);
      // Not every metric tile is guaranteed to render on every
      // user state — but if it IS referenced, it must be via
      // <Tile>, never <ActionTile>.  Fail only when ``ActionTile``
      // appears paired with the testid.
      const bad = new RegExp(
        `<ActionTile[\\s\\S]{0,400}?testid=["']${tid}["']`,
      );
      expect(
        PH_SRC,
        `metric testid ${tid} must NOT be rendered via <ActionTile>`,
      ).not.toMatch(bad);
      // Soft lock — if present, it must be a Tile.
      if (PH_SRC.includes(`testid="${tid}"`)) {
        expect(PH_SRC).toMatch(re);
      }
    }
  });
});

describe("Portal-Contrast · Quick Actions call sites still ship the 8 expected labels", () => {
  const QUICK_ACTION_LABELS = [
    "Service Reports",
    "Invoices",
    "Estimates",
    "Payment Method",
    "Leave a Review",
    "Photos",
    "Videos",
    "Messages",
  ];
  for (const label of QUICK_ACTION_LABELS) {
    it(`Quick Action label preserved: ${label}`, () => {
      expect(PH_SRC).toContain(`label="${label}"`);
    });
  }
});
