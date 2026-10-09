/**
 * Phase 22 · Feb-2026 — Customer profile skeleton loader.
 *
 * Pre-Phase-22 the CustomerDetail page showed a single thin
 * ``<Skeleton height={160}>`` bar on mount — on a white page it
 * read as blank. Phase 22 replaces that early-return branch with
 * a comprehensive skeleton that mirrors the final layout 1:1 so
 * there is zero layout shift when the slim profile fetch
 * resolves and the real tree takes over.
 *
 * Covered contracts:
 *   • Skeleton SHELL — outer wrapper + 5 inner regions (back
 *     button, portal stack, action strip, tabs strip, header
 *     card, content area). All ``data-testid="cd-skeleton-*"``
 *     anchors are present in the DOM BEFORE any fetch resolves.
 *   • Phase 20 PARITY — the skeleton's action strip + tabs strip
 *     mirror the real Phase 20 double-strip layout (action row
 *     ABOVE tabs row, both in navy chrome). Mirrors the real
 *     ``flex flex-row flex-nowrap items-center gap-2
 *     overflow-x-auto`` affordance so there is no layout shift
 *     on swap-in.
 *   • animate-pulse — every placeholder uses the
 *     ``animate-pulse`` affordance so the user reads "loading"
 *     not "broken".
 *   • Swap behavior — once ``customer`` state is set, the full
 *     real tree renders. The skeleton branch is behind an
 *     ``if (!customer)`` guard, so a non-null customer renders
 *     the real layout (regression lock on the swap).
 *   • Phase 9d lazy tabs — unchanged. Phase 22 ONLY touches the
 *     top-level ``if (!customer)`` branch; the inner per-tab
 *     ``<Suspense fallback={<Skeleton />}>`` paths are left
 *     byte-identical.
 *
 * Source-inspection pattern — fast, deterministic, no React
 * render, no provider mount.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PAGE_PATH = resolve(__dirname,
  "../pages/customers/CustomerDetail.jsx");
const SRC = readFileSync(PAGE_PATH, "utf8");


describe("Phase 22 · skeleton SHELL renders on mount (no fetch resolved)", () => {
  it("if (!customer) early return carries the skeleton testid root", () => {
    // The early-return branch sits before the main render. Match
    // the ``if (!customer)`` guard + confirm the inner block
    // carries the Phase-22 shell testid.
    expect(SRC).toMatch(
      /if \(!customer\) \{[\s\S]{0,3000}data-testid="customer-detail-skeleton"/,
    );
  });

  it("skeleton mounts inside the same ``max-w-5xl`` wrapper as the real tree (no layout shift)", () => {
    const skelIdx = SRC.indexOf('data-testid="customer-detail-skeleton"');
    const openIdx = SRC.lastIndexOf("<div", skelIdx);
    const slice = SRC.slice(openIdx, skelIdx + 60);
    expect(slice).toMatch(
      /className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6"/,
    );
    // And the real tree uses the SAME wrapper classes.
    expect(SRC).toMatch(
      /className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="customer-detail"/,
    );
  });

  it("skeleton exposes every documented sub-region testid", () => {
    const REGIONS = [
      "customer-detail-skeleton",
      "cd-skeleton-portal-stack",
      "cd-skeleton-action-strip",
      "cd-skeleton-action-row",
      "cd-skeleton-tabs-strip",
      "cd-skeleton-tabs-row",
      "cd-skeleton-header-card",
      "cd-skeleton-avatar",
      "cd-skeleton-content",
    ];
    for (const tid of REGIONS) {
      expect(SRC).toContain(`data-testid="${tid}"`);
    }
  });
});


describe("Phase 22 · skeleton mirrors Phase 20 action-row + tabs-row chrome", () => {
  it("cd-skeleton-action-strip precedes cd-skeleton-tabs-strip in source order (same order as Phase 20 real tree)", () => {
    const actionIdx = SRC.indexOf('data-testid="cd-skeleton-action-strip"');
    const tabsIdx = SRC.indexOf('data-testid="cd-skeleton-tabs-strip"');
    expect(actionIdx).toBeGreaterThan(-1);
    expect(tabsIdx).toBeGreaterThan(actionIdx);
  });

  it("both skeleton strips carry the navy-strip chrome contract", () => {
    // The skeleton reuses the Phase-20 navy chrome via a shared
    // ``skelStripChrome`` local constant. Each strip's open-tag
    // must apply it via ``style={skelStripChrome}``, and the
    // constant's definition must bind ``backgroundColor:
    // colors.nav.bg`` so visual parity with Phase 20 holds.
    expect(SRC).toMatch(
      /const skelStripChrome = \{[\s\S]{0,200}backgroundColor:\s*colors\.nav\.bg/,
    );
    for (const tid of [
      "cd-skeleton-action-strip",
      "cd-skeleton-tabs-strip",
    ]) {
      const idx = SRC.indexOf(`data-testid="${tid}"`);
      expect(idx).toBeGreaterThan(-1);
      // Walk back to the owning ``<``.
      let openIdx = idx;
      while (openIdx > 0 && SRC[openIdx] !== "<") openIdx--;
      const closeIdx = SRC.indexOf(">", idx);
      const openTagSlice = SRC.slice(openIdx, closeIdx);
      expect(openTagSlice).toMatch(/className="rounded-2xl mb-4 px-3 py-3"/);
      expect(openTagSlice).toMatch(/style=\{skelStripChrome\}/);
    }
  });

  it("both skeleton rows carry the Phase-20 flex-row chrome", () => {
    for (const tid of [
      "cd-skeleton-action-row",
      "cd-skeleton-tabs-row",
    ]) {
      // Match the open-tag that OWNS the testid — walk back from
      // the testid position to the enclosing ``<`` and forward
      // to the next ``>``. The slice between those two indices
      // IS the open-tag of the row (comments / sibling tags are
      // excluded by construction).
      const idx = SRC.indexOf(`data-testid="${tid}"`);
      expect(idx).toBeGreaterThan(-1);
      // Walk back one char at a time (fast — tag is tiny) until
      // we hit the ``<`` that opens this tag.
      let openIdx = idx;
      while (openIdx > 0 && SRC[openIdx] !== "<") openIdx--;
      const closeIdx = SRC.indexOf(">", idx);
      const openTagSlice = SRC.slice(openIdx, closeIdx);
      expect(openTagSlice).toMatch(/flex[- ]row/);
      expect(openTagSlice).toMatch(/flex-nowrap/);
      expect(openTagSlice).toMatch(/overflow-x-auto/);
    }
  });
});


describe("Phase 22 · skeleton uses animate-pulse affordance throughout", () => {
  it("every skeleton placeholder is wired through the ``animate-pulse`` affordance", () => {
    // The skelBar + skelButton helpers each inject ``animate-pulse``
    // once per helper definition; the avatar, portal tiles, and
    // content-area placeholders inject it inline. Count the
    // skeleton block's hits.
    const guardIdx = SRC.indexOf("if (!customer)");
    const realIdx = SRC.indexOf('data-testid="customer-detail"');
    expect(guardIdx).toBeGreaterThan(-1);
    expect(realIdx).toBeGreaterThan(guardIdx);
    const skelBlock = SRC.slice(guardIdx, realIdx);
    const pulseHits = skelBlock.match(/animate-pulse/g) || [];
    // Minimum: 2 shared helpers (skelBar, skelButton) + 2 portal
    // tiles + 1 avatar + 1 content map + 1 header-card fallthrough.
    expect(pulseHits.length).toBeGreaterThanOrEqual(6);
  });

  it("skeleton avatar is a 16x16 pulse circle", () => {
    // Matches the brief: avatar placeholder circle (bg-slate-
    // 200 rounded-full w-16 h-16 animate-pulse) — tolerates
    // our palette-wrapped backgroundColor by only asserting
    // the shape classes.
    const idx = SRC.indexOf('data-testid="cd-skeleton-avatar"');
    const openIdx = SRC.lastIndexOf("<div", idx);
    const slice = SRC.slice(openIdx, idx + 60);
    expect(slice).toMatch(/w-16/);
    expect(slice).toMatch(/h-16/);
    expect(slice).toMatch(/rounded-full/);
    expect(slice).toMatch(/animate-pulse/);
  });
});


describe("Phase 22 · swap behavior · real tree gated on customer state", () => {
  it("skeleton branch returns inside if (!customer) — guard is non-negotiable", () => {
    // Regression lock — if a future refactor accidentally
    // short-circuits the guard, the real tree would try to
    // render with a null customer and crash.
    expect(SRC).toMatch(
      /if \(!customer\) \{[\s\S]{0,3000}data-testid="customer-detail-skeleton"[\s\S]{0,8000}return \(/,
    );
  });

  it("real tree sits AFTER the skeleton guard", () => {
    const guardIdx = SRC.indexOf("if (!customer)");
    const realIdx = SRC.indexOf('data-testid="customer-detail"');
    expect(guardIdx).toBeGreaterThan(-1);
    expect(realIdx).toBeGreaterThan(guardIdx);
  });

  it("thin single-bar Skeleton early-return is retired (regression lock)", () => {
    // Pre-Phase-22 shape was ``<Skeleton style={{ height: 160 }} />``
    // on its own inside the early-return.  Confirm that exact
    // string is no longer present so a future refactor doesn't
    // accidentally revert to the blank-reading placeholder.
    expect(SRC).not.toMatch(
      /<Skeleton style=\{\{ height: 160 \}\} \/>/,
    );
  });
});


describe("Phase 22 · Phase 9d lazy-tab + Phase 20 action-row preserved", () => {
  it("Phase 9d per-tab Skeleton fallbacks remain intact", () => {
    // The real tree still renders per-tab Skeleton placeholders
    // when a lazy tab panel is first clicked (Phase 9d
    // behavior). The ``<Skeleton`` component import is still
    // live and reachable in the real tree AFTER the skeleton
    // guard — regression lock that Phase 22 did not strip the
    // inner lazy-tab skeletons.
    const realIdx = SRC.indexOf('data-testid="customer-detail"');
    const realBlock = SRC.slice(realIdx);
    const skeletonHits = realBlock.match(/<Skeleton\b/g) || [];
    expect(skeletonHits.length).toBeGreaterThanOrEqual(1);
  });

  it("Phase 20 action row + tabs row still render in the real tree (regression lock)", () => {
    // The real tree carries both cd-command-strip (actions) and
    // cd-command-strip-tabs (Overview/Send/Create) in source
    // order below the skeleton guard.
    const realIdx = SRC.indexOf('data-testid="customer-detail"');
    const realBlock = SRC.slice(realIdx);
    const strip = realBlock.indexOf('data-testid="cd-command-strip"');
    const stripTabs = realBlock.indexOf('data-testid="cd-command-strip-tabs"');
    expect(strip).toBeGreaterThan(-1);
    expect(stripTabs).toBeGreaterThan(strip);
    // And the cd-action-row + cd-tabs-row anchors.
    expect(realBlock).toContain('data-testid="cd-action-row"');
    expect(realBlock).toContain('data-testid="cd-tabs-row"');
  });
});


describe("Phase 22 · no mount-time blocker", () => {
  it("component body contains no top-level ``await`` before the first return", () => {
    // Grab the component function body (from the ``export default
    // function CustomerDetail()`` header to the first ``return``
    // of the real tree). The slice must NOT contain a bare
    // ``await`` at top-level — those would block the first paint.
    const funcIdx = SRC.indexOf("export default function CustomerDetail()");
    const firstReturnIdx = SRC.indexOf(
      "data-testid=\"customer-detail-skeleton\"",
      funcIdx,
    );
    const prelude = SRC.slice(funcIdx, firstReturnIdx);
    // Any ``await`` in the prelude must sit inside a nested
    // function / arrow (useEffect / useCallback / event
    // handler). We regex-scan for a bare top-level ``\n  await``
    // (2-space indent — the component's own scope) and assert
    // none exist.
    expect(prelude).not.toMatch(/^\s{2}await\s/m);
  });
});
