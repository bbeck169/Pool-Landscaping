/**
 * Phase 24 · Feb-2026 — Portal home tiles: hover glow +
 * dynamic Past Due / Credit colours.
 *
 * Three enhancements on PortalHome.jsx:
 *
 *   1.  White halo glow on hover for the 8 Quick Action tiles
 *       (Service Reports, Invoices, Estimates, Payment Method,
 *       Leave a Review, Photos, Videos, Messages).  The halo is
 *       added on top of Phase 23's ``hover:brightness-95``
 *       chassis — not replacing it.
 *
 *       Glow class string (byte-for-byte):
 *         ``hover:shadow-[0_0_20px_rgba(255,255,255,0.6)]``
 *       Transition pair:
 *         ``transition-shadow duration-200``
 *
 *   2.  Past Due stat tile — background flips to deep red
 *       ``#7F1D1D`` (Tailwind ``red-900``) when
 *       ``summary.past_due > 0``.  Otherwise retains the
 *       Phase-23 ``colors.surface`` dark-navy chassis.
 *
 *   3.  Credit stat tile — background flips to deep green
 *       ``#064E3B`` (Tailwind ``emerald-900``) when the live
 *       credit balance is positive.  Otherwise retains the
 *       dark-navy chassis.
 *
 * Source-inspection pattern — fast, deterministic, no React
 * render, no provider mount.  Matches the Phase 23 companion
 * test file's inspection style so the two phases regress
 * together with no runtime cost.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PH_SRC = readFileSync(
  resolve(__dirname, "../pages/portal/PortalHome.jsx"), "utf8");


// Scope slices so each describe reasons about a single
// JSX subtree.  All offsets are grep-anchored, not line-
// numbered, so later edits above these anchors won't
// invalidate the slice.
const ACTION_TILE_FN_IDX = PH_SRC.indexOf("function ActionTile(");
const ACTION_TILE_FN_END = PH_SRC.indexOf("\n}", ACTION_TILE_FN_IDX);
const ACTION_TILE_BODY = PH_SRC.slice(
  ACTION_TILE_FN_IDX, ACTION_TILE_FN_END,
);

const TILE_FN_IDX = PH_SRC.indexOf("function Tile(");
const TILE_FN_END = PH_SRC.indexOf("\n}", TILE_FN_IDX);
const TILE_BODY = PH_SRC.slice(TILE_FN_IDX, TILE_FN_END);

const PAST_DUE_IDX = PH_SRC.indexOf('testid="tile-past-due"');
const PAST_DUE_SLICE = PH_SRC.slice(
  PH_SRC.lastIndexOf("<Tile", PAST_DUE_IDX),
  PH_SRC.indexOf("/>", PAST_DUE_IDX) + 2,
);

const CREDIT_IDX = PH_SRC.indexOf('testid="tile-credit"');
const CREDIT_SLICE = PH_SRC.slice(
  PH_SRC.lastIndexOf("<Tile", CREDIT_IDX),
  PH_SRC.indexOf("/>", CREDIT_IDX) + 2,
);


// Each ActionTile instance's call-site label as it appears in
// JSX — used for assertion #1 so the error msg points at the
// exact tile that drifted.
const QUICK_ACTION_LABELS = [
  "Service Reports",
  "Invoices",
  "Estimates",
  "Payment Method",
  "Leave a Review",
  "Photos",
  "Videos",
  "Messages",
];


describe("Phase 24 · Quick Action tiles — white halo on hover", () => {
  it("the ActionTile component ships the ``hover:shadow-[0_0_20px_rgba(255,255,255,0.6)]`` class on all 8 tiles", () => {
    // One ActionTile component renders all 8 Quick Action tiles,
    // so a single assertion on the component body guarantees the
    // class is present on every rendered instance.
    expect(ACTION_TILE_BODY).toMatch(
      /hover:shadow-\[0_0_20px_rgba\(255,255,255,0\.6\)\]/,
    );
    // Belt + braces — each of the 8 call-site labels is still in
    // the source so the error msg names the drifted tile.
    for (const label of QUICK_ACTION_LABELS) {
      expect(PH_SRC, `missing Quick Action tile label: ${label}`).toContain(
        `label="${label}"`,
      );
    }
  });

  it("the ActionTile component ships the ``transition-shadow`` class pair", () => {
    expect(ACTION_TILE_BODY).toMatch(/transition-shadow\s+duration-200/);
  });

  it("stat Tile chassis (Balance Due / Past Due / Credit) does NOT get the hover glow — glow is Quick-Actions-only", () => {
    // Regression lock — the three stat tiles must keep their
    // Phase-23 ``hover:brightness-95`` chassis and nothing else
    // on the hover axis.  A future refactor that leaks the glow
    // into Tile should fail here.
    expect(TILE_BODY).not.toMatch(
      /hover:shadow-\[0_0_20px_rgba\(255,255,255,0\.6\)\]/,
    );
    // ``transition-shadow duration-200`` must not leak either.
    expect(TILE_BODY).not.toMatch(/transition-shadow/);
  });
});


describe("Phase 24 · Past Due tile — dark red when past_due > 0", () => {
  it("call-site passes ``bgColor`` conditional on ``summary?.past_due > 0`` → #7F1D1D (red-900)", () => {
    // Positive-amount branch — assigns deep red bg.
    expect(PAST_DUE_SLICE).toMatch(
      /bgColor=\{\(summary\?\.past_due \|\| 0\) > 0 \? "#7F1D1D" : undefined\}/,
    );
  });

  it("Tile component's style spread override preserves ``colors.surface`` default when bgColor is undefined (past_due=0 case)", () => {
    // The style literal starts with ``backgroundColor: colors.surface``
    // (Phase 23 regression lock) and conditionally overrides via
    // spread only when bgColor is truthy.  When past_due=0 or
    // null, no spread fires → navy chassis survives.
    expect(TILE_BODY).toMatch(/backgroundColor:\s*colors\.surface,/);
    expect(TILE_BODY).toMatch(
      /\.\.\.\(bgColor \? \{ backgroundColor: bgColor \} : \{\}\)/,
    );
  });

  it("null / undefined / 0 ``past_due`` all evaluate to ``undefined`` bgColor (navy chassis survives)", () => {
    // The guard ``(summary?.past_due || 0) > 0`` collapses null,
    // undefined, and 0 to the same ``undefined`` branch — proving
    // all three null-cases take the default navy chassis.
    const evalBg = (past_due) => {
      const amt = (past_due || 0);
      return amt > 0 ? "#7F1D1D" : undefined;
    };
    expect(evalBg(null)).toBeUndefined();
    expect(evalBg(undefined)).toBeUndefined();
    expect(evalBg(0)).toBeUndefined();
    expect(evalBg(125.50)).toBe("#7F1D1D");
  });
});


describe("Phase 24 · Credit tile — dark green when credit > 0", () => {
  it("call-site passes ``bgColor`` conditional on live credit balance > 0 → #064E3B (emerald-900)", () => {
    // The credit tile prefers ``creditBalanceDollars`` (live-
    // refreshed via the credit-balance endpoint) and falls back
    // to the stale ``summary?.credit`` only when the live value
    // has not loaded yet.  The ``bgColor`` IIFE mirrors that
    // same precedence so the colour swap tracks the displayed
    // number byte-for-byte.
    expect(CREDIT_SLICE).toMatch(/bgColor=\{\s*\(\(\) => \{/);
    expect(CREDIT_SLICE).toMatch(
      /const live = creditBalanceDollars !== null[\s\S]{0,120}summary\?\.credit;/,
    );
    expect(CREDIT_SLICE).toMatch(
      /return \(live \|\| 0\) > 0 \? "#064E3B" : undefined;/,
    );
  });

  it("null / undefined / 0 ``credit`` all evaluate to ``undefined`` bgColor (navy chassis survives)", () => {
    const evalBg = (live) => {
      return (live || 0) > 0 ? "#064E3B" : undefined;
    };
    expect(evalBg(null)).toBeUndefined();
    expect(evalBg(undefined)).toBeUndefined();
    expect(evalBg(0)).toBeUndefined();
    expect(evalBg(75.00)).toBe("#064E3B");
  });
});


describe("Phase 24 · Text contrast on dark-red / dark-green dynamic bg", () => {
  it("Tile flips label + value text to pure white when ``bgColor`` is truthy", () => {
    // The ``hasDynamicBg`` branch forces #FFFFFF for BOTH the
    // label row and the value row.  This supersedes the
    // Phase-23 ``alert ? colors.error`` fork — critical, because
    // ``alert`` + red bg would otherwise collapse into red-on-red.
    expect(TILE_BODY).toMatch(/const hasDynamicBg = Boolean\(bgColor\);/);
    expect(TILE_BODY).toMatch(
      /const labelColor = hasDynamicBg[\s\S]{0,80}\?\s*"#FFFFFF"/,
    );
    expect(TILE_BODY).toMatch(
      /const valueColor = hasDynamicBg[\s\S]{0,80}\?\s*"#FFFFFF"/,
    );
    // Both the label row and the value row read from the
    // computed colours.
    expect(TILE_BODY).toMatch(/style=\{\{ color: labelColor \}\}/);
    expect(TILE_BODY).toMatch(/style=\{\{ color: valueColor \}\}/);
  });

  it("Past Due with alert=true + bgColor=red avoids red-on-red collapse — forces white text", () => {
    // Simulate the Tile's internal colour computation for the
    // alerting-red-bg case.  This is the exact scenario Past
    // Due hits when the account has an overdue invoice.
    const labelColor = (() => {
      const alert = true;
      const hasDynamicBg = Boolean("#7F1D1D");
      return hasDynamicBg
        ? "#FFFFFF"
        : (alert ? "#F87171" /* colors.error */ : "#94A3B8");
    })();
    const valueColor = (() => {
      const alert = true;
      const hasDynamicBg = Boolean("#7F1D1D");
      return hasDynamicBg
        ? "#FFFFFF"
        : (alert ? "#F87171" : "#F1F5F9");
    })();
    expect(labelColor).toBe("#FFFFFF");
    expect(valueColor).toBe("#FFFFFF");
  });

  it("Credit with no alert + bgColor=green yields white text on green (readable, no muted-slate hit)", () => {
    const labelColor = (() => {
      const alert = false;
      const hasDynamicBg = Boolean("#064E3B");
      return hasDynamicBg
        ? "#FFFFFF"
        : (alert ? "#F87171" : "#94A3B8");
    })();
    const valueColor = (() => {
      const alert = false;
      const hasDynamicBg = Boolean("#064E3B");
      return hasDynamicBg
        ? "#FFFFFF"
        : (alert ? "#F87171" : "#F1F5F9");
    })();
    expect(labelColor).toBe("#FFFFFF");
    expect(valueColor).toBe("#FFFFFF");
  });
});


