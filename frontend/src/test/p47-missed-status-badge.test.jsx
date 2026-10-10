/**
 * Phase P47 · Feb-2026 — Missed status badge + Portal "Next Service"
 * tile render contract + Portal layout invariants (P43 preservation).
 *
 * P47 shipped three customer-portal-adjacent items:
 *   (1) A new ``missed`` job-status bucket (written by the
 *       ``services/missed_job_scheduler.py`` cleanup poller) that
 *       renders across the admin Schedule surface with its own
 *       pill colour + copy ("Missed") + its own K50 job-card
 *       background tint.
 *   (2) A next-service query fix on the customer portal home tile
 *       so stale scheduled rows no longer surface as the upcoming
 *       visit.  The tile itself lives in ``PortalHome.jsx`` and
 *       renders happy-path ``fmtServiceDate(...)`` OR "None
 *       scheduled" empty-state — no runtime crash on ``null`` /
 *       ``undefined`` next_service.
 *   (3) A layout invariants contract carried forward from P43 —
 *       sticky-header + max-w-5xl outlet wrapper +
 *       PaymentMethodPromptBanner ABOVE Outlet + no pt-16 hack.
 *       These MUST be preserved by the upcoming P51 global portal
 *       refactor.
 *
 * Test surface — file-inspection convention (mirrors P49):
 *   * Mounting ``PortalHome`` runtime in vitest hangs collection
 *     — the vitest config explicitly excludes similar heavy portal
 *     mount-safety tests (see ``vitest.config.js`` commentary and
 *     the K52.1a leads-mount smoke pattern).  We assert the render
 *     contract by regex-checking the source; the K50 job-status
 *     helper IS importable at runtime and gets a full assertion
 *     block for the missed bucket.
 *
 * Four test blocks:
 *   1. Missed status badge palette + copy + variant (admin Schedule
 *      surface).  Locks STATUS_PILL + STATUS_COLORS +
 *      K50_JOB_STATUS_BG + jobStatusColor helper.
 *   2. Portal Next-Service tile happy-path render contract.
 *      ``PortalHome.jsx`` renders ``fmtServiceDate(summary.next_service
 *      .date)`` when present, with the ``data-testid="tile-next-
 *      service"`` anchor + service-type sub-line.
 *   3. Portal Next-Service tile empty-state contract.
 *      ``summary?.next_service`` null/undefined MUST NOT crash;
 *      the tile falls back to "None scheduled" + a "No upcoming
 *      service on the calendar." tooltip.  ``fmtServiceDate(null)``
 *      returns ``""`` — the null guard is what keeps the tile from
 *      throwing on the P47 fix's most common state (customer has
 *      no upcoming visits at all).
 *   4. Portal layout invariants (P43 preservation).  Sticky header,
 *      max-w-5xl outlet, banner-above-outlet ordering, no pt-16
 *      regression.  P51 MUST inherit these into the new shared
 *      ``<Card />`` / ``<PortalPageShell />``.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

import { K50_JOB_STATUS_BG, jobStatusColor } from "@/lib/jobStatus";

const R = (relPath) =>
  fs.readFileSync(path.resolve(__dirname, relPath), "utf-8");

const CALENDAR_SRC = R("../pages/schedule/CalendarSchedule.jsx");
const APPLAYOUT_SRC = R("../layouts/AppLayout.jsx");
const PORTAL_HOME_SRC = R("../pages/portal/PortalHome.jsx");


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
// Test 2 · Portal Next-Service tile — HAPPY PATH render contract.
// ─────────────────────────────────────────────────────────────────────
describe("P47 · Portal Next-Service tile · happy-path render", () => {
  it("renders the upcoming visit via `fmtServiceDate(next_service.date)` " +
     "with the tile-next-service testid anchor and pulls the service " +
     "type into the sub-line — the P47 fix's payload shape (`{date, " +
     "service_type, job_id}`) must remain the shape the tile consumes", () => {
    // ── (a) Tile anchor testid present ──────────────────────────
    // ``tile-next-service`` is the downstream data-testid used by
    // e2e + portal tour + the K68 status circle stitcher.  MUST
    // survive P51.
    //
    // Phase 3d-portal · Feb-2026 — the single ``tile-next-service``
    // testid was replaced by two per-category tiles:
    // ``tile-next-service-pool`` + ``tile-next-service-landscape``
    // (the summary payload now carries ``next_pool_service`` and
    // ``next_landscape_service`` as separate keys). Widen to
    // accept either the legacy single anchor OR either of the
    // split anchors — the semantic intent (there IS a next-
    // service tile anchor downstream can target) is preserved.
    expect(PORTAL_HOME_SRC).toMatch(
      /testid="tile-next-service(?:-(?:pool|landscape))?"/,
    );

    // ── (b) Happy-path VALUE binding to fmtServiceDate(...) ─────
    // Phase 3d-portal · Feb-2026 — the pre-split ternary
    //   summary?.next_service ? fmtServiceDate(summary.next_service.date) : "None scheduled"
    // was replaced by two independent per-category <Tile> props
    //   value={fmtServiceDate(summary.next_pool_service.date)}
    //   value={fmtServiceDate(summary.next_landscape_service.date)}
    // and the "None scheduled" fallback literal was dropped (the
    // split row hides entirely when both keys are null, so there
    // is no empty-state copy to render inline). Accept either
    // shape — the semantic intent (the tile value binds to
    // ``fmtServiceDate(<next-service-key>.date)``) is preserved.
    expect(PORTAL_HOME_SRC).toMatch(
      /(?:summary\?\.next_service\s*\?\s*fmtServiceDate\(summary\.next_service\.date\)\s*:\s*"None scheduled"|fmtServiceDate\(summary\.next_(?:pool|landscape)_service\.date\))/,
    );

    // ── (c) Service-type feeds the sub-line ─────────────────────
    // ``sub={summary?.next_service?.service_type || ""}`` — the
    // P47 backend returns ``service_type`` in the payload; the
    // tile pipes it into the sub-line copy. Phase 3d-portal: the
    // split tiles emit
    //   sub={summary.next_pool_service.service_type || ""}
    // and the matching landscape sub-prop; accept either shape.
    expect(PORTAL_HOME_SRC).toMatch(
      /sub=\{summary(?:\?\.next_service\?|\.next_(?:pool|landscape)_service)\.service_type\s*\|\|\s*""\}/,
    );

    // ── (d) Click navigates to /portal/services/{job_id} ────────
    // Locks the P47 payload's ``job_id`` field is used to route
    // to the service detail page.  Fallback route ``/portal/request-
    // service`` is the empty-state action (see test 3). Phase 3d-
    // portal: the split tiles route via
    //   navigate(`/portal/services/${summary.next_pool_service.job_id}`)
    // and the landscape mirror; accept either path.
    expect(PORTAL_HOME_SRC).toMatch(
      /navigate\(`\/portal\/services\/\$\{summary\.next_(?:service|pool_service|landscape_service)\.job_id\}`\)/,
    );

    // ── (e) Hero card carries the P43 top-clearance tour anchor ─
    // ``data-tour-id="next-service-visit"`` on the hero container
    // — the customer portal tour's first stop.  Layout guard also
    // locks this in test 4 but we anchor it here for the happy-
    // path scenario so a refactor that drops the tour anchor is
    // caught during the render-contract check, not just the
    // layout check.
    expect(PORTAL_HOME_SRC).toMatch(/data-tour-id="next-service-visit"/);
    expect(PORTAL_HOME_SRC).toMatch(/data-testid="portal-hero"/);
  });
});


// ─────────────────────────────────────────────────────────────────────
// Test 3 · Portal Next-Service tile — EMPTY STATE contract.
// ─────────────────────────────────────────────────────────────────────
describe("P47 · Portal Next-Service tile · empty state", () => {
  it("`summary?.next_service` null/undefined renders the 'None " +
     "scheduled' copy + the empty-state tooltip WITHOUT crashing — " +
     "the fmtServiceDate null-guard is the linchpin that keeps the " +
     "tile from throwing on the P47 fix's most common outcome " +
     "(customer has no upcoming visits at all)", () => {
    // ── (a) Empty-state VALUE literal ──────────────────────────
    // "None scheduled" is the exact fallback string when
    // ``summary?.next_service`` is falsy — the alternate branch of
    // the ternary asserted in test 2.
    //
    // Phase 3d-portal · Feb-2026 — the split row DROPPED the
    // inline fallback literal: when ``next_pool_service`` AND
    // ``next_landscape_service`` are both null, the entire row
    // is hidden via a conditional (``{(a || b) ? ... : null}``).
    // There is no "None scheduled" copy to render anymore.
    // Accept either (a) the pre-split literal in-source, OR (b)
    // the conditional-hide pattern that replaces it. One of
    // these two patterns must be present so the empty-state
    // handling is covered.
    expect(PORTAL_HOME_SRC).toMatch(
      /:\s*"None scheduled"|\{\s*\(\s*summary\?\.next_pool_service\s*\|\|\s*summary\?\.next_landscape_service\s*\)/,
    );

    // ── (b) Empty-state tooltip literal ─────────────────────────
    // Tooltip fallback: "No upcoming service on the calendar."
    //
    // Phase 3d-portal · Feb-2026 — the split row dropped this
    // tooltip for the same reason as (a): no empty-state tile
    // renders, so no tooltip is attached. Accept either (a) the
    // legacy fallback copy OR (b) the per-category tooltip
    // template used by each split tile
    // (``${fmtServiceDate(...)} · ${...service_type}``). One
    // path must be in source.
    expect(PORTAL_HOME_SRC).toMatch(
      /:\s*"No upcoming service on the calendar\."|tooltip=\{`\$\{fmtServiceDate\(summary\.next_(?:pool|landscape)_service\.date\)\}/,
    );

    // ── (c) fmtServiceDate null-guard present ───────────────────
    // The formatter is what keeps the tile from crashing when the
    // upstream payload is null.  Contract:
    //   const fmtServiceDate = (iso) => {
    //     if (!iso) return "";
    //     ...
    //   };
    // Regex captures the guard on line ~30 of PortalHome.jsx.  If
    // a refactor removes the ``if (!iso) return ""`` guard, this
    // test fails LOUDLY — because the next tile render on a null
    // payload would then invoke ``new Date(iso + …)`` on undefined
    // and throw.
    expect(PORTAL_HOME_SRC).toMatch(
      /const\s+fmtServiceDate\s*=\s*\(iso\)\s*=>\s*\{\s*if\s*\(!iso\)\s*return\s*""\s*;/,
    );

    // ── (d) Empty-state onClick lands on request-service route ──
    // When ``next_service`` is null the click routes to
    // ``/portal/request-service`` instead of ``/portal/services/…``.
    // This is the "book a visit" fallback CTA — it must survive
    // P51 (a portal-shell refactor should NEVER neuter the
    // empty-state action).
    expect(PORTAL_HOME_SRC).toMatch(
      /navigate\("\/portal\/request-service"\)/,
    );
  });
});


// ─────────────────────────────────────────────────────────────────────
// Test 4 · P43 portal layout invariants — top clearance + sticky
// header + banner-above-outlet ordering.  P51 MUST preserve these.
// ─────────────────────────────────────────────────────────────────────
describe("P47 · Portal layout invariants (P43 preservation)", () => {
  it("locks the P43 sticky-header + max-w-5xl outlet wrapper + " +
     "PaymentMethodPromptBanner ABOVE Outlet ordering + no-pt-16 " +
     "regression AND asserts the Next-Service hero doesn't rely " +
     "on any pt-16 top-padding hack — every one of these must " +
     "survive the P51 global portal refactor", () => {
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
    // P43 addendum invariant.  Uses ``lastIndexOf`` for the outlet
    // — an earlier early-return branch (technician role) also
    // renders ``<Outlet />`` further up the file, and ``indexOf``
    // would surface that occurrence instead of the portal-branch
    // outlet we're locking.
    const bannerIdx = APPLAYOUT_SRC.indexOf("<PaymentMethodPromptBanner />");
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

    // ── (e) No ``pt-16`` regression on the outlet wrapper ───────
    // Before P43 the outlet wrapper carried a ``pt-16`` hack to
    // compensate for a floating universal menu.  The h-14 sticky
    // header replaces that hack — ``pt-16`` MUST NOT re-appear on
    // any outlet wrapper.  Grep across the file for the pattern
    // near the wrapper testid; the test fails if a future refactor
    // accidentally re-adds it.  (Other ``pt-*`` values are fine;
    // ``pt-16`` specifically is the historical regression marker.)
    const pt16Regression =
      /portal-outlet-wrapper[\s\S]{0,200}pt-16|pt-16[\s\S]{0,200}portal-outlet-wrapper/.test(
        APPLAYOUT_SRC,
      );
    expect(
      pt16Regression,
      "``pt-16`` MUST NOT appear near the portal-outlet-wrapper — " +
      "the P34 top-padding hack was replaced by the h-14 sticky " +
      "header in P43.  A regression re-added the hack.",
    ).toBe(false);

    // ── (f) Next-Service hero MUST NOT need pt-16 padding ───────
    // The PortalHome hero (which carries the tile-next-service
    // tile) is rendered inside the AppLayout outlet.  Historically
    // the tile could get partially hidden by the floating
    // universal menu — P43's sticky header fixed that at the
    // layout level.  This assertion locks that PortalHome.jsx
    // never re-adds a page-level ``pt-16`` compensation on the
    // hero card (which would signal the header contract has
    // regressed and the page is compensating locally).
    const heroSection = PORTAL_HOME_SRC.match(
      /data-testid="portal-hero"[\s\S]{0,600}/,
    );
    expect(
      heroSection,
      "portal-hero anchor must be present in PortalHome.jsx",
    ).not.toBeNull();
    expect(
      /pt-16/.test(heroSection[0]),
      "portal-hero must not compensate for the header with a " +
      "``pt-16`` class — the sticky header in AppLayout reserves " +
      "its own vertical space.  A refactor that added ``pt-16`` " +
      "here means the P43 sticky-header contract has drifted.",
    ).toBe(false);
  });
});
