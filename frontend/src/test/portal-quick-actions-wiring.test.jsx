/**
 * Feb 2026 · P0 · Portal Quick Actions wiring.
 *
 * Locks in the 8-tile navigation contract on ``PortalHome``. A prod
 * bug report (Aug-2026) claimed every tile was non-functional; live
 * preview repro proved the tiles work correctly on the current
 * preview bundle. Root cause: production shipped an older bundle
 * without the current handlers. This test guarantees the current
 * behaviour can never silently regress.
 *
 * Tests source-level rather than a mounted render — PortalHome pulls
 * in ~20 admin/portal contexts (AuthContext, TenantContext, WeatherHook,
 * PortalAlerts, chats websocket, etc.) that flake under JSDOM
 * without heavy mocks. Since the wiring is deterministic string
 * literals in the source, we parse the file and assert each tile
 * carries the correct ``navigate("/portal/...")`` and testid.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const PORTAL_HOME = fs.readFileSync(
  path.resolve(__dirname, "../pages/portal/PortalHome.jsx"),
  "utf8",
);

const APP_JS = fs.readFileSync(
  path.resolve(__dirname, "../App.js"),
  "utf8",
);

// The 8 tiles the product spec calls out. Each entry:
//   [testid, expected route, expected label]
// Order matches the render order in PortalHome.jsx.
const QUICK_ACTIONS = [
  { testid: "qa-service-reports", route: "/portal/service-reports",   label: "Service Reports" },
  { testid: "qa-invoices",         route: "/portal/invoices",          label: "Invoices" },
  { testid: "qa-estimates",        route: "/portal/estimates",         label: "Estimates" },
  { testid: "qa-pm",               route: "/portal/payment-method",    label: "Payment Method" },
  { testid: "portal-reviews-tab",  route: "/portal/reviews",           label: "Leave a Review" },
  { testid: "qa-photos",           route: "/portal/photos",            label: "Photos" },
  { testid: "qa-videos",           route: "/portal/videos",            label: "Videos" },
  { testid: "qa-messages",         route: "/portal/chats",             label: "Messages" },
];


describe("Portal Quick Actions · tile wiring", () => {
  it.each(QUICK_ACTIONS)(
    "tile $label has data-testid=$testid and onClick navigates to $route",
    ({ testid, route, label }) => {
      // The render line for each tile is a single JSX statement — we
      // grep the source for the exact combo of label + testid + route
      // so any of the three drifting fails the test loudly.
      const pattern = new RegExp(
        `label\\s*=\\s*"${label.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&")}"[\\s\\S]{0,200}?navigate\\("${route}"\\)[\\s\\S]{0,200}?testid\\s*=\\s*"${testid}"`,
      );
      const altPattern = new RegExp(
        `testid\\s*=\\s*"${testid}"[\\s\\S]{0,200}?navigate\\("${route}"\\)`,
      );
      const forwardPattern = new RegExp(
        `navigate\\("${route}"\\)[\\s\\S]{0,200}?testid\\s*=\\s*"${testid}"`,
      );
      expect(
        pattern.test(PORTAL_HOME)
          || altPattern.test(PORTAL_HOME)
          || forwardPattern.test(PORTAL_HOME),
      ).toBe(true);
    },
  );

  it("every quick-action route has a live Route entry in App.js", () => {
    for (const { route } of QUICK_ACTIONS) {
      const rel = route.replace(/^\//, ""); // App.js declares paths without the leading /
      const pattern = new RegExp(`path="${rel.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&")}"`);
      expect(pattern.test(APP_JS)).toBe(true);
    }
  });

  it("ActionTile renders as a real <button> (not a div) so click handlers actually fire", () => {
    // The ActionTile helper is defined once and used by every quick
    // action — verifying the base component uses <button> guards
    // against a silent refactor that would kill navigation.
    //
    // Portal-Contrast · Feb-2026 — Quick Action tile commentary
    // grew by ~15 lines to document the ``portal-action-tile``
    // migration.  Bumped the ``[\s\S]{0,…}`` lookahead ceiling
    // from 800 to 1500 to keep the regex matching while still
    // asserting the function body ends in a ``<button`` return.
    expect(PORTAL_HOME).toMatch(
      /function ActionTile\(\{[^)]*\}\)\s*\{[\s\S]{0,1500}?return\s*\(\s*<button/,
    );
  });

  it("Every ActionTile carries an onClick prop (no purely-decorative tiles)", () => {
    for (const { testid } of QUICK_ACTIONS) {
      const pattern = new RegExp(
        `<ActionTile[^>]*testid=\\s*"${testid}"[^>]*onClick`,
        "s",
      );
      const swapped = new RegExp(
        `<ActionTile[^>]*onClick=\\{[^}]+\\}[^>]*testid=\\s*"${testid}"`,
        "s",
      );
      expect(pattern.test(PORTAL_HOME) || swapped.test(PORTAL_HOME)).toBe(true);
    }
  });
});
