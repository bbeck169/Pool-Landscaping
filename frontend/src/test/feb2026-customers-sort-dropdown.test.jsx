/**
 * Feb-2026 · Customers list — Sort dropdown (Newest → Oldest default).
 *
 * Contract:
 *   1. A ``data-testid="customers-filter-sort"`` <select> is rendered
 *      on the filter row.
 *   2. Options exist for ``created_desc`` (Newest → Oldest) and
 *      ``created_asc`` (Oldest → Newest); ``created_desc`` is the
 *      default when no localStorage entry exists.
 *   3. Changing the dropdown fires a new ``api.get('/customers?...'
 *      &sort=<value>')`` call with the chosen value.
 *   4. Sort choice is persisted to ``localStorage['customers.sortBy']``
 *      on change and read back on next mount.
 *   5. Unknown persisted values fall back to the default.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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


// Minimal router — routes tag/count/list GETs so the page can render.
function _installRouter() {
  mockGet.mockImplementation((path) => {
    if (path.startsWith("/customer-tags")) {
      return Promise.resolve({ items: [] });
    }
    if (path.includes("count_only=true")) {
      return Promise.resolve({ count: 3 });
    }
    return Promise.resolve({
      items: [
        { id: "c-1", name: "Alpha Customer", is_active: true },
        { id: "c-2", name: "Bravo Customer", is_active: true },
      ],
      total: 2,
      page: 1,
      page_size: 100,
      total_pages: 1,
    });
  });
}


beforeEach(() => {
  mockGet.mockClear();
  try { localStorage.clear(); } catch { /* jsdom */ }
});


describe("CustomersList · Sort dropdown (Newest → Oldest default)", () => {
  it("renders the sort dropdown with the two options + created_desc default", async () => {
    _installRouter();
    _mount("admin");
    const sel = await waitFor(() =>
      screen.getByTestId("customers-filter-sort"));
    // Default value.
    expect(sel.value).toBe("created_desc");
    // Both options present with the product-spec labels.
    const options = Array.from(sel.querySelectorAll("option"));
    const values = options.map((o) => o.value);
    const labels = options.map((o) => o.textContent);
    expect(values).toContain("created_desc");
    expect(values).toContain("created_asc");
    expect(labels).toContain("Newest → Oldest");
    expect(labels).toContain("Oldest → Newest");
  });

  it("initial /customers fetch includes sort=created_desc", async () => {
    _installRouter();
    _mount("admin");
    await waitFor(() => {
      const paths = mockGet.mock.calls.map((c) => c[0]);
      expect(
        paths.some((p) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("sort=created_desc")
          && !p.includes("count_only=true")),
      ).toBe(true);
    });
  });

  it("changing the dropdown to Oldest → Newest triggers a fetch with sort=created_asc", async () => {
    _installRouter();
    _mount("admin");
    await waitFor(() =>
      expect(screen.getByTestId("customers-filter-sort")).toBeTruthy());
    mockGet.mockClear();
    fireEvent.change(screen.getByTestId("customers-filter-sort"),
      { target: { value: "created_asc" } });
    await waitFor(() => {
      const paths = mockGet.mock.calls.map((c) => c[0]);
      expect(
        paths.some((p) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("sort=created_asc")
          && !p.includes("count_only=true")),
      ).toBe(true);
    });
  });

  it("persists the chosen sort to localStorage under customers.sortBy", async () => {
    _installRouter();
    _mount("admin");
    await waitFor(() =>
      expect(screen.getByTestId("customers-filter-sort")).toBeTruthy());
    fireEvent.change(screen.getByTestId("customers-filter-sort"),
      { target: { value: "created_asc" } });
    // Effect fires synchronously in the microtask queue.
    await waitFor(() =>
      expect(localStorage.getItem("customers.sortBy")).toBe("created_asc"));
  });

  it("hydrates the sort from localStorage on next mount", async () => {
    localStorage.setItem("customers.sortBy", "created_asc");
    _installRouter();
    _mount("admin");
    const sel = await waitFor(() =>
      screen.getByTestId("customers-filter-sort"));
    expect(sel.value).toBe("created_asc");
    // And the initial /customers fetch reflects the hydrated value.
    await waitFor(() => {
      const paths = mockGet.mock.calls.map((c) => c[0]);
      expect(
        paths.some((p) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("sort=created_asc")),
      ).toBe(true);
    });
  });

  it("falls back to created_desc when localStorage holds an unknown value", async () => {
    localStorage.setItem("customers.sortBy", "garbage_value");
    _installRouter();
    _mount("admin");
    const sel = await waitFor(() =>
      screen.getByTestId("customers-filter-sort"));
    expect(sel.value).toBe("created_desc");
  });

  it("changing the sort resets pagination to page=1 (mirrors other filter changes)", async () => {
    // Router — page 1 returns 250 total so a pager exists. Items
    // must be non-empty on every page so the EmptyState branch
    // doesn't hide the pager (see CustomersList.jsx render).
    mockGet.mockImplementation((path) => {
      if (path.startsWith("/customer-tags"))
        return Promise.resolve({ items: [] });
      if (path.includes("count_only=true"))
        return Promise.resolve({ count: 250 });
      const url = new URL("http://x" + path);
      const p = parseInt(url.searchParams.get("page") || "1", 10) || 1;
      const items = Array.from({ length: 50 }, (_, i) => ({
        id: `c-p${p}-${i}`, name: `Customer ${p}.${i}`, is_active: true,
      }));
      return Promise.resolve({
        items, total: 250, page: p, page_size: 100, total_pages: 3,
      });
    });
    _mount("admin");
    await waitFor(() =>
      expect(screen.getByTestId("customers-pager-top")).toBeTruthy());
    // Advance to page 3.
    fireEvent.click(screen.getByTestId("customers-pager-top-page-3"));
    await waitFor(() => {
      const paths = mockGet.mock.calls.map((c) => c[0]);
      expect(paths.some((p) => typeof p === "string" && p.includes("page=3"))).toBe(true);
    });
    mockGet.mockClear();
    // Now switch the sort — should re-fetch with page=1.
    fireEvent.change(screen.getByTestId("customers-filter-sort"),
      { target: { value: "created_asc" } });
    await waitFor(() => {
      const paths = mockGet.mock.calls.map((c) => c[0]);
      expect(
        paths.some((p) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("page=1")
          && p.includes("sort=created_asc")
          && !p.includes("count_only=true")),
      ).toBe(true);
    });
  });
});