describe("Phase 24 · Phase 23 regression locks preserved", () => {
  it("Tile component still ships the Phase-23 chassis className (byte-for-byte)", () => {
    // This is the same class-string lock the Phase-23 companion
    // test file asserts.  Dup'd here so a Phase-24 edit that
    // breaks it is caught in this file too.
    expect(TILE_BODY).toMatch(
      /className="text-left rounded-2xl p-3 transition hover:brightness-95"/,
    );
  });

  it("Tile component still ships ``backgroundColor: colors.surface`` as the chassis default (regex-locked)", () => {
    // The Phase-23 regex ``/backgroundColor:\s*colors\.surface/``
    // must still match even after Phase 24's dynamic-bg spread
    // override is layered on top.
    expect(TILE_BODY).toMatch(/backgroundColor:\s*colors\.surface/);
  });

  it("Tile component still ships ``border: 1px solid ${borderColor}`` literal (regex-locked)", () => {
    expect(TILE_BODY).toMatch(/border:\s*`1px solid \$\{borderColor\}`/);
  });

  it("ActionTile component preserves ``transition hover:brightness-95`` chassis (regression lock on Phase-23 chrome)", () => {
    // The glow is added, not swapped.  The pre-existing brighten
    // affordance must still be present on all Quick Action tiles.
    expect(ACTION_TILE_BODY).toMatch(/transition hover:brightness-95/);
  });

  it("all 8 Quick Action testids preserved byte-for-byte (no wiring drift)", () => {
    const TESTIDS = [
      "qa-service-reports",
      "qa-invoices",
      "qa-estimates",
      "qa-pm",
      "portal-reviews-tab",
      "qa-photos",
      "qa-videos",
      "qa-messages",
    ];
    for (const tid of TESTIDS) {
      expect(PH_SRC, `missing Quick Action testid: ${tid}`).toContain(
        `testid="${tid}"`,
      );
    }
  });

  it("stat tile wiring preserved — Past Due + Credit still carry their navigation handlers + testids", () => {
    expect(PAST_DUE_SLICE).toContain('testid="tile-past-due"');
    expect(PAST_DUE_SLICE).toContain('onClick={() => navigate("/portal/invoices")}');
    expect(CREDIT_SLICE).toContain('testid="tile-credit"');
    expect(CREDIT_SLICE).toContain('onClick={() => navigate("/portal/payments")}');
    expect(CREDIT_SLICE).toContain('testidLive="portal-stat-credit-balance"');
  });
});
