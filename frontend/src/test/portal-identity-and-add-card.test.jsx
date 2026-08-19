/**
 * Feb-2026 P0 · Customer portal identity + Add-card regression guard.
 *
 * Two closely related fixes shipped in the same pass:
 *
 * 1. **Bug 1 (identity leak)** — ``PortalHome`` binds the greeting
 *    to the SERVER-scoped customer name from ``/portal/home``, not
 *    the JWT ``user.name`` claim. So if a stale/mis-linked
 *    ``users.customer_id`` ever resolves the wrong customer on the
 *    server, the greeting will reflect the CUSTOMER the data
 *    actually corresponds to (identity_mismatch flag makes the
 *    disconnect visible).
 *
 *    Also asserts the accidental arrow-function boundary bug on
 *    ``loadSummary`` is gone — the function used to only include
 *    the first ``.then(setSummary)`` and left the credit-balance
 *    fetch as a module-level side-effect that ran on every render.
 *
 * 2. **Bug 2 (Add card "Not Found") · Item A rebase** — the LIVE
 *    portal payment-method surface is ``<PortalPaymentMethod>``
 *    (singular) inside ``pages/portal/PortalPages.jsx``, mounted on
 *    the ``/portal/payment-method`` route. Prior fix landed on the
 *    dead-code ``PortalPaymentMethods.jsx`` (plural). This suite
 *    now targets the correct component and locks in:
 *      • no more calls to the missing ``/payments/method`` or
 *        ``/payments/setup-session`` endpoints,
 *      • the inline SetupIntent + Elements flow via the shared
 *        ``StripeAddCardForm`` component,
 *      • the payment-methods list read from the portal-scoped
 *        ``/customer-portal/payment-methods`` endpoint,
 *      • the legacy plural component + route are gone.
 */
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const HOME  = readFileSync(
  resolve(__dirname, "../pages/portal/PortalHome.jsx"), "utf8");
const PAGES = readFileSync(
  resolve(__dirname, "../pages/portal/PortalPages.jsx"), "utf8");
const APP   = readFileSync(
  resolve(__dirname, "../App.js"), "utf8");


// Slice out just the ``PortalPaymentMethod`` component so tests
// don't accidentally match strings elsewhere in this 1000+ line file.
function _pmComponent() {
  const start = PAGES.indexOf("export function PortalPaymentMethod()");
  expect(start).toBeGreaterThan(-1);
  const end = PAGES.indexOf("\nexport function ", start + 1);
  return end === -1 ? PAGES.slice(start) : PAGES.slice(start, end);
}


