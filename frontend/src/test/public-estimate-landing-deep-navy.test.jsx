/**
 * Feb 2026 · Public-estimate landing · deep-navy full-viewport background.
 *
 * Mirrors the treatment shipped in commit 932c45c65 on the two
 * public-invoice magic-link surfaces (``PublicInvoicePay`` +
 * ``PublicInvoiceMagic``). Both containers on
 * ``PublicEstimateLanding`` — the happy-path root and the
 * missing-token error branch — now paint a full-viewport deep-navy
 * background using ``colors.nav.bgDeep`` (== ``#03002e``, defined
 * in the ``nav`` bucket at ``frontend/src/theme.js``). The white
 * estimate card inside ``<EstimateView>`` is intentionally NOT
 * touched — it stays white and floats visually over the navy page.
 *
 * ``colors.nav.bg`` (== ``#1B1F5C`` — the sitewide sidebar / menu
 * navy) is intentionally NOT reused here; the deep and menu navies
 * must never conflate on the same surface. Guardrail: the file
 * must import ``{ colors }`` from ``@/theme`` and both hex values
 * must still resolve to their pinned tokens in ``theme.js``. If
 * either token is ever renamed or moved out of the ``nav`` bucket,
 * this suite must fail so the rename lands here in the same PR.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const LANDING_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/portal/PublicEstimateLanding.jsx"),
  "utf8",
);

/** ``className`` / ``style`` / ``data-testid`` order-agnostic co-presence. */
function nearBoth(src, testId, needle, window = 400) {
  const re = new RegExp(
    `${needle}[\\s\\S]{0,${window}}data-testid="${testId}"` +
    `|data-testid="${testId}"[\\s\\S]{0,${window}}${needle}`,
  );
  return re.test(src);
}

describe("PublicEstimateLanding · Feb 2026 deep-navy page background", () => {
  it("imports ``{ colors }`` from ``@/theme``", () => {
    expect(LANDING_SRC).toMatch(
      /import\s+\{\s*colors\s*\}\s+from\s+"@\/theme"/,
    );
  });

  it("root happy-path container paints ``colors.nav.bgDeep`` + full-viewport minHeight", () => {
    // Same shape as PublicInvoicePay / PublicInvoiceMagic — the
    // outer wrapper carries the navy background + minHeight 100vh
    // so the white estimate card floats over the navy page.
    expect(
      nearBoth(LANDING_SRC, "public-estimate-landing",
                "background:\\s*colors\\.nav\\.bgDeep"),
    ).toBe(true);
    expect(
      nearBoth(LANDING_SRC, "public-estimate-landing",
                "minHeight:\\s*[\"']100vh[\"']"),
    ).toBe(true);
  });

  it("missing-token error container also paints deep-navy + full viewport", () => {
    expect(
      nearBoth(LANDING_SRC, "public-estimate-landing-missing-token",
                "background:\\s*colors\\.nav\\.bgDeep"),
    ).toBe(true);
    expect(
      nearBoth(LANDING_SRC, "public-estimate-landing-missing-token",
                "minHeight:\\s*[\"']100vh[\"']"),
    ).toBe(true);
  });

  it("never falls back to ``colors.nav.bg`` (sidebar-navy) on this surface", () => {
    // ``colors.nav.bg`` is the sitewide sidebar / menu navy
    // (``#1B1F5C``) used by AppLayout / AdminTopBar / NavyFilterBar.
    // Only ``colors.nav.bgDeep`` may appear on the public-estimate
    // surface so the deep + menu navies never conflate.
    expect(LANDING_SRC).not.toMatch(/colors\.nav\.bg\b/);
  });

  it("does NOT tint the inner estimate card (EstimateView renders its own white surface)", () => {
    // Guardrail: no ``background: colors.`` on the inner wrapper
    // that houses <EstimateView />. The inner container keeps only
    // its layout classes (``max-w-4xl mx-auto ...``) so the white
    // estimate card retains its intentional white background.
    expect(LANDING_SRC).toMatch(
      /max-w-4xl\s+mx-auto\s+px-2\s+sm:px-4\s+lg:px-6\s+py-4/,
    );
    // No colors.* on any element that also carries the max-w-4xl
    // layout class — the layout class must live on a bare div.
    const innerMatch = LANDING_SRC.match(
      /<div[^>]*max-w-4xl[^>]*>/,
    );
    expect(innerMatch).not.toBeNull();
    expect(innerMatch[0]).not.toMatch(/colors\./);
    expect(innerMatch[0]).not.toMatch(/background:/);
  });

  it("``colors.nav.bgDeep`` (and ``colors.nav.bg``) still resolve to their pinned hex values in theme.js", () => {
    // Silent-rename guardrail — if either token moves or the hex
    // changes, this landing surface (bgDeep) or any admin nav
    // chrome consumer (bg) would silently break. Assert both hex
    // values directly against the theme source so any rename
    // must land in the same PR as an update here.
    const THEME_SRC = fs.readFileSync(
      path.resolve(__dirname, "../theme.js"),
      "utf8",
    );
    const navBlock = THEME_SRC.match(/\bnav\s*:\s*\{[\s\S]*?\n\s*\},/);
    expect(navBlock).not.toBeNull();
    // ``bg`` — sitewide sidebar / menu navy — stays as-is.
    expect(navBlock[0]).toMatch(/\bbg\s*:\s*"#1B1F5C"/);
    // ``bgDeep`` — deep navy shared with the two public-invoice
    // magic-link surfaces + this public-estimate landing.
    expect(navBlock[0]).toMatch(/\bbgDeep\s*:\s*"#03002e"/);
  });
});
