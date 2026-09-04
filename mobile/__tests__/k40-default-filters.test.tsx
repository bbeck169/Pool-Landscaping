/**
 * Phase K40 · Feb-2026 — Default all filter dropdowns to "No filter"
 * site-wide (Mobile parity). Cross-page contract check that pins
 * K40 invariants against every mobile list page in scope so a
 * regression trips CI.
 *
 * K40 Rules (mobile-specific application):
 *   1. Category/status/type dropdown filters on list pages default
 *      to "all" / "" on every mount.
 *   3. Customers list EXCEPTION: statusFilter still defaults to
 *      "active".
 *   4. No AsyncStorage persistence for these filter values.
 *
 * Source-body regex pattern — the full pages transitively require
 * expo-router + a large mock graph; this suite pins the specific
 * K40 wiring against the .tsx files directly so any refactor that
 * regresses it fails loudly. Peers using the same pattern:
 * ``customersActiveFilter.test.tsx`` (post-K40 update).
 */
import fs from "node:fs";
import path from "node:path";

const read = (relative: string) =>
  fs.readFileSync(path.resolve(__dirname, "..", relative), "utf-8");

const CUSTOMERS = read("app/(app)/customers.tsx");
const JOBS      = read("app/(app)/jobs.tsx");
const INVOICES  = read("app/invoices.tsx");
const LEADS     = read("app/leads/index.tsx");
const REVIEWS_R = read("app/(app)/reviews/requests/index.tsx");

// ═════════════════════════════════════════════════════════════════
// Rule 1 · Default "all" / "" on every mobile filter
// ═════════════════════════════════════════════════════════════════
describe("K40 · Mobile · Rule 1 — filters default to 'all' / no-filter", () => {
  it("jobs.tsx filter defaults to 'all'", () => {
    expect(JOBS).toMatch(/const \[filter, setFilter\] = useState\("all"\);/);
  });

  it("invoices.tsx filter defaults to 'all'", () => {
    expect(INVOICES).toMatch(
      /const \[filter, setFilter\] = useState\("all"\);/,
    );
  });

  it("leads/index.tsx filter defaults to 'all'", () => {
    expect(LEADS).toMatch(
      /const \[filter, setFilter\] = useState\("all"\);/,
    );
  });

  it("reviews/requests/index.tsx filter defaults to '' (no outcome filter)", () => {
    expect(REVIEWS_R).toMatch(
      /const \[filter, setFilter\] = useState\(""\);/,
    );
  });
});

// ═════════════════════════════════════════════════════════════════
// Rule 3 · Customers list EXCEPTION — statusFilter defaults to Active
// ═════════════════════════════════════════════════════════════════
describe("K40 · Mobile · Rule 3 — Customers exception ('active' default)", () => {
  it("statusFilter initializer is the literal 'active'", () => {
    expect(CUSTOMERS).toMatch(
      /useState<"active" \| "inactive" \| "all" \| "waitlist">\("active"\)/,
    );
  });

  it("portalFilter (the OTHER filter on Customers) still defaults to 'all'", () => {
    expect(CUSTOMERS).toMatch(
      /useState<"all" \| "activated" \| "not_activated">\("all"\)/,
    );
  });
});

// ═════════════════════════════════════════════════════════════════
// Rule 4 · No AsyncStorage persistence for filter values
// ═════════════════════════════════════════════════════════════════
describe("K40 · Mobile · Rule 4 — no AsyncStorage persistence", () => {
  it("customers.tsx has NO storage.getItem / setItem for filter keys", () => {
    expect(CUSTOMERS).not.toMatch(/storage\.getItem[^;]*customerListFilter\./);
    expect(CUSTOMERS).not.toMatch(/storage\.setItem[^;]*customerListFilter\./);
  });

  it("customers.tsx does NOT import the ``@/src/utils/storage`` helper", () => {
    // The storage helper import was stripped by K40 — if a future
    // change reintroduces it, this test fires. (An unrelated storage
    // dep would still land in a different file.)
    expect(CUSTOMERS).not.toMatch(/import\s+\{\s*storage\s*\}\s+from\s+"@\/src\/utils\/storage"/);
  });

  it("jobs.tsx does NOT persist its filter to AsyncStorage", () => {
    // ``jv_`` (last-viewed timestamps) is a per-JOB key, not a
    // filter key — verified by inspection. This assertion pins that
    // NO ``AsyncStorage.setItem`` line carries the string ``filter``.
    expect(JOBS).not.toMatch(/AsyncStorage\.setItem\([^)]*filter/i);
    expect(JOBS).not.toMatch(/storage\.setItem\([^)]*filter/i);
  });

  it("invoices.tsx does NOT persist its filter to AsyncStorage", () => {
    expect(INVOICES).not.toMatch(/AsyncStorage\.setItem\([^)]*filter/i);
    expect(INVOICES).not.toMatch(/storage\.setItem\([^)]*filter/i);
  });

  it("leads/index.tsx does NOT persist its filter to AsyncStorage", () => {
    expect(LEADS).not.toMatch(/AsyncStorage\.setItem\([^)]*filter/i);
    expect(LEADS).not.toMatch(/storage\.setItem\([^)]*filter/i);
  });
});
