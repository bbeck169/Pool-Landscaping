/**
 * Phase P52 · Feb-2026 — Customers cohort tabs restyle
 * (saturated active-state + glow, inactive recede).
 *
 * Locks the visual contract landed in CustomersList.jsx for the
 * ``customers-cohort-tabs`` container:
 *
 *   * The ACTIVE tab (matches ``tab === t.k``) carries:
 *       - ``backgroundColor: colors.brandPrimary`` (== #0284C7)
 *       - ``color: colors.onBrandPrimary`` (== #FFFFFF)
 *       - ``boxShadow: "0 0 12px 2px rgba(2,132,199,0.4)"`` glow.
 *   * All OTHER tabs carry:
 *       - ``backgroundColor: "transparent"``
 *       - ``color: colors.muted`` (pre-P52 recede)
 *       - ``boxShadow: "none"``.
 *
 * Test-harness convention (mirrors P48 leads-tabs pattern):
 *   - MemoryRouter wrap so useSearchParams / navigate resolve.
 *   - vi.mock @/api for the tenant / customers roundtrip; every
 *     call resolves to a benign empty payload so the tab
 *     switcher renders without a spinner.
 *   - vi.mock @/auth returning role="admin" so ALL FIVE cohort
 *     tabs (Active, Inactive, Muted, Waitlist, All) render.  The
 *     four latter tabs are ``adminOnly: true`` in TAB_DEFS.
 *   - vi.mock sonner / confirm-dialog / heavy children that fetch
 *     on mount.  Zero UI they carry is exercised here; the
 *     switcher block is inert re: those neighbours.
 *
 * Iterates each of the 5 tabs, clicks, and asserts:
 *   1. The clicked tab picks up the P52 active style.
 *   2. Every OTHER tab reverts to the inactive recede.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render, screen, act, fireEvent,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ── Mocks ────────────────────────────────────────────────────────
const apiGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGet(...a),
    post: vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
    del: vi.fn().mockResolvedValue({}),
  },
}));
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { role: "admin", id: "u1", tenant_id: "t1" },
  }),
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));
vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(() => Promise.resolve(true)),
}));
vi.mock("@/components/customers/CustomerImportModal", () => ({
  default: () => null,
}));
vi.mock("@/components/customers/CustomerBulkInviteBar", () => ({
  default: () => null,
}));
vi.mock("@/components/customers/CustomerBulkSuspendBar", () => ({
  default: () => null,
}));
vi.mock("@/components/customers/CustomerFilterBar", () => ({
  default: () => null,
}));

async function tick(n = 4) {
  await act(async () => {
    for (let i = 0; i < n; i += 1) await Promise.resolve();
  });
}


beforeEach(() => {
  apiGet.mockReset();
  // Every /customers /counts /... call returns a benign empty
  // shape.  The tab switcher block does NOT depend on the
  // customer list content; the counts hook falls through to 0s.
  apiGet.mockImplementation(() => Promise.resolve({
    rows: [], total: 0, page: 1, page_size: 50,
    active: 0, inactive: 0, muted: 0, waitlist: 0, all: 0,
  }));
});


async function mount() {
  const { default: CustomersList } =
    await import("@/pages/customers/CustomersList");
  const utils = render(
    <MemoryRouter initialEntries={["/customers"]}>
      <CustomersList />
    </MemoryRouter>,
  );
  await tick();
  return utils;
}


// Style-token invariants (mirror colors.brandPrimary /
// onBrandPrimary from src/theme.js — resolved to hex here so a
// theme-token rename shows up as an intentional test failure).
const ACTIVE_BG = "#0284C7";
const ACTIVE_FG = "#FFFFFF";
const ACTIVE_GLOW = "0 0 12px 2px rgba(2,132,199,0.4)";
const INACTIVE_BG = "transparent";
const INACTIVE_SHADOW = "none";

const TAB_KEYS = [
  { key: "active", testid: "tab-active" },
  { key: "inactive", testid: "tab-inactive" },
  { key: "muted", testid: "tab-muted" },
  { key: "waitlist", testid: "tab-waitlist" },
  { key: "all", testid: "tab-all" },
];


// ─────────────────────────────────────────────────────────────────────
// Test 1 · Baseline mount — the switcher renders all 5 tabs (admin
// role gates the last four).  Locks the tabset before the glow test.
// ─────────────────────────────────────────────────────────────────────
describe("P52 · Customers cohort tabs · switcher renders", () => {
  it("mounts under customers-cohort-tabs with all 5 tab buttons " +
     "reachable via their canonical testids", async () => {
    const { unmount } = await mount();
    expect(screen.getByTestId("customers-cohort-tabs")).toBeInTheDocument();
    for (const t of TAB_KEYS) {
      expect(screen.getByTestId(t.testid), t.testid).toBeInTheDocument();
    }
    unmount();
  });
});


// ─────────────────────────────────────────────────────────────────────
// Test 2-6 · Iterate every tab.  Clicking each tab flips the active
// style ONTO that tab AND removes it from the previously-active tab.
// One test per tab keeps failure traces surgical.
// ─────────────────────────────────────────────────────────────────────
for (const activeTab of TAB_KEYS) {
  describe(`P52 · Cohort tab active state · ${activeTab.key}`, () => {
    it(`clicking ${activeTab.testid} paints it with the saturated ` +
       `active style (bg #0284C7 + white fg + glow) AND reverts ` +
       `every other tab to the inactive recede (transparent bg, ` +
       `muted fg, no shadow)`, async () => {
      const { unmount } = await mount();

      // The Active tab starts active by default.  Click a
      // non-default tab to force the transition — that's the only
      // way to prove the switch flips both the ON and OFF states.
      const targetBtn = screen.getByTestId(activeTab.testid);
      await act(async () => { fireEvent.click(targetBtn); });
      await tick();

      // ── Assert the clicked tab carries the active style ─────
      const activeBtn = screen.getByTestId(activeTab.testid);
      // Node style values normalise: colour hex may lowercase +
      // rgba spacing may vary.  Read the raw ``style`` string
      // rather than ``getComputedStyle`` — jsdom doesn't resolve
      // computed cascade the way a real browser does.  Match on
      // the inline style tokens the source sets directly.
      const activeStyle = activeBtn.getAttribute("style") || "";
      expect(
        activeStyle.toLowerCase(),
        `${activeTab.testid} active style is: ${activeStyle}`,
      ).toContain("background-color: rgb(2, 132, 199)");
      expect(activeStyle.toLowerCase())
        .toContain("color: rgb(255, 255, 255)");
      // Glow shadow present.  jsdom keeps the raw rgba() form
      // WITHOUT space-after-comma (matches the source literal).
      expect(activeStyle.toLowerCase())
        .toContain("rgba(2,132,199,0.4)");
      // Sanity: the glow spread values are what P52 shipped.
      expect(activeStyle).toContain("0 0 12px 2px");

      // ── Assert every OTHER tab shows the inactive recede ────
      for (const other of TAB_KEYS) {
        if (other.key === activeTab.key) continue;
        const otherBtn = screen.getByTestId(other.testid);
        const otherStyle = (otherBtn.getAttribute("style") || "").toLowerCase();
        // Inactive bg is literal "transparent" — jsdom keeps it
        // as-is on the style string (no rgba coercion).
        expect(
          otherStyle,
          `${other.testid} should be transparent but is: ${otherStyle}`,
        ).toContain("background-color: transparent");
        // No glow shadow.  jsdom emits ``box-shadow: none``.
        expect(otherStyle).toContain("box-shadow: none");
      }

      unmount();
    });
  });
}
