/**
 * Phase F6c · Feb-2026 — Web `/customers` Active/Inactive segmented
 * filter parity with mobile (F6b).
 *
 * Contract check via source-body regex against `CustomersList.jsx`.
 * The full page requires auth + router + API mocks + a very large
 * fixture — this suite pins the specific F6c wiring so any future
 * refactor that regresses it fails loudly.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomersList.jsx"),
  "utf-8",
);

describe("CustomersList · F6c active/inactive filter parity", () => {
  it("renders the segmented cohort tabs (Active / Inactive / All)", () => {
    expect(SRC).toMatch(/data-testid="customers-cohort-tabs"/);
    expect(SRC).toMatch(/testid: "tab-active"/);
    expect(SRC).toMatch(/testid: "tab-inactive"/);
    expect(SRC).toMatch(/testid: "tab-all"/);
  });

  it("wires is_active into the /customers fetch", () => {
    // Active → is_active=true, Inactive → is_active=false, no All override.
    expect(SRC).toMatch(
      /if \(tab === "active"\) params\.set\("is_active", "true"\)/,
    );
    expect(SRC).toMatch(
      /else if \(tab === "inactive"\) params\.set\("is_active", "false"\)/,
    );
  });

  it("defaults to Active on first mount", () => {
    // Fallback chain terminates in ``"active"``.
    expect(SRC).toMatch(/return "active";/);
  });

  it("persists the tab under customerListFilter.status in localStorage",
     () => {
    // Phase K40 · Feb-2026 — persistence REMOVED. The old
    // ``_COHORT_STORAGE_KEY`` localStorage plumbing has been stripped
    // per K40 rule #4 (no persistence across page loads). This test
    // now enforces the ABSENCE of that plumbing so a well-meaning
    // future PR doesn't reintroduce it.
    expect(SRC).not.toMatch(/_COHORT_STORAGE_KEY/);
    expect(SRC).not.toMatch(
      /localStorage\.(get|set)Item\([^)]*customerListFilter\.status/,
    );
  });

  it("resets pagination to page 1 on tab change (skips first mount)",
     () => {
    // Must guard with a ref so an initial ``?page=3`` query param
    // isn't stomped on mount.
    expect(SRC).toMatch(/_tabInitRef\s*=\s*React\.useRef\(true\)/);
    expect(SRC).toMatch(/setPage\(1\);/);
  });

  it("URL sync effect still lives in the page (unchanged surface)", () => {
    // Guard against accidentally deleting the pre-existing tab→URL
    // sync that Feb-2026 relies on for shareable links.
    expect(SRC).toMatch(/next\.set\("tab", tab\)/);
  });
});
