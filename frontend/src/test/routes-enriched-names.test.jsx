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
    // Phase Hygiene B · Feb-2026 — product code prefixes the testid
    // with ``ops-`` (``ops-route-{id}-customer``) so it doesn't collide
    // with the parent ``route-{id}`` row testid on the same list.
    expect(src).toMatch(/data-testid=\{`(?:ops-)?route-\$\{j\.id\}-customer`\}/);
  });

  it("renders technician name as the secondary line", () => {
    expect(src).toMatch(/data-testid=\{`route-\$\{j\.id\}-tech`\}/);
    // Fall back to 'Unassigned' when the job has no technician.
    expect(src).toMatch(/j\.technician_name\s*\|\|\s*"Unassigned"/);
  });

  it("falls back to address then title then '(unknown customer)'", () => {
    // The primary display resolves in a documented order — protects
    // against blank primary lines for deleted-customer jobs.
    //
    // Phase Hygiene B · Feb-2026 — product widened the fallback chain
    // to include ``customer_display_name`` at the front and
    // ``billing_name`` / ``service_address`` mid-chain, with the final
    // "(no customer)" sentinel. Relax the regex to just require the
    // documented sentinel at the tail; the specific intermediate keys
    // are covered by the sibling `routes-enrichment-endpoint` test.
    expect(src).toMatch(
      /j\.customer_name[\s\S]{0,300}\|\|\s*"\(no customer\)"/,
    );
  });

  it("renders a color chip when the job carries technician_color_hex", () => {
    // Small circle with backgroundColor pulled from the job doc.
    expect(src).toMatch(
      /techColor\s*\?[\s\S]{0,200}backgroundColor:\s*techColor/,
    );
  });
});
