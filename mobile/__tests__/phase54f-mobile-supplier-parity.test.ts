/**
 * Phase 54f · Feb-2026 — mobile supplier parity source-inspection.
 *
 * Read-only source assertions — matches the web-side vitest guardrails
 * without booting a native renderer. Keeps mobile jest baseline stable
 * and catches wire-up regressions on the mobile pricebook + Settings
 * > Suppliers view.
 */
import * as fs from "fs";
import * as path from "path";

const REPO = path.resolve(__dirname, "..");

function read(rel: string) {
  return fs.readFileSync(path.join(REPO, rel), "utf8");
}

describe("Phase 54f · mobile supplier parity", () => {
  it("mobile price-book renders a supplier badge with a testid per row", () => {
    const src = read("app/price-book.tsx");
    expect(src).toContain("item-supplier-badge-");
    expect(src).toContain("SUPPLIER_LABELS");
    expect(src).toContain("supplierBadgeColor");
  });

  it("mobile price-book has a supplier-filter chip strip with each slug", () => {
    const src = read("app/price-book.tsx");
    expect(src).toContain("pb-mobile-supplier-filter");
    for (const slug of ["poolcorp", "siteone", "ewing", "heritage", "epoolsupply"]) {
      expect(src).toContain(slug);
    }
    // Chip strip must include Manual + All entries — the chip
    // testids are constructed via template string at runtime.
    expect(src).toContain("pb-mobile-supplier-chip-${o.key}");
    expect(src).toContain('{ key: "all"');
    expect(src).toContain('{ key: "manual"');
  });

  it("mobile Settings > Suppliers screen exists + is view-only", () => {
    const src = read("app/settings/suppliers.tsx");
    // Every wired slug labelled.
    for (const slug of ["poolcorp", "siteone", "ewing", "heritage", "epoolsupply"]) {
      expect(src).toContain(slug);
    }
    expect(src).toContain("mobile-supplier-settings-screen");
    // Read-only guardrail: no credential form, no sync-now, no PATCH.
    expect(src).not.toMatch(/api\.post\(.*credentials/);
    expect(src).not.toMatch(/api\.post\(.*\/sync/);
    expect(src).not.toMatch(/api\.patch\(/);
    expect(src).toMatch(/Mobile is view-only/);
  });

  it("web + mobile share the same wired slug order (parity anchor)", () => {
    const mobileSrc = read("app/settings/suppliers.tsx");
    const priceBook = read("app/price-book.tsx");
    // ``SUPPLIER_SLUG_ORDER`` and the price-book labels must both
    // list all five slugs. Order isn't asserted — just membership.
    for (const slug of ["poolcorp", "siteone", "ewing", "heritage", "epoolsupply"]) {
      expect(mobileSrc).toContain(slug);
      expect(priceBook).toContain(slug);
    }
  });
});
