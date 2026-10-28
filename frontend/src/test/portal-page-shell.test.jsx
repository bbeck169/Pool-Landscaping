/**
 * Phase 18b · Feb-2026 — Portal page shell wrapper + sweep.
 *
 * Two-layer coverage:
 *
 *   1. Shell contract — ``PortalPageShell`` renders the pixel-
 *      identical home-page card chrome (outer page wrapper + white
 *      inner card with the inline-style white bg + border).
 *
 *   2. Adoption sweep — every portal sub-page under
 *      ``src/pages/portal/`` that should render inside the shell
 *      imports and mounts ``<PortalPageShell>`` exactly once per
 *      top-level export.
 *
 *   3. Exclusion lock — the three EXCLUDED surfaces
 *      (``PortalHome``, ``PortalSign``, ``/portal/login`` →
 *      ``Login`` with ``variant="customer"``) MUST NOT mount
 *      ``PortalPageShell`` to avoid double-wrapping or breaking
 *      the full-bleed signature capture surface.
 *
 * Source-grep style — zero runtime render, so this stays fast and
 * doesn't need the deep DOM mocks every portal page already pulls
 * in for runtime rendering.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";


function read(rel) {
  return fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");
}


const SHELL_SRC    = read("src/components/portal/PortalPageShell.jsx");
const HOME_SRC     = read("src/pages/portal/PortalHome.jsx");
const PAGES_SRC    = read("src/pages/portal/PortalPages.jsx");
const SR_SRC       = read("src/pages/portal/PortalServiceReports.jsx");
const WAR_SRC      = read("src/pages/portal/PortalWarranties.jsx");
const CHATS_SRC    = read("src/pages/portal/PortalChatsPage.jsx");
const PHOTOS_SRC   = read("src/pages/portal/PortalPhotosPage.jsx");
const VIDEOS_SRC   = read("src/pages/portal/PortalVideosPage.jsx");
const REVIEWS_SRC  = read("src/pages/portal/PortalReviews.jsx");
const TERMS_SRC    = read("src/pages/portal/PortalTerms.jsx");
const REFER_SRC    = read("src/pages/portal/PortalReferralsPage.jsx");
const PREFS_SRC    = read("src/pages/portal/PortalPreferences.jsx");
const SIGN_SRC     = read("src/pages/portal/PortalSign.jsx");


describe("PortalPageShell · Phase 18b · shell chrome contract", () => {
  it("renders the pixel-identical home-page outer wrapper classes", () => {
    // Grep-sourced from PortalHome.jsx line ~143:
    //   <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
    //        data-testid="portal-home">
    expect(SHELL_SRC).toMatch(
      /className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6"/,
    );
    // Confirm the home page is still the source-of-truth for the
    // same outer wrapper. If this snaps, the shell diverged from
    // home and the two surfaces will drift apart visually.
    expect(HOME_SRC).toMatch(
      /className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6"/,
    );
  });

  it("renders the pixel-identical home-page white dashboard card classes + inline style", () => {
    // Grep-sourced from PortalHome.jsx line ~194-198:
    //   <div className="rounded-3xl p-5 md:p-6 mb-5 shadow-lg"
    //        style={{ backgroundColor: "#FFFFFF",
    //                 border: "1px solid #E5E7EB" }}
    //        data-testid="portal-dashboard-card">
    //
    // The shell appends a scope class ``portal-page-shell-card``
    // so the ``.portal-dark`` text-color carve-out in
    // ``src/styles/portal-dark.css`` applies; the base class
    // string must still match the home-page source verbatim.
    expect(SHELL_SRC).toMatch(
      /"rounded-3xl p-5 md:p-6 mb-5 shadow-lg portal-page-shell-card "/,
    );
    expect(SHELL_SRC).toMatch(
      /backgroundColor:\s*"#FFFFFF"\s*,\s*border:\s*"1px solid #E5E7EB"/,
    );
    // Confirm the home page still carries the same class + style.
    expect(HOME_SRC).toMatch(
      /className="rounded-3xl p-5 md:p-6 mb-5 shadow-lg"/,
    );
    expect(HOME_SRC).toMatch(
      /backgroundColor:\s*"#FFFFFF"\s*,\s*border:\s*"1px solid #E5E7EB"/,
    );
  });

  it("emits the shell + card data-testids so adoption can be verified in DOM tests", () => {
    // Outer wrapper exposes a configurable testid (default:
    // ``portal-page-shell``).
    expect(SHELL_SRC).toMatch(/data-testid=\{testid\}/);
    // Inner card exposes a stable testid for CSS carve-out +
    // visual regression anchoring.
    expect(SHELL_SRC).toMatch(/data-testid="portal-page-shell-card"/);
  });
});


describe("PortalPageShell · Phase 18b · portal sub-page adoption sweep", () => {
  const WRAPPED = [
    ["PortalPages.jsx",            PAGES_SRC],
    ["PortalServiceReports.jsx",   SR_SRC],
    ["PortalWarranties.jsx",       WAR_SRC],
    ["PortalChatsPage.jsx",        CHATS_SRC],
    ["PortalPhotosPage.jsx",       PHOTOS_SRC],
    ["PortalVideosPage.jsx",       VIDEOS_SRC],
    ["PortalReviews.jsx",          REVIEWS_SRC],
    ["PortalTerms.jsx",            TERMS_SRC],
    ["PortalReferralsPage.jsx",    REFER_SRC],
    ["PortalPreferences.jsx",      PREFS_SRC],
  ];

  it.each(WRAPPED)("%s imports PortalPageShell", (_name, src) => {
    expect(src).toMatch(
      /import\s+PortalPageShell\s+from\s+"@\/components\/portal\/PortalPageShell"/,
    );
  });

  it.each(WRAPPED)("%s mounts <PortalPageShell> at least once", (_name, src) => {
    // ZZ-A Wave 3-C · Feb-2026 — loosened the open-tag regex from
    // the no-attribute form to a form that allows one or more
    // attributes (``<PortalPageShell testid="portal-reviews-page">``
    // added in a later Phase 18b sub-pass to PortalReviews.jsx).
    // Negative guards below for PortalHome / PortalSign keep the
    // no-attribute form so they still correctly assert the files
    // have NO wrapper at all.
    expect(src).toMatch(/<PortalPageShell(\s[^>]*)?>/);
    expect(src).toMatch(/<\/PortalPageShell>/);
  });

  it("PortalPages.jsx wraps each of its 13 exported sub-pages", () => {
    // The file exports 13 named components (one per portal
    // sub-page route). Every export must sit inside a shell wrap
    // — count must match.
    const exportCount = (PAGES_SRC.match(/^export function \w+\(\)/gm) || []).length;
    const openCount = (PAGES_SRC.match(/<PortalPageShell>/g) || []).length;
    const closeCount = (PAGES_SRC.match(/<\/PortalPageShell>/g) || []).length;
    expect(exportCount).toBe(13);
    expect(openCount).toBe(13);
    expect(closeCount).toBe(13);
  });

  it("PortalServiceReports.jsx wraps both the list and the detail exports", () => {
    // ZZ-A Wave 3-C · Feb-2026 — the thesis is "every export is
    // wrapped at least once", not "exactly 2 opens total". The
    // file's 2 exports now render 4 wrap-points (list @213, detail
    // @473, two state-branch render paths @535/@562) because the
    // detail export's success / loading / error states each
    // short-circuit with their own ``<PortalPageShell>`` wrap
    // rather than a single top-level wrap. Rebaselined to assert
    // ``openCount >= exportCount`` so each export is guaranteed
    // wrapped without over-constraining the state-branch count.
    const exportCount = (SR_SRC.match(/^export function \w+\(\)/gm) || []).length;
    const openCount = (SR_SRC.match(/<PortalPageShell>/g) || []).length;
    expect(exportCount).toBe(2);
    expect(openCount).toBeGreaterThanOrEqual(exportCount);
  });
});


describe("PortalPageShell · Phase 18b · exclusion lock", () => {
  it("PortalHome.jsx is NOT wrapped (already carries its own portal-dashboard-card inline)", () => {
    // Home ships the white card chrome inline — adding
    // ``<PortalPageShell>`` on top would double-wrap.
    expect(HOME_SRC).not.toMatch(
      /import\s+PortalPageShell\s+from\s+"@\/components\/portal\/PortalPageShell"/,
    );
    expect(HOME_SRC).not.toMatch(/<PortalPageShell>/);
  });

  it("PortalSign.jsx is NOT wrapped (full-bleed signature capture)", () => {
    // PortalSign uses the ``portal-sign-scope`` CSS carve-out
    // for its own white-on-navy signature surface — a shell
    // wrap would nest two conflicting carve-outs.
    expect(SIGN_SRC).not.toMatch(/<PortalPageShell>/);
  });
});
