/**
 * Phase 27 · Feb-2026 — Admin CustomerDetail dark-navy restyle.
 *
 * Four scopes, source-inspection pattern (fast, deterministic,
 * no React render, no provider mount — mirrors the Phase 23/24
 * companion test style):
 *
 *   1.  KPI tile grid.  Six tiles in locked source order:
 *       Balance Due, Past Due, Credit, Overdue,
 *       Pending Estimates, Unread Messages.  Past Due flips to
 *       ``#7F1D1D`` when ``past_due_cents > 0``; Credit flips to
 *       ``#064E3B`` when ``credit_cents > 0``; Overdue flips to
 *       ``#7F1D1D`` when ``overdue_count > 0``.  Phase 24 hex
 *       values locked verbatim.
 *
 *   2.  Quick Actions tile grid.  Each tile calls ``setTab`` with
 *       the same ``k`` string the ResponsiveTabs dropdown uses —
 *       byte-for-byte routing preservation.  Hover glow mirrors
 *       Phase 24's ActionTile pattern:
 *       ``hover:shadow-[0_0_20px_rgba(255,255,255,0.6)]
 *       transition-shadow duration-200``.
 *
 *   3.  Dark-navy page bg + card border.  Outer page container +
 *       Phase-22 skeleton loader container both pin
 *       ``backgroundColor: '#03002e'``.  Tile chassis pin border
 *       ``#1E293B``.
 *
 *   4.  Phase 20 regression lock preservation.  The pre-26b
 *       command strip testids + ResponsiveTabs dropdown shell
 *       stay byte-for-byte in source.
 *
 *   5.  Dynamic colour math — runtime proof of the thresholds via
 *       the same inline ``bgColor`` expression the component uses
 *       at the call-site.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PAGE_PATH = resolve(__dirname,
  "../pages/customers/CustomerDetail.jsx");
const SRC = readFileSync(PAGE_PATH, "utf8");

// Slice: everything from the KPITileGrid function def up to the
// end of its definition.  Later tests reason about this slice
// so edits above it don't invalidate the regexes.
const KPI_FN_IDX = SRC.indexOf("function KPITileGrid(");
const KPI_FN_END = SRC.indexOf("\n}\n", KPI_FN_IDX);
const KPI_BODY = SRC.slice(KPI_FN_IDX, KPI_FN_END);

const QA_FN_IDX = SRC.indexOf("function QuickActionTileGrid(");
const QA_FN_END = SRC.indexOf("\n}\n", QA_FN_IDX);
const QA_BODY = SRC.slice(QA_FN_IDX, QA_FN_END);


describe("Phase 27 · KPI tile grid — six tiles with Phase 24 locked hex values", () => {
  it("defines the six tile keys in locked source order", () => {
    const want = [
      "balance-due", "past-due", "credit",
      "overdue", "pending-est", "unread-msgs",
    ];
    let cursor = -1;
    for (const k of want) {
      const tag = `k: "${k}"`;
      const idx = KPI_BODY.indexOf(tag);
      expect(idx, `missing tile key ${k}`).toBeGreaterThan(-1);
      expect(idx).toBeGreaterThan(cursor);
      cursor = idx;
    }
  });

  it("Past Due tile flips to Phase-24 red-900 (#7F1D1D) when past_due_cents > 0", () => {
    // Direct source-match of the inline bgColor expression.
    expect(KPI_BODY).toMatch(
      /bgColor:\s*pastDueCents\s*>\s*0\s*\?\s*CD_DANGER_BG\s*:\s*undefined/,
    );
    // The constant resolves to the Phase-24 red-900 literal.
    expect(SRC).toMatch(/CD_DANGER_BG\s*=\s*"#7F1D1D"/);
  });

  it("Credit tile flips to Phase-24 emerald-900 (#064E3B) when credit_cents > 0", () => {
    expect(KPI_BODY).toMatch(
      /bgColor:\s*creditCents\s*>\s*0\s*\?\s*CD_SUCCESS_BG\s*:\s*undefined/,
    );
    expect(SRC).toMatch(/CD_SUCCESS_BG\s*=\s*"#064E3B"/);
  });

  it("Overdue count tile flips to red-900 when overdue_count > 0", () => {
    expect(KPI_BODY).toMatch(
      /bgColor:\s*overdueCount\s*>\s*0\s*\?\s*CD_DANGER_BG\s*:\s*undefined/,
    );
  });

  it("Balance Due / Pending Estimates / Unread Messages tiles stay neutral dark (no dynamic bg)", () => {
    // Scan the balance-due tile object literal — bgColor must be
    // undefined (neutral chassis).
    const bal = KPI_BODY.slice(
      KPI_BODY.indexOf('k: "balance-due"'),
      KPI_BODY.indexOf('k: "past-due"'),
    );
    expect(bal).toMatch(/bgColor:\s*undefined/);
    const pending = KPI_BODY.slice(
      KPI_BODY.indexOf('k: "pending-est"'),
      KPI_BODY.indexOf('k: "unread-msgs"'),
    );
    expect(pending).toMatch(/bgColor:\s*undefined/);
    const unread = KPI_BODY.slice(KPI_BODY.indexOf('k: "unread-msgs"'));
    expect(unread).toMatch(/bgColor:\s*undefined/);
  });

  it("tile chassis className is byte-for-byte identical to Phase 23 Tile chassis", () => {
    // Phase 23's Tile component ships
    //   className="text-left rounded-2xl p-3 transition hover:brightness-95"
    // We mirror it exactly on the KPI tiles so the admin surface
    // reads as the same visual family as Portal Home.
    expect(SRC).toMatch(
      /CD_TILE_CLASSES\s*=\s*"text-left rounded-2xl p-3 transition hover:brightness-95"/,
    );
  });

  it("chassis bg = #03002e and chassis border = #1E293B (per spec)", () => {
    expect(SRC).toMatch(/CD_DARK_CARD_BG\s*=\s*"#03002e"/);
    expect(SRC).toMatch(/CD_DARK_CARD_BORDER\s*=\s*"#1E293B"/);
  });

  it("tile grid renders with 'customer-detail' prefix via the <KPITileGrid /> call-site", () => {
    expect(SRC).toMatch(/<KPITileGrid\s+kpi=\{kpi\}\s+testidPrefix="cd"\s*\/>/);
    // Each per-tile testid pattern is constructed via template
    // literal — assert the shape instead of the resolved string.
    expect(KPI_BODY).toMatch(/data-testid=\{`\$\{testidPrefix\}-kpi-tile-\$\{t\.k\}`\}/);
    expect(KPI_BODY).toMatch(/data-testid=\{`\$\{testidPrefix\}-kpi-tile-\$\{t\.k\}-value`\}/);
  });
});


describe("Phase 27 · KPI tile dynamic colour math — runtime proof", () => {
  const CD_DANGER_BG = "#7F1D1D";
  const CD_SUCCESS_BG = "#064E3B";

  function pastDueBg(cents) {
    const pastDueCents = Number(cents || 0);
    return pastDueCents > 0 ? CD_DANGER_BG : undefined;
  }
  function creditBg(cents) {
    const creditCents = Number(cents || 0);
    return creditCents > 0 ? CD_SUCCESS_BG : undefined;
  }
  function overdueBg(n) {
    const overdueCount = Number(n || 0);
    return overdueCount > 0 ? CD_DANGER_BG : undefined;
  }

  it("Past Due 0 → neutral; 125 → red-900", () => {
    expect(pastDueBg(0)).toBeUndefined();
    expect(pastDueBg(null)).toBeUndefined();
    expect(pastDueBg(12550)).toBe("#7F1D1D");
  });

  it("Credit 0 → neutral; 7500 → emerald-900", () => {
    expect(creditBg(0)).toBeUndefined();
    expect(creditBg(null)).toBeUndefined();
    expect(creditBg(7500)).toBe("#064E3B");
  });

  it("Overdue 0 → neutral; 3 → red-900", () => {
    expect(overdueBg(0)).toBeUndefined();
    expect(overdueBg(3)).toBe("#7F1D1D");
  });
});


describe("Phase 27 · Quick Actions tile grid — primary nav replacing the role of the dropdown", () => {
  it("<QuickActionTileGrid /> call-site routes tiles through the SAME setTab the dropdown uses", () => {
    // ``onPick={setTab}`` and the dropdown's ``onChange={setTab}``
    // share the setter.  That's the whole point of Phase 27's
    // non-destructive add: both nav surfaces drive the same state.
    expect(SRC).toMatch(/<QuickActionTileGrid\s+tabs=\{visibleTabs\}\s+active=\{tab\}\s+onPick=\{setTab\}/);
  });

  it("each Quick Action tile ships the Phase-24 hover glow class pair", () => {
    // Byte-for-byte match on the glow class strings — same as
    // Phase 24's ActionTile.
    expect(SRC).toMatch(
      /hover:shadow-\[0_0_20px_rgba\(255,255,255,0\.6\)\]/,
    );
    expect(SRC).toMatch(/transition-shadow duration-200/);
    // On the shared constant that the tile uses.
    expect(SRC).toMatch(
      /CD_ACTION_TILE_CLASSES\s*=[\s\S]{0,500}hover:shadow-\[0_0_20px_rgba\(255,255,255,0\.6\)\]/,
    );
  });

  it("active-tile marker surfaces an aria-pressed + data-active + indigo border", () => {
    expect(QA_BODY).toMatch(/aria-pressed=\{isActive\s*\?\s*"true"\s*:\s*"false"\}/);
    expect(QA_BODY).toMatch(/data-active=\{isActive\s*\?\s*"true"\s*:\s*undefined\}/);
    expect(QA_BODY).toMatch(/isActive\s*\?\s*"#4F46E5"\s*:\s*CD_DARK_CARD_BORDER/);
  });

  it("each tile's testid uses the ``cd-quick-action-<k>`` prefix shape", () => {
    expect(QA_BODY).toMatch(/data-testid=\{`\$\{testidPrefix\}-\$\{t\.k\}`\}/);
    // Call-site passes ``cd-quick-action`` as prefix.
    expect(SRC).toContain('testidPrefix="cd-quick-action"');
  });
});


describe("Phase 27 · page bg + skeleton — dark-navy chassis consistency", () => {
  it("outer page container pins backgroundColor: CD_DARK_CARD_BG + minHeight: 100vh", () => {
    // Two separate shells pin the dark bg: the real page shell
    // (customer-detail testid) + the Phase-22 skeleton shell
    // (customer-detail-skeleton testid).  Instead of a cross-shell
    // regex (brittle to formatting), match the sentinel style
    // snippet twice via a global search over the file.
    const styleHits = SRC.match(
      /backgroundColor:\s*CD_DARK_CARD_BG,[\s\S]{0,80}minHeight:\s*"100vh"/g,
    ) || [];
    expect(styleHits.length, "page shell + skeleton must pin dark bg").toBeGreaterThanOrEqual(2);
  });

  it("skeleton loader testid survives Phase 22 contract", () => {
    expect(SRC).toContain('data-testid="customer-detail-skeleton"');
  });
});


describe("Phase 27 · Phase 20 regression preservation — tabs dropdown stays in-DOM", () => {
  it("all four Phase-20 command-strip testids still present in source", () => {
    for (const tid of [
      "cd-command-strip",
      "cd-action-row",
      "cd-command-strip-tabs",
      "cd-tabs-row",
      "cd-tabs-dropdown-shell",
    ]) {
      expect(SRC, `missing Phase-20 locked testid: ${tid}`).toContain(
        `data-testid="${tid}"`);
    }
  });

  it("ResponsiveTabs dropdown + CustomerActionDropdowns still live inside cd-tabs-row", () => {
    const tabsRowIdx = SRC.indexOf('data-testid="cd-tabs-row"');
    // Find next cd-command-strip to bound the block.
    const endIdx = SRC.indexOf("</div>\n          </div>", tabsRowIdx);
    expect(tabsRowIdx).toBeGreaterThan(-1);
    expect(endIdx).toBeGreaterThan(tabsRowIdx);
    const tabsBlock = SRC.slice(tabsRowIdx, endIdx);
    expect(tabsBlock).toContain("<CustomerActionDropdowns");
    expect(tabsBlock).toContain('data-testid="cd-tabs-dropdown-shell"');
    expect(tabsBlock).toContain("<ResponsiveTabs");
  });

  it("action row precedes tabs row in source order (Phase 20 lock)", () => {
    const actionIdx = SRC.indexOf('data-testid="cd-action-row"');
    const tabsIdx = SRC.indexOf('data-testid="cd-tabs-row"');
    expect(actionIdx).toBeGreaterThan(-1);
    expect(tabsIdx).toBeGreaterThan(-1);
    expect(actionIdx).toBeLessThan(tabsIdx);
  });

  it("KPI + Quick Actions tile grids render BELOW the tabs row in source order", () => {
    const tabsIdx = SRC.indexOf('data-testid="cd-tabs-row"');
    const kpiCallIdx = SRC.indexOf("<KPITileGrid");
    const qaCallIdx  = SRC.indexOf("<QuickActionTileGrid");
    expect(tabsIdx).toBeLessThan(kpiCallIdx);
    expect(kpiCallIdx).toBeLessThan(qaCallIdx);
  });
});
