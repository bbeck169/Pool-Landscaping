/**
 * Feb-2026 · Dashboard consistency ship — verify the relabeled copy
 * on the three revenue tiles (Total Paid Revenue lifetime + Revenue-
 * by-Category paid this-month + Income-by-Service-Category paid
 * this-month).
 *
 * Prior copy was ambiguous — "Total Revenue" vs "Revenue by Category"
 * looked comparable but wasn't (top card was lifetime-paid; per-
 * category tiles were current-month-all-statuses). This test locks
 * in the new copy so an accidental relabel back to the terse form
 * fails loudly.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";


// ─── Shared mocks — the tile components use several app hooks ────────
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));
vi.mock("@/api", () => ({
  api: { get: apiGetMock, post: vi.fn(), patch: vi.fn(), put: vi.fn(), del: vi.fn() },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u-admin", role: "admin", email: "a@x.co", name: "A" },
  }),
  AuthProvider: ({ children }) => <>{children}</>,
}));


beforeEach(() => {
  vi.clearAllMocks();
  // Neutral "no items" response so the tile renders a header + empty
  // state — we only care about the label copy.
  apiGetMock.mockResolvedValue({
    items: [], total: 0, currency: "USD",
    range: { start: "2026-02-01", end: "2026-02-28" },
  });
});


// ══════════════════════════════════════════════════════════════════════
// 1 · Revenue-by-Category tile — label reads "paid, this month".
// ══════════════════════════════════════════════════════════════════════
describe("RevenueByCategoryTile · relabeled copy", () => {
  it("renders 'Revenue by Category (paid, this month)' — not the terse form", async () => {
    const { default: Tile } = await import(
      "@/components/dashboard/RevenueByCategoryTile"
    );
    render(<Tile />);
    // Wait for the label to hit the DOM. Regex over textContent covers
    // any incidental whitespace / punctuation.
    const label = await screen.findByText(
      /Revenue by Category \(paid, this month\)/i,
    );
    expect(label).toBeTruthy();
    // Guardrail — the plain "Revenue by Category" string with NO
    // qualifier must not be an exact match anywhere, otherwise a
    // future edit could regress the copy.
    const bareMatches = screen.queryAllByText(
      (_, node) => node?.textContent?.trim() === "Revenue by Category",
    );
    expect(bareMatches).toEqual([]);
  });
});


// ══════════════════════════════════════════════════════════════════════
// 2 · Income-by-Service-Category tile — same qualifier suffix.
// ══════════════════════════════════════════════════════════════════════
describe("IncomeByServiceCategoryTile · relabeled copy", () => {
  it("renders 'Income by Service Category (paid, this month)'", async () => {
    const { default: Tile } = await import(
      "@/components/dashboard/IncomeByServiceCategoryTile"
    );
    render(<Tile />);
    const label = await screen.findByText(
      /Income by Service Category \(paid, this month\)/i,
    );
    expect(label).toBeTruthy();
    const bareMatches = screen.queryAllByText(
      (_, node) =>
        node?.textContent?.trim() === "Income by Service Category",
    );
    expect(bareMatches).toEqual([]);
  });
});


// ══════════════════════════════════════════════════════════════════════
// 3 · Admin Dashboard — Feb-2026 Priority 2 removed the "Total Paid
//      Revenue (lifetime)" emerald hero tile entirely. The RevenueSplitChip
//      that sits directly below now carries the equivalent breakdown, so
//      the hero copy is intentionally absent. This test used to lock in
//      the hero's "(lifetime)" qualifier — it now guards the removal
//      so a future paste-back regression fails loudly at CI time.
// ══════════════════════════════════════════════════════════════════════
describe("Admin Dashboard · top-card label", () => {
  it("Dashboard.jsx no longer renders the emerald hero copy", async () => {
    // Priority 2 removed the ``Total Paid Revenue (lifetime)`` hero.
    // If it's back, someone regressed the removal — this test fails
    // BEFORE the emerald gradient ships.
    // eslint-disable-next-line import/no-unresolved
    const src = (
      await import("@/pages/admin/Dashboard.jsx?raw")
    ).default;
    expect(src).not.toContain("Total Paid Revenue (lifetime)");
    expect(src).not.toMatch(/data-testid="dashboard-hero"/);
    // RevenueSplitChip carries the equivalent breakdown — must survive.
    expect(src).toMatch(/<RevenueSplitChip/);
  });
});
