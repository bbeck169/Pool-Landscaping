/**
 * Feb-2026 · Batch 2026-P2 — Priority 2 · 3 · 7 lock-in.
 *
 * Source-lints (no full DOM mount) that guard the three dashboard
 * ships from silent regressions:
 *
 *   P2 · Emerald hero tile removed. The huge "Total Paid Revenue"
 *        gradient card no longer renders on the admin dashboard.
 *        RevenueSplitChip stays — it carries the equivalent
 *        breakdown at a tenth the visual weight.
 *
 *   P7 · KPI tiles route to filtered list pages. Four KpiCard
 *        invocations in the grid — Active Jobs, Pending, Customers,
 *        Technicians — declare deterministic ``navigate(...)``
 *        targets so a Dashboard drill-down lands the operator on
 *        the correct filtered view.
 *
 *   P3 · Autobilling opt-in CTA on ``/portal/payment-complete``.
 *        Renders only when the reconcile response reports
 *        ``payment_method_saved: true`` AND
 *        ``autobilling_enabled: false``. Enable / Not-now buttons
 *        carry stable data-testids. Copy matches the spec.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const DASH_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/admin/Dashboard.jsx"),
  "utf8",
);

const PORTAL_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/portal/PortalPages.jsx"),
  "utf8",
);

const JOBS_LIST_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobsList.jsx"),
  "utf8",
);


describe("Priority 2 · Emerald hero tile removed from admin Dashboard", () => {
  it("Dashboard.jsx no longer renders a ``dashboard-hero`` element", () => {
    expect(DASH_SRC).not.toMatch(/data-testid="dashboard-hero"/);
  });

  it("No ``data-tone=\"emerald\"`` hero surface remains", () => {
    // Guard against a copy-paste regression where someone shims
    // an alternate hero back in with the same tone token.
    const heroToneMatches = DASH_SRC.match(/data-tone="emerald"/g) || [];
    // The Technicians KPI tile ships tone="emerald" via the KpiCard
    // ``data-tone={tone || "sky"}`` fallback, so the raw literal
    // "emerald" should not appear as a data-tone attribute in the
    // JSX — the tone comes through the tone prop instead.
    expect(heroToneMatches.length).toBe(0);
  });

  it("Pool vs Landscape split chip has been removed by user request (Feb-2026 cleanup)", () => {
    // User requested removal of the ``Mixed $X.XX (100%)`` full-
    // width gray bar that this chip rendered when the tenant had
    // no Pool/Landscape breakdown. Removal is intentional; a
    // paste-back regression must fail loudly. RevenueByCategoryTile
    // carries the by-category breakdown at higher fidelity now.
    expect(DASH_SRC).not.toMatch(/<RevenueSplitChip/);
    expect(DASH_SRC).not.toMatch(/from ["']@\/components\/dashboard\/RevenueSplitChip["']/);
  });

  it("The removal comment references Priority 2 so future greps land it", () => {
    expect(DASH_SRC).toMatch(/Priority 2/);
  });
});


describe("Priority 7 · Dashboard KPI tiles are clickable drill-downs", () => {
  const startIdx = DASH_SRC.indexOf("{/* KPI grid */}");
  const endIdx = DASH_SRC.indexOf(
    "{/* Referral Revenue tile — Phase 20B module B */}");
  const block = DASH_SRC.slice(startIdx, endIdx);

  it("Active Jobs routes to /admin/jobs?status=active", () => {
    expect(block).toMatch(
      /testId="kpi-active-jobs"[\s\S]{0,200}navigate\("\/admin\/jobs\?status=active"\)|navigate\("\/admin\/jobs\?status=active"\)[\s\S]{0,200}testId="kpi-active-jobs"/,
    );
  });

  it("Pending routes to /admin/jobs?status=pending", () => {
    expect(block).toMatch(
      /testId="kpi-pending"[\s\S]{0,200}navigate\("\/admin\/jobs\?status=pending"\)|navigate\("\/admin\/jobs\?status=pending"\)[\s\S]{0,200}testId="kpi-pending"/,
    );
  });

  it("Active Customers routes to /customers?status=active (Feb-2026 tile swap)", () => {
    // Feb-2026 · The bottom row of the KPI grid was swapped from
    // ``Customers`` (total) + ``Technicians`` to Active Customers +
    // Inactive Customers.  Both drill down into a filtered customer
    // list keyed by ``?status=``.  Legacy lock-ins for ``kpi-customers``
    // and ``kpi-technicians`` are retired below.
    expect(block).toMatch(
      /testId="kpi-active-customers"[\s\S]{0,200}navigate\("\/customers\?status=active"\)|navigate\("\/customers\?status=active"\)[\s\S]{0,200}testId="kpi-active-customers"/,
    );
  });

  it("Inactive Customers routes to /customers?status=inactive (Feb-2026 tile swap)", () => {
    expect(block).toMatch(
      /testId="kpi-inactive-customers"[\s\S]{0,200}navigate\("\/customers\?status=inactive"\)|navigate\("\/customers\?status=inactive"\)[\s\S]{0,200}testId="kpi-inactive-customers"/,
    );
  });

  it("Legacy Customers + Technicians tiles are gone from the KPI grid", () => {
    expect(block).not.toMatch(/testId="kpi-customers"/);
    expect(block).not.toMatch(/testId="kpi-technicians"/);
  });

  it("JobsList reads the ?status= URL param on mount", () => {
    // The list page must hydrate its filter from useSearchParams
    // so the Dashboard KPI clicks land on a filtered view.
    expect(JOBS_LIST_SRC).toMatch(/useSearchParams/);
    expect(JOBS_LIST_SRC).toMatch(
      /useState\(\s*searchParams\.get\("status"\)/,
    );
  });

  it("JobsList exposes ``active`` + ``pending`` in the filter <select>", () => {
    // Both statuses must render as options so the drill-down lands
    // on a visibly-selected filter, not a blank select.
    expect(JOBS_LIST_SRC).toMatch(/value:\s*"active"/);
    expect(JOBS_LIST_SRC).toMatch(/value:\s*"pending"/);
  });
});


