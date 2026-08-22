/**
 * Feb-2026 · P35 — CustomersList pagination integration + pager UX.
 *
 * Coverage:
 *   1. Top + bottom pagers both render.
 *   2. Clicking Next on the top pager refetches with page=2.
 *   3. Ellipsis rendering — 14 pages, current=7 → 1 … 6 7 8 … 14.
 *   4. total_pages=1 → pager hidden.
 *   5. Changing tab resets page to 1 (URL param stripped).
 *   6. Filter change (search input) resets page to 1.
 *   7. "Showing X-Y of Z" label reflects current page correctly.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ── mocks ────────────────────────────────────────────────────────────
let currentRole = "admin";

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: currentRole,
    effectiveRole: currentRole,
    isAdmin: currentRole === "admin" || currentRole === "super_admin",
    isAdminOrManager:
      currentRole === "admin" || currentRole === "super_admin"
      || currentRole === "manager",
    canDo: () => true,
  }),
}));

const mockGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(), warning: vi.fn(),
  }),
}));


import CustomersList from "@/pages/customers/CustomersList";


function _mount(role = "admin") {
  currentRole = role;
  return render(
    <MemoryRouter initialEntries={["/customers"]}>
      <CustomersList />
    </MemoryRouter>,
  );
}


// Build a synthetic paginated envelope.
function _envelope({ total, page, page_size = 100 }) {
  const total_pages = total === 0 ? 0
    : Math.ceil(total / page_size);
  const from = (page - 1) * page_size + 1;
  const to = Math.min(page * page_size, total);
  const items = [];
  for (let i = from; i <= to; i++) {
    items.push({
      id: `c-${i}`, name: `Customer ${String(i).padStart(4, "0")}`,
      is_active: true,
    });
  }
  return { items, total, page, page_size, total_pages };
}


// Route calls by URL path so we can vary total across tests.
function _installRouter({ total = 250, mutedTotal = 4 } = {}) {
  mockGet.mockImplementation((path) => {
    if (path.startsWith("/customer-tags")) return Promise.resolve({ items: [] });
    if (path.includes("count_only=true")) {
      if (path.includes("is_muted=true")) return Promise.resolve({ count: mutedTotal });
      if (path.includes("is_active=true")) return Promise.resolve({ count: total });
      if (path.includes("is_active=false")) return Promise.resolve({ count: 0 });
      return Promise.resolve({ count: 0 });
    }
    // Parse the requested page.
    const url = new URL("http://x" + (path.startsWith("/") ? path : "/" + path));
    const p = parseInt(url.searchParams.get("page") || "1", 10) || 1;
    const ps = parseInt(url.searchParams.get("page_size") || "100", 10) || 100;
    // Vary result set per tab / search.
    let effective = total;
    if (url.searchParams.get("is_muted") === "true") effective = mutedTotal;
    if (url.searchParams.get("search")) effective = 3;
    return Promise.resolve(_envelope({ total: effective, page: p, page_size: ps }));
  });
}


beforeEach(() => {
  mockGet.mockClear();
});


describe("CustomersList · P35 pagination", () => {
  it("renders top AND bottom pagers", async () => {
    _installRouter({ total: 250 });
    _mount("admin");
    await waitFor(() =>
      expect(screen.getByTestId("customers-pager-top")).toBeTruthy());
    expect(screen.getByTestId("customers-pager-bottom")).toBeTruthy();
    // Both must include a page-2 button (total_pages=3).
    expect(within(screen.getByTestId("customers-pager-top"))
      .getByTestId("customers-pager-top-page-2")).toBeTruthy();
    expect(within(screen.getByTestId("customers-pager-bottom"))
      .getByTestId("customers-pager-bottom-page-2")).toBeTruthy();
  });

  it("clicking Next on the top pager fetches page=2", async () => {
    _installRouter({ total: 250 });
    _mount("admin");
    await waitFor(() =>
      expect(screen.getByTestId("customers-pager-top-next")).toBeTruthy());
    fireEvent.click(screen.getByTestId("customers-pager-top-next"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      expect(
        calls.some((p) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("page=2")
          && p.includes("page_size=100")
          && !p.includes("count_only=true")),
      ).toBe(true);
    });
  });

  it("condenses number strip with ellipsis when total_pages > 7", async () => {
    // 14 pages: seed router with total = 1400.
    _installRouter({ total: 1400 });
    _mount("admin");
    await waitFor(() =>
      expect(screen.getByTestId("customers-pager-top")).toBeTruthy());
    // Use the jump-input to hop to page 7 (page 7 is not in the
    // initial ``1 2 … 13 14`` strip).
    const jumpInput = screen.getAllByTestId("customers-pager-top-jump-input")[0];
    fireEvent.change(jumpInput, { target: { value: "7" } });
    fireEvent.submit(jumpInput.closest("form"));

    // The load() call unmounts the pager (skeleton) then re-mounts
    // it. Wait for the re-mount + aria-current=page marker.
    await waitFor(() => {
      const cur = screen.getByTestId("customers-pager-top-page-7");
      expect(cur.getAttribute("aria-current")).toBe("page");
    });
    const top = screen.getByTestId("customers-pager-top");
    // Adjacent window: pages 6, 7, 8 present; 3, 4, 5, 9, 10, 11, 12 absent.
    expect(within(top).getByTestId("customers-pager-top-page-6")).toBeTruthy();
    expect(within(top).getByTestId("customers-pager-top-page-8")).toBeTruthy();
    expect(within(top).queryByTestId("customers-pager-top-page-4")).toBeNull();
    expect(within(top).queryByTestId("customers-pager-top-page-10")).toBeNull();
    // Anchors present.
    expect(within(top).getByTestId("customers-pager-top-page-1")).toBeTruthy();
    expect(within(top).getByTestId("customers-pager-top-page-14")).toBeTruthy();
    // Two ellipsis markers (one each side of the window).
    const ellipses = within(top).queryAllByTestId(
      /customers-pager-top-ellipsis-\d+/);
    expect(ellipses.length).toBe(2);
  });

  it("hides both pagers when total_pages < 2", async () => {
    _installRouter({ total: 5 });
    _mount("admin");
    // Wait for the first fetch to settle so state is populated.
    await waitFor(() =>
      expect(screen.getByTestId("customers-table")).toBeTruthy());
    expect(screen.queryByTestId("customers-pager-top")).toBeNull();
    expect(screen.queryByTestId("customers-pager-bottom")).toBeNull();
  });

  it("changing tab resets page to 1", async () => {
    _installRouter({ total: 1400 });
    _mount("admin");
    await waitFor(() =>
      expect(screen.getByTestId("customers-pager-top")).toBeTruthy());
    // Jump to page 3 (14 pages total, so page 3 isn't in the number
    // strip — use the jump input instead).
    const jumpInput = screen.getAllByTestId("customers-pager-top-jump-input")[0];
    fireEvent.change(jumpInput, { target: { value: "3" } });
    fireEvent.submit(jumpInput.closest("form"));
    await waitFor(() => {
      const c = mockGet.mock.calls.map((x) => x[0]);
      expect(c.some((p) => typeof p === "string" && p.includes("page=3"))).toBe(true);
    });
    mockGet.mockClear();
    // Switch to Inactive tab. Filter effect should reset page → 1.
    fireEvent.click(screen.getByTestId("tab-inactive"));
    await waitFor(() => {
      const c = mockGet.mock.calls.map((x) => x[0]);
      // At least one fetch to /customers?... with page=1 for the new tab.
      expect(
        c.some((p) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("page=1")
          && p.includes("is_active=false")
          && !p.includes("count_only=true")),
      ).toBe(true);
    });
  });

  it("changing search input resets page to 1", async () => {
    _installRouter({ total: 1400 });
    _mount("admin");
    await waitFor(() =>
      expect(screen.getByTestId("customers-pager-top")).toBeTruthy());
    // Advance to page 5.
    const jumpInput = screen.getAllByTestId("customers-pager-top-jump-input")[0];
    fireEvent.change(jumpInput, { target: { value: "5" } });
    fireEvent.submit(jumpInput.closest("form"));
    await waitFor(() => {
      const c = mockGet.mock.calls.map((x) => x[0]);
      expect(c.some((p) => typeof p === "string" && p.includes("page=5"))).toBe(true);
    });
    mockGet.mockClear();

    // Type in the search box — debounced, so we wait ~350ms.
    fireEvent.change(screen.getByTestId("customers-search"),
      { target: { value: "Bravo" } });

    await waitFor(() => {
      const c = mockGet.mock.calls.map((x) => x[0]);
      expect(
        c.some((p) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("search=Bravo")
          && p.includes("page=1")
          && !p.includes("count_only=true")),
      ).toBe(true);
    }, { timeout: 2000 });
  });

  it("Showing X-Y of Z label reflects the current page", async () => {
    _installRouter({ total: 250 });
    _mount("admin");
    await waitFor(() =>
      expect(screen.getByTestId("customers-pager-top")).toBeTruthy());
    // Page 1 → Showing 1-100 of 250.
    let label = screen.getByTestId("customers-pager-top-showing-label");
    expect(label.textContent).toMatch(/Showing\s+1-100\s+of\s+250/);
    // Advance to page 3 → Showing 201-250 of 250.
    fireEvent.click(screen.getByTestId("customers-pager-top-page-3"));
    await waitFor(() => {
      label = screen.getByTestId("customers-pager-top-showing-label");
      expect(label.textContent).toMatch(/Showing\s+201-250\s+of\s+250/);
    });
  });
});
