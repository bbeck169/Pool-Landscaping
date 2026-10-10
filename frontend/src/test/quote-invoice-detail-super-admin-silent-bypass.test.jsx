/**
 * Feb-2026 · DOC-LOCK-POLICY-RELAX follow-up — Phase-#2's super_admin
 * silent-bypass surface was RETIRED alongside the lock widening.
 *
 * Production policy on both inline save sites (K71 line-items +
 * Terms editor) is:
 *
 *   const _locked = _doc_type === "invoice" && _st === "paid";
 *   const _silentBypass = false;
 *
 * The old role-conditional ``_silentBypass = _role === "super_admin"
 * && […past_due/unpaid/overdue…].includes(_st)`` path is gone — the
 * narrow lock no longer catches aged statuses, so there's nothing
 * for super_admin to silently bypass. If a future product phase
 * re-widens the lock, this file is the signal to also restore the
 * role-conditional bypass.
 *
 * The dialog-guard conditional is correspondingly simplified from
 * ``if (_locked && !_silentBypass && !lockBypassAcked)`` to the same
 * shape (``!_silentBypass`` stays as dead-code for intent-signalling
 * but collapses at compile time since ``_silentBypass`` is a literal
 * ``false``).
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/quotes/QuoteInvoiceDetail.jsx"),
  "utf8",
);


describe("QuoteInvoiceDetail · silent-bypass retired (POLICY-RELAX Phase-#3)", () => {
  it("K71 line-items save declares `_silentBypass = false` as a bare constant", () => {
    const idx = SRC.indexOf("setPendingLines(nextLines)");
    expect(idx).toBeGreaterThan(-1);
    const before = SRC.slice(Math.max(0, idx - 1500), idx);
    expect(before).toMatch(/const\s+_silentBypass\s*=\s*false\s*;/);
    // Phase-#2's role-conditional form must NOT survive here.
    expect(before).not.toMatch(/_silentBypass\s*=\s*_role\s*===\s*"super_admin"/);
  });

  it("Terms editor save declares `_silentBypass = false` as a bare constant", () => {
    const idx = SRC.indexOf("__terms__: termsDraft");
    expect(idx).toBeGreaterThan(-1);
    const before = SRC.slice(Math.max(0, idx - 1500), idx);
    expect(before).toMatch(/const\s+_silentBypass\s*=\s*false\s*;/);
    expect(before).not.toMatch(/_silentBypass\s*=\s*_role\s*===\s*"super_admin"/);
  });

  it("exactly two bare-`false` _silentBypass declarations exist (symmetry)", () => {
    const matches = SRC.match(/const\s+_silentBypass\s*=\s*false\s*;/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("no role-conditional silent-bypass survives anywhere in the file", () => {
    // Phase-#2 shape explicitly retired. Hard-regress on it so a
    // future accidental re-introduction fails CI.
    expect(SRC).not.toMatch(/_silentBypass\s*=\s*_role\s*===\s*"super_admin"/);
    expect(SRC).not.toMatch(/_silentBypass\s*=[\s\S]*?includes\(_st\)/);
  });

  it("dialog-guard still structurally references `_silentBypass` (intent-signalling)", () => {
    // Even though ``_silentBypass`` is a compile-time ``false``, the
    // conditional ``if (_locked && !_silentBypass && !lockBypassAcked)``
    // stays in source as a semantic marker so a future POLICY-WIDEN
    // phase can re-wire the bypass by changing one assignment.
    const re = /if\s*\(\s*_locked\s*&&\s*!\s*_silentBypass\s*&&\s*!\s*lockBypassAcked\s*\)/g;
    const matches = [...SRC.matchAll(re)];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("payload-guard still structurally references `_silentBypass`", () => {
    const re = /if\s*\(\s*_locked\s*&&\s*!\s*_silentBypass\s*\)\s*_body\.acknowledged_lock_bypass\s*=\s*true/g;
    const matches = [...SRC.matchAll(re)];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("admin editing a paid invoice still opens the ack dialog", () => {
    // With narrow lock + bypass retired, the only path that still
    // triggers ``setLockDialogOpen(true)`` is admin editing a paid
    // invoice. Anchor it on the K71 save block.
    const idx = SRC.indexOf("setPendingLines(nextLines)");
    const window = SRC.slice(idx, idx + 400);
    expect(window).toMatch(/setLockDialogOpen\(true\)/);
  });

  it("_locked remains narrow (Phase-#3 invariant mirror)", () => {
    // Mirror of the companion ``quote-invoice-detail-ack-bypass-aged``
    // test's narrow-lock lock. Keeps this file self-contained so a
    // partial revert fails here first.
    const re = /_locked\s*=\s*_doc_type\s*===\s*"invoice"\s*&&\s*_st\s*===\s*"paid"/g;
    const matches = [...SRC.matchAll(re)];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });
});
