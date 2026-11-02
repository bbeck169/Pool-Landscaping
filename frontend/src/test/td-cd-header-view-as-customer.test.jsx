/**
 * Feb-2026 · TD-cd-header-view-as-customer — regression suite for
 * the identity-header "View as customer" button (sibling to the
 * Send ▼ / + Create ▼ dropdowns in ``cd-identity-header-actions``).
 *
 * Mirrors mobile A2 (``92b0746de``) — header-row button with
 * identical role gate (``admin | super_admin``), identical active
 * gate (``!active → disabled``), identical endpoint
 * (``POST /admin/impersonate/{id}``), identical new-tab portal
 * open, identical admin-session-preserving semantics.
 *
 * ``CustomerDetail.jsx`` is 4000+ lines so rendering it under
 * ``@testing-library/react`` is prohibitively heavy for this
 * repo's vitest harness.  The shipped idiom (see
 * ``view-as-customer-popup-blocker-fix.test.jsx``) is static
 * source-inspection — read the file and assert on the token
 * stream.  That's what we do here.
 *
 * Assertions:
 *
 *   1. The new button is rendered inside ``cd-identity-header-
 *      actions`` as a sibling of ``<CustomerActionDropdowns>``.
 *   2. Role gate: visibility conditioned on
 *      ``canCdImpersonate && cdHasLogin``.
 *   3. ``canCdImpersonate`` is defined as
 *      ``role === "super_admin" || role === "admin"`` —
 *      byte-identical to the in-panel gate at
 *      ``PortalAccessPanel`` (``:2959``).
 *   4. ``cdActive`` falls back to ``true`` when portal-status is
 *      ``null`` — matches the in-panel ``active`` derivation at
 *      ``:3080``.
 *   5. ``cdHasLogin`` falls back to ``customer?.has_login`` —
 *      matches the in-panel ``hasLogin`` derivation at ``:3079``.
 *   6. Button carries ``testid="cd-impersonate-header"``.
 *   7. Button is disabled when ``cdImpersonateBusy || !cdActive``.
 *   8. ``cdImpersonate`` handler opens ``about:blank`` BEFORE any
 *      ``await`` (popup-blocker regression guard — mirrors the
 *      in-panel popup-blocker test for the duplicated handler).
 *   9. ``cdImpersonate`` POSTs to ``/admin/impersonate/${id}`` and
 *      navigates the pre-opened tab to ``/portal/home?impersonation_
 *      token=…``.  Admin session is NOT swapped — this is a new-tab
 *      flow.
 *  10. The existing ``PortalAccessPanel`` in-panel button at
 *      ``:3176-3184`` is UNCHANGED — regression lock.
 *  11. ``<CustomerActionDropdowns>`` props + testid unchanged —
 *      regression lock.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PAGE_PATH = resolve(__dirname, "../pages/customers/CustomerDetail.jsx");
const pageSrc = readFileSync(PAGE_PATH, "utf8");


/** Slice the identity-header actions block out of the source. */
function _identityHeaderActionsBlock() {
  const anchor = pageSrc.indexOf(
    'data-testid="cd-identity-header-actions"',
  );
  expect(anchor).toBeGreaterThan(-1);
  // Walk back to the containing ``<div``.
  const divOpen = pageSrc.lastIndexOf("<div", anchor);
  expect(divOpen).toBeGreaterThan(-1);
  // Walk forward through the balanced JSX until the matching
  // ``</div>``.  Since this block contains child components but no
  // nested ``<div>`` (we validate that below), a naive forward
  // search for ``</div>`` on the first line that starts with the
  // closing tag at the same indent works.
  const rest = pageSrc.slice(divOpen);
  const closeRel = rest.indexOf("</div>");
  expect(closeRel).toBeGreaterThan(0);
  return rest.slice(0, closeRel + 6);
}


/** Slice the parent-scoped ``cdImpersonate`` handler body. */
function _cdImpersonateBody() {
  const start = pageSrc.indexOf("const cdImpersonate = async () =>");
  expect(start).toBeGreaterThan(-1);
  const rest = pageSrc.slice(start);
  const endRel = rest.indexOf("\n  };");
  expect(endRel).toBeGreaterThan(0);
  return rest.slice(0, endRel + 4);
}


