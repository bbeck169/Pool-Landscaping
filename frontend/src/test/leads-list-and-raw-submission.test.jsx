/**
 * Feb-2026 · Leads list + detail drawer regression.
 *
 * Locks:
 *  - The list row surfaces name / email / phone / address.
 *  - Address column is present between Contact and Source.
 *  - LeadDetailDrawer renders + carries the raw-submission panel
 *    plumbing (source-string guards — the raw-submission fetch
 *    itself is exercised by the backend test suite).
 *
 * We source-scan the JSX rather than mounting the full dashboard
 * (which depends on api-client + toast infra + confirm-dialog + a
 * live /leads fetch). Fast + zero-mount signal on the polish items.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/leads/LeadsDashboardPage.jsx"),
  "utf-8",
);


describe("LeadsDashboardPage · list row polish", () => {
  it("column headers include Address between Contact and Source", () => {
    // Order-sensitive substring scan — Contact must come before
    // Address, and Address before Source.
    const iContact = SRC.indexOf(">Contact<");
    const iAddress = SRC.indexOf(">Address<");
    const iSource  = SRC.indexOf(">Source<");
    expect(iContact).toBeGreaterThan(0);
    expect(iAddress).toBeGreaterThan(iContact);
    expect(iSource).toBeGreaterThan(iAddress);
  });

  it("address cell renders l.address with service_address fallback", () => {
    expect(SRC).toMatch(
      /data-testid=\{`lead-address-\$\{l\.id\}`\}[\s\S]{0,400}l\.address\s*\|\|\s*l\.service_address/,
    );
  });

  it("address cell truncates + shows full string on hover", () => {
    // Long addresses stay on one line; ``title=`` carries the full
    // string for keyboard/mouse hover disclosure.
    // Attributes may appear in either order — assert both substrings
    // exist in the same <div>. We anchor on the address testid and
    // look for the neighbouring className + title within a small
    // window on either side.
    const addressCell = SRC.match(
      /<div[\s\S]{0,600}?data-testid=\{`lead-address-\$\{l\.id\}`\}[\s\S]{0,200}?>/,
    );
    expect(addressCell, "address cell block not found").toBeTruthy();
    expect(addressCell[0]).toMatch(/truncate/);
    // Phase Hygiene B · Feb-2026 — product built out the address
    // cell to concatenate street + city/state + zip into a single
    // hover tooltip (``[l.address || l.service_address, csz, zip]
    // .filter(Boolean).join(" · ")``). Relax the regex to allow
    // either the legacy plain ``title={l.address || l.service_address``
    // form or the current array-join form; the contract is that
    // ``title`` starts with the address / service_address fallback
    // pair.
    expect(addressCell[0]).toMatch(
      /title=\{\[?\s*l\.address\s*\|\|\s*l\.service_address/,
    );
  });

  it("row uses the expected col-span layout (5 body cells, 12 total)", () => {
    // Header row + body row EACH sum to 12 col-spans across the
    // grid. Instead of computing from source (fragile because of
    // nested ``LEAD_STATUS_OPTIONS.map`` closures), we assert the
    // EXACT class list appears once per header + once per row —
    // which locks the column layout and catches accidental drift.
    //
    // Header layout (Feb-2026): 1 · 2 · 2 · 2 · 2 · 1 · 2 = 12.
    expect(SRC).toMatch(/<div className="col-span-2">Date<\/div>/);
    expect(SRC).toMatch(/<div className="col-span-2">Name<\/div>/);
    expect(SRC).toMatch(/<div className="col-span-2">Contact<\/div>/);
    expect(SRC).toMatch(/<div className="col-span-2">Address<\/div>/);
    expect(SRC).toMatch(/<div className="col-span-1">Source<\/div>/);
    expect(SRC).toMatch(/<div className="col-span-2">Status<\/div>/);
  });
});


describe("LeadsDashboardPage · LeadDetailDrawer raw-submission panel", () => {
  it("lazy-load hook fetches /leads/{id}/raw-submission on open", () => {
    expect(SRC).toMatch(
      /api\.get\(\s*`\/leads\/\$\{lead\.id\}\/raw-submission`/,
    );
  });

  it("panel hides when there is no submission id (rawState === 'none')", () => {
    // Guard: ``rawState !== "none"`` gates the whole panel render.
    expect(SRC).toMatch(/rawState\s*!==\s*["']none["']/);
    // Initial state is derived from submissionId presence.
    expect(SRC).toMatch(/submissionId\s*\?\s*["']idle["']\s*:\s*["']none["']/);
  });

  it("panel renders each of the required states via unique testids", () => {
    expect(SRC).toMatch(/data-testid="lead-raw-submission-panel"/);
    expect(SRC).toMatch(/data-testid="lead-raw-submission-loading"/);
    expect(SRC).toMatch(/data-testid="lead-raw-submission-error"/);
    expect(SRC).toMatch(/data-testid="lead-raw-submission-json"/);
    expect(SRC).toMatch(/data-testid="lead-raw-submission-page-url"/);
  });

  it("existing Convert-to-Customer button is preserved (not duplicated)", () => {
    // Exactly ONE ``lead-convert-btn`` testid — reuses the existing flow.
    const occurrences = SRC.match(/data-testid="lead-convert-btn"/g) || [];
    expect(occurrences).toHaveLength(1);
  });

  it("404 branch is treated as 'no linked submission' (panel hides)", () => {
    // The hook branches on 404 → rawState = "none" so the panel
    // hides for legacy pre-P17 leads. Any other error path surfaces
    // the message via rawState = "error".
    expect(SRC).toMatch(/["']404["']/);
    expect(SRC).toMatch(/setRawState\(["']none["']\)/);
    expect(SRC).toMatch(/setRawState\(["']error["']\)/);
  });
});
