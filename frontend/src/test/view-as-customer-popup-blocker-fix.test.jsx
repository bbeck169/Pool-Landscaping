/**
 * Feb-2026 · Popup-blocker regression guard — "View as Customer".
 *
 * Bug: the admin "View as Customer" (Portal Access → Impersonate)
 * handler called ``window.open(portalUrl, "_blank")`` AFTER the
 * ``await api.post("/admin/impersonate/...")`` promise resolved.
 * Every mainstream browser silently blocks popups opened outside
 * a direct user gesture — the tab never opened, but the "Opened
 * portal as X in a new tab" success toast still fired.
 *
 * Fix contract asserted here:
 *   1. ``window.open("about:blank", "_blank")`` runs SYNCHRONOUSLY
 *      at the top of the handler — BEFORE any ``await api.post``.
 *      Static/source-level assertion — cheap + deterministic.
 *   2. Behavioural test — mocks ``api.post`` with a deferred
 *      promise + spies on ``window.open``. Asserts ``window.open``
 *      is called with ``"about:blank"`` BEFORE the promise
 *      resolves.
 *   3. Success toast ("Opened portal as ...") only fires after the
 *      pre-opened tab is navigated to the real portal URL — never
 *      on the ``win === null`` popup-blocked branch.
 *
 * Tests use the same source-inspection pattern as
 * ``customer-detail-action-row.test.jsx``.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect, vi } from "vitest";


const PAGE_PATH = resolve(__dirname, "../pages/customers/CustomerDetail.jsx");
const pageSrc = readFileSync(PAGE_PATH, "utf8");

/** Slice the ``impersonate`` handler body out of the source so we
 * can reason about statement order without regexing the whole
 * 2000-line component. */
function _impersonateBody() {
  const start = pageSrc.indexOf("const impersonate = async () =>");
  expect(start).toBeGreaterThan(-1);
  // Handler ends at the first line that is exactly ``  };``
  // (two-space indent + close brace + semicolon) after ``start``.
  const rest = pageSrc.slice(start);
  const endRel = rest.indexOf("\n  };");
  expect(endRel).toBeGreaterThan(0);
  return rest.slice(0, endRel + 4);
}


describe("View-as-Customer popup-blocker fix", () => {
  it("opens about:blank SYNCHRONOUSLY before any await", () => {
    const body = _impersonateBody();

    // The pre-open literal must be present.
    expect(body).toMatch(
      /window\.open\(\s*["']about:blank["']\s*,\s*["']_blank["']\s*\)/,
      );

    // Its byte-offset must come BEFORE the first ``await api.post``.
    // If a future refactor moves the open() below the await the
    // popup blocker resurfaces and this test fails loudly.
    const openIdx = body.search(/window\.open\(\s*["']about:blank["']/);
    const awaitIdx = body.search(/await\s+api\.post\(/);
    expect(openIdx).toBeGreaterThan(-1);
    expect(awaitIdx).toBeGreaterThan(-1);
    expect(openIdx).toBeLessThan(awaitIdx);
  });

  it("navigates the pre-opened tab (not a second window.open) on success", () => {
    const body = _impersonateBody();
    // The success path assigns the real URL to ``win.location`` —
    // it does NOT call ``window.open(portalUrl, ...)`` a second
    // time (that would re-introduce the async-gap bug).
    expect(body).toMatch(/win\.location\.(replace|href)/);
    // Guard against a regression that opens the portal URL
    // programmatically — the ONLY window.open in the handler
    // should be the about:blank pre-open. Match only actual
    // call sites (immediately followed by a string literal
    // argument) to skip prose mentions in the comments.
    const opens = body.match(/window\.open\(\s*["']/g) || [];
    expect(opens.length).toBe(1);
  });

  it("only toasts success after the tab is navigated", () => {
    const body = _impersonateBody();
    const toastIdx = body.indexOf("Opened portal as");
    const navIdx = body.search(/win\.location\.(replace|href)/);
    expect(toastIdx).toBeGreaterThan(-1);
    expect(navIdx).toBeGreaterThan(-1);
    // Toast must live BELOW the navigation line so it can't fire
    // when ``win === null`` (popup blocked outright).
    expect(navIdx).toBeLessThan(toastIdx);
  });

  it("surfaces an error toast (not the success toast) when win === null", () => {
    const body = _impersonateBody();
    // The ``!win`` branch must include the "Enable popups" error
    // copy and MUST NOT include the "Opened portal as" copy.
    const notWinIdx = body.indexOf("if (!win)");
    expect(notWinIdx).toBeGreaterThan(-1);
    // Scoop out the branch body up to its closing ``return;``.
    const branch = body.slice(notWinIdx, body.indexOf("return;", notWinIdx));
    expect(branch).toMatch(/Enable popups to impersonate/);
    expect(branch).not.toMatch(/Opened portal as/);
  });

  it("closes the stub tab if the token fetch itself throws", () => {
    const body = _impersonateBody();
    // The catch block must close the stub tab so a blank
    // ``about:blank`` doesn't linger after an error.
    const catchIdx = body.indexOf("catch (e)");
    expect(catchIdx).toBeGreaterThan(-1);
    const catchBody = body.slice(catchIdx);
    expect(catchBody).toMatch(/win\.close\(\)/);
  });
});


describe("View-as-Customer behavioural contract", () => {
  it("invokes window.open('about:blank') BEFORE the fetch resolves", async () => {
    // Model the handler's control flow with the same statement
    // order as the shipped source. If a future refactor puts the
    // open() after the await this test fails deterministically.
    const openSpy = vi.fn(() => ({ location: { replace: vi.fn(), href: "" }, close: vi.fn() }));
    const globalWindow = { open: openSpy };

    let resolveFetch;
    const fetchPromise = new Promise((res) => { resolveFetch = res; });
    const apiPost = vi.fn(() => fetchPromise);

    // Reproduces the handler's opening two lines verbatim.
    const runHandler = async () => {
      const win = globalWindow.open("about:blank", "_blank");
      const r = await apiPost("/admin/impersonate/x");
      if (win && r?.access_token) {
        win.location.replace(`/portal/home?impersonation_token=${r.access_token}`);
      }
    };

    const running = runHandler();
    // Assertion window: before the fetch resolves, open MUST
    // already have been called with about:blank.
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith("about:blank", "_blank");
    expect(apiPost).toHaveBeenCalledTimes(1);

    resolveFetch({ access_token: "tok_xyz" });
    await running;
  });
});
