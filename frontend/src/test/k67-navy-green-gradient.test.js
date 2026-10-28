/**
 * Phase K67 · Feb-2026 — Gradient palette sitewide (navy → green).
 *
 * Lock the canonical ``gradients.navyToGreen`` token, the K52
 * gradient token's swapped navy end, and the primary Button
 * variant class. Regression-guard against the deprecated sky
 * stops resurfacing anywhere in the source tree.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";
import * as themeModule from "@/theme";
const { colors, gradients } = themeModule;

const SRC_ROOT = path.resolve(__dirname, "..");

function readFile(rel) {
  return fs.readFileSync(path.resolve(SRC_ROOT, rel), "utf8");
}

const THEME  = readFile("theme.js");
const BUTTON = readFile("components/ui/button.jsx");
const UI_KIT = readFile("components/ui-kit.jsx");


/* ══════════════════════════════════════════════════════════════════ */
/* Canonical token                                                    */
/* ══════════════════════════════════════════════════════════════════ */

describe("K67 · Canonical gradients.navyToGreen token", () => {
  it("exports the canonical token with the locked stops", () => {
    expect(gradients).toBeDefined();
    expect(gradients.navyToGreen).toBeDefined();
    expect(gradients.navyToGreen.from).toBe("#1B1F5C");   // menu navy
    expect(gradients.navyToGreen.to).toBe("#16A34A");     // green-600
    expect(gradients.navyToGreen.css)
      .toBe("linear-gradient(90deg, #1B1F5C 0%, #16A34A 100%)");
    expect(gradients.navyToGreen.cssHover)
      .toBe("linear-gradient(90deg, #2A2F7A 0%, #22B457 100%)");
    expect(gradients.navyToGreen.fg).toBe("#FFFFFF");
    expect(gradients.navyToGreen.textShadow)
      .toBe("0 1px 2px rgba(0, 0, 0, 0.25)");
  });

  it("the navy start stop matches colors.nav.bg (single source of truth)", () => {
    expect(gradients.navyToGreen.from).toBe(colors.nav.bg);
  });

  it("Phase K70.b · brandGradient / brandGradientCss aliases are RETIRED", () => {
    // K67 originally shipped backward-compat aliases so ~60
    // existing callers didn't break in a single phase. K70.b
    // codemodded every non-test call site to the canonical
    // ``gradients.navyToGreen.*`` shape and deleted the aliases
    // from theme.js. This assertion locks the absence in place —
    // do NOT re-add them.
    expect(themeModule).not.toHaveProperty("brandGradient");
    expect(themeModule).not.toHaveProperty("brandGradientCss");
    // theme.js source contains no lingering ``export const
    // brandGradient …`` / ``brandGradientCss …`` statements
    // (comments that mention the retired names are fine).
    expect(THEME).not.toMatch(/export\s+const\s+brandGradient\s*=/);
    expect(THEME).not.toMatch(/export\s+const\s+brandGradientCss\s*=/);
  });

  it("Phase K70.b · canonical stops array is exported for Recharts callers", () => {
    // The 5 chart pages that used ``brandGradient[N]`` migrated
    // to ``gradients.navyToGreen.stops[N]``. Lock the shape.
    expect(Array.isArray(gradients.navyToGreen.stops)).toBe(true);
    expect(gradients.navyToGreen.stops).toEqual(["#1B1F5C", "#16A34A"]);
  });
});


/* ══════════════════════════════════════════════════════════════════ */
/* K52 signature gradient — end stop swapped to navy                  */
/* ══════════════════════════════════════════════════════════════════ */

