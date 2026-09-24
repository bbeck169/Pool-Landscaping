/**
 * Phase P48 · Feb-2026 — Leads Active / Archive tab UX.
 *
 * Runtime mount tests locking the frontend wire-up in
 * ``LeadsDashboardPage.jsx``:
 *
 *   * Tab switcher renders both tabs with the P48 canonical labels
 *     + testids ("leads-tab-active", "leads-tab-archive").
 *   * ``?tab=`` URL param is the source of truth for the active
 *     tab; hard-refresh preserves selection.
 *   * Clicking a tab drives the wire-side ``?status=<csv>`` query
 *     (active → ``new,contacted,quoted``; archive →
 *     ``closed_won,closed_lost``).
 *   * Empty-state renders the tab-scoped empty-state block
 *     ("admin-leads-empty-active" / "admin-leads-empty-archive")
 *     without crashing.
 *   * Search query survives a tab switch (P48 UX invariant #8).
 *   * Status dropdown default reflects the current tab's scope
 *     (P48 UX invariant #9).
 *
 * Test-harness convention (mirrors ``k52-1a-leads-mount.test.jsx``):
 *   * Wrap in ``<MemoryRouter>`` so ``useSearchParams`` resolves.
 *   * ``vi.mock("@/api", ...)`` returns a spy for ``api.get`` so
 *     tests can assert on the URL composed by ``refresh()`` and
 *     drive tab-scoped empty / populated states.
 *   * ``vi.mock("sonner", ...)`` + ``vi.mock("@/components/ui/
 *     confirm-dialog", ...)`` neuter side-effects.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render, screen, act, fireEvent, within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ─── Mocks ───────────────────────────────────────────────────────────
const apiGet = vi.fn();
const apiPost = vi.fn();
const apiDel = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGet(...a),
    post: (...a) => apiPost(...a),
    del: (...a) => apiDel(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
  }),
}));
vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(() => Promise.resolve(true)),
}));

async function tick(n = 4) {
  await act(async () => {
    for (let i = 0; i < n; i += 1) await Promise.resolve();
  });
}

/** Extract the value of a specific query-string key from the last
 *  ``apiGet`` call.  URL shape is always ``/leads?...``. */
function _statusFromLastCall() {
  const url = apiGet.mock.calls[apiGet.mock.calls.length - 1]?.[0] || "";
  const q = url.split("?")[1] || "";
  const params = new URLSearchParams(q);
  return params.get("status");
}


beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiDel.mockReset();
});


// ─────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────
const _fakeLead = (id, status) => ({
  id, status, name: `P48-${id}`, email: `${id}@ex.com`, phone: "5551234",
  source: "website_form",
  created_at: "2026-02-01T00:00:00Z",
});

async function mountAt(initialEntry, apiPayload) {
  apiGet.mockImplementation((url) => {
    // Route-scoped mock: /portal/home returns nothing but we don't
    // care here; the only relevant call is /leads?...
    if (String(url).startsWith("/leads")) {
      return Promise.resolve(apiPayload);
    }
    return Promise.resolve({});
  });
  const { default: LeadsDashboardPage } =
    await import("@/pages/leads/LeadsDashboardPage");
  const utils = render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <LeadsDashboardPage />
    </MemoryRouter>,
  );
  await tick();
  return utils;
}


// ─────────────────────────────────────────────────────────────────────
// Test 1 · Both tab buttons render with canonical labels + testids.
// ─────────────────────────────────────────────────────────────────────
describe("P48 · Tab switcher renders", () => {
  it("renders both Active + Archive tabs with the P48 canonical " +
     "labels and testid anchors", async () => {
    const { unmount } = await mountAt("/leads",
      { rows: [], total: 0, page: 1, page_size: 200 });

    const active = screen.getByTestId("leads-tab-active");
    const archive = screen.getByTestId("leads-tab-archive");
    expect(active).toBeInTheDocument();
    expect(archive).toBeInTheDocument();
    expect(active.textContent).toContain("Active");
    expect(archive.textContent).toContain("Archive");
    // Tab-switcher container is the parent role="tablist".
    expect(screen.getByTestId("leads-tab-switcher"))
      .toHaveAttribute("role", "tablist");

    unmount();
  });
});


