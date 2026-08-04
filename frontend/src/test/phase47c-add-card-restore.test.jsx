/**
 * Phase 47c · Feb 2026 — source-inspection vitest for the restored
 * /portal/add-card magic-link page + App.js route.
 *
 * Regression guards against Phase LZ4 sneaking back:
 *   • App.js must import AddCardPage and mount a Route.
 *   • The old "removed" comments must be gone / updated.
 *   • AddCardPage must NOT contain any Lumino / Zapier fetches.
 *   • The public backend endpoints it calls must be spelled correctly.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const APP_JS = resolve(__dirname, "../App.js");
const PAGE = resolve(__dirname, "../pages/public/AddCardPage.jsx");

const _app = readFileSync(APP_JS, "utf8");
const _page = readFileSync(PAGE, "utf8");

describe("Phase 47c · App.js route restoration", () => {
  it("imports AddCardPage from the public pages tree", () => {
    expect(_app).toMatch(
      /import\s+AddCardPage\s+from\s+["']@\/pages\/public\/AddCardPage["']/,
    );
  });

  it("mounts the /portal/add-card route with AddCardPage", () => {
    expect(_app).toMatch(
      /<Route\s+path=["']\/portal\/add-card["']\s+element=\{<AddCardPage\s*\/>\}\s*\/>/,
    );
  });

  it("no longer carries the Phase LZ4 'removed' comment as the live status", () => {
    // The exact old comment substrings must be gone from App.js —
    // they described the route as intentionally removed. If they
    // reappear, the route is going to disappear again on the next
    // App.js rewrite. Also confirms Phase 47c's restoration comment
    // is present.
    expect(_app).not.toContain(
      "/portal/add-card routes removed in Phase LZ4 (Feb 2026)",
    );
    expect(_app).not.toContain(
      "AddCardPage removed with the Stripe SDK\n// retirement",
    );
    expect(_app).toContain("Phase 47c");
    expect(_app).toContain("RESTORED");
  });
});

describe("Phase 47c · AddCardPage page shape", () => {
  it("uses the direct-Stripe SetupIntent endpoint (no Lumino, no Zapier)", () => {
    expect(_page).toContain("/customers/add-card/");
    expect(_page).toContain("/setup-intent");
    expect(_page).toContain("/attach");
    // Regression guard — the page must NOT call Lumino / Zapier at runtime.
    // Strip comments (both /* … */ and //-to-EOL) before scanning so the
    // docstring header explaining WHY we swapped away from Lumino/Zapier
    // doesn't trip the guard.
    const codeOnly = _page
      .replace(/\/\*[\s\S]*?\*\//g, "")   // block comments
      .replace(/^\s*\/\/.*$/gm, "");       // line comments
    expect(codeOnly).not.toMatch(/lumino/i);
    expect(codeOnly).not.toMatch(/zapier/i);
    expect(codeOnly).not.toMatch(/request-payment-link/);
    // Regression guard — the page must NOT depend on a Bearer token
    // (public magic link flow).
    expect(codeOnly).not.toMatch(/Authorization:\s*`Bearer/);
  });

  it("mounts Stripe Elements with the PaymentElement", () => {
    expect(_page).toMatch(/from ["']@stripe\/stripe-js["']/);
    expect(_page).toMatch(/from ["']@stripe\/react-stripe-js["']/);
    expect(_page).toContain("<Elements");
    expect(_page).toContain("<PaymentElement");
    expect(_page).toContain("confirmSetup");
  });

  it("reads the JWT from the URL query string, not from the auth store", () => {
    expect(_page).toContain("URLSearchParams");
    expect(_page).toContain('.get("token")');
  });

  it("gates rendering behind bootError / loading / saved / ready branches", () => {
    // Exhaustive UI states — required so the customer sees a clear
    // signal in every failure mode instead of a blank page.
    for (const testid of [
      "phase47c-add-card-page",
      "phase47c-add-card-title",
      "phase47c-add-card-loading",
      "phase47c-add-card-boot-error",
      "phase47c-add-card-form",
      "phase47c-add-card-submit",
      "phase47c-add-card-error",
      "phase47c-add-card-success",
    ]) {
      expect(_page).toContain(`data-testid="${testid}"`);
    }
  });

  it("wires the API base off REACT_APP_BACKEND_URL (no hard-coded host)", () => {
    expect(_page).toContain("process.env.REACT_APP_BACKEND_URL");
    // Anti-hardcode check.
    expect(_page).not.toMatch(/https?:\/\/(?!localhost)[^`"'\s]*emergent/);
    expect(_page).not.toContain("localhost:8001");
  });
});
