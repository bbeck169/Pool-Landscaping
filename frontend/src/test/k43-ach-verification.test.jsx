/**
 * Phase K43 · Feb-2026 — ACH verify UI vitest.
 *
 * Source-body contract checks matching the K41/K41b/K41c pattern
 * already used across the repo — validates the admin card capture
 * panel wires the K43 verify actions, and the K38 bulk-charge modal
 * links unverified rows to the customer detail page.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const PANEL = read("src/components/customers/AdminCardCapturePanel.jsx");
const K38_MODAL = read("src/components/invoices/BulkChargeModal.jsx");
const ADD_BANK = read("src/components/payments/StripeAddBankForm.jsx");


describe("K43 · Admin panel — micro-deposit verify action", () => {
  it("adds an onVerifyMicrodeposits prop on BankRow", () => {
    expect(PANEL).toMatch(/onVerifyMicrodeposits/);
    expect(PANEL).toMatch(/data-testid=\{`admin-bank-verify-microdeposits-\$\{pmId\}`\}/);
  });

  it("shows Verify (micro-deposits) for pending_microdeposit / pending / new", () => {
    expect(PANEL).toMatch(/pendingMicrodeposit = status === "pending_microdeposit"[\s\S]{0,120}status === "pending"[\s\S]{0,80}status === "new"/);
    expect(PANEL).toMatch(/pendingMicrodeposit \?[\s\S]{0,600}Verify \(micro-deposits\)/);
  });

  it("shows Re-verify bank for anything unverified that isn't pending", () => {
    expect(PANEL).toMatch(/needsReverify = !!status && status !== "verified"[\s\S]{0,100}!pendingMicrodeposit/);
    expect(PANEL).toMatch(/\(failed \|\| needsReverify\) \?[\s\S]{0,300}Re-verify bank/);
  });

  it("renders the micro-deposit verify modal with amounts + descriptor modes", () => {
    expect(PANEL).toMatch(/data-testid="admin-bank-verify-modal"/);
    expect(PANEL).toMatch(/data-testid="admin-bank-verify-mode-amounts"/);
    expect(PANEL).toMatch(/data-testid="admin-bank-verify-mode-descriptor"/);
    expect(PANEL).toMatch(/data-testid="admin-bank-verify-amt-a"/);
    expect(PANEL).toMatch(/data-testid="admin-bank-verify-amt-b"/);
    expect(PANEL).toMatch(/data-testid="admin-bank-verify-descriptor"/);
    expect(PANEL).toMatch(/data-testid="admin-bank-verify-submit"/);
    expect(PANEL).toMatch(/data-testid="admin-bank-verify-cancel"/);
  });

  it("POSTs to the K43 verify-microdeposits endpoint", () => {
    expect(PANEL).toMatch(/\/customers\/\$\{customerId\}\/bank-accounts\/\$\{verifyPm\.provider_payment_method_id\}\/verify-microdeposits/);
    // Body contract — either amounts_cents or descriptor_code.
    expect(PANEL).toMatch(/body = \{ amounts_cents: \[a, b\] \}/);
    expect(PANEL).toMatch(/body = \{ descriptor_code: code \}/);
  });

  it("validates amount inputs client-side (cents between 1 and 99)", () => {
    expect(PANEL).toMatch(/a < 1 \|\| a > 99 \|\| b < 1 \|\| b > 99/);
  });

  it("POSTs to the K43 re-verify endpoint", () => {
    expect(PANEL).toMatch(/\/customers\/\$\{customerId\}\/bank-accounts\/\$\{row\.provider_payment_method_id\}\/re-verify/);
    expect(PANEL).toMatch(/toast\.success\(\s*json\.email_sent[\s\S]{0,180}Re-verify link emailed/);
  });

  it("no longer opens the local Add-Bank form for re-verify (K37 → K43 diff)", () => {
    // The K37 stub called setAddOpen("bank") — the K43 flow calls the
    // dedicated endpoint instead.  Guard against regression.
    const rev = PANEL.substring(
      PANEL.indexOf("startReverify"),
      PANEL.indexOf("startVerifyMicrodeposits"),
    );
    expect(rev).not.toMatch(/setAddOpen\("bank"\)/);
    expect(rev).toMatch(/re-verify/);
  });
});


describe("K43 · K38 bulk-charge modal QoL link", () => {
  it("renders the BANK NOT VERIFIED pill as a link to the customer detail", () => {
    expect(K38_MODAL).toMatch(/r\.skip_reason === "bank_unverified" && r\.customer_id/);
    expect(K38_MODAL).toMatch(/href=\{`\/customers\/\$\{r\.customer_id\}`\}/);
    expect(K38_MODAL).toMatch(/data-testid=\{`\$\{testIdPrefix\}-row-\$\{r\.invoice_id\}-verify-link`\}/);
    expect(K38_MODAL).toMatch(/title="Open customer detail to verify bank"/);
  });

  it("falls back to a plain pill when the skip reason isn't bank_unverified", () => {
    // The link branch is guarded — other skip reasons still render as
    // the original <span> pill.
    expect(K38_MODAL).toMatch(/\) : \(\s*<span\s+className=\{`rounded px-1\.5/);
  });
});


describe("K43 · StripeAddBankForm — SetupIntent FC path documented", () => {
  it("documents the K43 SetupIntent FC upgrade in the file docblock", () => {
    expect(ADD_BANK).toMatch(/K43 · Feb-2026 — the backend ``create_setup_intent`` helper now/);
    expect(ADD_BANK).toMatch(/verification_method[\s\S]{0,120}instant/);
    expect(ADD_BANK).toMatch(/financial_connections\.permissions/);
  });
});
