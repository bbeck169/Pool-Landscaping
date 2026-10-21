/**
 * TD-96-g1 · Feb-2026 — QuotesList ``?lead=<lid>`` filter.
 *
 * Locks:
 *   1. ``/quotes?lead=<lid>`` triggers a fetch with ``lead_id`` query
 *      param forwarded to the BE.
 *   2. Lead filter badge renders with hydrated lead name from
 *      GET /leads/<lid>; falls back to truncated id on fetch failure.
 *   3. Clicking "Clear" removes ``?lead`` from the URL and refetches
 *      the full list (no ``lead_id`` param on subsequent request).
 *   4. No ``?lead`` on the URL → no badge, no ``lead_id`` on fetch.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup }
  from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";


const { getMock, postMock, navigateMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
  navigateMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    put: (...a) => postMock(...a),
    patch: (...a) => postMock(...a),
    delete: (...a) => postMock(...a),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin" } }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

// Shim CustomerFilterBar — tested elsewhere; keep this suite focused
// on the new lead filter surface.
vi.mock("@/components/customers/CustomerFilterBar", () => ({
  __esModule: true, default: () => null,
}));

vi.mock("@/components/quotes/QuotesBulkToolbar", () => ({
  __esModule: true, default: () => null,
}));

vi.mock("@/components/customer", () => ({
  CustomerLink: ({ name }) => <span>{name}</span>,
}));


import QuotesList from "@/pages/quotes/QuotesList";


function _wire({ leadRow, quotes = [] }) {
  getMock.mockImplementation((url) => {
    if (url.startsWith("/leads/")) {
      return leadRow ? Promise.resolve(leadRow) : Promise.reject(new Error("404"));
    }
    if (url.startsWith("/quotes")) {
      return Promise.resolve(quotes);
    }
    return Promise.resolve([]);
  });
}


function _mount(url) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/quotes" element={<QuotesList />} />
      </Routes>
    </MemoryRouter>,
  );
}


afterEach(() => {
  cleanup();
  getMock.mockReset();
  postMock.mockReset();
  navigateMock.mockReset();
});


describe("TD-96-g1 · QuotesList · ?lead= filter", () => {
  it("forwards lead_id to the BE and renders the lead badge with hydrated name", async () => {
    _wire({
      leadRow: { id: "lead-abc", name: "Larry Lead" },
      quotes: [
        { id: "q-1", title: "Pool build", status: "accepted",
          total: 500.0, customer_name: "Materialized Cust" },
      ],
    });
    _mount("/quotes?lead=lead-abc&view=all");

    await waitFor(() => {
      const calls = getMock.mock.calls.map((c) => c[0]);
      const quotesCall = calls.find((u) => u.startsWith("/quotes?"));
      expect(quotesCall).toBeTruthy();
      expect(quotesCall).toContain("lead_id=lead-abc");
    });

    const badge = await screen.findByTestId("quotes-filter-lead-badge");
    expect(badge).toBeTruthy();
    expect(badge.textContent).toContain("Larry Lead");
  });

  it("falls back to truncated id if GET /leads/{lid} fails", async () => {
    _wire({ leadRow: null, quotes: [] });
    _mount("/quotes?lead=lead-does-not-exist-xyz&view=all");

    const badge = await screen.findByTestId("quotes-filter-lead-badge");
    // Fallback label: "Lead " + first 8 chars of the id.
    expect(badge.textContent).toContain("Lead lead-doe");
  });

  it("Clear button removes ?lead from URL AND refetches without lead_id", async () => {
    _wire({
      leadRow: { id: "lead-abc", name: "Larry Lead" },
      quotes: [],
    });
    _mount("/quotes?lead=lead-abc&view=all");

    await screen.findByTestId("quotes-filter-lead-badge");
    // Confirm initial fetch carried lead_id.
    const initialQuotesCall = getMock.mock.calls
      .map((c) => c[0]).find((u) => u.startsWith("/quotes?"));
    expect(initialQuotesCall).toContain("lead_id=lead-abc");

    getMock.mockClear();
    _wire({ leadRow: null, quotes: [] });

    fireEvent.click(screen.getByTestId("quotes-filter-lead-clear"));

    await waitFor(() => {
      const calls = getMock.mock.calls.map((c) => c[0]);
      const quotesCall = calls.find((u) => u.startsWith("/quotes?"));
      expect(quotesCall).toBeTruthy();
      expect(quotesCall).not.toContain("lead_id=");
    });

    // Badge is gone.
    expect(screen.queryByTestId("quotes-filter-lead-badge")).toBeNull();
    expect(screen.queryByTestId("quotes-filter-lead-bar")).toBeNull();
  });

  it("no ?lead on URL → no badge, no lead_id on fetch", async () => {
    _wire({ leadRow: null, quotes: [] });
    _mount("/quotes?view=all");

    await waitFor(() => {
      const calls = getMock.mock.calls.map((c) => c[0]);
      const quotesCall = calls.find((u) => u.startsWith("/quotes?"));
      expect(quotesCall).toBeTruthy();
      expect(quotesCall).not.toContain("lead_id=");
    });

    expect(screen.queryByTestId("quotes-filter-lead-badge")).toBeNull();
    expect(screen.queryByTestId("quotes-filter-lead-bar")).toBeNull();
    // GET /leads/* should NOT be called when no lead param is present.
    const leadCall = getMock.mock.calls
      .map((c) => c[0]).find((u) => u.startsWith("/leads/"));
    expect(leadCall).toBeFalsy();
  });
});
