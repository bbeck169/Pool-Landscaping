/**
 * Routes tab enrichment · Feb-2026.
 *
 * Contract test — asserts the Routes tab renders both customer name
 * and technician name on each stop, with a tech-color chip when the
 * job doc carries one, and falls back gracefully when the customer
 * was deleted. Source-inspection style (matches the sibling
 * ``admin-sidebar-pinned-nav`` and ``recurring-jobs-ends-mode``
 * tests) — avoids mounting the full 2700-line OpsHub tree.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const src = fs.readFileSync(
  path.resolve(__dirname, "../pages/ops/OpsHub.jsx"),
  "utf8",
);

describe("Routes tab · enrichment", () => {
  it("wires the enrichment endpoint when a specific tech is selected", () => {
    // The load() body must hit /routes/{techId}/stops?date=... when
    // techId is truthy. Legacy /jobs client-filter path stays for the
    // "All techs" fallback only.
    expect(src).toMatch(
      /if\s*\(techId\)\s*\{[\s\S]{0,200}api\.get\(`\/routes\/\$\{techId\}\/stops\?date=\$\{date\}`\)/,
    );
  });

  it("renders customer name as the primary line", () => {
    expect(src).toMatch(/data-testid=\{`route-\$\{j\.id\}-customer`\}/);
  });

  it("renders technician name as the secondary line", () => {
    expect(src).toMatch(/data-testid=\{`route-\$\{j\.id\}-tech`\}/);
    // Fall back to 'Unassigned' when the job has no technician.
    expect(src).toMatch(/j\.technician_name\s*\|\|\s*"Unassigned"/);
  });

  it("falls back to address then title then '(unknown customer)'", () => {
    // The primary display resolves in that order — protects against
    // blank primary lines for deleted-customer jobs.
    expect(src).toMatch(
      /j\.customer_name\s*\|\|\s*j\.address\s*\|\|\s*j\.title\s*\|\|\s*"\(unknown customer\)"/,
    );
  });

  it("renders a color chip when the job carries technician_color_hex", () => {
    // Small circle with backgroundColor pulled from the job doc.
    expect(src).toMatch(
      /techColor\s*\?[\s\S]{0,200}backgroundColor:\s*techColor/,
    );
  });
});