describe("Bug 1 · portal home identity binding", () => {
  it("greeting prefers server-scoped customer first_name over JWT user.name", () => {
    expect(HOME).toMatch(/data\?\.customer\?\.first_name/);
    expect(HOME).toMatch(/server-scoped|SERVER-scoped/);
  });

  it("loadSummary is a real function that fires BOTH portal-summary calls", () => {
    const idx = HOME.indexOf("const loadSummary =");
    expect(idx).toBeGreaterThan(-1);
    const slice = HOME.slice(idx, idx + 700);
    expect(slice).toMatch(/const loadSummary = \(\)\s*=>\s*\{/);
    expect(slice).toContain("/customer-portal/summary");
    expect(slice).toContain("/customer-portal/credits/balance");
    const openIdx  = slice.indexOf("{");
    const closeIdx = slice.indexOf("};", openIdx);
    const body = slice.slice(openIdx, closeIdx);
    expect(body).toContain("/customer-portal/summary");
    expect(body).toContain("/customer-portal/credits/balance");
  });
});


describe("Bug 2 · Item A · <PortalPaymentMethod> in PortalPages.jsx", () => {
  it("mounts on /portal/payment-method and legacy plural route is gone", () => {
    expect(APP).toMatch(/path="portal\/payment-method"\s+element=\{<PortalPaymentMethod\s*\/>/);
    expect(APP).not.toMatch(/path="portal\/payment-methods"/);
    expect(APP).not.toMatch(/import PortalPaymentMethods /);
  });

  it("legacy dead component file has been deleted", () => {
    const dead = resolve(__dirname, "../pages/portal/PortalPaymentMethods.jsx");
    expect(existsSync(dead)).toBe(false);
  });

  it("no longer calls the missing /payments/method or /payments/setup-session endpoints", () => {
    const src = _pmComponent();
    // Only fail on ACTUAL api.get/api.post calls to those paths —
    // doc comments referencing the old paths are fine and desirable.
    expect(PAGES).not.toMatch(/api\.(get|post)\(\s*["']\/payments\/method["']/);
    expect(PAGES).not.toMatch(/api\.(get|post)\(\s*["']\/payments\/setup-session["']/);
    expect(src).not.toMatch(/api\.(get|post)\(\s*["']\/payments\/method["']/);
    expect(src).not.toMatch(/api\.(get|post)\(\s*["']\/payments\/setup-session["']/);
  });

  it("reads the card list from the portal-scoped /customer-portal/payment-methods endpoint", () => {
    const src = _pmComponent();
    expect(src).toContain('/customer-portal/payment-methods');
    // Picks the default (or first) card so the summary chip works
    // with the ``{methods: [...]}`` envelope shape.
    expect(src).toMatch(/Array\.isArray\(r\?\.methods\)/);
    expect(src).toMatch(/is_default/);
  });

  it("Add card uses the inline SetupIntent + Elements form (no redirect, no /undefined)", () => {
    const src = _pmComponent();
    expect(src).toMatch(/import\s+StripeAddCardForm|StripeAddCardForm/);
    expect(src).toMatch(/<StripeAddCardForm\b/);
    // The handler must NOT redirect via window.location or open a
    // new tab (that was the old checkout-session flow).
    expect(src).not.toMatch(/window\.location\.assign/);
    expect(src).not.toMatch(/window\.open\(/);
    // Elements form gets a real publishable key from the shared
    // /payments/stripe/config endpoint helper, and the auth token
    // from localStorage — same wiring the shared form expects.
    expect(src).toMatch(/getStripeConfig/);
    expect(src).toMatch(/publishableKey=\{pubKey\}/);
  });

  it("Add card handler never constructs a URL with /undefined", () => {
    // The shared ``StripeAddCardForm`` posts to
    // ``/payments/stripe/setup-intent`` internally and the backend
    // derives ``customer_id`` from the JWT — so there is no code
    // path in this component that interpolates a raw customer id
    // into a URL. Confirm the component does NOT build a
    // payment-methods URL from a client-side id at all.
    const src = _pmComponent();
    expect(src).not.toMatch(/api\.(get|post|delete)\([^)]*\/payment-methods\/\$\{/);
  });

  it("onSuccess refreshes the card-on-file summary so the banner clears", () => {
    const src = _pmComponent();
    expect(src).toMatch(/onSuccess=\{onAddCardSuccess\}/);
    expect(src).toMatch(/const\s+onAddCardSuccess\s*=/);
    // The refresh calls the same loader the initial mount uses.
    expect(src).toMatch(/loadPm\(\)/);
  });
});


describe("Bug 2 · Item A · <PortalPayments> summary chip", () => {
  it("reads card-on-file from /customer-portal/payment-methods (not /payments/method)", () => {
    // The Payments page shows a chip that used to hit /payments/method.
    const start = PAGES.indexOf("export function PortalPayments()");
    const end   = PAGES.indexOf("\nexport function ", start + 1);
    const src   = PAGES.slice(start, end);
    expect(src).toContain('/customer-portal/payment-methods');
    // Only fail on the ACTUAL api.get call to the old path (comments
    // referencing it are welcome for context).
    expect(src).not.toMatch(/api\.get\(\s*["']\/payments\/method["']/);
  });
});
