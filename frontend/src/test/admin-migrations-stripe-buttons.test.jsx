/**
 * Feb-2026 P0 — Admin Migrations page · Stripe cards render guards.
 *
 * Root cause (from screenshot + Playwright DOM inspection):
 *   ``colors.primary`` doesn't exist on ``theme.js`` — the theme
 *   exports ``brand`` / ``brandPrimary``. The Stripe cards read
 *   ``colors.primary`` on their Preview button ``background`` inline
 *   style, so the CSS resolved to ``background: undefined`` →
 *   transparent → white text on white card → invisible. Buttons
 *   were IN the DOM (Playwright ``is_visible`` returned true) but
 *   the user couldn't see them.
 *
 * Guards:
 *   1. Neither Stripe card reads ``colors.primary`` anywhere (regex
 *      guard so a future refactor can't reintroduce the typo).
 *   2. Preview + Run + confirm-input testids present on both cards.
 *   3. Preview button uses ``colors.brand`` (the correct theme key).
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const src = fs.readFileSync(
  path.resolve(__dirname, "../pages/admin/AdminMigrationsPage.jsx"),
  "utf8",
);
const themeSrc = fs.readFileSync(
  path.resolve(__dirname, "../theme.js"),
  "utf8",
);


describe("theme sanity — colors.primary does not exist", () => {
  it("theme.js exports ``brand`` / ``brandPrimary`` but not ``primary``", () => {
    // The exact typo that caused the P0. If someone renames the key
    // to ``primary`` this test flips green and the migration cards
    // switch to a real color.
    expect(themeSrc).toMatch(/\bbrand:\s*"#/);
    expect(themeSrc).toMatch(/\bbrandPrimary:\s*"#/);
    // Non-scoped ``primary:`` should NOT appear as a top-level key.
    // ``brandPrimary`` legitimately contains ``Primary`` so we
    // assert on the leading word boundary + colon shape.
    expect(themeSrc).not.toMatch(/^\s*primary:\s*"#/m);
  });
});


describe("AdminMigrationsPage — Stripe cards render + testids", () => {
  it("neither Stripe card reads colors.primary (P0 regression guard)", () => {
    expect(src).not.toMatch(/colors\.primary/);
  });

  it("Sync Stripe Customers card renders Preview + Run + confirm testids pre-preview", () => {
    // These testids MUST be present in the initial DOM so E2E flows
    // can query them without first driving a preview action.
    expect(src).toMatch(/data-testid="id-migration-stripe-preview-btn"/);
    expect(src).toMatch(/data-testid="id-migration-stripe-run-btn"/);
    expect(src).toMatch(/data-testid="id-migration-stripe-confirm-input"/);
  });

  it("Sync Stripe Billing History card renders Preview + Run + confirm testids pre-preview", () => {
    expect(src).toMatch(/data-testid="id-migration-stripe-billing-preview-btn"/);
    expect(src).toMatch(/data-testid="id-migration-stripe-billing-run-btn"/);
    expect(src).toMatch(/data-testid="id-migration-stripe-billing-confirm-input"/);
  });

  it("Preview buttons on Stripe cards use colors.brand (not undefined)", () => {
    // Locate the Preview buttons by testid and check the sibling
    // ``style`` prop uses ``colors.brand`` (a real theme key).
    // Slice ~600 chars around each hit — plenty for the style
    // block.
    for (const testid of [
      "id-migration-stripe-preview-btn",
      "id-migration-stripe-billing-preview-btn",
    ]) {
      const idx = src.indexOf(`data-testid="${testid}"`);
      expect(idx).toBeGreaterThan(-1);
      const block = src.slice(Math.max(0, idx - 400), idx + 200);
      expect(block).toMatch(/background:\s*colors\.brand,/);
    }
  });

  it("Preview button on both cards is NOT rendered inside a hasPreviewed conditional", () => {
    // A prior regression hypothesis was that Preview only mounted
    // AFTER a first preview ran (chicken-and-egg). This guard locks
    // in that the Preview button precedes the run+confirm row and
    // is not wrapped in a ``hasPreviewed &&`` gate on either card.
    for (const testid of [
      "id-migration-stripe-preview-btn",
      "id-migration-stripe-billing-preview-btn",
    ]) {
      const idx = src.indexOf(`data-testid="${testid}"`);
      // Look at the 800 chars immediately before this testid — if a
      // ``hasPreviewed &&`` opens in this window without a matching
      // close, the button is gated.
      const before = src.slice(Math.max(0, idx - 800), idx);
      // No ``{hasPreviewed &&`` gate opens directly before.
      expect(before).not.toMatch(/\{\s*hasPreviewed\s*&&\s*\(?\s*$/);
    }
  });

  it("api.post calls on both Stripe cards pass a numeric timeout (P0 abort-toast fix)", () => {
    // ``api.post(p, body, timeoutMs)`` — 3rd arg MUST be a number.
    // Passing ``{signal: ...}`` there was silently coerced to NaN
    // → treated as 0ms → the internal AbortController in
    // ``api.js::request`` fired before fetch was issued, surfacing
    // as "Request timed out" on the very first click.
    for (const path of [
      "/admin/migrations/sync-stripe-customers",
      "/admin/migrations/sync-stripe-billing-history",
    ]) {
      const idx = src.indexOf(path);
      expect(idx).toBeGreaterThan(-1);
      // Slice out to the closing of the ``api.post(...)`` call —
      // ~600 chars is plenty for the multi-line call.
      const block = src.slice(idx, idx + 600);
      // Positive assertion: a numeric literal (with optional ``_``
      // separators) appears as the 3rd argument. Trailing comma +
      // inline comment allowed before ``);``.
      expect(block).toMatch(/,\s*\d[\d_]*,/);
      // Negative assertion: no ``{signal:`` options object in the
      // same call block.
      expect(block).not.toMatch(/\{\s*signal:/);
    }
  });
});
