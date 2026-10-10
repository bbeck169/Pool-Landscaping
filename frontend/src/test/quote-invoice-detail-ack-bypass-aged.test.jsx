/**
 * Feb 2026 · DOC-LOCK-POLICY-RELAX anchor — QuoteInvoiceDetail
 * client-side lock narrowed to **invoice + paid only**.
 *
 * Historical context (preserved for future archaeologists):
 *   Phase #1  — ``_locked = _doc_type === "invoice" && _st === "paid"``
 *   Phase #2  — widened to ``["sent", "accepted", "paid", "past_due",
 *                "unpaid", "overdue"].includes(_st)`` with a
 *                ``_silentBypass = _role === "super_admin"`` escape hatch
 *                so super_admins could still edit aged invoices.
 *   Phase #3  — DOC-LOCK-POLICY-RELAX reverted to Phase-#1 narrow lock +
 *                replaced the role-conditional bypass with a bare
 *                ``_silentBypass = false`` so the backend is the single
 *                source of truth for lock state (over-locking caused
 *                support tickets). Current production policy.
 *
 * This file replaces the stranded Phase-#2 anchor test. It locks the
 * Phase-#3 invariants on both inline save sites (K71 line-items +
 * Terms editor) via source-grep — matches the project's convention
 * (see ``doc-lock-policy-relax.test.jsx``, ``invoice-pay-now-restyle
 * .test.jsx``) of locking string shapes via file grep rather than
 * mounting the router-heavy detail page.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/quotes/QuoteInvoiceDetail.jsx"),
  "utf8",
);


describe("QuoteInvoiceDetail · narrow lock (POLICY-RELAX Phase-#3)", () => {
  it("K71 line-items save uses the narrow invoice+paid _locked form", () => {
    // Anchor on ``setPendingLines(nextLines)`` sentinel for the K71
    // save site. The narrow form sits ~5 lines above it.
    const idx = SRC.indexOf("setPendingLines(nextLines)");
    expect(idx).toBeGreaterThan(-1);
    const before = SRC.slice(Math.max(0, idx - 1500), idx);
    expect(before).toMatch(
      /_locked\s*=\s*_doc_type\s*===\s*"invoice"\s*&&\s*_st\s*===\s*"paid"/,
    );
  });

  it("Terms editor save uses the narrow invoice+paid _locked form", () => {
    // Anchor on the ``__terms__`` sentinel for the Terms editor save.
    const idx = SRC.indexOf("__terms__: termsDraft");
    expect(idx).toBeGreaterThan(-1);
    const before = SRC.slice(Math.max(0, idx - 1500), idx);
    expect(before).toMatch(
      /_locked\s*=\s*_doc_type\s*===\s*"invoice"\s*&&\s*_st\s*===\s*"paid"/,
    );
  });

  it("both _locked sites agree on the narrow form (no drift)", () => {
    // Regression guard — a future edit that widens one site but
    // forgets the other will fail here.
    const re = /_locked\s*=\s*_doc_type\s*===\s*"invoice"\s*&&\s*_st\s*===\s*"paid"/g;
    const matches = [...SRC.matchAll(re)];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("no Phase-#2 widened array literal survives at either save site", () => {
    // Make the regression hard — a future accidental re-widening to
    // the 6-status array must fail CI loudly.
    expect(SRC).not.toMatch(
      /\[\s*"sent",\s*"accepted",\s*"paid",\s*"past_due",\s*"unpaid",\s*"overdue"\s*\]\.includes\(_st\)/,
    );
  });

  it("_silentBypass is the bare `false` constant (no role-conditional)", () => {
    // Phase-#3 removed the role-based silent-bypass path. Both save
    // sites must carry ``const _silentBypass = false;`` so the
    // compile-time dead-code elimination collapses the whole bypass
    // branch at build time.
    const matches = SRC.match(/const\s+_silentBypass\s*=\s*false\s*;/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
    expect(SRC).not.toMatch(/_silentBypass\s*=\s*_role\s*===\s*"super_admin"/);
  });

  it("EditLockConfirmDialog is still imported for the paid-invoice path", () => {
    // Even with the narrow lock, admin editing a paid invoice must
    // still receive the ack popup. The dialog component remains wired.
    expect(SRC).toMatch(/import EditLockConfirmDialog from/);
  });

  it("canEdit gate still excludes non-staff roles", () => {
    expect(SRC).toMatch(/canEdit=\{[\s\S]{0,80}isStaff/);
  });

  it("isStaff stays narrow (admin + super_admin only)", () => {
    expect(SRC).toMatch(
      /isStaff = \["admin", "super_admin"\]\.includes\(String\(user\?\.role \|\| ""\)\)/,
    );
  });
});
