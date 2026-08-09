/**
 * Phase 54g · Feb-2026 — mobile supplier analytics source-inspection.
 */
import * as fs from "fs";
import * as path from "path";

const REPO = path.resolve(__dirname, "..");
function read(rel: string) {
  return fs.readFileSync(path.join(REPO, rel), "utf8");
}

describe("Phase 54g · mobile supplier analytics", () => {
  it("mobile analytics screen exists at /app/reports/supplier-syncs.tsx", () => {
    const src = read("app/reports/supplier-syncs.tsx");
    expect(src).toContain("mobile-supplier-analytics-screen");
    // View-only — no POST/PATCH surface.
    expect(src).not.toMatch(/api\.post\(/);
    expect(src).not.toMatch(/api\.patch\(/);
  });

  it("renders the three health-signal palettes + range chips", () => {
    const src = read("app/reports/supplier-syncs.tsx");
    for (const sig of ["healthy", "warning", "critical"]) {
      expect(src).toContain(sig);
    }
    // Range chip test-ids are template-literal — the raw source
    // contains the ``${n}`` placeholder.
    expect(src).toContain("mobile-analytics-range-${n}");
    for (const r of [7, 30, 60, 90]) {
      expect(src).toContain(`${r}`);
    }
  });

  it("carries testid hooks for card + signal + error per supplier", () => {
    const src = read("app/reports/supplier-syncs.tsx");
    expect(src).toContain("mobile-analytics-card-${s.slug}");
    expect(src).toContain("mobile-analytics-signal-${s.slug}");
    expect(src).toContain("mobile-analytics-error-${s.slug}");
  });
});
