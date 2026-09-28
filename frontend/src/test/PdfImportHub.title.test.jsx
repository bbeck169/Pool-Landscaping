/**
 * PDF-HUB · Feb-2026 — Page title + subtitle vitest suite.
 *
 * Locks the visible rebranding from "PDF Invoice Import" to
 * "PDF Import Hub" + the multi-type subtitle. Regression guard
 * against a future copy edit accidentally reverting.
 *
 * Also verifies the sidebar/nav config file was updated to match
 * (source-inspect since mounting the full nav pulls in every
 * feature-flag helper).
 */
import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import PdfInvoiceImportPage from "@/pages/admin/imports/PdfInvoiceImportPage";


const NAV_SRC = readFileSync(
  resolve(__dirname, "../nav/adminNav.js"),
  "utf8",
);


describe("PDF-HUB · Page header render", () => {
  it("renders the 'PDF Import Hub' title", () => {
    render(<PdfInvoiceImportPage />);
    // ``PageHeader`` renders the title inside an <h1>; the query
    // via getByText matches the visible text so a future refactor
    // that changes the heading level still passes.
    const hit = screen.getByText("PDF Import Hub");
    expect(hit).toBeTruthy();
    // Guard: the previous title must NOT still be rendered — no
    // stale "PDF Invoice Import" copy anywhere on the page.
    expect(screen.queryByText("PDF Invoice Import")).toBeNull();
  });

  it("renders the multi-type subtitle mentioning Invoices, " +
     "Estimates, and Payment History", () => {
    render(<PdfInvoiceImportPage />);
    // Subtitle content-safety: mentions all three doc kinds so
    // operators know the hub is not invoice-only.
    const page = screen.getByTestId("pdf-invoice-import-page");
    const text = page.textContent || "";
    expect(text).toMatch(/Upload PDFs/);
    expect(text).toMatch(/Invoices/);
    expect(text).toMatch(/Estimates/);
    expect(text).toMatch(/Payment History/);
    // Legacy "draft invoices" copy must NOT survive the rename.
    expect(text).not.toMatch(/turn them into draft invoices/);
  });
});


describe("PDF-HUB · Nav config label update", () => {
  it("sidebar entry label is 'PDF Import Hub' (not the legacy " +
     "'PDF Import' or 'PDF Invoice Import')", () => {
    expect(NAV_SRC).toMatch(/label:\s*"PDF Import Hub"/);
    // Legacy labels must NOT appear as the primary ``label`` (they
    // may still live in the ``aliases`` array for backward-compat
    // search hits — that's allowed).
    expect(NAV_SRC).not.toMatch(/label:\s*"PDF Import"[,\s]/);
    expect(NAV_SRC).not.toMatch(/label:\s*"PDF Invoice Import"/);
  });

  it("keeps the /admin/imports/pdf-invoice route wire intact", () => {
    // Route path is stable across the rename — only the label
    // changes. This guards against a future rename accidentally
    // moving the URL and 404-ing bookmarks.
    expect(NAV_SRC).toMatch(/to:\s*"\/admin\/imports\/pdf-invoice"/);
  });

  it("retains legacy labels in the aliases array for search backward-compat", () => {
    // "PDF Import" + "PDF Invoice Importer" must still resolve
    // from the nav search so operators who bookmarked the old
    // label find the page.
    expect(NAV_SRC).toMatch(/aliases:.*"PDF Import"/);
    expect(NAV_SRC).toMatch(/aliases:.*"PDF Invoice Importer"/);
  });
});
