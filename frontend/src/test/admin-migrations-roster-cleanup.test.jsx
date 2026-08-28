/**
 * Feb-2026 · Admin Migrations page · User Roster Cleanup card
 * (Preview/Run refactor).
 *
 * Previously the card only exposed Preview + Run buttons AFTER the
 * operator clicked "List roster" and manually checked users. The
 * new contract mirrors the Stripe migration cards: Preview + confirm
 * input + Run are always rendered up front. Preview/Run auto-resolve
 * the candidate set on the backend by POSTing an empty ``user_ids``
 * array; the existing "List roster" toggle is preserved as a
 * read-only secondary audit view.
 *
 * Guards:
 *   1. Preview + confirm + Run testids are all rendered pre-preview
 *      (no gating on selection or on "List roster" being clicked).
 *   2. ``api.post`` for both branches passes a NUMERIC timeout as
 *      the 3rd argument — repeats the P0 abort-toast fix from the
 *      Stripe cards' migration.
 *   3. Both branches POST ``user_ids: []`` so the backend
 *      auto-resolves the tenant's tech-adjacent roster.
 *   4. Preview button is NOT gated behind a ``hasPreviewed &&``
 *      conditional (chicken-and-egg protection — same regression
 *      guard the Stripe cards use).
 *   5. Run button reads ``disabled={!runReady}`` where ``runReady``
 *      combines ``hasPreviewed && confirmText === "DEACTIVATE"``.
 *   6. Preview button uses ``colors.brand`` (the correct theme key
 *      — ``colors.primary`` doesn't exist).
 *   7. "List roster" is preserved as a secondary toggle.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const src = fs.readFileSync(
  path.resolve(__dirname, "../pages/admin/AdminMigrationsPage.jsx"),
  "utf8",
);


describe("AdminMigrationsPage — Roster Cleanup card · Preview/Run", () => {
  it("Preview + Run testids are always rendered pre-preview", () => {
    // Same shape as the Stripe cards — E2E must be able to query
    // these testids without first driving any interaction. The
    // Feb-2026 friction sweep retired the ``id-roster-confirm-input``
    // text field; preview-first is the sole safety gate now.
    expect(src).toMatch(/data-testid="id-roster-preview-btn"/);
    expect(src).toMatch(/data-testid="id-roster-deactivate-btn"/);
    expect(src).not.toMatch(/data-testid="id-roster-confirm-input"/);
  });

  it("Preview button is NOT wrapped in a hasPreviewed conditional", () => {
    // Regression guard — if the Preview button ever gets gated
    // behind a ``{hasPreviewed && ...}`` fence, operators can never
    // reach it. Same guard the Stripe cards enforce.
    const idx = src.indexOf('data-testid="id-roster-preview-btn"');
    expect(idx).toBeGreaterThan(-1);
    const before = src.slice(Math.max(0, idx - 800), idx);
    expect(before).not.toMatch(/\{\s*hasPreviewed\s*&&\s*\(?\s*$/);
  });

  it("Preview button uses colors.brand (not colors.primary or undefined)", () => {
    // The Feb-2026 P0 rendered Stripe cards invisible because
    // ``colors.primary`` doesn't exist. Same failure mode applies
    // here — assert the Preview button uses ``colors.brand``.
    const idx = src.indexOf('data-testid="id-roster-preview-btn"');
    expect(idx).toBeGreaterThan(-1);
    const block = src.slice(Math.max(0, idx - 400), idx + 200);
    expect(block).toMatch(/background:\s*colors\.brand,/);
  });

  it("Preview + Run both POST /deactivate-users with empty user_ids", () => {
    // Auto-resolve mode — backend expands ``user_ids: []`` to the
    // tenant's full tech-adjacent roster. The card no longer
    // requires operators to click through a checkbox selection.
    const idx = src.indexOf("/admin/migrations/deactivate-users");
    expect(idx).toBeGreaterThan(-1);
    const block = src.slice(idx, idx + 400);
    expect(block).toMatch(/user_ids:\s*\[\s*\]/);
    expect(block).toMatch(/dry_run/);
  });

  it("api.post uses a NUMERIC timeout — no {signal:} options object (P0 abort fix)", () => {
    // ``api.post(p, body, timeoutMs)`` — 3rd arg MUST be a number.
    // Passing ``{signal: ...}`` was silently coerced to NaN → 0ms
    // → the internal AbortController fired before fetch was
    // issued, surfacing as "Request timed out" on the very first
    // click. Same lesson we shipped for the Stripe cards.
    const idx = src.indexOf("/admin/migrations/deactivate-users");
    expect(idx).toBeGreaterThan(-1);
    const block = src.slice(idx, idx + 400);
    // Positive: a numeric literal (with optional ``_`` separators)
    // sits between the body object's closing ``}`` and the closing
    // ``)`` of the ``api.post`` call.
    expect(block).toMatch(/,\s*\d[\d_]*,/);
    // Negative: no options object.
    expect(block).not.toMatch(/\{\s*signal:/);
  });

  it("Run button is gated behind hasPreviewed (type-to-confirm retired)", () => {
    // Same gate contract as every other migration card — preview
    // first, then Run enables. Feb-2026 friction sweep retired
    // the typed-DEACTIVATE gate.
    expect(src).toMatch(/hasPreviewed/);
    expect(src).not.toMatch(/confirmText\s*===\s*["']DEACTIVATE["']/);
    expect(src).toMatch(
      /disabled=\{!runReady\}[\s\S]{0,400}data-testid="id-roster-deactivate-btn"/,
    );
  });

  it("'List roster' is preserved as a secondary toggle (read-only audit view)", () => {
    // Product decision — do NOT lose the audit-view capability. The
    // "List roster" button still calls the roster GET, and the row
    // testids on the audit table are preserved.
    expect(src).toMatch(/data-testid="id-roster-list-btn"/);
    expect(src).toMatch(
      /api\.get\(\s*["']\/admin\/migrations\/roster["']\s*\)/,
    );
    // Audit view keeps the per-user row testid so downstream E2E
    // keeps working.
    expect(src).toMatch(/`id-roster-user-\$\{r\.id\}`/);
  });

  it("Preview report renders detail rows (email + role) via testids", () => {
    // The preview payload includes ``deactivated_details`` with
    // rich per-user info so the operator can eyeball what will be
    // deactivated before running the commit.
    expect(src).toMatch(/data-testid="id-roster-report"/);
    expect(src).toMatch(/data-testid="id-roster-report-count"/);
    expect(src).toMatch(/data-testid="id-roster-report-details"/);
    expect(src).toMatch(/`id-roster-report-row-\$\{d\.id\}`/);
  });
});