describe("Priority 3 · Autobilling opt-in CTA on payment-complete", () => {
  it("PortalPaymentComplete gates the CTA on payment_method_saved", () => {
    expect(PORTAL_SRC).toMatch(/showAutobillingCta/);
    expect(PORTAL_SRC).toMatch(/r\.payment_method_saved/);
    // Suppresses the CTA when the customer already opted in.
    expect(PORTAL_SRC).toMatch(/!r\.autobilling_enabled/);
  });

  it("Two-line CTA copy matches the spec verbatim", () => {
    // Headline — matches Priority 3 spec.
    expect(PORTAL_SRC).toMatch(/Never miss a payment/);
    // Body copy — matches the spec exactly.
    expect(PORTAL_SRC).toMatch(
      /Enable autobilling to charge future invoices to this saved payment method automatically\./,
    );
  });

  it("Enable + dismiss buttons carry stable testids", () => {
    expect(PORTAL_SRC).toMatch(/testid="autobilling-cta-enable"/);
    expect(PORTAL_SRC).toMatch(/testid="autobilling-cta-dismiss"/);
    expect(PORTAL_SRC).toMatch(/data-testid="autobilling-cta"/);
  });

  it("Enable button POSTs to /customer-portal/autobilling/enable", () => {
    expect(PORTAL_SRC).toMatch(
      /api\.post\(\s*["']\/customer-portal\/autobilling\/enable["']/,
    );
  });

  it("Success banner acknowledges autobilling is on", () => {
    expect(PORTAL_SRC).toMatch(/autobilling-enabled-banner/);
    expect(PORTAL_SRC).toMatch(
      /Autobilling is on\. Future invoices will charge automatically\./,
    );
  });

  it("Handles ``no_default_payment_method`` error branch", () => {
    // Frontend maps the 409 detail to a friendly nudge banner.
    expect(PORTAL_SRC).toMatch(/no_default_payment_method/);
    expect(PORTAL_SRC).toMatch(/autobilling-nopm-banner/);
  });
});
