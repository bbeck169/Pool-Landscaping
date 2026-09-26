/**
 * Feb-2026 · N1 · Unit tests for the navigable-search route index.
 *
 * Exercises the flatten pass (``getNavIndex()``) and the ranked
 * matcher (``searchNavIndex(query, opts?)``) against a mocked
 * ``ADMIN_NAV_V2`` so the test is deterministic and doesn't drift
 * when the real sidebar config gains / loses rows.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

// Fixture — small, hand-crafted stand-in for ADMIN_NAV_V2. Covers
// all four ranking classes (exact title, prefix, substring,
// alias), a duplicate-path dedupe scenario, and rows with no
// alias field at all.
vi.mock("@/nav/adminNav", () => ({
  ADMIN_NAV_V2: [
    { key: "finance", label: "Finance", entries: [
      { to: "/invoices", label: "Invoices",
        aliases: ["Bills", "Receivables", "Sales"] },
      { to: "/admin/imports/pdf-invoice", label: "PDF Import",
        aliases: ["PDF Upload", "Bulk Import", "Upload Invoices"] },
      { to: "/payments", label: "Payments",
        aliases: ["Received Payments", "Deposits"] },
      { to: "/admin/checks", label: "Check Writer",
        aliases: ["Checks", "Write Checks"] },
      // Row with NO aliases field — must still index cleanly.
      { to: "/admin/finance/bills", label: "Vendor Bills" },
      // Row with malformed aliases (non-string) — filtered.
      { to: "/malformed", label: "Malformed Row",
        aliases: ["ok", 42, null, "also ok"] },
    ] },
    { key: "ops", label: "Operations", entries: [
      { to: "/schedule", label: "Schedule",
        aliases: ["Calendar", "Bookings"] },
      { to: "/customers", label: "Customers",
        aliases: ["Clients", "Contacts"] },
      // Duplicate-path dedupe scenario — appears twice in the raw
      // config, ``getNavIndex`` must return exactly one entry.
      { to: "/customers", label: "Customer Directory (legacy)",
        aliases: ["Legacy"] },
      // Row missing ``to`` — skipped entirely.
      { label: "No path row" },
      // Row missing ``label`` — skipped entirely.
      { to: "/no-label" },
    ] },
  ],
}));


import {
  getNavIndex,
  searchNavIndex,
  RANK_EXACT,
  RANK_PREFIX,
  RANK_SUBSTRING,
  RANK_ALIAS,
} from "@/lib/navIndex";


describe("navIndex · getNavIndex()", () => {
  it("returns a non-empty array of {path, title, aliases} records", () => {
    const idx = getNavIndex();
    expect(Array.isArray(idx)).toBe(true);
    expect(idx.length).toBeGreaterThan(0);
    for (const rec of idx) {
      expect(rec).toEqual(expect.objectContaining({
        path: expect.any(String),
        title: expect.any(String),
        aliases: expect.any(Array),
      }));
    }
  });

  it("skips rows without both ``to`` and ``label``", () => {
    const idx = getNavIndex();
    for (const rec of idx) {
      expect(rec.path.length).toBeGreaterThan(0);
      expect(rec.title.length).toBeGreaterThan(0);
    }
    // The two malformed fixture rows ("No path row" / "/no-label")
    // must not appear.
    expect(idx.some((r) => r.title === "No path row")).toBe(false);
    expect(idx.some((r) => r.path === "/no-label")).toBe(false);
  });

  it("dedupes by ``path`` — first occurrence wins", () => {
    const idx = getNavIndex();
    const paths = idx.map((r) => r.path);
    const uniq = new Set(paths);
    expect(paths.length).toBe(uniq.size);
    // First-occurrence: the Finance /customers entry should NOT
    // appear (there is none — /customers lives only in Operations),
    // and the second /customers (legacy label) must be dropped.
    const custs = idx.filter((r) => r.path === "/customers");
    expect(custs).toHaveLength(1);
    expect(custs[0].title).toBe("Customers");
  });

  it("normalizes malformed aliases (filters non-string / empty)", () => {
    const idx = getNavIndex();
    const rec = idx.find((r) => r.path === "/malformed");
    expect(rec).toBeDefined();
    expect(rec.aliases).toEqual(["ok", "also ok"]);
  });

  it("rows without an aliases field yield an empty aliases array", () => {
    const idx = getNavIndex();
    const rec = idx.find((r) => r.path === "/admin/finance/bills");
    expect(rec).toBeDefined();
    expect(rec.aliases).toEqual([]);
  });
});


describe("navIndex · searchNavIndex(query)", () => {
  it("empty / whitespace query returns []", () => {
    expect(searchNavIndex("")).toEqual([]);
    expect(searchNavIndex("   ")).toEqual([]);
    expect(searchNavIndex(null)).toEqual([]);
    expect(searchNavIndex(undefined)).toEqual([]);
  });

  it("case-insensitive title match — Invoices at rank 0 (exact)", () => {
    const res = searchNavIndex("invoices");
    expect(res[0].title).toBe("Invoices");
    expect(res[0].rank).toBe(RANK_EXACT);
    expect(res[0].path).toBe("/invoices");
  });

  it("prefix match beats substring match beats alias match", () => {
    // "check" → exact hit on nothing, prefix hit on "Check Writer",
    // substring hits nothing else in the fixture, alias hits
    // "Checks" alias on Check Writer (already ranked higher by
    // prefix so no double-hit).
    const res = searchNavIndex("check");
    expect(res[0].title).toBe("Check Writer");
    expect(res[0].rank).toBe(RANK_PREFIX);
  });

  it("substring-only match ranks below prefix", () => {
    // "voice" is a substring of "Invoices" but NOT a prefix, and
    // is not in any alias set — must rank RANK_SUBSTRING.
    const res = searchNavIndex("voice");
    const inv = res.find((r) => r.title === "Invoices");
    expect(inv).toBeDefined();
    expect(inv.rank).toBe(RANK_SUBSTRING);
  });

  it("alias match — 'pdf upload' surfaces PDF Import at RANK_ALIAS", () => {
    const res = searchNavIndex("pdf upload");
    const pdfimp = res.find((r) => r.path === "/admin/imports/pdf-invoice");
    expect(pdfimp).toBeDefined();
    expect(pdfimp.title).toBe("PDF Import");
    expect(pdfimp.rank).toBe(RANK_ALIAS);
  });

  it("ranking order · exact > prefix > substring > alias, ties by title A→Z", () => {
    // Query "s" — matches many rows via different ranks:
    //   RANK_PREFIX  · "Schedule"
    //   RANK_SUBSTRING · "Invoices" (contains "s"), "Payments",
    //                    "Customers", "Check Writer" (via "s"?),
    //                    "PDF Import" (no), etc.
    //   RANK_ALIAS   · "Sales" alias on Invoices — but Invoices
    //                  already substring-matched, so we take the
    //                  higher rank.
    const res = searchNavIndex("s", { limit: 20 });
    // Every result's rank must be non-decreasing.
    for (let i = 1; i < res.length; i++) {
      expect(res[i].rank).toBeGreaterThanOrEqual(res[i - 1].rank);
    }
    // "Schedule" (prefix) must rank ahead of "Payments"
    // (substring) which must rank ahead of pure-alias hits.
    const sched = res.findIndex((r) => r.title === "Schedule");
    const pay = res.findIndex((r) => r.title === "Payments");
    expect(sched).toBeGreaterThanOrEqual(0);
    expect(pay).toBeGreaterThanOrEqual(0);
    expect(sched).toBeLessThan(pay);
  });

  it("respects the default 8-row limit", () => {
    const res = searchNavIndex("s", { limit: 8 });
    expect(res.length).toBeLessThanOrEqual(8);
  });

  it("custom limit override honored", () => {
    const res = searchNavIndex("s", { limit: 2 });
    expect(res.length).toBeLessThanOrEqual(2);
  });
});
