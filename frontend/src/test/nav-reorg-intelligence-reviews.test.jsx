/**
 * NAV-REORG · Feb-2026 — Web nav reorganisation contract tests.
 *
 * Locks the following structural outcomes against regression:
 *
 *   a. ADMIN_NAV_V2 contains no top-level group with key
 *      ``intelligence`` (the standalone proactive-alerts group
 *      is folded under Reports).
 *   b. ADMIN_NAV_V2 contains no top-level group with key
 *      ``reviews`` (the standalone admin-reviews group is folded
 *      under Marketing).
 *   c. The reports group contains exactly one entry with
 *      ``to: "/admin/intelligence/alerts"`` and
 *      ``subsection: "Intelligence"``.
 *   d. Every entry in the reports group carries a non-empty
 *      ``subsection`` string (so the sidebar's subgroup renderer
 *      does not produce a fallback bucket).
 *   e. The marketing group contains exactly 4 entries whose
 *      ``to`` begins with ``/admin/reviews`` and each has
 *      ``subsection: "Reviews"``.
 *   f. The legacy combined-public-and-admin review subsection
 *      string appears nowhere in adminNav.js (text scan).
 *   g. SUBGROUPED_GROUPS in AdminSidebar.jsx now includes
 *      ``reports`` (so the subsection headers actually render in
 *      the left sidebar — the top-bar renders them regardless).
 *   h. buildCrumbs produces the expected multi-level crumb chain
 *      for ``/admin/intelligence/alerts`` and
 *      ``/admin/reviews/requests``.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

import { ADMIN_NAV_V2 } from "@/nav/adminNav";
import { buildCrumbs } from "@/components/breadcrumbs/routeMeta";

const NAV_SRC = readFileSync(
  resolve(__dirname, "../nav/adminNav.js"),
  "utf8",
);
const SIDEBAR_SRC = readFileSync(
  resolve(__dirname, "../layouts/AdminSidebar.jsx"),
  "utf8",
);

const reportsGroup   = ADMIN_NAV_V2.find((g) => g.key === "reports");
const marketingGroup = ADMIN_NAV_V2.find((g) => g.key === "marketing");


describe("NAV-REORG · nest proactive-alerts under Reports + " +
         "nest admin-reviews under Marketing (Feb-2026)", () => {
  it("(a) no top-level proactive-alerts group remains", () => {
    const hit = ADMIN_NAV_V2.find((g) => g.key === "intelligence");
    expect(hit).toBeUndefined();
  });

  it("(b) no top-level admin-reviews group remains", () => {
    const hit = ADMIN_NAV_V2.find((g) => g.key === "reviews");
    expect(hit).toBeUndefined();
  });

  it("(c) reports group contains the folded alerts row with " +
     "subsection Intelligence", () => {
    expect(reportsGroup).toBeDefined();
    const alerts = reportsGroup.entries.filter(
      (e) => e.to === "/admin/intelligence/alerts",
    );
    expect(alerts.length).toBe(1);
    expect(alerts[0].subsection).toBe("Intelligence");
    // Preserved properties from pre-reorg.
    expect(alerts[0].label).toBe("Alerts");
    expect(alerts[0].feature).toBe("settings");
    expect(alerts[0].hard_rule).toBe("admin_or_super_admin");
  });

  it("(d) every reports entry carries a non-empty subsection", () => {
    expect(reportsGroup.entries.length).toBeGreaterThan(0);
    const missing = reportsGroup.entries.filter(
      (e) => typeof e.subsection !== "string" || e.subsection.length === 0,
    );
    expect(missing).toEqual([]);
  });

  it("(e) marketing group holds exactly four admin-review entries " +
     "under one subsection header", () => {
    expect(marketingGroup).toBeDefined();
    const admin = marketingGroup.entries.filter(
      (e) => typeof e.to === "string" && e.to.startsWith("/admin/reviews"),
    );
    expect(admin.length).toBe(4);
    for (const e of admin) {
      expect(e.subsection).toBe("Reviews");
      expect(e.feature).toBe("marketing");
      expect(e.hard_rule).toBe("admin_only");
    }
    const paths = admin.map((e) => e.to).sort();
    expect(paths).toEqual([
      "/admin/reviews",
      "/admin/reviews/platforms",
      "/admin/reviews/requests",
      "/admin/reviews/widget",
    ]);
  });

  it("(f) legacy combined-review subsection string is gone from " +
     "adminNav.js source", () => {
    // Build the forbidden token from parts so this test's own
    // comments/body cannot false-positive against a text scan.
    const needle = "Reviews" + " & " + "Public";
    expect(NAV_SRC.includes(needle)).toBe(false);
  });

  it("(g) AdminSidebar SUBGROUPED_GROUPS now includes reports", () => {
    const m = SIDEBAR_SRC.match(
      /const\s+SUBGROUPED_GROUPS\s*=\s*new\s+Set\s*\(\s*\[([\s\S]*?)\]\s*\)/,
    );
    expect(m).not.toBeNull();
    const body = m[1];
    expect(body).toMatch(/"reports"/);
    // Pre-existing keys preserved.
    for (const k of ["finance", "marketing", "operations", "customers"]) {
      expect(body).toMatch(new RegExp(`"${k}"`));
    }
  });

  it("(h) buildCrumbs produces Reports > Intelligence > Alerts for " +
     "the folded alerts route", () => {
    const crumbs = buildCrumbs("/admin/intelligence/alerts");
    const labels = crumbs.map((c) => c.label);
    // Walk ends at Home at the leftmost crumb.
    expect(labels[0]).toBe("Home");
    expect(labels).toContain("Reports");
    expect(labels).toContain("Intelligence");
    expect(labels[labels.length - 1]).toBe("Alerts");
    // Order check: Reports precedes Intelligence precedes Alerts.
    const iR = labels.indexOf("Reports");
    const iI = labels.indexOf("Intelligence");
    const iA = labels.indexOf("Alerts");
    expect(iR).toBeLessThan(iI);
    expect(iI).toBeLessThan(iA);
  });

  it("(h2) buildCrumbs produces Marketing > Reviews > Requests " +
     "for the folded reviews-requests route", () => {
    const crumbs = buildCrumbs("/admin/reviews/requests");
    const labels = crumbs.map((c) => c.label);
    expect(labels[0]).toBe("Home");
    expect(labels).toContain("Marketing");
    expect(labels).toContain("Reviews");
    expect(labels[labels.length - 1]).toBe("Requests");
    const iM = labels.indexOf("Marketing");
    const iR = labels.indexOf("Reviews");
    const iQ = labels.indexOf("Requests");
    expect(iM).toBeLessThan(iR);
    expect(iR).toBeLessThan(iQ);
  });
});