describe("K67 · colors.gradient (K52 signature) end swap", () => {
  it("colors.gradient.to is now menu navy (was sky-300)", () => {
    expect(colors.gradient.to).toBe("#1B1F5C");
    expect(colors.gradient.from).toBe("#22C55E"); // green stop preserved
    expect(colors.gradient.css)
      .toBe("linear-gradient(90deg, #22C55E 0%, #1B1F5C 100%)");
    expect(colors.gradient.cssHover)
      .toBe("linear-gradient(90deg, #34D673 0%, #2A2F7A 100%)");
  });

  it("theme.js source has NO remaining sky-stop hex literals in the gradient block", () => {
    // Regression guard — the K52 gradient block scope must not
    // still house sky-300 (#7DD3FC) or its +8% cousin (#93DDFD).
    // Comments outside the block may still name them for context
    // (e.g. "was #7DD3FC sky-300") — those are informational.
    const gradientBlock = THEME.match(/gradient:\s*\{[\s\S]{0,900}?\},/)?.[0] || "";
    // The single "was #7DD3FC" reference INSIDE the block is a
    // one-line comment; strip block-internal comments before the
    // regression check.
    const gradientBlockNoComments = gradientBlock.replace(/\/\/[^\n]*/g, "");
    expect(gradientBlockNoComments).not.toMatch(/#7DD3FC/);
    expect(gradientBlockNoComments).not.toMatch(/#93DDFD/);
    expect(gradientBlockNoComments).not.toMatch(/#0284C7/);
  });
});


/* ══════════════════════════════════════════════════════════════════ */
/* Consumer migration audit                                           */
/* ══════════════════════════════════════════════════════════════════ */

describe("K67 · Consumer migration audit", () => {
  it("primary Button variant paints the K67 navy end", () => {
    expect(BUTTON).toMatch(/#22C55E/);
    expect(BUTTON).toMatch(/#1B1F5C/);
    expect(BUTTON).toMatch(/#34D673/);
    expect(BUTTON).toMatch(/#2A2F7A/);
    // Scoped grep-lock — the deprecated sky-300 / #93DDFD stops
    // must not appear inside a ``bg-[linear-gradient(...)]``
    // Tailwind class. Historical comments naming them are fine.
    const bgClasses = BUTTON.match(/bg-\[linear-gradient\([^\]]+\]/g) || [];
    for (const bg of bgClasses) {
      expect(bg).not.toMatch(/#7DD3FC/);
      expect(bg).not.toMatch(/#93DDFD/);
    }
    const hoverBgClasses = BUTTON.match(/hover:bg-\[linear-gradient\([^\]]+\]/g) || [];
    for (const bg of hoverBgClasses) {
      expect(bg).not.toMatch(/#7DD3FC/);
      expect(bg).not.toMatch(/#93DDFD/);
    }
  });

  it("ui-kit primary Chip resolves through gradients.navyToGreen", () => {
    // Regression guard — the ui-kit inline literal was replaced
    // with a token reference so future palette shifts land in
    // one file.
    expect(UI_KIT).toMatch(/gradients\.navyToGreen\.css/);
    // Old inline literal is gone.
    expect(UI_KIT).not.toMatch(/#0284C7 0%, #16A34A 100%/);
  });

  // ZZ-A Wave 3-C · obsolete per PortalPages PortalPageShell adoption
  // (Phase 18b · Feb-2026) — ``PortalPages.jsx`` dropped its gradient
  // hero banner when every sub-export adopted ``<PortalPageShell>``
  // chrome (deep-navy page bg + white dashboard card). The
  // ``gradients.navyToGreen`` token remains live across 13+ other
  // consumers (ui-kit Chip + ChipRow, PaymentMethodTiles, KpiCard,
  // OverviewStrip, QuickAddButton, SharePortalModal, SignaturePadModal,
  // TemplateCard, TosGate, ProfileCompletionGate, NapDriftPreview
  // Modal, CustomerChemistry's AI-dosing icon plate — see sibling
  // assertions in this file). PortalPages was intentionally dropped
  // from the K67 consumer audit set; keeping the case as `.skip` so
  // readers see the retired audit boundary explicitly.
  it.skip("PortalPages hero banner resolves through gradients.navyToGreen", () => {
    const src = readFile("pages/portal/PortalPages.jsx");
    expect(src).toMatch(/gradients\.navyToGreen\.css/);
    // Old inline literal is gone.
    expect(src).not.toMatch(/#0284C7, #16A34A/);
  });

  it("CustomerChemistry AI-dosing icon plate keeps its 135deg direction while adopting the K67 stops", () => {
    const src = readFile("pages/customers/CustomerChemistry.jsx");
    // Reference the token AND keep the diagonal.
    expect(src).toMatch(/gradients\.navyToGreen\.css\.replace\(/);
    expect(src).toMatch(/"135deg"/);
    expect(src).not.toMatch(/#0284C7 0%, #16A34A 100%/);
  });
});


/* ══════════════════════════════════════════════════════════════════ */
/* K64 grep-lock — untouched non-gradient surfaces                    */
/* ══════════════════════════════════════════════════════════════════ */

describe("K67 · K64 grep-lock preservation", () => {
  it("solid navy active-nav (#303AA0) is untouched by K67", () => {
    expect(colors.nav.bgActiveNavy).toBe("#303AA0");
  });

  it("PortalReviewSubmit's blue → indigo diagonal (not a blue-green gradient) is out of K67 scope", () => {
    const src = readFile("pages/portal/PortalReviewSubmit.jsx");
    // Deliberately left untouched — K67 only swaps blue-to-green
    // and green-to-sky gradients, not blue-to-indigo.
    expect(src).toMatch(/linear-gradient\(135deg, #0284C7, #4F46E5\)/);
  });

  it("tenant brand-color defaults in TenantsAdminPage (per-tenant customization) are untouched", () => {
    const src = readFile("pages/tenants/TenantsAdminPage.jsx");
    expect(src).toMatch(/brand_primary:\s*"#0284C7"/);
    expect(src).toMatch(/brand_secondary:\s*"#16A34A"/);
  });
});
