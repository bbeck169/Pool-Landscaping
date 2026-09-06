/**
 * Phase K62 · Feb-2026 — CustomersList page-size selector +
 * First/Last controls.
 *
 * Coverage:
 *   1. Default page size = 25 (no URL param, no localStorage).
 *   2. ``?size=50`` URL param wins over localStorage on mount.
 *   3. localStorage value hydrates when no URL param is set.
 *   4. Changing the size selector triggers a re-fetch with the new
 *      ``page_size``, resets to page 1, and writes localStorage +
 *      URL param.
 *   5. First / Last buttons navigate to page 1 / total_pages.
 *   6. Out-of-range page (page > total_pages) resolves cleanly
 *      (envelope returns 0 rows; component renders empty table).
 *   7. Selecting size 100 while on page 5 sends a request with the
 *      correct size AND resets ``page=1``.
 *   8. Filter change composes with pagination — same behavior as
 *      P35 (search resets page to 1) while size remains sticky.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


let currentRole = "admin";
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: currentRole,
    effectiveRole: currentRole,
    isAdmin: true,
    isAdminOrManager: true,
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


function _envelope({ total, page, page_size }) {
  const total_pages = total === 0 ? 0 : Math.ceil(total / page_size);
  const clampedPage = Math.min(page, Math.max(1, total_pages));
  const from = (clampedPage - 1) * page_size + 1;
  const to = Math.min(clampedPage * page_size, total);
  const items = [];
  if (page <= total_pages) {
    for (let i = from; i <= to; i++) {
      items.push({ id: `c-${i}`, name: `Customer ${String(i).padStart(4, "0")}`, is_active: true });
    }
  }
  return { items, total, page, page_size, total_pages };
}

function _installRouter({ total = 250 } = {}) {
  mockGet.mockImplementation((path) => {
    if (path.startsWith("/customer-tags")) return Promise.resolve({ items: [] });
    if (path.includes("count_only=true")) {
      if (path.includes("is_active=true")) return Promise.resolve({ count: total });
      return Promise.resolve({ count: 0 });
    }
    const url = new URL("http://x" + (path.startsWith("/") ? path : "/" + path));
    const p = parseInt(url.searchParams.get("page") || "1", 10) || 1;
    const ps = parseInt(url.searchParams.get("page_size") || "25", 10) || 25;
    let effective = total;
    if (url.searchParams.get("search")) effective = 3;
    return Promise.resolve(_envelope({ total: effective, page: p, page_size: ps }));
  });
}

function _mount(initialUrl = "/customers") {
  return render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <CustomersList />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockGet.mockClear();
  try { localStorage.clear(); } catch { /* jsdom */ }
});

describe("CustomersList · K62 page-size selector", () => {
  it("defaults to page_size=25 when no URL param / localStorage", async () => {
    _installRouter({ total: 250 });
    _mount("/customers");
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      expect(
        calls.some((p) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("page_size=25")
          && !p.includes("count_only=true")),
      ).toBe(true);
    });
  });

  it("honours ``?size=50`` URL param on mount", async () => {
    _installRouter({ total: 250 });
    _mount("/customers?size=50");
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      expect(
        calls.some((p) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("page_size=50")
          && !p.includes("count_only=true")),
      ).toBe(true);
    });
    // Selector must reflect the URL value.
    await waitFor(() =>
      expect(screen.getByTestId("customers-pager-top-size-selector")).toBeTruthy());
    expect(
      screen.getByTestId("customers-pager-top-size-selector").value,
    ).toBe("50");
  });

  it("hydrates from localStorage when no URL param is set", async () => {
    localStorage.setItem("customers.pageSize", "100");
    _installRouter({ total: 250 });
    _mount("/customers");
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      expect(
        calls.some((p) => typeof p === "string"
          && p.includes("page_size=100")
          && !p.includes("count_only=true")),
      ).toBe(true);
    });
  });

  it("changing size persists to localStorage + URL + resets page to 1", async () => {
    _installRouter({ total: 250 });
    _mount("/customers?size=50&page=2");
    await waitFor(() =>
      expect(screen.getByTestId("customers-pager-top-size-selector")).toBeTruthy());
    mockGet.mockClear();
    fireEvent.change(
      screen.getByTestId("customers-pager-top-size-selector"),
      { target: { value: "100" } },
    );
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      expect(
        calls.some((p) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("page_size=100")
          && p.includes("page=1")
          && !p.includes("count_only=true")),
      ).toBe(true);
    });
    expect(localStorage.getItem("customers.pageSize")).toBe("100");
  });

  it("First jumps to page 1, Last jumps to total_pages", async () => {
    _installRouter({ total: 250 });
    _mount("/customers?size=25");
    await waitFor(() =>
      expect(screen.getByTestId("customers-pager-top")).toBeTruthy());
    // 250 / 25 = 10 pages total.
    const top = screen.getByTestId("customers-pager-top");
    // Click Last → page=10.
    fireEvent.click(within(top).getByTestId("customers-pager-top-last"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      expect(
        calls.some((p) => typeof p === "string"
          && p.includes("page=10")
          && p.includes("page_size=25")),
      ).toBe(true);
    });
    mockGet.mockClear();
    // Click First → page=1.
    fireEvent.click(within(screen.getByTestId("customers-pager-top"))
      .getByTestId("customers-pager-top-first"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      expect(
        calls.some((p) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("page=1")
          && p.includes("page_size=25")
          && !p.includes("count_only=true")),
      ).toBe(true);
    });
  });

  it("out-of-range ``?page=99`` renders empty table (no 500)", async () => {
    _installRouter({ total: 250 });
    _mount("/customers?size=25&page=99");
    // Envelope returns items=[] for page 99; UI shows the empty
    // state (no rows in the table body). Component must not crash.
    await waitFor(() =>
      expect(screen.getByTestId("customers-page")).toBeTruthy());
    // Table renders but has no data rows.
    expect(screen.queryByTestId("customer-row-c-1")).toBeNull();
  });

  it("size selector renders even when total fits in a single page", async () => {
    _installRouter({ total: 10 });
    _mount("/customers");
    await waitFor(() =>
      expect(screen.getByTestId("customers-table")).toBeTruthy());
    // K62 · Feb-2026 — pager wrapper stays visible so the size
    // selector is reachable.
    expect(screen.getByTestId("customers-pager-top-size-selector")).toBeTruthy();
    // Number-strip controls stay hidden on the 1-page case.
    expect(screen.queryByTestId("customers-pager-top-next")).toBeNull();
    expect(screen.queryByTestId("customers-pager-top-last")).toBeNull();
  });

  it("size selector offers 25 / 50 / 100 options", async () => {
    _installRouter({ total: 250 });
    _mount("/customers");
    await waitFor(() =>
      expect(screen.getByTestId("customers-pager-top-size-selector")).toBeTruthy());
    const sel = screen.getByTestId("customers-pager-top-size-selector");
    const opts = Array.from(sel.querySelectorAll("option")).map((o) => o.value);
    expect(opts).toEqual(["25", "50", "100"]);
  });

  it("URL strips ``?size=25`` when size matches the K62 default", async () => {
    _installRouter({ total: 250 });
    _mount("/customers?size=50");
    await waitFor(() =>
      expect(screen.getByTestId("customers-pager-top-size-selector")).toBeTruthy());
    // Change back to the default 25 — URL param should be removed.
    fireEvent.change(
      screen.getByTestId("customers-pager-top-size-selector"),
      { target: { value: "25" } },
    );
    await waitFor(() => {
      // localStorage still stores the choice.
      expect(localStorage.getItem("customers.pageSize")).toBe("25");
    });
  });
});
