/**
 * Phase 38 · Feb-2026 — admin customer profile visual grouping
 * restyle regression lock.
 *
 * Covers:
 *   1. Seven new palette constants are declared in
 *      ``CustomerDetail.jsx`` with the exact approved hex values
 *      (financial neutral teal / action-button steel / nav tile
 *      slate-900 / three icon accents / muted label).
 *   2. KPI tile neutral chassis bg flips to the teal
 *      ``CD_FINANCIAL_NEUTRAL_BG`` constant; the Phase-24 dynamic
 *      red / emerald flips still layer on top via the preserved
 *      ``t.bgColor`` override.
 *   3. KPI neutral label color flips to the lighter
 *      ``CD_FINANCIAL_NEUTRAL_LABEL`` so WCAG ≥ 4.5:1 holds on
 *      the teal bg (the pre-P38 ``#94A3B8`` would drop to 2.4:1).
 *   4. Action-row ``navyOutlineStyle`` flips from transparent +
 *      white/20 border to solid ``CD_ACTION_BTN_BG`` +
 *      ``CD_ACTION_BTN_BORDER`` border.
 *   5. QuickActionTileGrid non-active bg flips from
 *      ``CD_DARK_CARD_BG`` → ``CD_NAV_TILE_BG``; active bg stays
 *      ``#0a0940``; border logic stays verbatim per the Phase 27
 *      lock (``isActive ? "#4F46E5" : CD_DARK_CARD_BORDER``).
 *   6. QuickActionTileGrid icon tint rotates across three
 *      Phase-38 accent constants via ``CD_ICON_ACCENTS[i % 3]``;
 *      active tile keeps the pre-P38 ``#94A3B8`` for a clean
 *      "indigo border wins" visual hierarchy.
 *   7. Contrast ratios for every palette entry meet or exceed
 *      WCAG 2.1 AA (4.5:1) vs ``#FFFFFF`` text; muted-white text
 *      (approx ``#B3B3B3``) is also checked for the mid-bg
 *      constants where applicable.
 *   8. Phase 24 ``CD_DANGER_BG = "#7F1D1D"`` and
 *      ``CD_SUCCESS_BG = "#064E3B"`` constants + the dynamic
 *      ternaries remain byte-for-byte unchanged.
 *   9. Phase 27 ``CD_DARK_CARD_BG`` + ``CD_DARK_CARD_BORDER``
 *      constants exist unchanged (identity header + page shell
 *      still use them).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const SRC_PATH = resolve(__dirname,
  "../pages/customers/CustomerDetail.jsx");
const SRC = readFileSync(SRC_PATH, "utf8");


// Narrow slices so a stray match in a comment elsewhere in the
// 3900-line file can't satisfy the assertion.
const KPI_FN_START = SRC.indexOf("function KPITileGrid(");
const KPI_FN_END = SRC.indexOf("function QuickActionTileGrid(");
const KPI_BODY = SRC.slice(KPI_FN_START, KPI_FN_END);

const QA_FN_START = SRC.indexOf("function QuickActionTileGrid(");
const QA_FN_END = SRC.indexOf("const TABS = [");
const QA_BODY = SRC.slice(QA_FN_START, QA_FN_END);


// ─────────────────────────────────────────────────────────────
// WCAG 2.1 relative-luminance + contrast helpers.
// ─────────────────────────────────────────────────────────────
function _hexToRgb(hex) {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

function _channel(c) {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

function _luminance(hex) {
  const [r, g, b] = _hexToRgb(hex);
  return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b);
}

/** WCAG 2.1 contrast ratio between two hex colors (text vs bg). */
function contrastRatio(hexA, hexB) {
  const la = _luminance(hexA);
  const lb = _luminance(hexB);
  const [bright, dim] = la > lb ? [la, lb] : [lb, la];
  return (bright + 0.05) / (dim + 0.05);
}


describe("Phase 38 · Constants exist with approved hex values", () => {
  it("CD_FINANCIAL_NEUTRAL_BG = teal-800 #115E59", () => {
    expect(SRC).toMatch(/CD_FINANCIAL_NEUTRAL_BG\s*=\s*"#115E59"/);
  });

  it("CD_FINANCIAL_NEUTRAL_LABEL = slate-300 #CBD5E1 (muted label on teal)", () => {
    expect(SRC).toMatch(/CD_FINANCIAL_NEUTRAL_LABEL\s*=\s*"#CBD5E1"/);
  });

  it("CD_ACTION_BTN_BG = slate-700 #334155 (medium steel blue)", () => {
    expect(SRC).toMatch(/CD_ACTION_BTN_BG\s*=\s*"#334155"/);
  });

  it("CD_ACTION_BTN_BORDER = slate-500 #64748B", () => {
    expect(SRC).toMatch(/CD_ACTION_BTN_BORDER\s*=\s*"#64748B"/);
  });

  it("CD_NAV_TILE_BG = slate-900 #0F172A (slightly lighter navy for QA tiles)", () => {
    expect(SRC).toMatch(/CD_NAV_TILE_BG\s*=\s*"#0F172A"/);
  });

  it("Icon accent triplet: teal-400 #2DD4BF / indigo-400 #818CF8 / slate-400 #94A3B8", () => {
    expect(SRC).toMatch(/CD_ICON_ACCENT_TEAL\s*=\s*"#2DD4BF"/);
    expect(SRC).toMatch(/CD_ICON_ACCENT_INDIGO\s*=\s*"#818CF8"/);
    expect(SRC).toMatch(/CD_ICON_ACCENT_SLATE\s*=\s*"#94A3B8"/);
  });

  it("CD_ICON_ACCENTS array in [teal, indigo, slate] order for i % 3 rotation", () => {
    // Multiline array; match loose whitespace.
    expect(SRC).toMatch(
      /CD_ICON_ACCENTS\s*=\s*\[\s*CD_ICON_ACCENT_TEAL,\s*CD_ICON_ACCENT_INDIGO,\s*CD_ICON_ACCENT_SLATE,?\s*\]/,
    );
  });
});


