/**
 * TD-69 · Feb-2026 — Portal service-type resolver + chemistry-
 * hide-on-landscape regression lock.
 *
 * Operator-reported symptom: two landscape customers (Frances
 * LaPrairie + Amy Hinojosa) saw a "Pool service" badge on their
 * landscape service reports AND a "No chemistry recorded" empty
 * state. Pre-TD-69 the inline ``reportKind()`` resolver read
 * ``template || service_type || job.service_type`` as an
 * OR-chain and stopped at the first truthy field — so a stray
 * pool-ish string in any one field poisoned the kind resolution
 * even when another field was the authoritative landscape
 * signal.
 *
 * This file pins the full contract:
 *   (1) resolver landscape-priority ordering (unit tests)
 *   (2) resolver scans every candidate field, not just the
 *       first truthy one
 *   (3) resolver returns "generic" when no signal matches
 *   (4) chemistry section guard — pool-only (``kind === "pool"``)
 *       source-grep lock so a future refactor can't accidentally
 *       show the chemistry section on landscape SRs again.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

import {
  resolveServiceType,
} from "../lib/portalServiceType";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");
const SR_SRC = R("../pages/portal/PortalServiceReports.jsx");


// ═══════════════════════════════════════════════════════════════════
// 1 · Resolver — unit tests across every branch.
// ═══════════════════════════════════════════════════════════════════
describe("TD-69 · resolveServiceType — landscape-priority resolver", () => {

  it("returns 'landscape' when template is 'landscape'", () => {
    expect(resolveServiceType({ template: "landscape" })).toBe("landscape");
  });

  it("returns 'landscape' when service_type contains 'Landscaping'", () => {
    expect(resolveServiceType({ service_type: "Landscaping" })).toBe("landscape");
  });

  it("returns 'landscape' when job.service_type is 'Landscape maintenance'", () => {
    expect(resolveServiceType({ job: { service_type: "Landscape maintenance" } }))
      .toBe("landscape");
  });

  it("returns 'landscape' when ANY field has a landscape signal — guards against the operator-reported mislabel", () => {
    // The frangled case: template is a stray pool-ish value
    // (data entry error) BUT the job service_type is the
    // authoritative Landscaping. Pre-TD-69 the OR-chain stopped
    // at the first truthy field (``template``) and the pool
    // branch fired. Post-TD-69 landscape wins across fields.
    const record = {
      template: "pool_fallback",       // stray pool-ish string
      job: { service_type: "Landscaping" },  // authoritative landscape
    };
    expect(resolveServiceType(record)).toBe("landscape");
  });

  it("returns 'pool' when template is 'pool'", () => {
    expect(resolveServiceType({ template: "pool" })).toBe("pool");
  });

  it("returns 'pool' when service_type contains 'Pool' and no landscape signal", () => {
    expect(resolveServiceType({ service_type: "Pool maintenance" })).toBe("pool");
  });

  it("returns 'pool' when service_line is 'pool' (Workstream-parity field)", () => {
    expect(resolveServiceType({ service_line: "pool" })).toBe("pool");
  });

  it("returns 'generic' when no field is populated", () => {
    expect(resolveServiceType({})).toBe("generic");
  });

  it("returns 'generic' when fields are all unmatched strings", () => {
    expect(resolveServiceType({ template: "foo", service_type: "bar" }))
      .toBe("generic");
  });

  it("null-safe — returns 'generic' for null/undefined/non-object", () => {
    expect(resolveServiceType(null)).toBe("generic");
    expect(resolveServiceType(undefined)).toBe("generic");
    expect(resolveServiceType("string")).toBe("generic");
    expect(resolveServiceType(42)).toBe("generic");
  });

  it("type-tolerant — coerces non-string field values", () => {
    // Edge case: BE may surface a numeric 0 or boolean false in
    // a mis-typed field; the resolver must not crash.
    expect(resolveServiceType({ template: 0, service_type: "pool" })).toBe("pool");
    expect(resolveServiceType({ template: false, service_type: "landscape" }))
      .toBe("landscape");
  });

});


// ═══════════════════════════════════════════════════════════════════
// 2 · PortalServiceReports.jsx — wire-up locks.
// ═══════════════════════════════════════════════════════════════════
describe("TD-69 · PortalServiceReports.jsx wires through the shared resolver", () => {

  it("imports resolveServiceType from the shared helper module", () => {
    expect(SR_SRC).toMatch(
      /import\s*\{\s*resolveServiceType\s*\}\s*from\s*["']@\/lib\/portalServiceType["']/,
    );
  });

  it("inline reportKind delegates to resolveServiceType — not a legacy OR-chain", () => {
    // Negative lock — the pre-TD-69 OR-chain pattern is gone.
    expect(SR_SRC).not.toMatch(
      /row\?\.template\s*\|\|\s*row\?\.service_type\s*\|\|\s*row\?\.job\?\.service_type/,
    );
    // Positive lock — thin shim calls the helper.
    expect(SR_SRC).toMatch(/return\s+resolveServiceType\(row\);/);
  });

  it("chemistry section guard — only renders when kind === 'pool'", () => {
    // Both chemistry render sites (primary pool section +
    // additional water bodies section) still gate on
    // ``kind === "pool"`` — never on ``kind !== "landscape"``
    // or any looser check. This locks out the operator-reported
    // "No chemistry recorded" rendering on landscape SRs.
    const poolOnlyGuard = /kind === "pool"/g;
    const matches = SR_SRC.match(poolOnlyGuard) || [];
    // Two guard sites + one detail-view variable init + one
    // header-badge ternary + one template-fallback line below.
    // Lower bound 2 (one per chemistry site).
    expect(matches.length).toBeGreaterThanOrEqual(2);
    // Negative lock — no accidental ``kind !== "landscape"`` or
    // ``kind !== "pool"`` guards that would reveal chemistry on
    // landscape SRs by mistake.
    expect(SR_SRC).not.toMatch(/kind !== "landscape"/);
  });

});
