/**
 * Feb-2026 · Backlog Items 2 · 4 · 5 · 6 — source-lint lock-in.
 *
 * Static regex checks against the actual source files so a
 * regression fires at CI time BEFORE a full DOM-mount test
 * catches it. The heavier flow tests live under the item-specific
 * suites; this file is a fast tripwire.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const JOB_NEW_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobNew.jsx"),
  "utf8",
);

const CUSTOMER_COMBOBOX_SRC = fs.readFileSync(
  path.resolve(__dirname, "../components/customers/CustomerCombobox.jsx"),
  "utf8",
);

const STRIPE_CARD_SRC = fs.readFileSync(
  path.resolve(__dirname, "../components/payments/StripeAddCardForm.jsx"),
  "utf8",
);

const STRIPE_BANK_SRC = fs.readFileSync(
  path.resolve(__dirname, "../components/payments/StripeAddBankForm.jsx"),
  "utf8",
);

const POOL_CHECKLIST_SRC = fs.readFileSync(
  path.resolve(__dirname, "../components/checklist/PoolChecklistForm.jsx"),
  "utf8",
);


describe("Item 2 · Crew → technician auto-suggest on New Job form", () => {
  it("useState tracks a ``techDirty`` flag", () => {
    expect(JOB_NEW_SRC).toMatch(/const\s+\[techDirty,\s*setTechDirty\]/);
  });

  it("Effect keyed on form.crew_id populates technician_id", () => {
    expect(JOB_NEW_SRC).toMatch(
      /useEffect\(\(\)\s*=>\s*\{[\s\S]{0,600}form\.crew_id[\s\S]{0,600}technician_id/,
    );
  });

  it("Auto-suggest short-circuits when techDirty is true", () => {
    expect(JOB_NEW_SRC).toMatch(/if\s*\(techDirty\)\s*return/);
  });

  it("Fallback prefers default_tech_id then first crew member", () => {
    expect(JOB_NEW_SRC).toMatch(/crew\.default_tech_id/);
    expect(JOB_NEW_SRC).toMatch(/crew\.members[\s\S]{0,200}\.find/);
    expect(JOB_NEW_SRC).toMatch(/crew\.tech_ids/);
  });

  it("Manual tech pick flips techDirty=true so subsequent crew picks don't overwrite", () => {
    expect(JOB_NEW_SRC).toMatch(
      /jf-tech[\s\S]{0,600}setTechDirty\(true\)|setTechDirty\(true\)[\s\S]{0,600}jf-tech/,
    );
  });
});


describe("Item 4 · Chemical readings null vs zero distinction (lock-in)", () => {
  it("Empty input commits null, never coerces to zero", () => {
    // The existing implementation already handles this correctly —
    // this test locks it in so a future refactor doesn't regress.
    expect(POOL_CHECKLIST_SRC).toMatch(
      /if\s*\(draft\s*===\s*""\)\s*\{\s*onChange\(null\)/,
    );
  });

  it("hasValue check distinguishes 0 from null", () => {
    expect(POOL_CHECKLIST_SRC).toMatch(
      /reading\.value\s*!=\s*null\s*&&\s*reading\.value\s*!==\s*""/,
    );
  });

  it("Previous reading falls back to em-dash when null", () => {
    // ``Previously tested at: {previous ? ... : "—"}`` — the else
    // branch is the em-dash.
    expect(POOL_CHECKLIST_SRC).toMatch(/Previously tested at:[\s\S]{0,500}"—"/);
  });

  it("Validator returns null (not zero) for empty raw input", () => {
    expect(POOL_CHECKLIST_SRC).toMatch(
      /raw\s*===\s*""\s*\|\|\s*raw\s*==\s*null[\s\S]{0,60}value:\s*null/,
    );
  });
});


describe("Item 5 · CustomerCombobox email/phone subtitle", () => {
  it("Renders email + phone auxiliary line under the customer name", () => {
    expect(CUSTOMER_COMBOBOX_SRC).toMatch(/emailStr/);
    expect(CUSTOMER_COMBOBOX_SRC).toMatch(/_formatPhone\(/);
    expect(CUSTOMER_COMBOBOX_SRC).toMatch(/data-testid=\{`\$\{testid\}-item-\$\{c\.id\}-aux`\}/);
  });

  it("Subtitle hidden when both email + phone are empty", () => {
    expect(CUSTOMER_COMBOBOX_SRC).toMatch(/hasAux\s*\?\s*\(/);
  });

  it("Formats US phone as (XXX) XXX-XXXX", () => {
    expect(CUSTOMER_COMBOBOX_SRC).toMatch(/\(\$\{usDigits\.slice\(0,\s*3\)\}\)/);
  });

  it("Search value includes email + phone so admins can jump by either", () => {
    expect(CUSTOMER_COMBOBOX_SRC).toMatch(
      /searchValue\s*=\s*\[c\.name,\s*emailStr,\s*phoneStr\]/,
    );
  });
});


describe("Item 6 · Stripe pubkey race polish", () => {
  it("StripeAddCardForm gates 'not configured' error behind pubKeyLoading", () => {
    expect(STRIPE_CARD_SRC).toMatch(/pubKeyLoading/);
    expect(STRIPE_CARD_SRC).toMatch(/data-testid="stripe-add-card-loading-pubkey"/);
    expect(STRIPE_CARD_SRC).toMatch(/data-testid="stripe-add-card-not-configured"/);
  });

  it("StripeAddCardForm auto-detects race when caller doesn't pass pubKeyLoading", () => {
    // 6-second grace window — during that time we show the
    // spinner even without an explicit opt-in prop.
    expect(STRIPE_CARD_SRC).toMatch(/autoLoadingElapsed/);
    expect(STRIPE_CARD_SRC).toMatch(/setTimeout\([\s\S]{0,50}6000\)/);
  });

  it("StripeAddBankForm carries the same race guard", () => {
    expect(STRIPE_BANK_SRC).toMatch(/pubKeyLoading/);
    expect(STRIPE_BANK_SRC).toMatch(/data-testid="stripe-add-bank-loading-pubkey"/);
    expect(STRIPE_BANK_SRC).toMatch(/data-testid="stripe-add-bank-not-configured"/);
    expect(STRIPE_BANK_SRC).toMatch(/autoLoadingElapsed/);
  });

  it("Loading state shows 'Loading payment form…' copy", () => {
    // Verbatim per spec so a future translation / rename regresses
    // the visible copy the tester was after.
    expect(STRIPE_CARD_SRC).toMatch(/Loading payment form…/);
    expect(STRIPE_BANK_SRC).toMatch(/Loading payment form…/);
  });
});
