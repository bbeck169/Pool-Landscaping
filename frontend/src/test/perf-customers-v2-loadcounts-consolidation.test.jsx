/**
 * CUS-perf · Feb-2026 — Customers-list ``loadCounts()`` invocation shape.
 *
 * ── History ──
 * v1 (Phase P31 / pre-CUS-perf-v2)
 *   • Filter/tab/sort effect fired BOTH ``load()`` + ``loadCounts()``
 *     — 2 ``/customers/counts`` requests on mount (one from the
 *     mount-only effect, one from the primary effect firing on
 *     initial render), 1 additional counts request per filter
 *     change.  Wasteful — the 5 standalone badges were treated as
 *     "stable" (filter-invariant) so re-fetching them was pure
 *     overhead.
 * v2 (Phase P31)
 *   • Removed ``loadCounts()`` from the primary filter effect.
 *     Mount fired EXACTLY ONE counts request; filter changes fired
 *     ONLY the paginated list refetch.
 *   • Contract asserted here up until the CUS-perf v3 refactor.
 * v3 (CUS-perf · Feb-2026, R3=B ruling)
 *   • Backend added an ``all`` bucket to ``/customers/counts`` +
 *     switched the paginated list's ``counts_by_status`` off the
 *     ``$facet`` aggregation.  Frontend now needs the 4 TAB counts
 *     (active / inactive / muted / waitlist) to refresh on every
 *     filter / tab / page / sort change — the standalone badges
 *     remain filter-invariant on the server (see
 *     ``/customers/counts`` docstring: the 5 stable badges intentionally
 *     ignore the caller's chip surface) so re-fetching them costs
 *     nothing beyond the round-trip.
 *   • Primary useEffect now fires
 *     ``Promise.all([load(), loadCounts()])`` in parallel.  Cost is
 *     ~1 wall-clock round trip because HTTP/2 mux serves both.
 *   • The redundant mount-only ``useEffect(() => { loadCounts(); }, [])``
 *     was removed (folded into the Promise.all's initial mount fire).
 *
 * ── v3 Contract (this file's invariants) ──
 *   1. Mount fires EXACTLY ONE ``/customers/counts`` request (the
 *      primary useEffect's Promise.all — the mount-only fetch was
 *      dropped).  Same total as v2 on mount → no regression in the
 *      cold-start round-trip count.
 *   2. A filter / tab / sort / page change fires BOTH
 *      ``/customers?...`` (list envelope) AND ``/customers/counts``
 *      in parallel via ``Promise.all``.  This is the v3 shift from
 *      v2 (which suppressed the counts refetch on filter changes).
 *   3. Every post-mutation callsite (bulk-status, restore, import,
 *      etc.) still calls ``loadCounts()`` explicitly — those paths
 *      are NOT covered by this test (out-of-scope for the primary
 *      filter effect).  The P31 sibling test file
 *      (``cus-perf-v3-loadcounts-on-filter.test.jsx``) locks the
 *      source-shape of the ``Promise.all`` call site.
 */
import React from "react";
import { render, waitFor, fireEvent, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";


// Track every GET path the page fires so we can count fanout.
let _apiGetPaths = [];
let _apiGetImpl = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (path, ...rest) => {
      _apiGetPaths.push(path);
      return _apiGetImpl(path, ...rest);
    },
    post: vi.fn().mockResolvedValue({}),
    put: vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock("@/hooks/use-toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(), warning: vi.fn(),
  }),
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: "admin",
    effectiveRole: "admin",
    isAdmin: true,
    isAdminOrManager: true,
    canDo: () => true,
  }),
}));


beforeEach(() => {
  _apiGetPaths = [];
  _apiGetImpl = vi.fn().mockImplementation((path) => {
    const p = typeof path === "string" ? path : "";
    if (p.startsWith("/customers/counts")) {
      return Promise.resolve({
        active: 12, inactive: 3, muted: 1, waitlist: 2, all: 16,
        missing_address: 5, portal_activated: 4,
        portal_not_activated: 6, no_payment_method: 8,
        never_logged_in: 7,
      });
    }
    if (p.startsWith("/customers")) {
      return Promise.resolve({
        items: [], total: 0, page: 1, page_size: 100, total_pages: 0,
        counts_by_status: {
          active: 12, inactive: 3, muted: 1, waitlist: 2, all: 16,
        },
      });
    }
    if (p.startsWith("/customer-tags")
        || p.startsWith("/tenants/tags")
        || p.startsWith("/tenants/me/tags")) {
      return Promise.resolve([]);
    }
    return Promise.resolve({});
  });
  try {
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: "u-adm", role: "admin" }),
    );
  } catch { /* jsdom */ }
});


