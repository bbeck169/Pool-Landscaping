/**
 * Phase P47 · Feb-2026 — Missed status badge palette + Portal
 * layout invariants lock.
 *
 * P47 shipped two customer-portal-adjacent items:
 *   (1) A new ``missed`` job-status bucket (written by the
 *       ``services/missed_job_scheduler.py`` cleanup poller) that
 *       renders across the admin Schedule surface with its own
 *       pill colour + copy ("Missed") and its own K50 job-card
 *       background tint.
 *   (2) A next-service query fix on the customer portal home
 *       tile so stale scheduled rows no longer surface as the
 *       upcoming visit.
 *
 * Test surface:
 *   * Missed status badge palette — the STATUS_PILL / STATUS_COLORS
 *     inline maps in ``CalendarSchedule.jsx`` are module-local (not
 *     exported), so this file uses ``fs.readFileSync`` inspection
 *     to lock the palette / copy / variant.  The
 *     ``K50_JOB_STATUS_BG`` export in ``lib/jobStatus.js`` IS
 *     importable and gets a runtime assertion for the ``missed``
 *     bucket.  Mirrors the P49 file-inspection convention.
 *   * Layout invariants — the P43 sticky-header + top-clearance
 *     contract in ``layouts/AppLayout.jsx``.  These are the pieces
 *     P51 (Global Portal Refactor) MUST preserve when refactoring
 *     shared ``<Card>`` / ``<PortalPageShell>``.  Any P51 change
 *     that drops the sticky header, re-introduces the ``pt-16``
 *     hack, or moves ``PaymentMethodPromptBanner`` back OUTSIDE
 *     the outlet wrapper will fail this test.
 *
 * Runtime-mount tests intentionally omitted — mounting AppLayout
 * pulls in the entire admin/portal provider stack (auth + router
 * + maps + AI dock + portal walkthrough + sidebar) which hangs
 * vitest's collection phase in this repo (see vitest.config.js
 * commentary for the same behaviour on the old admin/portal
 * mount-safety tests).  File-inspection here is the same pattern
 * P49 used for the same reason.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

import { K50_JOB_STATUS_BG, jobStatusColor } from "@/lib/jobStatus";

const R = (relPath) =>
  fs.readFileSync(path.resolve(__dirname, relPath), "utf-8");

const CALENDAR_SRC = R("../pages/schedule/CalendarSchedule.jsx");
const APPLAYOUT_SRC = R("../layouts/AppLayout.jsx");


// ─────────────────────────────────────────────────────────────────────
// Test 1 · Missed status badge palette + copy + variant.
// ─────────────────────────────────────────────────────────────────────
describe("P47 · Missed job-status badge palette", () => {
  it("locks the missed pill/badge palette + label AND the K50 " +
     "background token AND the case-insensitive resolver — while " +
     "confirming unknown statuses still return null so the badge " +
     "does NOT render for other statuses", () => {
    // ── STATUS_PILL entry (module-local, not exported) ──────────
    // Locks the FULL badge contract: bg fill, fg text colour, and
    // the "Missed" label copy.  Any of the three fields changing
    // trips the test — including a copy tweak to "MISSED" / "Not
    // completed" / etc.
    const pillMatch = CALENDAR_SRC.match(
      /missed:\s*\{\s*bg:\s*"#FEE2E2",\s*fg:\s*"#B91C1C",\s*label:\s*"Missed"\s*\}/,
    );
    expect(
      pillMatch,
      "STATUS_PILL.missed must be `{ bg: '#FEE2E2', fg: '#B91C1C', " +
      "label: 'Missed' }` in CalendarSchedule.jsx — P47 pill contract",
    ).not.toBeNull();

    // ── STATUS_COLORS calendar-dot entry ────────────────────────
    // Muted red-orange dot for the ``missed`` bucket — distinct
    // from ``reopened`` (bright red) and ``cancelled`` (grey).
    const dotMatch = CALENDAR_SRC.match(/missed:\s*"#B91C1C"/);
    expect(
      dotMatch,
      "STATUS_COLORS.missed must be '#B91C1C' — P47 calendar-dot " +
      "colour must stay distinct from reopened + cancelled",
    ).not.toBeNull();

    // ── K50 job-card background (exported, runtime-checked) ─────
    expect(K50_JOB_STATUS_BG.missed).toBe("#FCA5A5");

    // ── jobStatusColor resolver — case-insensitive + trim ───────
    expect(jobStatusColor("missed")).toBe("#FCA5A5");
    expect(jobStatusColor("MISSED")).toBe("#FCA5A5");
    expect(jobStatusColor("  Missed  ")).toBe("#FCA5A5");

    // ── Unknown / typo statuses return null ─────────────────────
    // Locks the "does NOT render for other statuses" invariant —
    // the K50 card renderer treats null as "fall through to the
    // caller's default (white / colors.surface)" per the module
    // docstring.  A typo that accidentally resolved to
    // ``missed``'s hex would silently paint the wrong bucket.
    expect(jobStatusColor("misseed")).toBeNull();
    expect(jobStatusColor("unknown_status")).toBeNull();
    expect(jobStatusColor("")).toBeNull();
    expect(jobStatusColor(null)).toBeNull();
    expect(jobStatusColor(undefined)).toBeNull();
  });
});


// ─────────────────────────────────────────────────────────────────────
// Test 2 · P43 portal layout invariants — top clearance + sticky
// header + banner-above-outlet ordering.  P51 MUST preserve these.
// ─────────────────────────────────────────────────────────────────────
describe("P47 · Portal layout invariants (P43 preservation)", () => {
  it("locks the P43 sticky-header + max-w-5xl outlet wrapper + " +
     "PaymentMethodPromptBanner ABOVE Outlet ordering + no-pt-16 " +
     "regression — every one of these must survive the P51 global " +
     "portal refactor", () => {
    // ── (a) Sticky header markup + testid ───────────────────────
    // The header MUST retain ``sticky top-0 z-30`` positioning and
    // ``h-14`` height so the outlet doesn't need ``pt-16``
    // compensation.  ``data-testid="portal-sticky-header"`` is the
    // downstream anchor used by e2e + regression tests — it must
    // survive.
    expect(APPLAYOUT_SRC).toMatch(/data-testid="portal-sticky-header"/);
    expect(APPLAYOUT_SRC).toMatch(
      /className="sticky top-0 z-30 w-full flex items-center justify-end gap-2 h-14 bg-white border-b px-4"/,
    );

    // ── (b) Portal outlet wrapper (P43 max-w-5xl centre + gutter) ─
    // ``portal-outlet-wrapper`` testid + the exact class string
    // that caps width at max-w-5xl and adds mx-auto centring +
    // px-4 gutter.  A P51 refactor that changes the cap width
    // OR drops the wrapper testid trips this.
    expect(APPLAYOUT_SRC).toMatch(/data-testid=\s*\{\s*[\s\S]*?"portal-outlet-wrapper"[\s\S]*?\}/);
    expect(APPLAYOUT_SRC).toMatch(/"w-full max-w-5xl mx-auto px-4"/);

    // ── (c) PaymentMethodPromptBanner MUST sit ABOVE <Outlet /> ─
    // P43 addendum invariant.  Regex captures the ordering: banner
    // JSX appears first, then Outlet — same source-order the JSX
    // renderer walks.  A refactor that flips the two, or drops
    // the banner entirely, breaks this.
    const bannerIdx = APPLAYOUT_SRC.indexOf("<PaymentMethodPromptBanner />");
    // Use ``lastIndexOf`` for the outlet — an earlier early-return
    // branch (technician role) also renders ``<Outlet />`` further
    // up the file, and ``indexOf`` would surface that occurrence
    // instead of the portal-branch outlet we're locking.  The
    // portal outlet is the LAST ``<Outlet />`` in the file.
    const outletIdx = APPLAYOUT_SRC.lastIndexOf("<Outlet />");
    expect(
      bannerIdx,
      "PaymentMethodPromptBanner must be rendered inside AppLayout " +
      "as a JSX element — P43 invariant",
    ).toBeGreaterThan(-1);
    expect(
      outletIdx,
      "<Outlet /> must remain in AppLayout — the whole app renders " +
      "through it",
    ).toBeGreaterThan(-1);
    expect(
      bannerIdx < outletIdx,
      "P43 ordering: PaymentMethodPromptBanner MUST appear ABOVE " +
      "<Outlet /> in AppLayout so the banner stacks vertically on " +
      "the portal instead of racing the sidebar for horizontal " +
      "space.  Current source has them in the wrong order — a " +
      "refactor flipped the two.",
    ).toBe(true);

    // ── (d) Portal-only branch guard on the banner ──────────────
    // The banner must be gated behind ``location.pathname.startsWith
    // ("/portal")`` so admin/staff never render it.  A P51 refactor
    // that hoists the banner into every layout blows out the
    // admin surface.
    const bannerSurroundings = APPLAYOUT_SRC.slice(
      Math.max(0, bannerIdx - 400),
      bannerIdx,
    );
    expect(
      bannerSurroundings,
      "PaymentMethodPromptBanner must be gated behind " +
      "``location.pathname.startsWith('/portal')`` — admin surface " +
      "should NEVER render this banner",
    ).toMatch(/location\.pathname\.startsWith\(["']\/portal["']\)/);

    // ── (e) No ``pt-16`` regression ─────────────────────────────
    // Before P43 the outlet wrapper carried a ``pt-16`` hack to
    // compensate for a floating universal menu.  The h-14 sticky
    // header replaces that hack — ``pt-16`` MUST NOT re-appear on
    // any outlet wrapper.  Grep across the file for the pattern;
    // the test fails if a future refactor accidentally re-adds it.
    // (Other ``pt-*`` values are fine; ``pt-16`` specifically is
    // the historical regression marker.)
    const pt16InWrapper = /portal-outlet-wrapper[\s\S]{0,200}pt-16|pt-16[\s\S]{0,200}portal-outlet-wrapper/.test(
      APPLAYOUT_SRC,
    );
    expect(
      pt16InWrapper,
      "``pt-16`` MUST NOT appear near the portal-outlet-wrapper — " +
      "the P34 top-padding hack was replaced by the h-14 sticky " +
      "header in P43.  A regression re-added the hack.",
    ).toBe(false);
  });
});
