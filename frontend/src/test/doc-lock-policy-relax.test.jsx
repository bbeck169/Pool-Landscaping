/**
 * DOC-LOCK-POLICY-RELAX · Feb-2026 — frontend lock-strip assertions
 * for ``QuoteInvoiceDetail.jsx``.
 *
 * What this ticket changed on the frontend
 * ----------------------------------------
 * The old inline save path consulted
 * ``["sent", "accepted", "paid", "past_due", "unpaid",
 * "overdue"].includes(status)`` and opened a confirm-dialog
 * (``setLockDialogOpen``) before firing PUT. Under
 * DOC-LOCK-POLICY-RELAX:
 *
 *   * Estimates (``doc_type === "quote"``) are always editable.
 *     NO status gate on the client. The confirm-dialog never fires.
 *   * Invoices are editable except when ``status === "paid"``.
 *     ``void`` / ``cancelled`` land as backend 409 toasts (no
 *     client-side modal gate — the backend is the source of truth).
 *
 * Static-source checks lock the policy by inspecting the file
 * contents, mirroring the existing
 * ``public-invoice-pay-button.test.jsx`` convention. We do NOT
 * boot the component because that would require mocking the full
 * admin surface stack (useAuth / router / api / toasts). The policy
 * is a 1-line expression — grep-level assertion is sufficient.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";


const QID_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/quotes/QuoteInvoiceDetail.jsx"),
  "utf8",
);


describe("DOC-LOCK-POLICY-RELAX · QuoteInvoiceDetail client gate", () => {
  it("the inline line-items save path no longer locks on sent/accepted/aged statuses", () => {
    // The pre-relax expression that locked FIVE statuses must be
    // gone. Any future diff that restores it will fail this test.
    const legacyLockExpr =
      /\[\s*"sent",\s*"accepted",\s*"paid",\s*"past_due",\s*"unpaid",\s*"overdue"\s*\]\s*\.includes\s*\(\s*_st\s*\)/;
    expect(QID_SRC).not.toMatch(legacyLockExpr);
  });

  it("the inline save path narrows the lock to invoice + paid only", () => {
    // New policy: ``_locked = _doc_type === "invoice" && _st === "paid"``.
    // Match slightly loosely to tolerate whitespace/parentheses drift.
    expect(QID_SRC).toMatch(
      /_locked\s*=\s*_doc_type\s*===\s*"invoice"\s*&&\s*_st\s*===\s*"paid"/,
    );
  });

  it("the super_admin silent-bypass branch is reduced to a dead constant", () => {
    // Pre-relax: ``_silentBypass = _role === "super_admin" && [...].includes(_st)``.
    // Post-relax: ``_silentBypass = false``. Not a role lookup.
    expect(QID_SRC).not.toMatch(
      /_silentBypass\s*=\s*_role\s*===\s*"super_admin"/,
    );
    // Both save paths (line-items + terms) set it to false — assert
    // at least two literal ``const _silentBypass = false;`` lines.
    const matches = QID_SRC.match(/const\s+_silentBypass\s*=\s*false\s*;/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("the terms save path mirrors the line-items narrowing", () => {
    // The second occurrence of the paid-only ``_locked`` expression
    // guards the terms-and-conditions save button.
    const paidOnly =
      /_locked\s*=\s*_doc_type\s*===\s*"invoice"\s*&&\s*_st\s*===\s*"paid"/g;
    const matches = QID_SRC.match(paidOnly) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("DOC-LOCK-POLICY-RELAX comment anchors are present on both save paths", () => {
    // Each save-path block carries the ticket tag so future diffs
    // can trace the policy back to this change.
    const anchorCount = (QID_SRC.match(/DOC-LOCK-POLICY-RELAX/g) || []).length;
    expect(anchorCount).toBeGreaterThanOrEqual(2);
  });

  it("the lock dialog setter + ack flag code paths are preserved — only invoice/paid still routes through them", () => {
    // We did NOT remove ``setLockDialogOpen`` or
    // ``acknowledged_lock_bypass`` — invoices in ``paid`` status
    // still land there. Guard that the dialog machinery is still
    // wired so paid-invoice edits still see the confirm UX.
    expect(QID_SRC).toMatch(/setLockDialogOpen\(true\)/);
    expect(QID_SRC).toMatch(/acknowledged_lock_bypass\s*=\s*true/);
  });
});
