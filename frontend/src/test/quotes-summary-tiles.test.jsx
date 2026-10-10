/**
 * QUOTES-SUMMARY · Feb-2026 — summary tiles on the Quotes list.
 *
 * Locks the client-side dashboard contract for the tiles rendered
 * between the ``<PageHeader>`` and ``CustomerFilterBar``:
 *
 *   1. Total Value tile renders the summed row totals via
 *      ``money()``.
 *   2. Total Count tile renders ``rows.length`` as a plain string.
 *   3. Stage Breakdown per-status counts use the same
 *      ``decision || status`` resolution as the row-level pills.
 *   4. Tiles appear before the customer filter bar in DOM order.
 *   5. Tiles are hidden while ``rows`` is still ``null`` (initial
 *      load) so we don't flash a "$0.00 / 0" dashboard.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";


const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    put: vi.fn(),
    post: vi.fn(),
  },
}));


vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u-test-admin", role: "admin",
                              email: "admin@test.local" },
                     loading: false }),
  AuthProvider: ({ children }) => children,
}));

vi.mock("react-router-dom", async () => {
  const R = await import("react");
  return {
    useNavigate: () => () => null,
    useSearchParams: () => {
      const [params, setParams] = R.useState(new URLSearchParams(""));
      return [params, setParams];
    },
    Link: ({ to, children, ...rest }) =>
      R.createElement("a", { href: to, ...rest }, children),
  };
});


// Neutralise the customer-filter dropdown so the mount is fast and
// deterministic.  The tile ordering assertion still uses the
// wrapping ``div`` testid we control below.
vi.mock("@/components/customers/CustomerFilterBar", () => ({
  default: ({ testId }) =>
    <div data-testid={testId || "quotes-filter-customer"} />,
}));


beforeEach(() => {
  getSpy.mockReset();
  global.fetch = vi.fn().mockResolvedValue({
    ok: false, status: 424,
    json: () => Promise.resolve({}),
    headers: new Headers(),
  });
});

afterEach(() => { delete global.fetch; });


import QuotesList from "@/pages/quotes/QuotesList.jsx";


const ROWS = [
  { id: "q1", title: "Backyard reno",  customer_id: "c1", customer_name: "Alice",
    total: 1200.00, status: "draft" },
  { id: "q2", title: "Pool deck",      customer_id: "c2", customer_name: "Bob",
    total: 3450.00, status: "sent" },
  { id: "q3", title: "Landscape",      customer_id: "c3", customer_name: "Carol",
    total: 6000.00, status: "sent", decision: "accepted" },
  { id: "q4", title: "Fire pit",       customer_id: "c4", customer_name: "Dave",
    total: 895.00,  status: "approved" },
  { id: "q5", title: "Kitchen redo",   customer_id: "c5", customer_name: "Eve",
    total: 800.00,  status: "declined" },
];
// Expected total: 1200 + 3450 + 6000 + 895 + 800 = 12345.00 → $12,345.00
// Expected buckets: draft:1, sent:1, accepted:1, approved:1, declined:1
//   (row q3 counts as ACCEPTED via ``decision || status``.)


describe("QuotesList · QUOTES-SUMMARY summary tiles", () => {
  it("Total Value tile shows the summed formatted currency", async () => {
    getSpy.mockResolvedValue(ROWS);
    render(<QuotesList />);
    await waitFor(() =>
      expect(screen.queryByTestId("quotes-summary-tile-value"))
        .toBeTruthy());
    const tile = screen.getByTestId("quotes-summary-tile-value");
    expect(tile.textContent).toContain("$12,345.00");
    expect(tile.textContent).toContain("Total Value");
  });

  it("Total Count tile shows rows.length", async () => {
    getSpy.mockResolvedValue(ROWS);
    render(<QuotesList />);
    await waitFor(() =>
      expect(screen.queryByTestId("quotes-summary-tile-count"))
        .toBeTruthy());
    const tile = screen.getByTestId("quotes-summary-tile-count");
    expect(tile.textContent).toContain("5");
    expect(tile.textContent).toContain("Total Count");
  });

  it("Stage Breakdown counts every bucket, with decision beating status", async () => {
    getSpy.mockResolvedValue(ROWS);
    render(<QuotesList />);
    await waitFor(() =>
      expect(screen.queryByTestId("quotes-summary-tile-stages"))
        .toBeTruthy());
    // Row q3 has status="sent" + decision="accepted" → counts as
    // Accepted, NOT Sent.
    expect(
      screen.getByTestId("quotes-summary-stage-draft-count").textContent,
    ).toBe("1");
    expect(
      screen.getByTestId("quotes-summary-stage-sent-count").textContent,
    ).toBe("1");
    expect(
      screen.getByTestId("quotes-summary-stage-accepted-count").textContent,
    ).toBe("1");
    expect(
      screen.getByTestId("quotes-summary-stage-approved-count").textContent,
    ).toBe("1");
    expect(
      screen.getByTestId("quotes-summary-stage-declined-count").textContent,
    ).toBe("1");
  });

  it("decision beats status in the count resolution", async () => {
    getSpy.mockResolvedValue([
      { id: "a", title: "A", total: 100, status: "sent", decision: "accepted" },
      { id: "b", title: "B", total: 200, status: "sent" },
    ]);
    render(<QuotesList />);
    await waitFor(() =>
      expect(screen.queryByTestId("quotes-summary-tile-stages"))
        .toBeTruthy());
    // Two rows; the one with decision="accepted" counts as
    // Accepted, so Sent=1 and Accepted=1.
    expect(
      screen.getByTestId("quotes-summary-stage-sent-count").textContent,
    ).toBe("1");
    expect(
      screen.getByTestId("quotes-summary-stage-accepted-count").textContent,
    ).toBe("1");
  });

  it("tiles render BEFORE the customer filter bar in DOM order", async () => {
    getSpy.mockResolvedValue(ROWS);
    render(<QuotesList />);
    await waitFor(() =>
      expect(screen.queryByTestId("quotes-summary-tiles")).toBeTruthy());
    const tilesEl = screen.getByTestId("quotes-summary-tiles");
    const filterEl = screen.getByTestId("quotes-filter-customer");
    // `compareDocumentPosition` returns a bitmask.  The
    // FOLLOWING flag (0x04) is set when ``filterEl`` follows
    // ``tilesEl`` in document order.
    const pos = tilesEl.compareDocumentPosition(filterEl);
    // eslint-disable-next-line no-bitwise
    expect(pos & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("tiles are HIDDEN while rows are still loading (null)", async () => {
    // Delay the fetch resolution so the initial render sees null.
    let resolve;
    const promise = new Promise((r) => { resolve = r; });
    getSpy.mockReturnValue(promise);
    render(<QuotesList />);
    // Initial paint — rows is still null, tiles must not appear.
    expect(screen.queryByTestId("quotes-summary-tiles")).toBeNull();
    // Resolve to an empty list so React unblocks + we clean up.
    resolve([]);
    await waitFor(() =>
      expect(screen.queryByTestId("quotes-summary-tiles")).toBeTruthy());
  });
});
