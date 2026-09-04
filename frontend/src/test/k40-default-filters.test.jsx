/**
 * Phase K40 · Feb-2026 — Default all filter dropdowns to "No filter"
 * site-wide. This suite is the cross-page contract check that pins
 * the K40 invariants against every list page in scope so a
 * regression anywhere trips CI.
 *
 * K40 Rules (per phase brief):
 *   1. Category/status/type dropdown filters on list pages must
 *      default to "all" / "no filter" on every page load.
 *   2. Assignment filter (My/All) defaults to "All" for admin /
 *      dispatcher / super / office. Techs still don't see it.
 *      (No dedicated My/All filter surfaces exist on any of the
 *      in-scope list pages today — verified by grep; the rule
 *      applies preemptively should one land.)
 *   3. Customers page status filter EXCEPTION: defaults to "Active".
 *   4. No persistence across page loads (remove localStorage /
 *      AsyncStorage). Explicit URL params must still be honored.
 *   5. Out of scope: Date range pickers, Dispatch Board default
 *      view, Mobile Schedule tech-scoping, Reports page date
 *      defaults, Search/text-input filters.
 *
 * Source-body contract check pattern (matches the F5 / F6c / G4a
 * style already used across this repo). Every assertion runs against
 * the actual JSX/JS file so any regression is caught pre-preview.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (relative) =>
  fs.readFileSync(path.resolve(process.cwd(), relative), "utf-8");

// ─── Web list pages in scope ─────────────────────────────────
const CUSTOMERS = read("src/pages/customers/CustomersList.jsx");
const INVOICES  = read("src/pages/invoices/InvoicesList.jsx");
const QUOTES    = read("src/pages/quotes/QuotesList.jsx");
const JOBS      = read("src/pages/jobs/JobsList.jsx");
const JOB_REQ   = read("src/pages/job_requests/JobRequestsPages.jsx");
const COMMS     = read("src/pages/comms/CommsPages.jsx");
const REVIEWS   = read("src/pages/reviews/ReviewsPages.jsx");
const LEADS     = read("src/pages/leads/LeadsDashboardPage.jsx");
const USERS     = read("src/pages/admin/AdminUsersList.jsx");
const PAYMENTS  = read("src/pages/finance/FinancePages.jsx");
const ADMIN_REV = read("src/pages/admin/AdminReviewsPage.jsx");
const TIMEOFF   = read("src/pages/AdminTimeOffPage.jsx");
const SOCIAL    = read("src/pages/social/SocialExtras.jsx");


// ═════════════════════════════════════════════════════════════════
// Rule 1 · Default "all" / "" on every filter dropdown
// ═════════════════════════════════════════════════════════════════
describe("K40 · Rule 1 — filter dropdowns default to 'all' / no-filter", () => {
  it("InvoicesList status filter defaults to '' (all statuses)", () => {
    // URL-derived: params.get('status') || ""
    expect(INVOICES).toMatch(
      /const status = params\.get\("status"\)\s*\|\|\s*""/,
    );
  });

  it("InvoicesList card-on-file filter defaults to 'any'", () => {
    expect(INVOICES).toMatch(
      /const cardFilter = params\.get\("card"\)\s*\|\|\s*"any"/,
    );
  });

  it("QuotesList status filter defaults to '' (all statuses)", () => {
    expect(QUOTES).toMatch(
      /const status = params\.get\("status"\)\s*\|\|\s*""/,
    );
  });

  it("JobsList status filter defaults to '' (all statuses)", () => {
    expect(JOBS).toMatch(
      /useState\(searchParams\.get\("status"\)\s*\|\|\s*""\)/,
    );
  });

  it("AdminJobRequestsPage status filter defaults to '' (all)", () => {
    expect(JOB_REQ).toMatch(/const \[status, setStatus\] = useState\(""\);/);
  });

  it("CommsSendsHistoryPage kind + status default to '' (all)", () => {
    expect(COMMS).toMatch(/const \[kind, setKind\] = useState\(""\);/);
    expect(COMMS).toMatch(/const \[status, setStatus\] = useState\(""\);/);
  });

  it("ReviewsRequestsPage outcome filter defaults to '' (all)", () => {
    expect(REVIEWS).toMatch(
      /const \[filterOutcome, setFilterOutcome\] = useState\(""\);/,
    );
  });

  it("LeadsDashboardPage source + status filters default to '' (all)", () => {
    expect(LEADS).toMatch(
      /useState\(\{\s*source:\s*""\s*,\s*status:\s*""\s*,\s*search:\s*""\s*\}\)/,
    );
  });

  it("AdminUsersList role filter defaults to '' (all)", () => {
    expect(USERS).toMatch(/const \[role, setRole\] = useState\(""\);/);
  });

  it("PaymentsLedger method + status default to 'all' / '' (no filter)", () => {
    expect(PAYMENTS).toMatch(/const \[method, setMethod\] = useState\("all"\);/);
    expect(PAYMENTS).toMatch(/const \[status, setStatus\] = useState\(""\);/);
  });

  it("AdminReviewsPage filter object defaults every leg to '' (all)", () => {
    expect(ADMIN_REV).toMatch(
      /useState\(\{\s*status:\s*""[\s\S]{0,120}is_public:\s*""[\s\S]{0,120}min_rating:\s*""[\s\S]{0,120}max_rating:\s*""[\s\S]{0,20}\}\)/,
    );
  });

  it("K40 · AdminTimeOffPage tab defaults to 'all' (was 'pending')", () => {
    expect(TIMEOFF).toMatch(
      /const \[tab, setTab\] = useState\("all"\);/,
    );
  });

  it("K40 · Social ApprovalsPage status defaults to '' (was 'pending')", () => {
    expect(SOCIAL).toMatch(
      /const \[status, setStatus\] = useState\(""\);/,
    );
    // And the dropdown must now expose an "All" option so the
    // literal maps to a visible pass-through in the UI.
    expect(SOCIAL).toMatch(
      /<option value="">All<\/option>/,
    );
  });
});


// ═════════════════════════════════════════════════════════════════
// Rule 3 · Customers-page EXCEPTION — cohort tab defaults to Active
// ═════════════════════════════════════════════════════════════════
describe("K40 · Rule 3 — Customers cohort tab exception (default 'active')", () => {
  it("initial tab falls back to 'active' when no URL param is present", () => {
    // The initializer function must return the string literal
    // "active" as its terminal branch (URL params still win — see
    // Rule 4 below).
    expect(CUSTOMERS).toMatch(/return "active";/);
  });

  it("K40 · portalStatus (the OTHER filter on Customers) defaults to 'all'", () => {
    expect(CUSTOMERS).toMatch(
      /const \[portalStatus, setPortalStatus\] = useState\("all"\);/,
    );
  });
});


// ═════════════════════════════════════════════════════════════════
// Rule 4 · No persistence — remove localStorage / AsyncStorage
// ═════════════════════════════════════════════════════════════════
describe("K40 · Rule 4 — no persistence across page loads", () => {
  it("CustomersList · cohort tab has NO ``_COHORT_STORAGE_KEY`` plumbing", () => {
    expect(CUSTOMERS).not.toMatch(/_COHORT_STORAGE_KEY/);
    expect(CUSTOMERS).not.toMatch(
      /localStorage\.(get|set)Item\([^)]*customerListFilter\.status/,
    );
  });

  it("CustomersList · portalStatus has NO ``_PORTAL_STORAGE_KEY`` plumbing", () => {
    expect(CUSTOMERS).not.toMatch(/_PORTAL_STORAGE_KEY/);
    expect(CUSTOMERS).not.toMatch(
      /localStorage\.(get|set)Item\([^)]*customerListFilter\.portalStatus/,
    );
  });

  // Sort is NOT a filter (K40 rule targets category/status/type
  // filters). ``customers.sortBy`` persistence intentionally
  // remains — this test locks in that carve-out so a future PR
  // doesn't accidentally strip sort persistence "for consistency".
  it("CustomersList · sort persistence (``customers.sortBy``) IS retained (not a filter)", () => {
    expect(CUSTOMERS).toMatch(/customers\.sortBy/);
  });

  it("no in-scope list page reads a status filter from localStorage", () => {
    // Regression guard: sweep the concatenation of every in-scope
    // source for the pattern ``localStorage.getItem(<something with
    // 'filter' or 'status' in the key>)``. Only surfaces expected to
    // legitimately touch localStorage should slip past.
    const all = [
      INVOICES, QUOTES, JOBS, JOB_REQ, COMMS, REVIEWS, LEADS, USERS,
      PAYMENTS, ADMIN_REV, TIMEOFF,
    ].join("\n---\n");
    // No page should hydrate a *filter* value from localStorage.
    // (Note: some pages persist token/auth data — that's fine and
    // out of scope for this rule.)
    expect(all).not.toMatch(
      /localStorage\.getItem\([^)]*[Ff]ilter[^)]*\)/,
    );
    expect(all).not.toMatch(
      /localStorage\.getItem\([^)]*[Ss]tatus[^)]*\)/,
    );
    expect(all).not.toMatch(
      /localStorage\.getItem\([^)]*[Cc]ategory[^)]*\)/,
    );
  });
});


// ═════════════════════════════════════════════════════════════════
// Rule 4 · URL params still win
// ═════════════════════════════════════════════════════════════════
describe("K40 · Rule 4 (b) — explicit URL params still honored", () => {
  it("InvoicesList status is read directly from searchParams", () => {
    // Every mount hydrates from the URL — so /invoices?status=unpaid
    // still lands on the Unpaid filter even after K40.
    expect(INVOICES).toMatch(/params\.get\("status"\)/);
  });

  it("QuotesList status is read directly from searchParams", () => {
    expect(QUOTES).toMatch(/params\.get\("status"\)/);
  });

  it("JobsList status honors searchParams on first mount", () => {
    expect(JOBS).toMatch(/searchParams\.get\("status"\)/);
  });

  it("CustomersList honors ?tab / ?status URL params (Rule 4 override)", () => {
    // The cohort initializer inspects both aliases before falling
    // back to the "active" default.
    expect(CUSTOMERS).toMatch(/searchParams\.get\("tab"\)/);
    expect(CUSTOMERS).toMatch(/searchParams\.get\("status"\)/);
  });
});
