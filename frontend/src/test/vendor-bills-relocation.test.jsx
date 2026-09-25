/**
 * Task B · Phase 2 · Commit 1.5 — Vendor Bills relocation guard.
 *
 * Ground-truth history: Vendor Bills was historically mis-grouped
 * inside the Reports group (``adminNav.js`` ``{ key: "reports" }``
 * opened at line ~294) despite being a Finance / Invoicing
 * surface (payable-side invoices).  Commit 1.5 relocates the
 * row into Finance/Invoicing directly after PDF Import so
 * operators find:
 *
 *   * the receivable side (Invoices, Master Invoices,
 *     Auto-billing, Autobilling runs) — INVOICES you send OUT
 *   * the payable side (PDF Import → Vendor Bills) — INVOICES
 *     you receive
 *
 * in one place.
 *
 * Contract locked by this file:
 *
 *   1. Only ONE row references ``/admin/finance/bills`` — no
 *      duplicate left behind in Reports.
 *   2. That row sits inside the Finance group (before the
 *      ``ai_employees`` group opener) — not inside Reports.
 *   3. It lives in the Invoicing subsection (adjacent to PDF
 *      Import) with ``feature: "invoices"`` (was ``feature:
 *      "reports"`` in the mis-grouped era).
 *   4. Source ordering: Autobilling runs → PDF Import →
 *      Vendor Bills → Late Fees — strict ascending.
 *   5. Row properties preserved from the pre-relocation row:
 *      ``to: "/admin/finance/bills"``, ``label: "Vendor Bills"``,
 *      ``icon: Receipt``.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const NAV_SRC = readFileSync(
  resolve(__dirname, "../nav/adminNav.js"),
  "utf8",
);


describe("Vendor Bills · relocated to Finance/Invoicing " +
         "(Commit 1.5 · Feb-2026)", () => {
  it("appears exactly once in adminNav.js — no duplicate left " +
     "behind in the Reports group", () => {
    const rowMatches = NAV_SRC.match(
      /{\s*to:\s*"\/admin\/finance\/bills"/g,
    ) || [];
    expect(rowMatches.length).toBe(1);
  });

  it("sits inside the Finance group (before the ai_employees " +
     "opener) — not inside Reports", () => {
    const rowIdx = NAV_SRC.indexOf('to: "/admin/finance/bills"');
    const aiEmployeesOpenerIdx = NAV_SRC.indexOf(
      '{ key: "ai_employees"');
    const reportsOpenerIdx = NAV_SRC.indexOf(
      '{ key: "reports"');
    expect(rowIdx).toBeGreaterThan(-1);
    expect(aiEmployeesOpenerIdx).toBeGreaterThan(-1);
    expect(reportsOpenerIdx).toBeGreaterThan(-1);
    // Row must land in Finance (before ai_employees) — the
    // Reports group opens WAY later.
    expect(rowIdx).toBeLessThan(aiEmployeesOpenerIdx);
    expect(rowIdx).toBeLessThan(reportsOpenerIdx);
  });

  it("carries the Invoicing subsection + feature invoices " +
     "(was Reports-group with feature reports pre-relocation)", () => {
    const rowIdx = NAV_SRC.indexOf('to: "/admin/finance/bills"');
    const rowSlice = NAV_SRC.slice(rowIdx, rowIdx + 300);
    expect(rowSlice).toMatch(/subsection:\s*"Invoicing"/);
    expect(rowSlice).toMatch(/feature:\s*"invoices"/);
    // Preserved properties from the pre-relocation row.
    expect(rowSlice).toMatch(/label:\s*"Vendor Bills"/);
    expect(rowSlice).toMatch(/icon:\s*Receipt/);
    // NEGATIVE guard — the old feature-bucket must NOT survive.
    expect(rowSlice).not.toMatch(/feature:\s*"reports"/);
  });

  it("sits directly after PDF Import — Autobilling runs → PDF " +
     "Import → Vendor Bills → Late Fees strict ordering", () => {
    const autobillingIdx = NAV_SRC.indexOf('to: "/admin/autobilling-runs"');
    const pdfImportIdx   = NAV_SRC.indexOf('to: "/admin/imports/pdf-invoice"');
    const vendorIdx      = NAV_SRC.indexOf('to: "/admin/finance/bills"');
    const lateFeesIdx    = NAV_SRC.indexOf('to: "/settings/late-fees"');
    expect(autobillingIdx).toBeGreaterThan(-1);
    expect(pdfImportIdx).toBeGreaterThan(-1);
    expect(vendorIdx).toBeGreaterThan(-1);
    expect(lateFeesIdx).toBeGreaterThan(-1);
    expect(autobillingIdx).toBeLessThan(pdfImportIdx);
    expect(pdfImportIdx).toBeLessThan(vendorIdx);
    expect(vendorIdx).toBeLessThan(lateFeesIdx);
    // No other invoicing rows sneak between PDF Import and
    // Vendor Bills — window guard.
    expect(vendorIdx - pdfImportIdx).toBeLessThan(1000);
  });
});
