/**
 * QV-ui · Feb-2026 — QuotesList Viewed column tests.
 *
 * Coverage:
 *   1  Renders "Viewed" column header between Amount and Status.
 *   2  Shows Lucide <Eye> icon + relative time for a viewed quote.
 *   3  Shows count suffix "(3×)" when view_count > 1.
 *   4  Shows "—" empty state for a never-viewed quote.
 *   5  Cell + count-span testids follow the ``quote-*`` convention.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ── Shared mocks ─────────────────────────────────────────────
const _apiGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...args) => _apiGet(...args),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
    del: vi.fn(() => Promise.resolve({})),
  },
  TOKEN_KEY: "token",
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { role: "admin", id: "u-1" },
    role: "admin",
    loading: false,
  }),
}));

vi.mock("sonner", () => ({
  toast: { success: () => {}, error: () => {}, info: () => {} },
}));


// Reference dataset — 3 quotes:
//   q1 viewed 5 minutes ago (single view)
//   q2 viewed 2 hours ago (3 times total)
//   q3 never viewed
const NOW = Date.now();
const _iso = (msAgo) => new Date(NOW - msAgo).toISOString();
const FIXTURES = [
  {
    id: "q-viewed-once",
    title: "Weekly pool service quote",
    total: 1200,
    status: "sent",
    customer_id: "c-1", customer_name: "Diego",
    first_viewed_at: _iso(5 * 60 * 1000),
    last_viewed_at:  _iso(5 * 60 * 1000),
    view_count: 1,
  },
  {
    id: "q-viewed-thrice",
    title: "Landscape refresh estimate",
    total: 4750,
    status: "viewed",
    customer_id: "c-2", customer_name: "Maria",
    first_viewed_at: _iso(6 * 60 * 60 * 1000),
    last_viewed_at:  _iso(2 * 60 * 60 * 1000),
    view_count: 3,
  },
  {
    id: "q-never-viewed",
    title: "Salt-cell replacement quote",
    total: 850,
    status: "draft",
    customer_id: "c-3", customer_name: "Sam",
  },
];


beforeEach(() => {
  _apiGet.mockReset();
  _apiGet.mockImplementation((path) => {
    // QuotesList calls ``/quotes?doc_type=quote`` on mount +
    // ``CustomerFilterBar`` hits ``/customers``. Match by prefix
    // so query-string variants don't fall through to the hang.
    const p = typeof path === "string" ? path : "";
    if (p.startsWith("/quotes")) return Promise.resolve(FIXTURES);
    if (p.startsWith("/customers")) return Promise.resolve([]);
    return Promise.resolve([]);
  });
  window.localStorage?.clear?.();
});
afterEach(() => {
  cleanup();
});


async function _mountList() {
  const mod = await import("@/pages/quotes/QuotesList");
  const ListPage = mod.default;
  return render(
    <MemoryRouter>
      <ListPage />
    </MemoryRouter>,
  );
}


// ═════════════════════════════════════════════════════════════════
// 1 · Column header renders between Amount and Status
// ═════════════════════════════════════════════════════════════════
describe("QuotesList · Viewed column header position", () => {
  it("Viewed header sits between Amount and Status", async () => {
    const { container } = await _mountList();
    await waitFor(() => {
      expect(container.querySelector("table")).toBeTruthy();
    });
    const headers = Array.from(
      container.querySelectorAll("thead th"),
    ).map((h) => h.textContent.trim());
    const amountIdx = headers.indexOf("Amount");
    const viewedIdx = headers.indexOf("Viewed");
    const statusIdx = headers.indexOf("Status");
    expect(amountIdx).toBeGreaterThanOrEqual(0);
    expect(viewedIdx).toBeGreaterThan(amountIdx);
    expect(statusIdx).toBeGreaterThan(viewedIdx);
  });
});


// ═════════════════════════════════════════════════════════════════
// 2 · Viewed quote — Lucide <Eye> + relative time
// ═════════════════════════════════════════════════════════════════
describe("QuotesList · Viewed cell renders Eye icon + relative time", () => {
  it("renders <Eye> icon (lucide, NOT emoji) + '{N}m ago' for a viewed quote", async () => {
    await _mountList();
    const cell = await screen.findByTestId("quote-viewed-q-viewed-once");
    // Byte-parity check — must NOT contain the legacy 👁 emoji.
    expect(cell.textContent).not.toContain("\u{1F441}");
    // Lucide renders <svg> with lucide-eye class.
    const svg = cell.querySelector("svg");
    expect(svg).toBeTruthy();
    // Relative time format assertion — text contains "Nm ago" or
    // "0s..59s ago" depending on CI timing but MUST end with " ago".
    expect(cell.textContent).toMatch(/(\d+[smhd]|mo) ago/);
  });
});


// ═════════════════════════════════════════════════════════════════
// 3 · view_count > 1 renders "(N×)" suffix
// ═════════════════════════════════════════════════════════════════
describe("QuotesList · view_count suffix", () => {
  it("renders '(3×)' when view_count is 3", async () => {
    await _mountList();
    const countSpan = await screen.findByTestId(
      "quote-view-count-q-viewed-thrice",
    );
    expect(countSpan.textContent).toMatch(/\(\s*3\s*×\s*\)/);
  });

  it("does NOT render the count span when view_count is 1", async () => {
    await _mountList();
    // Cell is present for a once-viewed quote…
    await screen.findByTestId("quote-viewed-q-viewed-once");
    // …but the count span is not rendered.
    expect(
      screen.queryByTestId("quote-view-count-q-viewed-once"),
    ).toBeNull();
  });
});


// ═════════════════════════════════════════════════════════════════
// 4 · Never-viewed quote → em-dash empty state
// ═════════════════════════════════════════════════════════════════
describe("QuotesList · never-viewed empty state", () => {
  it("renders '—' for a quote with no first_viewed_at", async () => {
    await _mountList();
    const cell = await screen.findByTestId("quote-viewed-q-never-viewed");
    expect(cell.textContent.trim()).toBe("—");
    // No <Eye> icon rendered on the empty state.
    expect(cell.querySelector("svg")).toBeNull();
  });
});
