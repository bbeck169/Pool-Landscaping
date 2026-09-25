/**
 * Task N Round 2 · Phase N.7 · Feb-2026 — NotesHistoryList component tests.
 *
 * Locks the paginated per-customer notes history list against the
 * backend's ``GET /api/customers/{cid}/notes-history`` contract
 * (mocked via ``vi.mock("@/api")``).
 *
 * Covers full mode + compact mode + expander parity with the archive
 * page's Add-B testid convention.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";


const getMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...args) => getMock(...args) },
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", border: "#eee",
    onSurface: "#111827", onSurfaceSecondary: "#6B7280",
    brand: "#0284C7", inputBorder: "#3B82F6",
    nav: {
      bg: "#1B1F5C", fg: "#FFFFFF", fgMuted: "#a3a3c2",
      border: "rgba(255,255,255,0.10)",
    },
    gradient: { css: "linear-gradient(#000,#fff)", textShadow: "none" },
  },
}));


import NotesHistoryList from "@/components/customers/NotesHistoryList";


// ── Helpers ──────────────────────────────────────────────────
const LONG_NOTE = "y".repeat(300);

const _row = (overrides = {}) => ({
  sr_id: "sr-H1",
  job_id: "job-H1",
  submitted_at: "2026-03-11T12:00:00Z",
  customer_id: "cust-H",
  customer_name: "Diane Lloyd",
  tech_id: "tech-1",
  tech_name: "Mike Rivera",
  industry: "Pool",
  notes: "chemistry visit note",
  internal_notes: LONG_NOTE,
  customer_notes: "",
  ...overrides,
});

const _response = (rows = [_row()], total = null) => ({
  rows,
  total_count: total ?? rows.length,
  page: 1,
  page_size: 20,
  customer: {id: "cust-H", name: "Diane Lloyd", notes: ""},
});


beforeEach(() => { getMock.mockReset(); });
afterEach(() => cleanup());


// ═════════════════════════════════════════════════════════════
// Suite 1 · full mode
// ═════════════════════════════════════════════════════════════
describe("NotesHistoryList · full mode", () => {
  it("renders empty state when the endpoint returns zero rows", async () => {
    getMock.mockResolvedValue(_response([], 0));
    render(<NotesHistoryList customerId="cust-H"/>);
    await waitFor(() => {
      expect(screen.getByTestId("notes-history-empty")).toBeInTheDocument();
    });
  });

  it("renders one card per row with date + industry + tech", async () => {
    const rows = [
      _row({sr_id: "sr-A", submitted_at: "2026-03-11T12:00:00Z"}),
      _row({sr_id: "sr-B", submitted_at: "2026-03-10T12:00:00Z",
             industry: "Landscaping", tech_name: "Carla"}),
    ];
    getMock.mockResolvedValue(_response(rows, 2));
    render(<NotesHistoryList customerId="cust-H"/>);
    await waitFor(() => screen.getByTestId("notes-history-row-sr-A"));
    expect(screen.getByTestId("notes-history-row-sr-A")).toBeInTheDocument();
    expect(screen.getByTestId("notes-history-row-sr-B")).toBeInTheDocument();
    expect(screen.getByTestId("notes-history-row-sr-B"))
      .toHaveTextContent("Landscaping");
    expect(screen.getByTestId("notes-history-row-sr-B"))
      .toHaveTextContent("Carla");
  });

  it("expander preview → full → collapse cycle works per field", async () => {
    getMock.mockResolvedValue(_response([_row({sr_id: "sr-EXP"})]));
    render(<NotesHistoryList customerId="cust-H"/>);
    await waitFor(() => screen.getByTestId("notes-history-row-sr-EXP"));

    // Initial: long internal_notes shows preview + toggle.
    expect(screen.getByTestId(
      "notes-history-row-sr-EXP-internal_notes-preview")).toBeInTheDocument();
    expect(screen.queryByTestId(
      "notes-history-row-sr-EXP-internal_notes-full"))
      .not.toBeInTheDocument();

    // Expand.
    fireEvent.click(screen.getByTestId(
      "notes-history-row-sr-EXP-internal_notes-toggle"));
    expect(screen.getByTestId(
      "notes-history-row-sr-EXP-internal_notes-full")).toBeInTheDocument();
    expect(screen.queryByTestId(
      "notes-history-row-sr-EXP-internal_notes-preview"))
      .not.toBeInTheDocument();

    // Collapse.
    fireEvent.click(screen.getByTestId(
      "notes-history-row-sr-EXP-internal_notes-toggle"));
    expect(screen.getByTestId(
      "notes-history-row-sr-EXP-internal_notes-preview")).toBeInTheDocument();
    expect(screen.queryByTestId(
      "notes-history-row-sr-EXP-internal_notes-full"))
      .not.toBeInTheDocument();
  });
});


// ═════════════════════════════════════════════════════════════
// Suite 2 · compact mode
// ═════════════════════════════════════════════════════════════
describe("NotesHistoryList · compact mode", () => {
  it("passes page_size=3 to the endpoint and hides pagination", async () => {
    getMock.mockResolvedValue({..._response([_row()]), page_size: 3});
    render(<NotesHistoryList customerId="cust-H" compact />);
    await waitFor(() => screen.getByTestId("notes-history-list"));
    const calls = getMock.mock.calls.map((c) => c[0]);
    expect(calls.some((u) => u.includes("page_size=3"))).toBe(true);
    // No pagination footer in compact mode.
    expect(screen.queryByTestId("notes-history-prev-btn"))
      .not.toBeInTheDocument();
    expect(screen.queryByTestId("notes-history-next-btn"))
      .not.toBeInTheDocument();
  });

  it("renders 'See all N notes →' link when total_count > 3 and onSeeAll wired", async () => {
    // Return only 3 rows but total_count=8 → link should appear.
    const rows = [_row({sr_id: "s1"}),
                   _row({sr_id: "s2"}),
                   _row({sr_id: "s3"})];
    getMock.mockResolvedValue({rows, total_count: 8, page: 1, page_size: 3});
    const onSeeAll = vi.fn();
    render(<NotesHistoryList customerId="cust-H"
                              compact onSeeAll={onSeeAll} />);
    await waitFor(() => screen.getByTestId("notes-history-see-all"));
    const link = screen.getByTestId("notes-history-see-all");
    expect(link).toHaveTextContent("See all 8 notes");
    fireEvent.click(link);
    expect(onSeeAll).toHaveBeenCalledTimes(1);
  });

  it("does NOT render 'See all →' when total_count ≤ 3", async () => {
    const rows = [_row({sr_id: "s1"}), _row({sr_id: "s2"})];
    getMock.mockResolvedValue({rows, total_count: 2, page: 1, page_size: 3});
    render(<NotesHistoryList customerId="cust-H"
                              compact onSeeAll={vi.fn()} />);
    await waitFor(() => screen.getByTestId("notes-history-list"));
    expect(screen.queryByTestId("notes-history-see-all"))
      .not.toBeInTheDocument();
  });
});


// ═════════════════════════════════════════════════════════════
// Suite 3 · pagination
// ═════════════════════════════════════════════════════════════
describe("NotesHistoryList · pagination (full mode)", () => {
  it("Next button advances the fetched page", async () => {
    // Total 45 rows, page_size 20 → 3 pages.
    getMock.mockResolvedValue({
      rows: [_row({sr_id: "s1"})],
      total_count: 45, page: 1, page_size: 20,
    });
    render(<NotesHistoryList customerId="cust-H"/>);
    await waitFor(() => screen.getByTestId("notes-history-next-btn"));
    expect(screen.getByTestId("notes-history-page-indicator"))
      .toHaveTextContent("Page 1 of 3");
    getMock.mockClear();
    fireEvent.click(screen.getByTestId("notes-history-next-btn"));
    await waitFor(() => {
      const calls = getMock.mock.calls.map((c) => c[0]);
      expect(calls.some((u) => u.includes("page=2"))).toBe(true);
    });
  });
});
