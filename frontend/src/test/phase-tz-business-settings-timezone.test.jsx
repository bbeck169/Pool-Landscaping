/**
 * Feb-2026 · Timezone Finalization — parity guard.
 *
 * BillingSettings.jsx and BusinessSettings.jsx both import the same
 * TimezoneSelect + save through the same PATCH endpoint. A future
 * refactor that inlines the picker on one page would silently break
 * the "set on one page → shown on the other" contract. This test
 * pins the shared-component import path so a divergence fails CI
 * before it ships.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const ROOT = "/app/frontend/src";

function readSrc(relative) {
  return readFileSync(join(ROOT, relative), "utf-8");
}

describe("BillingSettings + BusinessSettings TimezoneSelect parity", () => {
  it("BillingSettings imports the shared TimezoneSelect component", () => {
    const src = readSrc("pages/settings/BillingSettings.jsx");
    expect(src).toMatch(
      /import\s*\{\s*TimezoneSelect\s*\}\s*from\s*["']@\/components\/settings\/TimezoneSelect["']/,
    );
  });

  it("BusinessSettings imports the shared TimezoneSelect component", () => {
    const src = readSrc("pages/settings/BusinessSettings.jsx");
    expect(src).toMatch(
      /import\s*\{\s*TimezoneSelect\s*\}\s*from\s*["']@\/components\/settings\/TimezoneSelect["']/,
    );
  });

  it("BillingSettings does NOT re-inline a raw <select> for timezone options", () => {
    // Guard: the pre-fix code had six literal <option value="…"> tags
    // inline. After the extraction, only the shared component owns them.
    const src = readSrc("pages/settings/BillingSettings.jsx");
    expect(src).not.toMatch(/<option value="America\/Phoenix"/);
    expect(src).not.toMatch(/<option value="America\/Los_Angeles"/);
  });

  it("Both pages save through PATCH /tenants/mine/settings with a timezone body", () => {
    const billing = readSrc("pages/settings/BillingSettings.jsx");
    const business = readSrc("pages/settings/BusinessSettings.jsx");
    for (const src of [billing, business]) {
      expect(src).toMatch(/api\.patch\(\s*["']\/tenants\/mine\/settings["']/);
      expect(src).toMatch(/timezone\s*:\s*nextTz/);
    }
  });

  it("BillingSettings preserves the ``tenant-timezone-picker`` data-testid for E2E parity", () => {
    // The E2E suite keys on this exact string. Even after extraction
    // the Billing surface must keep the same testid.
    const src = readSrc("pages/settings/BillingSettings.jsx");
    expect(src).toMatch(/testid=["']tenant-timezone-picker["']/);
  });

  it("BusinessSettings uses a disambiguated testid so both pickers can co-exist on one screen if ever bundled", () => {
    const src = readSrc("pages/settings/BusinessSettings.jsx");
    expect(src).toMatch(/testid=["']bs-tenant-timezone-picker["']/);
  });

  it("Both pages honor the shared i18n key ``timezone.label``", () => {
    // The English label routes through the i18n pipeline (or
    // the shared component's default) so a locale switch does
    // not leave the picker's label in English on a Spanish page.
    const business = readSrc("pages/settings/BusinessSettings.jsx");
    expect(business).toMatch(/t\(["']timezone\.label["']/);
  });
});