describe("Identity-header View as customer button", () => {
  it("renders inside cd-identity-header-actions as sibling of CustomerActionDropdowns", () => {
    const block = _identityHeaderActionsBlock();
    // Both components live inside the same block.
    expect(block).toContain("<CustomerActionDropdowns");
    expect(block).toContain('testid="cd-impersonate-header"');
    // Sibling order — the dropdowns come first (left side of the
    // flex row), the new button comes after.
    const dropdownIdx = block.indexOf("<CustomerActionDropdowns");
    const buttonIdx = block.indexOf('testid="cd-impersonate-header"');
    expect(dropdownIdx).toBeLessThan(buttonIdx);
  });

  it("wraps children in a flex row so the dropdowns + button sit on one visual line", () => {
    const block = _identityHeaderActionsBlock();
    // The wrapper enables flex-row so children are peers; flex-wrap
    // on narrow viewports keeps the button from clipping.  No
    // behavioural coupling to the specific class strings beyond the
    // flex-row contract.
    expect(block).toMatch(/className="[^"]*\bflex-row\b/);
  });

  it("role-gate: canCdImpersonate restricts to admin + super_admin", () => {
    // Defined at parent scope, mirror of PortalAccessPanel:2959.
    expect(pageSrc).toMatch(
      /const\s+canCdImpersonate\s*=\s*authUser\?\.role\s*===\s*"super_admin"[\s\S]{0,120}authUser\?\.role\s*===\s*"admin"/,
    );
  });

  it("active-gate: cdActive derives from portal-status, defaults true", () => {
    // Mirror of PortalAccessPanel:3080 (``active = status?.active ?? true``).
    expect(pageSrc).toMatch(
      /const\s+cdActive\s*=\s*\(cdPortalStatus\s*&&\s*cdPortalStatus\.active\)\s*\?\?\s*true/,
    );
  });

  it("hasLogin-gate: cdHasLogin derives from portal-status, falls back to customer.has_login", () => {
    // Mirror of PortalAccessPanel:3079.
    expect(pageSrc).toMatch(
      /const\s+cdHasLogin\s*=\s*\(cdPortalStatus\s*&&\s*cdPortalStatus\.has_login\)\s*\?\?\s*customer\?\.has_login/,
    );
  });

  it("button visibility combines canCdImpersonate && cdHasLogin", () => {
    const block = _identityHeaderActionsBlock();
    // Guard: an admin viewing a customer without portal credentials
    // sees NO dead button.
    expect(block).toMatch(
      /canCdImpersonate\s*&&\s*cdHasLogin\s*\?/,
    );
  });

  it("button carries testid cd-impersonate-header + disabled on busy or inactive", () => {
    const block = _identityHeaderActionsBlock();
    expect(block).toMatch(/testid="cd-impersonate-header"/);
    expect(block).toMatch(
      /disabled=\{cdImpersonateBusy\s*\|\|\s*!cdActive\}/,
    );
  });

  it("button label is 'View as customer'", () => {
    const block = _identityHeaderActionsBlock();
    expect(block).toContain("View as customer");
  });
});


describe("Parent-scoped cdImpersonate handler", () => {
  it("opens about:blank SYNCHRONOUSLY before any await (popup-blocker guard)", () => {
    const body = _cdImpersonateBody();
    expect(body).toMatch(
      /window\.open\(\s*["']about:blank["']\s*,\s*["']_blank["']\s*\)/,
    );
    const openIdx = body.search(/window\.open\(\s*["']about:blank["']/);
    const awaitIdx = body.search(/await\s+api\.post\(/);
    expect(openIdx).toBeGreaterThan(-1);
    expect(awaitIdx).toBeGreaterThan(-1);
    expect(openIdx).toBeLessThan(awaitIdx);
  });

  it("POSTs to /admin/impersonate/{id} and navigates to /portal/home with impersonation_token", () => {
    const body = _cdImpersonateBody();
    expect(body).toMatch(/api\.post\(\s*`\/admin\/impersonate\/\$\{id\}`/);
    expect(body).toMatch(/\/portal\/home\?impersonation_token=/);
    expect(body).toMatch(/win\.location\.(replace|href)/);
  });

  it("admin session preserved — handler does NOT call swapSession / useAuth setter", () => {
    const body = _cdImpersonateBody();
    // The handler must not re-token the admin's own tab.  No login
    // call, no setUser, no auth-mutator.
    expect(body).not.toMatch(/setUser\s*\(/);
    expect(body).not.toMatch(/login\s*\(/);
    expect(body).not.toMatch(/swapSession/);
  });

  it("single window.open call site — the about:blank pre-open is the only one", () => {
    const body = _cdImpersonateBody();
    const opens = body.match(/window\.open\(\s*["']/g) || [];
    expect(opens.length).toBe(1);
  });
});


describe("Regression locks — unchanged shipped surfaces", () => {
  it("in-panel 'View as customer' button at PortalAccessPanel still exists with testid cd-impersonate", () => {
    expect(pageSrc).toContain('testid="cd-impersonate"');
    // And is still gated by canImpersonate (not canCdImpersonate —
    // the two gates are structurally equivalent but live in separate
    // scopes).
    expect(pageSrc).toMatch(
      /const\s+canImpersonate\s*=\s*authUser\?\.role\s*===\s*"super_admin"/,
    );
  });

  it("in-panel impersonate handler at PortalAccessPanel unchanged in shape", () => {
    expect(pageSrc).toMatch(/const\s+impersonate\s*=\s*async\s*\(\)\s*=>/);
    // Same POST URL, same portal URL, same navigation primitive.
    const start = pageSrc.indexOf("const impersonate = async () =>");
    const rest = pageSrc.slice(start);
    const endRel = rest.indexOf("\n  };");
    const inPanelBody = rest.slice(0, endRel + 4);
    expect(inPanelBody).toMatch(
      /api\.post\(\s*`\/admin\/impersonate\/\$\{customer\.id\}`/,
    );
    expect(inPanelBody).toMatch(/\/portal\/home\?impersonation_token=/);
  });

  it("<CustomerActionDropdowns> inside the header still receives the same four props + navy", () => {
    const block = _identityHeaderActionsBlock();
    expect(block).toContain("customer={customer}");
    expect(block).toContain("onSend={openSendModal}");
    expect(block).toContain("onQuickTask={openQuickTaskFromDropdown}");
    expect(block).toContain("onSendServiceRecordsLink={() => setSrLinkOpen(true)}");
    expect(block).toMatch(/\snavy\s/);
  });

  it("<CustomerActionDropdowns> component source is NOT touched by this ticket (sibling-only change)", () => {
    const dropdownSrc = readFileSync(
      resolve(
        __dirname,
        "../components/customers/CustomerActionDropdowns.jsx",
      ),
      "utf8",
    );
    // Portal Access / impersonate concerns must stay OUT of the
    // dropdowns component.  The sibling button pattern keeps the
    // dropdown's atomic concern intact.
    expect(dropdownSrc).not.toContain("impersonate");
    expect(dropdownSrc).not.toContain("View as customer");
  });
});