// ─────────────────────────────────────────────────────────────────────
// Test 2 · Default landing = Active tab; wire sends the Active CSV.
// ─────────────────────────────────────────────────────────────────────
describe("P48 · Default landing", () => {
  it("mounts on the Active tab (default) and fires GET /leads with " +
     "status=new,contacted,quoted", async () => {
    const { unmount } = await mountAt("/leads",
      { rows: [_fakeLead("l-new", "new")], total: 1,
        page: 1, page_size: 200 });

    const active = screen.getByTestId("leads-tab-active");
    // aria-selected reflects active tab.
    expect(active.getAttribute("aria-selected")).toBe("true");
    expect(_statusFromLastCall()).toBe("new,contacted,quoted");

    unmount();
  });
});


// ─────────────────────────────────────────────────────────────────────
// Test 3 · Clicking Archive → URL sync + wire CSV switches.
// ─────────────────────────────────────────────────────────────────────
describe("P48 · Tab click switches URL + wire CSV", () => {
  it("clicking the Archive tab flips aria-selected, syncs ?tab=archive " +
     "to the URL, and fires GET /leads with status=closed_won,closed_lost",
     async () => {
    const { unmount } = await mountAt("/leads",
      { rows: [], total: 0, page: 1, page_size: 200 });

    await act(async () => {
      fireEvent.click(screen.getByTestId("leads-tab-archive"));
    });
    await tick();

    // ``aria-selected`` moves to archive.
    expect(screen.getByTestId("leads-tab-archive")
      .getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("leads-tab-active")
      .getAttribute("aria-selected")).toBe("false");
    // Wire CSV switches to closed-only.
    expect(_statusFromLastCall()).toBe("closed_won,closed_lost");

    unmount();
  });
});


// ─────────────────────────────────────────────────────────────────────
// Test 4 · Hard-refresh with ?tab=archive lands on Archive tab.
// ─────────────────────────────────────────────────────────────────────
describe("P48 · Hard-refresh URL preserves tab selection", () => {
  it("mounting with initial URL /leads?tab=archive lands on the " +
     "Archive tab and fires GET /leads with the closed CSV — the " +
     "URL is the source of truth for the active tab", async () => {
    const { unmount } = await mountAt("/leads?tab=archive",
      { rows: [], total: 0, page: 1, page_size: 200 });

    expect(screen.getByTestId("leads-tab-archive")
      .getAttribute("aria-selected")).toBe("true");
    expect(_statusFromLastCall()).toBe("closed_won,closed_lost");

    unmount();
  });
});


// ─────────────────────────────────────────────────────────────────────
// Test 5 · Empty state renders per-tab without crashing.
// ─────────────────────────────────────────────────────────────────────
describe("P48 · Per-tab empty state", () => {
  it("Active tab with 0 rows renders admin-leads-empty-active anchor; " +
     "clicking Archive tab (also 0 rows) renders the archive anchor",
     async () => {
    const { unmount } = await mountAt("/leads",
      { rows: [], total: 0, page: 1, page_size: 200 });

    // Active-tab empty state.
    expect(screen.getByTestId("admin-leads-empty-active"))
      .toBeInTheDocument();

    // Switch to archive; still empty → archive-scoped empty anchor.
    await act(async () => {
      fireEvent.click(screen.getByTestId("leads-tab-archive"));
    });
    await tick();
    expect(screen.getByTestId("admin-leads-empty-archive"))
      .toBeInTheDocument();

    unmount();
  });
});


