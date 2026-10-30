/**
 * Feb-2026 · FIN-PAID-STATUS-PARITY · Commit 2a — vitest for the
 * RecordPaymentModal "no save-card" info banner.
 *
 * Operator Bug 2 ("'Save card' on manual payment doesn't persist")
 * traced to a misreading of this modal: no save-card toggle exists
 * on the manual Record Payment flow because cash / check /
 * external card have no card number to tokenise. Commit 2a adds an
 * info banner clarifying this + pointing users at the two paths
 * that DO save a card (Charge card flow for existing saved cards;
 * magic-link / portal pay for first-card capture).
 *
 * Test posture — source-inspection, matching the shipped
 * ``task-h0-backfill-date-ui.test.jsx`` cases 5-6 which exercise
 * the SAME modal (``RecordPaymentModal`` inside
 * ``pages/quotes/QuoteInvoiceDetail.jsx``). Full DOM mount would
 * require stubbing every deep ``QuoteInvoiceDetail`` dep and is
 * disproportionate for a single new render block.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";


const QID_PATH = path.resolve(
  __dirname,
  "..",
  "pages",
  "quotes",
  "QuoteInvoiceDetail.jsx",
);
const QID_SRC = fs.readFileSync(QID_PATH, "utf8");


describe("RecordPaymentModal · no-save-card info banner (Commit 2a)", () => {
  it("renders the save-card info banner with the required testid", () => {
    // The ``data-testid`` is the stable hook e2e / support
    // scripts latch onto. The exact string MUST stay stable
    // because it ships into the DOM.
    expect(QID_SRC).toContain(
      'data-testid="record-payment-save-card-info"',
    );
  });

  it("tells the user manual payments don't save a payment method", () => {
    // Load-bearing copy — the whole point of the commit is this
    // one sentence. Match the exact phrasing shipped so a future
    // copy edit that drops the intent trips this test. The copy
    // is JSX-split across lines (prettier line-wrap), so match
    // the normalised whitespace form.
    const normalised = QID_SRC.replace(/\s+/g, " ");
    expect(normalised).toContain(
      "do not save a payment method for future use",
    );
    expect(normalised).toContain(
      "Manual payments (cash, check, external card)",
    );
  });

  it("points the user at the two paths that DO save a card", () => {
    // The banner must name both alternative paths — otherwise
    // the operator's confusion repeats on the next ticket.
    expect(QID_SRC).toContain('"Charge card" flow');
    expect(QID_SRC).toContain("payment link");
  });

  it("renders inside the RecordPaymentModal, not elsewhere", () => {
    // The banner MUST live inside RecordPaymentModal's JSX —
    // not accidentally in ConvertToJobModal or any sibling.
    // Easy cross-check: both the modal's title literal AND the
    // banner testid are present in the same source file, in
    // that order (title precedes the modal body).
    const titleIdx = QID_SRC.indexOf('title="Record Payment"');
    const bannerIdx = QID_SRC.indexOf(
      'data-testid="record-payment-save-card-info"',
    );
    const nextModalIdx = QID_SRC.indexOf(
      "function ConvertToJobModal",
    );
    expect(titleIdx).toBeGreaterThan(-1);
    expect(bannerIdx).toBeGreaterThan(titleIdx);
    expect(nextModalIdx).toBeGreaterThan(bannerIdx);
  });
});
