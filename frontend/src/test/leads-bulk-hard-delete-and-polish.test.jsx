/**
 * Phase LD1 · Feb 2026 — Leads bulk HARD delete + visual polish.
 *
 * Source-scan tests over `LeadsDashboardPage.jsx` so we lock the
 * markup contract without spinning up the full dashboard (which
 * needs the api client + toast infra + a live /leads fetch).
 * Fast + zero-mount signal on the polish items — matches the
 * pattern used by `leads-list-and-raw-submission.test.jsx`.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/leads/LeadsDashboardPage.jsx"),
  "utf-8",
);


describe("LeadsDashboardPage · Phase LD1 bulk hard delete", () => {
  it("renders the red 'Delete permanently (N)' toolbar button", () => {
    expect(SRC).toMatch(/data-testid="bulk-hard-delete-button"/);
    expect(SRC).toMatch(/Delete permanently \(\{selectedCount\}\)/);
  });

  it("keeps the archive (soft-delete) path alongside the hard-delete path", () => {
    // Both buttons must coexist — the soft-delete flow was NOT
    // removed. The archive button now uses a warmer amber palette
    // so admins can tell it apart from the destructive red one.
    expect(SRC).toMatch(/data-testid="bulk-delete-button"/);
    expect(SRC).toMatch(/data-testid="bulk-hard-delete-button"/);
  });

  it("hard-delete button opens the acknowledge modal", () => {
    // Button click must set both ``hardConfirmOpen`` AND reset
    // ``hardAcknowledged`` so a previous session's tick doesn't
    // carry over.
    expect(SRC).toMatch(/setHardConfirmOpen\(true\)/);
    expect(SRC).toMatch(/setHardAcknowledged\(false\)/);
  });

  it("hard-delete confirm modal has an explicit acknowledge checkbox", () => {
    expect(SRC).toMatch(/data-testid="bulk-hard-delete-confirm"/);
    expect(SRC).toMatch(/data-testid="bulk-hard-delete-ack"/);
    expect(SRC).toMatch(/I understand this is permanent and cannot be recovered/);
  });

  it("hard-delete confirm button is disabled until the ack is checked", () => {
    // ``disabled={busy || !hardAcknowledged}`` is the exact guard.
    expect(SRC).toMatch(/disabled=\{busy \|\| !hardAcknowledged\}/);
  });

  it("hard-delete confirm posts to /leads/bulk-hard-delete with lead_ids", () => {
    expect(SRC).toMatch(/api\.post\(\s*["']\/leads\/bulk-hard-delete["']\s*,\s*\{\s*lead_ids:/);
  });

  it("hard-delete handler consumes {results, summary} response shape", () => {
    expect(SRC).toMatch(/res\.results\s*\|\|\s*\[\]/);
    expect(SRC).toMatch(/res\.summary\?\.succeeded/);
    expect(SRC).toMatch(/res\.summary\?\.failed/);
  });

  it("hard-delete handler filters deleted rows out of local state", () => {
    // Filter uses the results[] `ok` flag to derive the id list.
    expect(SRC).toMatch(/results\.filter\(\(r\)\s*=>\s*r\.ok\)\.map\(\(r\)\s*=>\s*r\.id\)/);
  });
});


describe("LeadsDashboardPage · Phase LD1 visual polish", () => {
  it("exposes a density toggle wired to localStorage 'leads-density'", () => {
    expect(SRC).toMatch(/data-testid="leads-density-toggle"/);
    expect(SRC).toMatch(/data-testid=\{`leads-density-\$\{o\.v\}`\}/);
    // Persistence read + write both hit the same key.
    expect(SRC).toMatch(/localStorage\.getItem\(["']leads-density["']\)/);
    expect(SRC).toMatch(/localStorage\.setItem\(["']leads-density["']/);
  });

  it("row + header padding are density-driven", () => {
    // Row uses the ``rowPad`` computed class; header uses ``headerPad``.
    expect(SRC).toMatch(/const rowPad = density === "compact" \? "py-1\.5" : "py-3"/);
    expect(SRC).toMatch(/const headerPad = density === "compact" \? "py-1\.5" : "py-2"/);
    expect(SRC).toMatch(/px-4 \$\{rowPad\}/);
    expect(SRC).toMatch(/px-4 \$\{headerPad\}/);
  });

  it("table header sticks to the top of the scroll container", () => {
    // Sticky header sits inside <Card overflow-hidden>, so top-0 +
    // z-10 pins it against the page viewport for long lists.
    const header = SRC.match(
      /<div[\s\S]{0,400}?data-testid="leads-table-header"[\s\S]{0,200}?>/,
    );
    expect(header, "leads-table-header block not found").toBeTruthy();
    expect(header[0]).toMatch(/sticky top-0 z-10/);
  });

  it("empty state distinguishes 'no leads yet' from 'no leads match'", () => {
    // rows.length === 0 → onboarding copy;
    // rows.length > 0 with filtered visible.length === 0 → search
    // empty state + clear filters CTA.
    expect(SRC).toMatch(/No leads yet/);
    expect(SRC).toMatch(/data-testid="admin-leads-empty-search"/);
    expect(SRC).toMatch(/data-testid="admin-leads-clear-filters"/);
    expect(SRC).toMatch(/No leads match your filters/);
  });

  it("empty state 'Clear filters' resets all three filter keys", () => {
    // Regression against a subtle bug where clearing only wiped the
    // search box and left the source/status dropdowns in place.
    expect(SRC).toMatch(
      /setFilters\(\{\s*source:\s*""\s*,\s*status:\s*""\s*,\s*search:\s*""\s*\}\)/,
    );
  });

  it("row hover transition-colors class is present", () => {
    // Locks the subtle hover polish so it can't be removed
    // accidentally.
    expect(SRC).toMatch(/hover:bg-slate-50 cursor-pointer transition-colors/);
  });
});
