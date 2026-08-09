/**
 * Phase 54g / 54g-B · Feb-2026 — mobile supplier analytics source-inspection.
 *
 * Locks the shape of the mobile ``app/reports/supplier-syncs.tsx``
 * screen. Phase 54g-B upgrades the interim card list with a
 * sparkline, retry-queue summary badges, and a proper admin-plus
 * role gate.
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

// ── Phase 54g-B upgrades ────────────────────────────────────────────
describe("Phase 54g-B · mobile supplier analytics upgrades", () => {
  it("wraps the body in a shared RoleGate at admin_plus", () => {
    const src = read("app/reports/supplier-syncs.tsx");
    expect(src).toContain("RoleGate");
    expect(src).toMatch(/level=\"admin_plus\"/);
  });

  it("renders an SVG sparkline per supplier via react-native-svg", () => {
    const src = read("app/reports/supplier-syncs.tsx");
    expect(src).toContain('from "react-native-svg"');
    expect(src).toContain("mobile-analytics-sparkline-${s.slug}");
    // Both success (green) + error (red) segments are drawn.
    expect(src).toContain("#16A34A");
    expect(src).toContain("#DC2626");
  });

  it("surfaces the aggregated retry-queue summary", () => {
    const src = read("app/reports/supplier-syncs.tsx");
    for (const k of [
      "mobile-analytics-summary",
      "mobile-analytics-summary-critical",
      "mobile-analytics-summary-warning",
      "mobile-analytics-summary-retries",
      "mobile-analytics-summary-errors",
    ]) {
      expect(src).toContain(k);
    }
  });

  it("shows per-supplier failure + retry badges when relevant", () => {
    const src = read("app/reports/supplier-syncs.tsx");
    expect(src).toContain("mobile-analytics-failure-badge-${s.slug}");
    expect(src).toContain("mobile-analytics-retry-badge-${s.slug}");
    // Retry summary maps to ``consecutive_errors`` from the endpoint.
    expect(src).toContain("consecutive_errors");
  });

  it("still supports pull-to-refresh + reuses /suppliers/analytics endpoint", () => {
    const src = read("app/reports/supplier-syncs.tsx");
    expect(src).toContain("RefreshControl");
    expect(src).toContain("/suppliers/analytics?days=");
  });
});