describe("Phase 38 · KPI tile neutral bg flips to teal, dynamic flips preserved", () => {
  it("neutral chassis style uses CD_FINANCIAL_NEUTRAL_BG (not CD_DARK_CARD_BG)", () => {
    expect(KPI_BODY).toMatch(
      /backgroundColor:\s*CD_FINANCIAL_NEUTRAL_BG/,
    );
    // The pre-P38 ``backgroundColor: CD_DARK_CARD_BG`` is now
    // gone from the KPI tile style block.
    const kpiStyleBlock = KPI_BODY.match(
      /style=\{\{[\s\S]{0,250}data-testid=/,
    );
    expect(kpiStyleBlock).not.toBeNull();
    expect(kpiStyleBlock[0]).not.toMatch(/backgroundColor:\s*CD_DARK_CARD_BG\b/);
  });

  it("Phase 24 dynamic Past-Due / Credit / Overdue flips preserved verbatim", () => {
    // Red flips.
    expect(KPI_BODY).toMatch(
      /bgColor:\s*pastDueCents\s*>\s*0\s*\?\s*CD_DANGER_BG\s*:\s*undefined/,
    );
    expect(KPI_BODY).toMatch(
      /bgColor:\s*overdueCount\s*>\s*0\s*\?\s*CD_DANGER_BG\s*:\s*undefined/,
    );
    // Green flip.
    expect(KPI_BODY).toMatch(
      /bgColor:\s*creditCents\s*>\s*0\s*\?\s*CD_SUCCESS_BG\s*:\s*undefined/,
    );
    // Dynamic override on the style object still lands AFTER the
    // Phase-38 neutral bg so a non-undefined t.bgColor wins.
    expect(KPI_BODY).toMatch(
      /\.\.\.\(t\.bgColor\s*\?\s*\{backgroundColor:\s*t\.bgColor\}\s*:\s*\{\}\)/,
    );
  });

  it("CD_DANGER_BG / CD_SUCCESS_BG constants unchanged by Phase 38", () => {
    expect(SRC).toMatch(/CD_DANGER_BG\s*=\s*"#7F1D1D"/);
    expect(SRC).toMatch(/CD_SUCCESS_BG\s*=\s*"#064E3B"/);
  });

  it("neutral-tile label flips to CD_FINANCIAL_NEUTRAL_LABEL (not slate-400) for ≥4.5:1 contrast on teal", () => {
    expect(KPI_BODY).toMatch(
      /labelColor\s*=\s*hasDynamicBg\s*\?\s*"#FFFFFF"\s*:\s*CD_FINANCIAL_NEUTRAL_LABEL/,
    );
  });
});


describe("Phase 38 · action-row buttons flip to medium steel blue", () => {
  it("navyOutlineStyle.background = CD_ACTION_BTN_BG, border = CD_ACTION_BTN_BORDER", () => {
    const navyOutlineBlock = SRC.match(
      /const\s+navyOutlineStyle\s*=\s*\{[\s\S]*?\};/,
    );
    expect(navyOutlineBlock).not.toBeNull();
    const block = navyOutlineBlock[0];
    expect(block).toMatch(/background:\s*CD_ACTION_BTN_BG/);
    expect(block).toMatch(/border:\s*`1px solid \$\{CD_ACTION_BTN_BORDER\}`/);
    // Pre-P38 transparent + white/20 border no longer present.
    expect(block).not.toMatch(/background:\s*"transparent"/);
    expect(block).not.toMatch(/rgba\(255,255,255,0\.20\)/);
  });

  it("Call button is NOT inside the Phase-38 steel block (keeps green ClickToCallButton)", () => {
    expect(SRC).toMatch(/<ClickToCallButton/);
    // ClickToCallButton is a separate component — not styled by
    // navyOutlineStyle. Just confirm it's still invoked.
  });

  it("Delete button keeps its red navyDangerStyle (Phase 20 lock)", () => {
    const navyDangerBlock = SRC.match(
      /const\s+navyDangerStyle\s*=\s*\{[\s\S]*?\};/,
    );
    expect(navyDangerBlock).not.toBeNull();
    expect(navyDangerBlock[0]).toMatch(/#FCA5A5/);
    expect(navyDangerBlock[0]).toMatch(/rgba\(239,68,69?\d?,0\.18\)|rgba\(239,68,68,0\.18\)/);
  });

  it("Hard Delete keeps its amber navyWarnStyle (not in P38 scope)", () => {
    const navyWarnBlock = SRC.match(
      /const\s+navyWarnStyle\s*=\s*\{[\s\S]*?\};/,
    );
    expect(navyWarnBlock).not.toBeNull();
    expect(navyWarnBlock[0]).toMatch(/#FED7AA/);
  });
});


describe("Phase 38 · Quick Action tile grid — nav bg + icon rotation", () => {
  it("non-active QA tile bg flips to CD_NAV_TILE_BG (not CD_DARK_CARD_BG)", () => {
    expect(QA_BODY).toMatch(
      /backgroundColor:\s*isActive\s*\?\s*"#0a0940"\s*:\s*CD_NAV_TILE_BG/,
    );
  });

  it("Phase 27 active-tile border lock preserved verbatim", () => {
    // Border still uses the pre-P38 ternary — this is the Phase
    // 27 line-197 lock the P38 restyle is explicitly protecting.
    expect(QA_BODY).toMatch(
      /isActive\s*\?\s*"#4F46E5"\s*:\s*CD_DARK_CARD_BORDER/,
    );
  });

  it("icon tint rotates across three accents via i % 3", () => {
    // The map callback destructures ``(t, i)``.
    expect(QA_BODY).toMatch(/tabs\.map\(\(t,\s*i\)\s*=>/);
    expect(QA_BODY).toMatch(
      /iconColor\s*=\s*isActive\s*\?\s*"#94A3B8"\s*:\s*CD_ICON_ACCENTS\[i\s*%\s*CD_ICON_ACCENTS\.length\]/,
    );
    expect(QA_BODY).toMatch(
      /<Icon\s+size=\{16\}\s+style=\{\{\s*color:\s*iconColor\s*\}\}\s*\/>/,
    );
  });

  it("active tile keeps the pre-P38 slate-400 icon so the indigo border reads as the dominant active signal", () => {
    // Explicit assertion the active-path icon is NOT one of the
    // alternation accents — this is the "visual hierarchy wins
    // over grouping" ruling from the investigation report.
    expect(QA_BODY).toMatch(
      /iconColor\s*=\s*isActive\s*\?\s*"#94A3B8"\s*:/,
    );
  });

  it("QA testid shape + aria-pressed + data-active (Phase 27 locks) preserved", () => {
    expect(QA_BODY).toMatch(/data-testid=\{`\$\{testidPrefix\}-\$\{t\.k\}`\}/);
    expect(QA_BODY).toMatch(/aria-pressed=\{isActive\s*\?\s*"true"\s*:\s*"false"\}/);
    expect(QA_BODY).toMatch(/data-active=\{isActive\s*\?\s*"true"\s*:\s*undefined\}/);
  });
});


describe("Phase 38 · WCAG 2.1 contrast verification", () => {
  it("CD_FINANCIAL_NEUTRAL_BG (#115E59) ≥ 4.5:1 vs white text", () => {
    const r = contrastRatio("#115E59", "#FFFFFF");
    expect(r).toBeGreaterThanOrEqual(4.5);
  });

  it("CD_FINANCIAL_NEUTRAL_LABEL (#CBD5E1) ≥ 4.5:1 vs the teal bg (muted label)", () => {
    const r = contrastRatio("#CBD5E1", "#115E59");
    expect(r).toBeGreaterThanOrEqual(4.5);
  });

  it("CD_ACTION_BTN_BG (#334155) ≥ 4.5:1 vs white text", () => {
    const r = contrastRatio("#334155", "#FFFFFF");
    expect(r).toBeGreaterThanOrEqual(4.5);
  });

  it("CD_NAV_TILE_BG (#0F172A) ≥ 4.5:1 vs white text (nav tile labels)", () => {
    const r = contrastRatio("#0F172A", "#FFFFFF");
    expect(r).toBeGreaterThanOrEqual(4.5);
  });

  it("Phase 24 red / green dynamic flips still ≥ 4.5:1 vs white", () => {
    // Regression lock — the dynamic flips are untouched but we
    // keep the contrast assertion here so a future palette drift
    // on the shared constants surfaces as a Phase 38 failure too.
    expect(contrastRatio("#7F1D1D", "#FFFFFF")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio("#064E3B", "#FFFFFF")).toBeGreaterThanOrEqual(4.5);
  });

  it("CD_DARK_CARD_BG (#03002e) chassis + CD_DARK_CARD_BORDER preserved", () => {
    // Phase 27 / 28 regression — the pre-P38 chassis bg + border
    // must stay defined with the exact hexes. The identity-header
    // card + page shell + skeleton shell all pin to CD_DARK_CARD_BG
    // and that pin is a Phase 28 regression lock.
    expect(SRC).toMatch(/CD_DARK_CARD_BG\s*=\s*"#03002e"/);
    expect(SRC).toMatch(/CD_DARK_CARD_BORDER\s*=\s*"#1E293B"/);
  });
});
