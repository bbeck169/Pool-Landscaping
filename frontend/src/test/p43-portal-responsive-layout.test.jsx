/**
 * Phase P43 · Feb-2026 — Portal Sticky Header + Responsive Layout Polish.
 *
 * Contract locked by these tests:
 *
 *   1. The customer-portal branch of ``AppLayout`` renders a real
 *      sticky ``<header data-testid="portal-sticky-header">`` (not
 *      the floating three-pill cluster from P34/P38).
 *   2. That header hosts ``<UniversalMenu variant="inline"
 *      showSignOut />`` so Sign-out + Bell + hamburger sit inline in
 *      the header row (no floating right-3 anchors, no ``pt-16``
 *      compensation shim on the outlet).
 *   3. The portal outlet wrapper caps at ``max-w-5xl mx-auto`` with
 *      ``px-4`` gutters + ``w-full`` on the customer branch only.
 *      Admin/staff wrapper stays empty-className.
 *   4. Every portal page's leading top-padding hack (``mt-12`` /
 *      ``sm:mt-0``) that used to compensate for the floating menu
 *      has been stripped — the sticky header now owns that vertical
 *      space natively.
 *   5. ``UniversalMenu`` accepts ``showSignOut`` and honors it inside
 *      the inline variant (renders a portal Sign-out pill in the
 *      header row).
 *   6. The floating variant of ``UniversalMenu`` still exists (kept
 *      as defensive fallback) and still wraps its cluster in the
 *      P38 wrapper (``fixed top-3 right-3 z-40 flex items-center
 *      gap-2``) — but no known caller passes the default variant.
 *   7. ``PaymentMethodPromptBanner`` renders INSIDE the portal
 *      outlet wrapper, BEFORE ``<Outlet />`` in DOM order.  This is
 *      the P43 addendum — the banner used to sit as a flex-row
 *      sibling of the sidebar (competing horizontally on desktop
 *      and squashing at narrow widths).  It is now stacked
 *      vertically at the top of the ``max-w-5xl mx-auto`` container.
 *
 * File-inspection style mirrors ``phase30-3-portal-sign-out.test.jsx``
 * so this suite runs fast under ``vitest run`` without needing the
 * full router/auth/mocked-jsdom shell.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");
const APP_LAYOUT     = R("../layouts/AppLayout.jsx");
const UNIVERSAL_MENU = R("../layouts/UniversalMenu.jsx");
const PORTAL_HOME    = R("../pages/portal/PortalHome.jsx");

describe("Phase P43 · Portal sticky header + layout polish", () => {
  it("AppLayout mounts a sticky <header> with testid `portal-sticky-header` on the customer-portal branch", () => {
    // The customer-portal branch is the ``!["admin", "super_admin",
    // "manager", "technician"].includes(...)`` guard just above the
    // header render.  We assert both the guard and the sticky
    // ``top-0 z-30`` positioning on the header itself.
    expect(APP_LAYOUT).toMatch(
      /!\[\s*"admin"\s*,\s*"super_admin"\s*,\s*"manager"\s*,\s*"technician"\s*\]\.includes\(/,
    );
    const header = APP_LAYOUT.match(
      /<header[\s\S]{0,600}data-testid=["']portal-sticky-header["'][\s\S]{0,120}>/,
    );
    expect(header).not.toBeNull();
    // Positioning contract — sticky top-0, above outlet z-index.
    expect(header[0]).toMatch(/sticky/);
    expect(header[0]).toMatch(/top-0/);
    // The 56px vertical slot (``h-14``) is what replaces the old
    // ``pt-16`` compensation — the outlet gets its space back naturally.
    expect(header[0]).toMatch(/h-14/);
  });

  it("portal-sticky-header mounts <UniversalMenu variant='inline' showSignOut />", () => {
    // Grab the header block and assert the inline-variant menu with
    // Sign-out sits inside it.
    const block = APP_LAYOUT.match(
      /<header[\s\S]{0,600}data-testid=["']portal-sticky-header["'][\s\S]*?<\/header>/,
    );
    expect(block).not.toBeNull();
    expect(block[0]).toMatch(
      /<UniversalMenu\s+variant=["']inline["']\s+showSignOut\s*\/>/,
    );
  });

  it("portal outlet wrapper uses `w-full max-w-5xl mx-auto px-4` and NOT a `pt-16` compensation shim", () => {
    // The classname is emitted only on the portal branch (via the
    // ``location.pathname.startsWith("/portal")`` ternary).  Match
    // the ternary + the exact class string in one shot.
    expect(APP_LAYOUT).toMatch(
      /location\.pathname\.startsWith\(["']\/portal["']\)\s*\?\s*["']w-full max-w-5xl mx-auto px-4["']/,
    );
    // Regression guard — the pre-P43 ``pt-16`` compensation (added
    // in P34 to clear the floating UniversalMenu) must be gone.
    expect(APP_LAYOUT).not.toMatch(/["']w-full max-w-5xl mx-auto px-4 pt-16["']/);
    expect(APP_LAYOUT).not.toMatch(/pt-16 sm:pt-\d+/);
  });

  it("portal outlet wrapper carries `data-testid='portal-outlet-wrapper'`", () => {
    expect(APP_LAYOUT).toMatch(
      /data-testid=\{\s*[\s\S]{0,200}\?\s*["']portal-outlet-wrapper["']\s*:\s*["']admin-outlet-wrapper["']/,
    );
  });

  it("PaymentMethodPromptBanner renders INSIDE the portal outlet wrapper ABOVE <Outlet />", () => {
    // Isolate the portal outlet wrapper block (the <div> whose
    // testid ternary picks between ``portal-outlet-wrapper`` and
    // ``admin-outlet-wrapper``) and assert the banner + Outlet
    // both live inside it, banner FIRST.
    const wrapperMatch = APP_LAYOUT.match(
      /<div\s+className=\{[\s\S]{0,220}max-w-5xl[\s\S]{0,220}data-testid=\{[\s\S]{0,220}portal-outlet-wrapper[\s\S]*?<\/div>\s*<\/OnboardingGate>/,
    );
    expect(wrapperMatch).not.toBeNull();
    const wrapper = wrapperMatch[0];

    // Banner must be present, gated on the portal path (portal-only).
    expect(wrapper).toMatch(/<PaymentMethodPromptBanner\s*\/>/);
    expect(wrapper).toMatch(
      /location\.pathname\.startsWith\(["']\/portal["']\)\s*\?\s*\(\s*<PaymentMethodPromptBanner/,
    );
    // Outlet must be present.
    expect(wrapper).toMatch(/<Outlet\s*\/>/);

    // DOM order — banner index < Outlet index inside the wrapper.
    // Strip JSX/JS block comments first so the P43 explanatory
    // comment that mentions ``<Outlet />`` in prose can't shadow
    // the real render's index.
    const wrapperNoComments = wrapper
      .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")   // strip {/* JSX comments */}
      .replace(/\/\*[\s\S]*?\*\//g, "");      // strip /* JS comments */
    const bannerIdx = wrapperNoComments.indexOf("<PaymentMethodPromptBanner");
    const outletIdx = wrapperNoComments.indexOf("<Outlet");
    expect(bannerIdx).toBeGreaterThan(-1);
    expect(outletIdx).toBeGreaterThan(-1);
    expect(bannerIdx).toBeLessThan(outletIdx);
  });

  it("legacy `PaymentMethodPromptBanner` render slot in the outer flex-row is removed", () => {
    // Pre-P43 the banner rendered as a direct child of the outer
    // ``<div className="min-h-screen flex flex-col md:flex-row">``,
    // above the ``<aside>`` sidebar.  That slot must be gone (only
    // one PaymentMethodPromptBanner render call should remain, and
    // it must be the one inside the outlet wrapper — asserted above).
    const renders = APP_LAYOUT.match(/<PaymentMethodPromptBanner\s*\/>/g) || [];
    expect(renders.length).toBe(1);
  });

  it("UniversalMenu accepts a `showSignOut` prop and renders the Sign-out pill inline when it's truthy", () => {
    // Prop threading — the default value pattern should be
    // ``{ variant = "floating", showSignOut = false } = {}`` (P43
    // introduces the second key; do not gate on default value order).
    expect(UNIVERSAL_MENU).toMatch(/showSignOut\s*=\s*false/);
    // Inline variant should conditionally render a
    // ``data-testid="portal-signout"`` button when ``showSignOut &&
    // user`` is truthy.
    expect(UNIVERSAL_MENU).toMatch(
      /showSignOut\s*&&\s*user\s*\?\s*\(\s*<button[\s\S]{0,600}data-testid=["']portal-signout["']/,
    );
  });

  it("UniversalMenu floating variant keeps the P38 cluster wrapper (defensive fallback)", () => {
    // The floating branch must still wrap its three children in
    // ``fixed top-3 right-3 z-40 flex items-center gap-2`` — the
    // P38 fix that stopped three separate ``fixed`` anchors from
    // fighting each other for the top-right pixel.
    expect(UNIVERSAL_MENU).toMatch(
      /data-testid=["']universal-menu-floating-wrap["'][\s\S]{0,200}fixed top-3 right-3 z-40 flex items-center gap-2/,
    );
  });

  it("PortalHome CTA row no longer carries the `mt-12` / `sm:mt-0` top-offset hack", () => {
    // The CTA row is ``data-testid="portal-cta-row"``.  Its class
    // list must NOT contain the ``mt-12`` compensation used to push
    // it below the floating UniversalMenu pill cluster.
    const cta = PORTAL_HOME.match(
      /<div[\s\S]{0,400}data-testid=["']portal-cta-row["']/,
    );
    expect(cta).not.toBeNull();
    expect(cta[0]).not.toMatch(/mt-12/);
    expect(cta[0]).not.toMatch(/sm:mt-0/);
    // Belt-and-suspenders — no other portal-page-level ``mt-12``
    // top-padding hack should survive elsewhere in PortalHome
    // (defensive check; the CTA row was the only site).
    expect(PORTAL_HOME).not.toMatch(/className=["'][^"']*\bmt-12\b/);
  });
});
