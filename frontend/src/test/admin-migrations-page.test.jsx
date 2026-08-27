/**
 * Feb-2026 · AdminMigrationsPage — source-level smoke.
 *
 * Locks the two-step interaction contract the user requested:
 *   1. Preview (Dry Run) button always enabled — POSTs with
 *      dry_run=true.
 *   2. Run Backfill button gated behind (a) at least one preview
 *      AND (b) typed confirmation ("BACKFILL"). POSTs with
 *      dry_run=false.
 *   3. All required testids present.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/admin/AdminMigrationsPage.jsx"),
  "utf-8",
);


describe("AdminMigrationsPage · P19 backfill card", () => {
  it("exposes all required testids", () => {
    expect(SRC).toMatch(/data-testid="id-admin-migrations-page"/);
    expect(SRC).toMatch(/data-testid="id-migration-p19-card"/);
    expect(SRC).toMatch(/data-testid="id-migration-p19-preview"/);
    expect(SRC).toMatch(/data-testid="id-migration-p19-run"/);
    expect(SRC).toMatch(/data-testid="id-migration-p19-diff-table"/);
    expect(SRC).toMatch(/data-testid="id-migration-p19-confirm-input"/);
    expect(SRC).toMatch(/data-testid="id-migration-p19-summary"/);
  });

  it("POSTs dry_run=true for Preview and dry_run=false for Run", () => {
    // Query-string composition matches the API contract.
    expect(SRC).toMatch(
      /\/admin\/migrations\/backfill-website-visitor-leads[\s\S]{0,120}dry_run=\$\{dry_run\s*\?\s*["']true["']\s*:\s*["']false["']\}/,
    );
    // Preview button calls invoke(true). Widened window because the
    // button has extensive style + attribute props before onClick.
    expect(SRC).toMatch(
      /onClick=\{\(\)\s*=>\s*invoke\(true\)\}[\s\S]{0,200}data-testid="id-migration-p19-preview"/,
    );
    // Run button calls invoke(false).
    expect(SRC).toMatch(
      /onClick=\{\(\)\s*=>\s*invoke\(false\)\}[\s\S]{0,200}data-testid="id-migration-p19-run"/,
    );
  });

  it("gates the Run button behind preview + typed 'BACKFILL' confirmation", () => {
    // Guard expression exists AND references both conditions.
    expect(SRC).toMatch(/hasPreviewed/);
    expect(SRC).toMatch(/confirmText\s*===\s*["']BACKFILL["']/);
    // The disabled attribute on the run button reads !runReady.
    expect(SRC).toMatch(
      /disabled=\{!runReady\}[\s\S]{0,300}data-testid="id-migration-p19-run"/,
    );
  });

  it("empty-state message when no leads match the P19 filter", () => {
    // Preview against a tenant with 0 candidates → renders the
    // empty-state placeholder, not the diff table.
    expect(SRC).toMatch(/data-testid="id-migration-p19-empty"/);
    expect(SRC).toMatch(/No leads matched/i);
  });
});


describe("AdminMigrationsPage · Roster Cleanup card", () => {
  it("card + toggle + first-class Preview/Run testids all present", () => {
    // Feb 2026 · Preview/Run refactor — Preview + confirm-input +
    // Run buttons are now FIRST-CLASS (always rendered), and the
    // legacy "List roster" toggle is preserved as a secondary
    // read-only audit view.
    expect(SRC).toMatch(/data-testid="id-roster-cleanup-card"/);
    expect(SRC).toMatch(/data-testid="id-roster-list-btn"/);
    expect(SRC).toMatch(/data-testid="id-roster-table"/);
    expect(SRC).toMatch(/data-testid="id-roster-preview-btn"/);
    expect(SRC).toMatch(/data-testid="id-roster-deactivate-btn"/);
    expect(SRC).toMatch(/data-testid="id-roster-confirm-input"/);
  });

  it("audit-view row testid follows the id-roster-user-{user_id} template", () => {
    // Row testids preserved on the read-only audit table so any
    // downstream E2E that relies on them keeps working.
    expect(SRC).toMatch(/`id-roster-user-\$\{r\.id\}`/);
  });

  it("List button GETs /admin/migrations/roster (toggle behaviour)", () => {
    expect(SRC).toMatch(
      /api\.get\(\s*["']\/admin\/migrations\/roster["']\s*\)/,
    );
  });

  it("Preview/Run POST /deactivate-users with empty user_ids + numeric timeout", () => {
    // Preview + Run call the same endpoint with auto-resolve
    // (``user_ids: []``) — the backend expands to the tenant's
    // tech-adjacent roster. Third arg is a NUMERIC timeout (never
    // an options object — that was the P0 abort bug).
    const idx = SRC.indexOf("/admin/migrations/deactivate-users");
    expect(idx).toBeGreaterThan(-1);
    const block = SRC.slice(idx, idx + 400);
    expect(block).toMatch(/user_ids:\s*\[\s*\]/);
    expect(block).toMatch(/dry_run/);
    // Numeric timeout as 3rd arg + no ``{signal:`` options object.
    expect(block).toMatch(/,\s*\d[\d_]*,/);
    expect(block).not.toMatch(/\{\s*signal:/);
  });

  it("Run button gated behind hasPreviewed + typed 'DEACTIVATE'", () => {
    // Same shape as the Stripe cards' Preview/Run gate.
    expect(SRC).toMatch(/hasPreviewed/);
    expect(SRC).toMatch(/confirmText\s*===\s*["']DEACTIVATE["']/);
    expect(SRC).toMatch(
      /disabled=\{!runReady\}[\s\S]{0,400}data-testid="id-roster-deactivate-btn"/,
    );
  });
});
