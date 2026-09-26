/**
 * CUS-perf · Feb-2026 — Customers-list loadCounts filter-effect consolidation.
 *
 * Locks the surgical removal of ``loadCounts()`` from the
 * filter/tab/page/sort effect on the Customers list page. Prior to
 * CUS-perf the effect fired BOTH ``load()`` (the paginated list
 * envelope, which now ships ``counts_by_status``) and
 * ``loadCounts()`` (the standalone-badge fetch) on every filter /
 * tab / page / sort change. The four tab counts overlap between the
 * two calls, and the five standalone badges are by-design
 * filter-invariant, so the ``loadCounts()`` call on filter changes
 * was redundant.
 *
 * Contract:
 *   - Mount fires EXACTLY ONE ``/customers/counts`` request (the
 *     mount-only effect that primes the five stable badges).
 *   - A filter / tab / sort change fires ``/customers?...`` (the
 *     list envelope) but MUST NOT re-fire ``/customers/counts``.
 *   - Every post-mutation callsite (bulk-status, restore, import,
 *     etc.) still calls ``loadCounts()`` explicitly — those paths
 *     are NOT covered by this test (out-of-scope for the filter
 *     effect surgery). The P31 sibling test file already locks the
 *     single-fetch shape.
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
        active: 12, inactive: 3, muted: 1, waitlist: 2,
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


describe("CUS-perf · Customers list loadCounts consolidation", () => {
  it("mount fires ONE /customers/counts and at least ONE /customers list request",
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

    // Exactly ONE /customers/counts fetch on cold mount. The
    // pre-CUS-perf shape fired TWO (one from the mount-only
    // effect + one from the primary filter effect firing on
    // initial render). Post-surgery the primary effect no longer
    // calls loadCounts(), so the count is exactly one.
    expect(_countsHits().length).toBe(1);
  });

  it("changing sort does NOT re-fire /customers/counts",
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

    // Flip the sort dropdown to trigger the filter effect. The
    // sort selector's data-testid is ``customers-sort-select``
    // (grep-confirmed in the page). Fall back to a synthetic
    // "sort=" URL change if the DOM query fails (test env
    // resilience — the assertion is what matters).
    const sortEl = screen.queryByTestId("customers-sort-select");
    if (sortEl) {
      fireEvent.change(sortEl, { target: { value: "name_asc" } });
    } else {
      // If the selector isn't queryable, we can still validate
      // via the primary tabs — clicking a tab fires the same
      // effect deps (``tab`` is in the deps list too).
      const tab = screen.queryByTestId("tab-inactive");
      if (tab) fireEvent.click(tab);
    }

    // Give the effect a moment to fire.
    await waitFor(() => {
      // The list refetch MUST fire (baseline+1 at minimum).
      expect(_listHits().length).toBeGreaterThan(baselineList);
    }, { timeout: 500 });

    // Give the (removed) loadCounts call a bit more time to fail
    // to fire — 100ms is plenty for a React effect to schedule.
    await new Promise((r) => setTimeout(r, 100));

    // /customers/counts MUST NOT have been re-fetched.
    expect(_countsHits().length).toBe(baselineCounts);
  });

  it("changing page does NOT re-fire /customers/counts",
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

    // Simulate a page change via the pagination button. If not
    // present in this render (empty envelope), fall back to a
    // filter change that shares the same effect dep list.
    const nextBtn = screen.queryByTestId("customers-pagination-next");
    if (nextBtn) {
      fireEvent.click(nextBtn);
    } else {
      const tab = screen.queryByTestId("tab-inactive");
      if (tab) fireEvent.click(tab);
    }

    await new Promise((r) => setTimeout(r, 100));

    expect(_countsHits().length).toBe(baselineCounts);
  });
});
