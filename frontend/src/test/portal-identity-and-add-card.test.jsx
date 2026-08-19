/**
 * Feb-2026 P0 · Customer portal identity + add-card regression guard.
 *
 * Source-inspection tests (same fast pattern as
 * ``customer-detail-action-row.test.jsx``) for the two P0 fixes
 * shipped in the same pass:
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
 * 2. **Bug 2 (add card not found)** — ``PortalPaymentMethods``
 *    reads the customer id from ``id`` (which is what ``/api/me``
 *    returns for a portal user) instead of ``customer_id`` (which
 *    doesn't exist on the customer doc). Accepts either shape for
 *    forward compatibility if the caller ever migrates to
 *    ``/api/auth/me``.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const HOME = readFileSync(
  resolve(__dirname, "../pages/portal/PortalHome.jsx"), "utf8");
const PM   = readFileSync(
  resolve(__dirname, "../pages/portal/PortalPaymentMethods.jsx"), "utf8");


describe("Bug 1 · portal home identity binding", () => {
  it("greeting prefers server-scoped customer first_name over JWT user.name", () => {
    // The greeting resolves ``data?.customer?.first_name`` first,
    // falling back to the JWT ``user.name`` only when the server
    // hasn't responded. Locks in server-authoritative rendering.
    expect(HOME).toMatch(/data\?\.customer\?\.first_name/);
    // The comment references defense-in-depth so future refactors
    // don't accidentally invert the precedence.
    expect(HOME).toMatch(/server-scoped|SERVER-scoped/);
  });

  it("loadSummary is a real function that fires BOTH portal-summary calls", () => {
    // Regression guard for the arrow-body bug: previously the
    // arrow function ended after the FIRST ``.then(setSummary)``,
    // and the credit-balance call became a module-level side-effect
    // that ran on every render.
    const idx = HOME.indexOf("const loadSummary =");
    expect(idx).toBeGreaterThan(-1);
    const slice = HOME.slice(idx, idx + 700);
    // Braces present → the function body includes both calls.
    expect(slice).toMatch(/const loadSummary = \(\)\s*=>\s*\{/);
    expect(slice).toContain("/customer-portal/summary");
    expect(slice).toContain("/customer-portal/credits/balance");
    // Both calls are inside the same block (before the closing brace).
    const openIdx  = slice.indexOf("{");
    const closeIdx = slice.indexOf("};", openIdx);
    const body = slice.slice(openIdx, closeIdx);
    expect(body).toContain("/customer-portal/summary");
    expect(body).toContain("/customer-portal/credits/balance");
  });
});


describe("Bug 2 · portal Add-card resolves customer id from /api/me correctly", () => {
  it("PortalPaymentMethods reads id||customer_id from /api/me (tolerates both shapes)", () => {
    // ``/api/me`` returns the CUSTOMER doc with ``id`` = customer_id
    // and NO ``customer_id`` field. The fix accepts either.
    expect(PM).toMatch(/meJson\?\.customer_id\s*\|\|\s*meJson\?\.id/);
  });

  it("Payment-methods URL is built with the resolved customerId (never undefined)", () => {
    // The URL previously interpolated ``meJson.customer_id`` which
    // was undefined for portal users → ``.../payment-methods/undefined``
    // → 403 "Not allowed". Assert the fixed variable name is used.
    expect(PM).toMatch(/payments\/stripe\/payment-methods\/\$\{customerId\}/);
  });

  it("Guard branch uses the resolved id, not the raw payload shape", () => {
    // The "Your account isn't linked to a customer record" banner
    // must only render when we truly couldn't resolve an id — not
    // when the payload shape simply differs from the expectation.
    expect(PM).toMatch(/if\s*\(!meRes\.ok\s*\|\|\s*!customerId\)/);
  });
});
