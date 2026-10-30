/**
 * Feb-2026 · TD-80 follow-up (operator Q2=a) — PropertiesListPage
 * cap-hit footer + explicit ``limit=2000`` on the active-list fetch.
 *
 * Scope locked at 4 vitest cases per the operator dispatch:
 *   1. Fetches with `limit=2000` in the query string
 *   2. Footer renders when row count == limit (cap hit)
 *   3. Footer hidden when row count < limit (cap not hit)
 *   4. Footer copy includes the true active-accounts aggregator
 *      count when `/dashboard` returns it; falls back to the
 *      heuristic-only copy otherwise.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach,
} from "vitest";
import { MemoryRouter } from "react-router-dom";
import {
  render, screen, waitFor,
} from "@testing-library/react";


// ─── hoisted api mock ─────────────────────────────────────────────
const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));
vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: { get: (...a) => getSpy(...a), post: vi.fn() },
}));

// ─── shim heavy adjacent modules the test env doesn't need ────────
vi.mock("@/components/ui-kit", () => ({
  PageHeader: ({ title, subtitle }) => (
    <header>
      <h1>{title}</h1>
      {subtitle ? <div>{subtitle}</div> : null}
    </header>
  ),
  Chip: ({ children, ...rest }) => <span {...rest}>{children}</span>,
  Skeleton: ({ style }) => <div style={style} data-testid="skeleton" />,
  EmptyState: ({ title, description, children }) => (
    <div>
      <h2>{title}</h2>
      <p>{description}</p>
      {children}
    </div>
  ),
  Button: ({ children, ...rest }) => (
    <button type="button" {...rest}>{children}</button>
  ),
}));

vi.mock("@/theme", () => ({
  colors: {
    brandTertiary: "#fef3c7",
    textDim: "#78350f",
    muted: "#64748b",
    text: "#0f172a",
    border: "#e2e8f0",
    panel: "#ffffff",
    surface: "#ffffff",
    onSurface: "#0f172a",
    onSurfaceMuted: "#64748b",
  },
}));

// CustomerGroup is defined inline in PropertiesListPage.jsx — no
// module to mock. The real one renders a header + a row per
// property; it's cheap enough to let it run.

import PropertiesListPage from "../PropertiesListPage";


function _mkRow(i) {
  return {
    id: `prop-${i}`,
    customer_id: `cust-${(i % 25) + 1}`,
    label: `Property ${i}`,
    active: true,
    service_category: "pool",
    address: { line1: `${i} Pool Ln`, city: "Phoenix" },
  };
}


function _mkRows(n) {
  return Array.from({ length: n }).map((_, i) => _mkRow(i + 1));
}


function _route(initialPath = "/admin/properties") {
  return (
    <MemoryRouter initialEntries={[initialPath]}>
      <PropertiesListPage />
    </MemoryRouter>
  );
}


function _wireApi({ items, dashboard }) {
  getSpy.mockImplementation((path) => {
    if (path.startsWith("/properties")) {
      return Promise.resolve({ items, limit: 2000, offset: 0,
                               returned: items.length });
    }
    if (path === "/dashboard") {
      return dashboard !== undefined
        ? Promise.resolve(dashboard)
        : Promise.reject(new Error("no dashboard"));
    }
    if (path.startsWith("/customers")) {
      return Promise.resolve({ items: [] });
    }
    return Promise.reject(new Error(`unmocked GET ${path}`));
  });
}


describe("PropertiesListPage (TD-80 follow-up — cap-hit footer)", () => {
  beforeEach(() => {
    getSpy.mockReset();
  });

  // 1. Query-string carries the explicit limit=2000.
  it("1. fetches /properties with limit=2000 in the query string", async () => {
    _wireApi({ items: _mkRows(10) });
    render(_route());
    await waitFor(() => {
      const propCall = getSpy.mock.calls.find(
        (c) => typeof c[0] === "string" && c[0].startsWith("/properties"),
      );
      expect(propCall).toBeTruthy();
      expect(propCall[0]).toContain("limit=2000");
    });
  });

  // 2. Footer renders when row count == PROPERTIES_LIST_LIMIT (2000).
  it("2. renders cap-hit footer when returned rows fill the limit", async () => {
    _wireApi({
      items: _mkRows(2000),
      dashboard: { active_accounts_count: 2501 },
    });
    render(_route());
    await waitFor(() => {
      expect(screen.getByTestId("properties-list-cap-footer")).toBeTruthy();
    });
    const txt = screen.getByTestId("properties-list-cap-footer").textContent;
    expect(txt).toContain("Showing first 2,000");
    expect(txt).toContain("refine filters");
  });

  // 3. Footer hidden when row count < limit.
  it("3. does not render cap-hit footer when rows < limit", async () => {
    _wireApi({
      items: _mkRows(42),
      dashboard: { active_accounts_count: 42 },
    });
    render(_route());
    // Wait for the grouped list to render so we know the fetch
    // resolved; then assert the footer is absent.
    await waitFor(() => {
      expect(screen.getByTestId("properties-list-grouped")).toBeTruthy();
    });
    expect(screen.queryByTestId("properties-list-cap-footer")).toBeNull();
  });

  // 4. Footer copy includes the aggregator count when available;
  //    falls back to heuristic-only copy when /dashboard fails.
  it("4. footer copy uses aggregator count; falls back when /dashboard fails", async () => {
    // 4a — aggregator present and > limit → "of M" rendered.
    _wireApi({
      items: _mkRows(2000),
      dashboard: { active_accounts_count: 3147 },
    });
    const { unmount } = render(_route());
    await waitFor(() => {
      expect(screen.getByTestId("properties-list-cap-footer")).toBeTruthy();
    });
    expect(
      screen.getByTestId("properties-list-cap-footer").textContent,
    ).toContain("of 3,147");
    unmount();

    // 4b — aggregator fails to load → heuristic-only copy.
    getSpy.mockReset();
    _wireApi({ items: _mkRows(2000) /* dashboard omitted → rejects */ });
    render(_route());
    await waitFor(() => {
      expect(screen.getByTestId("properties-list-cap-footer")).toBeTruthy();
    });
    const txt2 = screen.getByTestId("properties-list-cap-footer").textContent;
    expect(txt2).toContain("Showing first 2,000");
    // No "of N" segment when aggregator is unknown.
    expect(txt2).not.toMatch(/of\s[\d,]+\sactive/);
  });
});
