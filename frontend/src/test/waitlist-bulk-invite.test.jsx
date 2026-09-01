/**
 * Phase I2 · Feb-2026 — CustomersList Waitlist bulk invite button.
 *
 * Source-body contract check. Locks the invariants for the
 * "Send portal invite to entire Waitlist" affordance that appears
 * ONLY on the Waitlist cohort tab (H4) for admin+ users, and only
 * when the waitlist cohort has ≥1 customer.
 *
 *   - Button testid + admin+ + Waitlist-tab gating.
 *   - Re-fetches waitlist ids at click time so a stale tab count
 *     can't corrupt the payload.
 *   - > 20 rows requires typing WAITLIST via window.prompt;
 *     ≤ 20 rows uses window.confirm.
 *   - POSTs to /admin/customers/portal-invite/bulk with customer_ids.
 *   - Uses sonner toast (not the undefined ``toast`` global) for
 *     success + error surfaces.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(),
    "src/pages/customers/CustomersList.jsx"),
  "utf-8",
);


describe("CustomersList · I2 Waitlist bulk portal-invite button", () => {
  it("button testid is ``waitlist-bulk-invite-btn``", () => {
    expect(SRC).toMatch(/data-testid="waitlist-bulk-invite-btn"/);
  });

  it("button renders only on the Waitlist tab, admin+ only, when count > 0", () => {
    expect(SRC).toMatch(
      /tab\s*===\s*"waitlist"\s*&&\s*isAdmin\s*&&\s*counts\.waitlist\s*>\s*0/,
    );
  });

  it("button label includes the current Waitlist count", () => {
    expect(SRC).toMatch(
      /Send portal invite to entire Waitlist \(\{counts\.waitlist\}\)/,
    );
  });

  it("click handler re-fetches waitlist ids at click time (no stale state)", () => {
    // Guards against relying on cached ``rows`` — must GET a fresh
    // waitlisted=true page_size=500 list before dispatching invites.
    expect(SRC).toMatch(
      /api\.get\(\s*"\/customers\?waitlisted=true&page=1&page_size=500"/,
    );
  });

  it("large lists (>20) gate on typing ``WAITLIST`` via window.prompt", () => {
    expect(SRC).toMatch(/ids\.length\s*>\s*20/);
    expect(SRC).toMatch(/window\.prompt\(confirmMsg\)/);
    expect(SRC).toMatch(/typed\s*!==\s*"WAITLIST"/);
  });

  it("small lists (≤20) gate on window.confirm", () => {
    expect(SRC).toMatch(/window\.confirm\(confirmMsg\)/);
  });

  it("POST hits /admin/customers/portal-invite/bulk with customer_ids", () => {
    const idx = SRC.indexOf('waitlist-bulk-invite-btn');
    expect(idx).toBeGreaterThan(-1);
    const block = SRC.slice(idx, idx + 2200);
    expect(block).toMatch(
      /api\.post\(\s*"\/admin\/customers\/portal-invite\/bulk"\s*,\s*\{\s*customer_ids/,
    );
  });

  it("uses sonnerToast (not an undefined ``toast`` global)", () => {
    // Regression guard — an earlier draft called ``toast.success``
    // which is undefined in this module (sonner is imported as
    // sonnerToast). Locking to sonnerToast prevents the ReferenceError.
    const idx = SRC.indexOf('waitlist-bulk-invite-btn');
    expect(idx).toBeGreaterThan(-1);
    const block = SRC.slice(idx, idx + 2400);
    expect(block).toMatch(/sonnerToast\.success/);
    expect(block).toMatch(/sonnerToast\.error/);
    // And should NOT reference an unaliased ``toast.success`` /
    // ``toast.error`` — those would throw.
    expect(block).not.toMatch(/(^|\W)toast\.success\(/);
    expect(block).not.toMatch(/(^|\W)toast\.error\(/);
  });

  it("empty-list branch bails with an info toast + early return", () => {
    expect(SRC).toMatch(
      /if\s*\(!ids\.length\)\s*\{\s*sonnerToast\.info\?\.\(/,
    );
  });
});


describe("I2 · regression guards for the H4 Waitlist tab", () => {
  it("preserves the H4 Waitlist cohort tab testids", () => {
    expect(SRC).toMatch(/testid:\s*"tab-waitlist"/);
    expect(SRC).toMatch(/counts\.waitlist/);
  });

  it("preserves the H1 selection-scoped bulk-invite button", () => {
    // The tab-scoped Waitlist button must NOT replace or hide the
    // H1 selection-scoped button ("Send portal invite (N)").
    expect(SRC).toMatch(/testid="bulk-portal-invite"/);
  });
});