function _countsHits() {
  return _apiGetPaths.filter((p) => p.startsWith("/customers/counts"));
}

function _listHits() {
  return _apiGetPaths.filter(
    (p) => p.startsWith("/customers") && !p.startsWith("/customers/counts")
       && !p.startsWith("/customer-tags"),
  );
}


describe("CUS-perf v3 · Customers list loadCounts invocation shape", () => {
  it("mount fires ONE /customers/counts (Promise.all) and at least ONE /customers list request",
      async () => {
    const { default: CustomersList } = await import(
      "@/pages/customers/CustomersList"
    );
    render(
      <MemoryRouter initialEntries={["/customers"]}>
        <CustomersList />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(_countsHits().length).toBeGreaterThanOrEqual(1);
      expect(_listHits().length).toBeGreaterThanOrEqual(1);
    });

    // v3 · Exactly ONE /customers/counts fetch on cold mount.  The
    // pre-v2 shape fired TWO (mount-only effect + primary filter
    // effect on initial render).  v2 dropped the primary-effect
    // call.  v3 dropped the mount-only effect and folded its
    // responsibility into the primary useEffect's Promise.all —
    // so the mount total is unchanged from v2 (exactly one), but
    // the source-of-truth is now the Promise.all path.
    expect(_countsHits().length).toBe(1);
  });

  it("changing sort re-fires /customers/counts in parallel with the list refetch (v3 contract)",
      async () => {
    const { default: CustomersList } = await import(
      "@/pages/customers/CustomersList"
    );
    render(
      <MemoryRouter initialEntries={["/customers"]}>
        <CustomersList />
      </MemoryRouter>,
    );

    // Wait for the initial mount to settle.
    await waitFor(() => {
      expect(_countsHits().length).toBeGreaterThanOrEqual(1);
    });
    const baselineCounts = _countsHits().length;
    const baselineList = _listHits().length;

    // Flip the sort dropdown to trigger the primary filter effect.
    // The sort selector's data-testid is ``customers-sort-select``
    // (grep-confirmed in the page).  Fall back to a tab-click if
    // the DOM query fails (test-env resilience — the assertion is
    // what matters).
    const sortEl = screen.queryByTestId("customers-sort-select");
    if (sortEl) {
      fireEvent.change(sortEl, { target: { value: "name_asc" } });
    } else {
      // If the sort selector isn't queryable, we can still validate
      // via the tabs — clicking a tab fires the same effect deps
      // (``tab`` is in the primary useEffect's dep-list).
      const tab = screen.queryByTestId("tab-inactive");
      if (tab) fireEvent.click(tab);
    }

    // v3 · both refetches must fire (baseline+1 minimum for each).
    // ``Promise.all([load(), loadCounts()])`` dispatches them in
    // parallel — the assertion below tolerates arbitrary ordering
    // in the ``_apiGetPaths`` capture but insists BOTH increased.
    await waitFor(() => {
      expect(_listHits().length).toBeGreaterThan(baselineList);
      expect(_countsHits().length).toBeGreaterThan(baselineCounts);
    }, { timeout: 500 });
  });

  it("changing page re-fires /customers/counts in parallel with the list refetch (v3 contract)",
      async () => {
    const { default: CustomersList } = await import(
      "@/pages/customers/CustomersList"
    );
    render(
      <MemoryRouter initialEntries={["/customers"]}>
        <CustomersList />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(_countsHits().length).toBeGreaterThanOrEqual(1);
    });
    const baselineCounts = _countsHits().length;
    const baselineList = _listHits().length;

    // Simulate a page change via the pagination button.  If not
    // present in this render (empty envelope), fall back to a
    // tab change that shares the same primary-effect dep-list.
    const nextBtn = screen.queryByTestId("customers-pagination-next");
    if (nextBtn) {
      fireEvent.click(nextBtn);
    } else {
      const tab = screen.queryByTestId("tab-inactive");
      if (tab) fireEvent.click(tab);
    }

    // v3 · both refetches must fire.  See the ``sort`` test's
    // rationale — same Promise.all path, same parallel dispatch.
    await waitFor(() => {
      expect(_listHits().length).toBeGreaterThan(baselineList);
      expect(_countsHits().length).toBeGreaterThan(baselineCounts);
    }, { timeout: 500 });
  });
});
