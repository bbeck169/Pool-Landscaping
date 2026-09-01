/**
 * Phase G4a · Feb-2026 — CustomersList portal-status filter.
 *
 * Source-body contract check (mirrors the F5 / F6c pattern used
 * across this test suite). Runs against the actual JSX file so any
 * regression that drops the filter, its localStorage plumbing, or
 * the request wiring is caught by CI before it ever hits preview.
 *
 * The full runtime interaction test (render CustomersList, drive
 * the dropdown, capture ``api.get`` calls, snapshot localStorage)
 * needs the router + shell context which many peers in this
 * directory intentionally do NOT wire up — see the F5 and
 * schedule-crew-filter tests for the established shape.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomersList.jsx"),
  "utf-8",
);


describe("CustomersList · G4a portal-status filter", () => {
  it("declares the localStorage key mirroring the F6c convention", () => {
    // Must match ``customerListFilter.portalStatus`` to stack with
    // ``customerListFilter.status`` (the F6c cohort key).
    expect(SRC).toMatch(
      /_PORTAL_STORAGE_KEY\s*=\s*"customerListFilter\.portalStatus"/,
    );
  });

  it("defines exactly three portal-status options", () => {
    expect(SRC).toMatch(
      /_PORTAL_STATUS_OPTIONS\s*=\s*\[[\s\S]{0,600}"all"[\s\S]{0,600}"activated"[\s\S]{0,600}"not_activated"[\s\S]{0,80}\]/,
    );
  });

  it("hydrates initial value from localStorage under the G4a key", () => {
    expect(SRC).toMatch(
      /localStorage\.getItem\(_PORTAL_STORAGE_KEY\)/,
    );
  });

  it("persists the selection back to localStorage", () => {
    expect(SRC).toMatch(
      /localStorage\.setItem\(_PORTAL_STORAGE_KEY,\s*portalStatus\)/,
    );
  });

  it("resets pagination to page 1 on filter change (not on mount)", () => {
    // Mount-skip guard identical to the F6c cohort effect.
    expect(SRC).toMatch(/_portalStatusInitRef/);
    // Effect body sets page back to 1 when the ref flips.
    expect(SRC).toMatch(
      /_portalStatusInitRef\.current\s*=\s*false;[\s\S]{0,60}return;\s*\}\s*setPage\(1\);/,
    );
  });

  it("sends ?portal_status=<value> to /api/customers only when non-default", () => {
    // The load() body should skip the param when portalStatus === "all"
    // so the wire log stays clean.
    expect(SRC).toMatch(
      /if\s*\(portalStatus\s*&&\s*portalStatus\s*!==\s*"all"\)\s*\{\s*params\.set\("portal_status",\s*portalStatus\);/,
    );
  });

  it("adds portalStatus to the load() effect dep-array", () => {
    // Otherwise the fetch does not refetch on dropdown change.
    expect(SRC).toMatch(
      /\[searchDeb[\s\S]{0,400}portalStatus\]/,
    );
  });

  it("renders the dropdown with the G4a testid + all three options", () => {
    expect(SRC).toMatch(
      /data-testid="customers-filter-portal-status"/,
    );
    expect(SRC).toMatch(
      /data-testid={`portal-status-option-\$\{o\.value\}`}/,
    );
  });

  it("dropdown lives inside the shared 'Filter row' toolbar (visual parity with sort)", () => {
    // The G4a select must appear AFTER the sort select and BEFORE
    // the city select so it sits alongside the other segmented
    // filters — that's the "Portal" chip the human spec calls for.
    const sortIdx = SRC.indexOf('data-testid="customers-filter-sort"');
    const portalIdx = SRC.indexOf('data-testid="customers-filter-portal-status"');
    expect(sortIdx).toBeGreaterThan(-1);
    expect(portalIdx).toBeGreaterThan(sortIdx);
  });
});


describe("G4a · segmented cohort tabs still ship (no accidental removal)", () => {
  it("preserves the F6c segmented cohort tab shell so the two filters stack", () => {
    // Regression guard: the portal filter must NOT have replaced
    // the segmented tabs — spec says STACKS with them.
    expect(SRC).toMatch(/data-testid="customers-cohort-tabs"/);
    expect(SRC).toMatch(/testid:\s*"tab-active"/);
    expect(SRC).toMatch(/testid:\s*"tab-inactive"/);
    expect(SRC).toMatch(/testid:\s*"tab-muted"/);
    expect(SRC).toMatch(/testid:\s*"tab-all"/);
  });
});