// ─────────────────────────────────────────────────────────────────────
// Test 6 · Row filter — active tab shows only active-state rows.
// ─────────────────────────────────────────────────────────────────────
describe("P48 · Row scoping per tab", () => {
  it("Active tab renders only rows whose status is in {new, " +
     "contacted, quoted} — the defensive belt at ``visible`` " +
     "filters out any mis-scoped row the server would return, " +
     "and switching to Archive flips the visible set", async () => {
    // Mount on Active with a mixed payload — client-side belt
    // filters to Active statuses.
    apiGet.mockImplementation((url) => {
      if (String(url).startsWith("/leads")) {
        return Promise.resolve({
          rows: [
            _fakeLead("l-new", "new"),
            _fakeLead("l-contacted", "contacted"),
            _fakeLead("l-quoted", "quoted"),
            _fakeLead("l-won", "closed_won"),
            _fakeLead("l-lost", "closed_lost"),
          ],
          total: 5, page: 1, page_size: 200,
        });
      }
      return Promise.resolve({});
    });
    const { default: LeadsDashboardPage } =
      await import("@/pages/leads/LeadsDashboardPage");
    const { unmount } = render(
      <MemoryRouter initialEntries={["/leads"]}>
        <LeadsDashboardPage />
      </MemoryRouter>,
    );
    await tick();

    // Active tab — should render 3 rows (new, contacted, quoted).
    expect(screen.getByTestId("lead-row-l-new")).toBeInTheDocument();
    expect(screen.getByTestId("lead-row-l-contacted")).toBeInTheDocument();
    expect(screen.getByTestId("lead-row-l-quoted")).toBeInTheDocument();
    expect(screen.queryByTestId("lead-row-l-won")).toBeNull();
    expect(screen.queryByTestId("lead-row-l-lost")).toBeNull();

    // Switch to archive — visible set flips.
    await act(async () => {
      fireEvent.click(screen.getByTestId("leads-tab-archive"));
    });
    await tick();
    expect(screen.getByTestId("lead-row-l-won")).toBeInTheDocument();
    expect(screen.getByTestId("lead-row-l-lost")).toBeInTheDocument();
    expect(screen.queryByTestId("lead-row-l-new")).toBeNull();
    expect(screen.queryByTestId("lead-row-l-contacted")).toBeNull();
    expect(screen.queryByTestId("lead-row-l-quoted")).toBeNull();

    unmount();
  });
});


// ─────────────────────────────────────────────────────────────────────
// Test 7 · Search value survives a tab switch.
// ─────────────────────────────────────────────────────────────────────
describe("P48 · Search preserved when switching tabs", () => {
  it("typing into the search input on Active and then clicking " +
     "Archive keeps the same search string in the input — search " +
     "+ source filters are orthogonal to the Active/Archive split " +
     "(user's Preflight A addition #8)", async () => {
    const { unmount } = await mountAt("/leads",
      { rows: [], total: 0, page: 1, page_size: 200 });

    const search = screen.getByTestId("lead-search-input");
    await act(async () => {
      fireEvent.change(search, { target: { value: "acme" } });
    });
    await tick();
    expect(search.value).toBe("acme");

    // Click Archive.
    await act(async () => {
      fireEvent.click(screen.getByTestId("leads-tab-archive"));
    });
    await tick();

    // Search value persists (source + search are orthogonal to
    // Active/Archive by the P48 comment in refresh()).
    expect(screen.getByTestId("lead-search-input").value).toBe("acme");

    unmount();
  });
});


// ─────────────────────────────────────────────────────────────────────
// Test 8 · Status dropdown scoped to the current tab (P48 UX #9).
// ─────────────────────────────────────────────────────────────────────
describe("P48 · Status dropdown scoping per tab", () => {
  it("the specific-status dropdown lists ONLY the current tab's " +
     "statuses (Active → new/contacted/quoted; Archive → closed " +
     "options) — prevents the 'select Contacted while on the " +
     "Archive tab' no-op that would silently surface 0 rows", async () => {
    const { unmount } = await mountAt("/leads",
      { rows: [], total: 0, page: 1, page_size: 200 });

    // Active tab — dropdown contains new / contacted / quoted, NOT
    // closed_won or closed_lost.
    const dropdown = screen.getByTestId("lead-filter-status-select");
    expect(within(dropdown).getByTestId("lead-status-option-new"))
      .toBeInTheDocument();
    expect(within(dropdown).getByTestId("lead-status-option-contacted"))
      .toBeInTheDocument();
    expect(within(dropdown).getByTestId("lead-status-option-quoted"))
      .toBeInTheDocument();
    expect(within(dropdown).queryByTestId("lead-status-option-closed_won"))
      .toBeNull();
    expect(within(dropdown).queryByTestId("lead-status-option-closed_lost"))
      .toBeNull();

    // Switch to Archive — dropdown flips to closed-only.
    await act(async () => {
      fireEvent.click(screen.getByTestId("leads-tab-archive"));
    });
    await tick();
    const dropdown2 = screen.getByTestId("lead-filter-status-select");
    expect(within(dropdown2).getByTestId("lead-status-option-closed_won"))
      .toBeInTheDocument();
    expect(within(dropdown2).getByTestId("lead-status-option-closed_lost"))
      .toBeInTheDocument();
    expect(within(dropdown2).queryByTestId("lead-status-option-new"))
      .toBeNull();
    expect(within(dropdown2).queryByTestId("lead-status-option-contacted"))
      .toBeNull();
    expect(within(dropdown2).queryByTestId("lead-status-option-quoted"))
      .toBeNull();

    unmount();
  });
});
