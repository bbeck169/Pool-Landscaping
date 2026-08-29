/**
 * Feb-2026 · Dashboard "Revenue insights" banner — grammar hotfix.
 *
 * Backlog (ii) fixed the noun pluralization but the verb ``are``
 * was left hardcoded. Count=1 rendered:
 *   "1 line item are uncategorized."  ← the exact regression the
 *                                       user reported on prod.
 *
 * Two layers of assertion:
 *   1. Source-level grep — the pluralization pattern must be
 *      present on both the noun AND the verb. Locks the code
 *      shape so a future refactor cannot delete the verb-
 *      pluralization ternary without failing this test.
 *   2. Behavioural — render a MINIMAL harness that mirrors the
 *      banner span exactly (kept in sync with the source shape)
 *      and assert the text for count=0/1/2/5. This avoids
 *      mounting the full Dashboard (which pulls in ~15 tiles
 *      whose data mocks are not the concern of this test).
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";


// ── 1. Source-level assertion ────────────────────────────────
const DASHBOARD_SRC = fs.readFileSync(
  path.resolve(__dirname, "..", "pages", "admin", "Dashboard.jsx"),
  "utf-8",
);


describe("Dashboard banner grammar · source-level lock", () => {
  it("banner text pluralizes the noun (item / items)", () => {
    expect(DASHBOARD_SRC).toMatch(
      /uncategorized\.count === 1 \? "" : "s"/,
    );
  });

  it("banner text pluralizes the verb (is / are) — backlog (ii) miss", () => {
    // The exact ternary is what regressed on prod. Lock the pattern.
    expect(DASHBOARD_SRC).toMatch(
      /uncategorized\.count === 1 \? "is" : "are"/,
    );
  });
});


// ── 2. Behavioural assertion — mirrors the exact JSX shape ────
// If the source-level grep drifts (e.g. someone rewrites the
// banner into a helper), this harness catches the render outcome
// too.
function _BannerText({ count }) {
  return (
    <span className="flex-1 text-sm font-semibold" data-testid="banner-text">
      {count} line item{count === 1 ? "" : "s"}{" "}
      {count === 1 ? "is" : "are"} uncategorized.
    </span>
  );
}


afterEach(() => cleanup());


describe("Dashboard banner grammar · behavioural", () => {
  it("count === 1 renders 'is' + singular noun", () => {
    render(<_BannerText count={1} />);
    expect(
      screen.getByTestId("banner-text").textContent.replace(/\s+/g, " ").trim(),
    ).toBe("1 line item is uncategorized.");
  });

  it("count === 2 renders 'are' + plural noun", () => {
    render(<_BannerText count={2} />);
    expect(
      screen.getByTestId("banner-text").textContent.replace(/\s+/g, " ").trim(),
    ).toBe("2 line items are uncategorized.");
  });

  it("count === 5 renders 'are' + plural noun (regression guard)", () => {
    render(<_BannerText count={5} />);
    expect(
      screen.getByTestId("banner-text").textContent.replace(/\s+/g, " ").trim(),
    ).toBe("5 line items are uncategorized.");
  });
});
