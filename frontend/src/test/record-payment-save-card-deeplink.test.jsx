/**
 * Feb-2026 · TD-admin-manual-payment-save-card-feature · Commit 1c
 * vitest for the in-banner deep-link to ``AdminCardCapturePanel``.
 *
 * Operator path 1c close-out: preserve the ``20fcb8c4d`` Feb-2026
 * decision (Record Payment stays save-card-free; info banner
 * copy untouched) BUT surface the shipped admin save-card path
 * so operators who open Record Payment expecting save-card have
 * a one-click bridge to ``CustomerDetail > Payments tab`` where
 * ``AdminCardCapturePanel`` already lives (shipped Phase 14a +
 * B1 Feb-2026 — SetupIntent + Stripe Elements attach for both
 * card and ACH).
 *
 * Test posture — source-inspection, matching the sibling
 * ``record-payment-save-card-info.test.jsx`` which locks the
 * banner itself.  Full DOM mount would require stubbing every
 * deep ``QuoteInvoiceDetail`` dep (BrowserRouter, api, colors,
 * canvas CAD surface) and is disproportionate for a single
 * link addition.
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


describe("RecordPaymentModal · in-banner save-card deep-link (Commit 1c)", () => {
  it("renders the deep-link with the stable testid", () => {
    expect(QID_SRC).toContain(
      'data-testid="record-payment-save-card-info-cta"',
    );
  });

  it("targets CustomerDetail > Payments tab via the shipped tab query-param", () => {
    // The tab-switcher in CustomerDetail restores from
    // ``?tab=<key>`` (``CustomerDetail.jsx:961-976``).  The link
    // MUST use that exact query-param shape or the Payments tab
    // won't auto-select on arrival.
    expect(QID_SRC).toContain(
      "to={`/customers/${invoice.customer_id}?tab=payments`}",
    );
  });

  it("uses react-router Link so navigation is in-app (no reload)", () => {
    // react-router ``Link`` prevents a hard reload + preserves
    // auth / state.  A plain ``<a href>`` would cause a full
    // page reload and lose the auth header context.
    expect(QID_SRC).toContain(
      'import { useNavigate, useParams, Link as RouterLink } from "react-router-dom"',
    );
    const normalised = QID_SRC.replace(/\s+/g, " ");
    expect(normalised).toContain(
      "<RouterLink to={`/customers/${invoice.customer_id}?tab=payments`}",
    );
  });

  it("closes the Record Payment modal on click", () => {
    // ``onClick={onClose}`` cleans up modal state before
    // react-router actually navigates.  Keeps the invoice-page
    // modal from being left hanging in a stale state when the
    // operator returns via the back button.
    const normalised = QID_SRC.replace(/\s+/g, " ");
    expect(normalised).toContain(
      "<RouterLink to={`/customers/${invoice.customer_id}?tab=payments`} onClick={onClose}",
    );
  });

  it("surfaces an accessible name describing the destination", () => {
    expect(QID_SRC).toContain(
      'aria-label="Open the customer page to save a card on file"',
    );
  });

  it("renders the user-visible CTA label", () => {
    const normalised = QID_SRC.replace(/\s+/g, " ");
    expect(normalised).toContain("Save a card on this customer →");
  });

  it("defensively hides the link when invoice.customer_id is missing", () => {
    // Current UX always threads a customer through the invoice,
    // but belt-and-braces: the conditional ``invoice?.customer_id``
    // short-circuit prevents a stray ``/customers/undefined``
    // navigation.
    expect(QID_SRC).toContain(
      "{invoice?.customer_id ? (",
    );
  });

  it("lives INSIDE the save-card info banner, not elsewhere", () => {
    // Co-location guard — the CTA must sit inside the banner div
    // so screen readers group it with the explanatory copy
    // (``aria-describedby`` would be stronger but the sibling
    // test asserts banner text is a single <div>, so inlining is
    // the right call).  Cross-check: both testids appear in the
    // source and the CTA testid comes AFTER the banner testid in
    // file order (banner wraps the CTA).
    const bannerIdx = QID_SRC.indexOf(
      'data-testid="record-payment-save-card-info"',
    );
    const ctaIdx = QID_SRC.indexOf(
      'data-testid="record-payment-save-card-info-cta"',
    );
    expect(bannerIdx).toBeGreaterThan(-1);
    expect(ctaIdx).toBeGreaterThan(-1);
    expect(ctaIdx).toBeGreaterThan(bannerIdx);
    // AND the CTA must come before the banner's closing </div>
    // tag that follows the banner id.  Easiest proxy — the CTA
    // appears before the next ``RecordPaymentModal`` function or
    // top-level JSX element.  Use ``canBackfill`` section marker
    // (the element RIGHT AFTER the banner closes) as the bound.
    const canBackfillIdx = QID_SRC.indexOf(
      '{canBackfill ? (',
    );
    expect(canBackfillIdx).toBeGreaterThan(ctaIdx);
  });

  it("does NOT soften or remove any of the shipped banner copy", () => {
    // Regression lock mirroring the sibling banner test file —
    // if a future author tries to "clean up" the banner while
    // adding more link surface area, these string checks fail
    // loudly before the sibling test gets to.
    const normalised = QID_SRC.replace(/\s+/g, " ");
    expect(normalised).toContain(
      "Manual payments (cash, check, external card)",
    );
    expect(normalised).toContain(
      "do not save a payment method for future use",
    );
    expect(QID_SRC).toContain('"Charge card" flow');
    expect(QID_SRC).toContain("payment link");
    expect(QID_SRC).toContain("Not saving a card.");
  });
});
