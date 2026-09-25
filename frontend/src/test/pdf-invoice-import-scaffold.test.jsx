/**
 * Task B · Phase 2 · Commit 1 — PdfInvoiceImportPage scaffold guards.
 *
 * Locks the idle-state contract for the new admin page landing at
 * ``/admin/imports/pdf-invoice``:
 *
 *   1. Page component renders WITHOUT throwing (idle state).
 *   2. Page root carries the ``pdf-invoice-import-page`` testid,
 *      the header + subtitle carry the ``pdf-import-header`` testid,
 *      and the file-choose button carries the
 *      ``pdf-import-choose-files-btn`` testid.
 *   3. The hidden ``<input type="file" multiple accept="application/pdf">``
 *      is present with the expected attributes so downstream
 *      commits (upload flow) have a wire-up point.
 *   4. The cap-summary strip announces the frozen client-side
 *      limits (20 files / 10 MB / admin-only) so operators see
 *      the caps up front — file-inspect for the literal strings.
 *
 * Route + sidebar wiring is locked via source-inspect (mounting
 * the full AppLayout pulls in ~200 routes).  Two guards:
 *
 *   * ``App.js`` registers ``admin/imports/pdf-invoice`` under
 *     ``<AdminOnly>`` (matches the backend ``require_admin`` gate).
 *   * ``adminNav.js`` inserts the entry inside the Finance group
 *     immediately after ``/admin/finance/bills`` (Vendor Bills),
 *     with ``hard_rule: "admin_only"`` per Phase 2 ruling E.4.
 */
import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import PdfInvoiceImportPage, {
  MAX_FILES_PER_BATCH,
  MAX_BYTES_PER_FILE,
  SOFT_WARN_FILES,
  CONCURRENCY_POOL,
} from "@/pages/admin/imports/PdfInvoiceImportPage";


const APP_SRC = readFileSync(
  resolve(__dirname, "../App.js"),
  "utf8",
);
const NAV_SRC = readFileSync(
  resolve(__dirname, "../nav/adminNav.js"),
  "utf8",
);


describe("PdfInvoiceImportPage · frozen client-side caps", () => {
  it("exports the three cap constants + concurrency pool", () => {
    // Committing these values as exported constants so downstream
    // commits (Commit 2 upload flow, Commit 3 poll loop) import
    // the same source-of-truth.
    expect(MAX_FILES_PER_BATCH).toBe(20);
    expect(MAX_BYTES_PER_FILE).toBe(10 * 1024 * 1024);
    expect(SOFT_WARN_FILES).toBe(10);
    expect(CONCURRENCY_POOL).toBe(2);
  });
});


describe("PdfInvoiceImportPage · idle-state render", () => {
  it("mounts without throwing and renders the header, dropzone, " +
     "and cap-summary strip", () => {
    render(<PdfInvoiceImportPage />);
    // Root + header + dropzone + button + input + cap strip.
    expect(
      screen.getByTestId("pdf-invoice-import-page"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("pdf-import-idle-zone"),
    ).toBeTruthy();
    const btn = screen.getByTestId("pdf-import-choose-files-btn");
    expect(btn).toBeTruthy();
    expect(btn.textContent).toMatch(/Choose PDF/);
    expect(
      screen.getByTestId("pdf-import-caps-strip"),
    ).toBeTruthy();
  });

  it("emits a hidden multipart PDF-accepting <input> with the " +
     "expected attributes for later wire-up", () => {
    render(<PdfInvoiceImportPage />);
    const input = screen.getByTestId("pdf-import-file-input");
    expect(input).toBeTruthy();
    expect(input.tagName.toLowerCase()).toBe("input");
    expect(input.getAttribute("type")).toBe("file");
    expect(input.hasAttribute("multiple")).toBe(true);
    expect(input.getAttribute("accept")).toBe("application/pdf");
    expect(input.hasAttribute("hidden")).toBe(true);
  });

  it("cap-summary strip surfaces the three frozen limits", () => {
    render(<PdfInvoiceImportPage />);
    const strip = screen.getByTestId("pdf-import-caps-strip");
    // Full text — literal strings so operators see them.
    expect(strip.textContent).toMatch(/Max 20 PDFs per batch/);
    expect(strip.textContent).toMatch(/Max 10 MB per PDF/);
    expect(strip.textContent).toMatch(/Admin-only/);
  });
});


describe("Task B · Commit 1 route + sidebar wiring (source-inspect)", () => {
  it("App.js lazy-loads PdfInvoiceImportPage from the admin/imports " +
     "chunk and mounts it under <AdminOnly>", () => {
    // Lazy import — chunk name is stable so bundle analysis can
    // find the page.
    expect(APP_SRC).toMatch(
      /const PdfInvoiceImportPage = React\.lazy\(\(\)\s*=>\s*import\(/,
    );
    expect(APP_SRC).toMatch(
      /webpackChunkName:\s*"p-admin-imports-pdfinvoice"/,
    );
    // Route element — the admin-only wrap is a strict requirement
    // per §E.4 (matches backend require_admin).
    expect(APP_SRC).toMatch(
      /<Route path="admin\/imports\/pdf-invoice" element=\{<AdminOnly><PdfInvoiceImportPage \/><\/AdminOnly>\} \/>/,
    );
  });

  it("adminNav.js inserts the PDF Import entry inside the Finance " +
     "group / Invoicing subsection immediately after Autobilling " +
     "runs, with admin_only rule", () => {
    // Sidebar-placement halt ruling (Option A) — the entry lives
    // in Finance/Invoicing (semantically correct — invoice-
    // producing action).  The recon report §B misread Vendor
    // Bills as Finance-grouped when it actually lived in Reports;
    // Vendor Bills gets relocated adjacent in a follow-up commit.
    //
    // Ordering lock — Autobilling runs sits before PDF Import,
    // and PDF Import sits before Late Fees (all three are in
    // Finance/Invoicing).
    const autobillingIdx = NAV_SRC.indexOf('to: "/admin/autobilling-runs"');
    const importIdx      = NAV_SRC.indexOf('to: "/admin/imports/pdf-invoice"');
    const lateFeesIdx    = NAV_SRC.indexOf('to: "/settings/late-fees"');
    expect(autobillingIdx).toBeGreaterThan(-1);
    expect(importIdx).toBeGreaterThan(autobillingIdx);
    expect(lateFeesIdx).toBeGreaterThan(importIdx);
    // The new entry must sit inside the Finance group — grep
    // guard: PDF Import's line must appear BEFORE the ai_employees
    // group opens.
    const aiEmployeesOpenerIdx = NAV_SRC.indexOf(
      '{ key: "ai_employees"');
    expect(aiEmployeesOpenerIdx).toBeGreaterThan(-1);
    expect(importIdx).toBeLessThan(aiEmployeesOpenerIdx);
    // Row properties.
    const importSlice = NAV_SRC.slice(importIdx, importIdx + 300);
    expect(importSlice).toMatch(/hard_rule:\s*"admin_only"/);
    expect(importSlice).toMatch(/feature:\s*"invoices"/);
    expect(importSlice).toMatch(/subsection:\s*"Invoicing"/);
    expect(importSlice).toMatch(/label:\s*"PDF Import"/);
    expect(importSlice).toMatch(/icon:\s*UploadCloud/);
  });

  it("adminNav.js imports UploadCloud from lucide-react", () => {
    // The icon barrel must include UploadCloud so the new entry
    // above doesn't render a broken import at build time.
    expect(NAV_SRC).toMatch(
      /import\s+\{[\s\S]*UploadCloud[\s\S]*\}\s+from\s+["']lucide-react["']/,
    );
  });
});
