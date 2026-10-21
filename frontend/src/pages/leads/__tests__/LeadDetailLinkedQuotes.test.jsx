/**
 * P2 #4 · Feb-2026 — LeadDetail Linked-Quotes mini-list.
 *
 * Locks four invariants:
 *   1. Panel renders ONLY when lead.quotes_count > 0 AND the lazy
 *      GET /leads/<id>/quotes fetch returns a non-empty items[] list.
 *   2. Each row renders title + total + status pill + reparented
 *      marker when appropriate; click navigates to /quotes/<id>.
 *   3. "View all" link renders only when items.length < total.
 *   4. Non-admin roles never see the panel (admin-only gate).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, cleanup, fireEvent, waitFor }
  from "@testing-library/react";


const navigateMock = vi.fn();
const getMock = vi.fn();
const postMock = vi.fn();
const patchMock = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    patch: (...a) => patchMock(...a),
    put: (...a) => postMock(...a),
  },
  TOKEN_KEY: "token",
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});

const _authMock = vi.hoisted(() => ({ user: { role: "admin" } }));
vi.mock("@/auth", () => ({ useAuth: () => _authMock }));

vi.mock("@/components/telephony/ClickToCallButton", () => ({
  __esModule: true, default: () => null,
}));

vi.mock("@/components/customer", () => ({
  PhoneLink: ({ phone }) => <span>{phone}</span>,
  AddressLink: ({ children }) => <span>{children}</span>,
}));

vi.mock("@/pages/leads/LeadComposeModal", () => ({
  __esModule: true, default: () => null,
}));


import LeadDetail from "@/pages/leads/LeadDetail";


const LEAD_WITH_QUOTES = {
  id: "lead-abc", name: "Larry Lead",
  phone: "480-555-0001", email: "larry@example.com",
  service_address: "100 Palo Verde Way", address: "100 Palo Verde Way",
  status: "new", source: "admin_manual",
  timeline: [], notes: "", quotes_count: 2,
};


function _wire({ lead, quotes }) {
  getMock.mockImplementation((url) => {
    if (url.includes("/communications")) {
      return Promise.resolve({ items: [], next_cursor: null, has_more: false });
    }
    if (url.includes("/quotes?")) {
      return Promise.resolve(quotes);
    }
    return Promise.resolve(lead);
  });
}


function _mount() {
  return render(
    <MemoryRouter initialEntries={["/leads/lead-abc"]}>
      <Routes>
        <Route path="/leads/:id" element={<LeadDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}


afterEach(() => {
  cleanup();
  getMock.mockReset(); postMock.mockReset(); patchMock.mockReset();
  navigateMock.mockReset();
  _authMock.user = { role: "admin" };
});


describe("LeadDetail · Linked Quotes mini-list", () => {
  it("renders the panel with rows + status pill + reparented marker when quotes exist", async () => {
    _authMock.user = { role: "admin" };
    _wire({
      lead: LEAD_WITH_QUOTES,
      quotes: {
        total: 2, limit: 10,
        items: [
          { id: "q-1", title: "Pool build", status: "sent",
            total: 500.0, reparented: false },
          { id: "q-2", title: "Add-on pump", status: "accepted",
            total: 1200.0, reparented: true },
        ],
      },
    });
    _mount();
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy());
    const panel = await screen.findByTestId("lead-linked-quotes-panel");
    expect(panel).toBeTruthy();
    expect(screen.getByTestId("lead-linked-quotes-count").textContent).toContain("2");
    // Row click navigates.
    fireEvent.click(screen.getByTestId("lead-linked-quote-row-q-1"));
    expect(navigateMock).toHaveBeenCalledWith("/quotes/q-1");
    // Status pill rendered for accepted quote.
    expect(screen.getByTestId("lead-linked-quote-status-accepted")).toBeTruthy();
    expect(screen.getByTestId("lead-linked-quote-status-sent")).toBeTruthy();
    // Reparented marker present on the reparented row's text.
    const q2Row = screen.getByTestId("lead-linked-quote-row-q-2");
    expect(q2Row.textContent).toContain("reparented");
  });

  it("renders View all link ONLY when items.length < total", async () => {
    _authMock.user = { role: "admin" };
    _wire({
      lead: { ...LEAD_WITH_QUOTES, quotes_count: 15 },
      quotes: {
        total: 15, limit: 10,
        items: Array.from({ length: 10 }, (_, i) => ({
          id: `q-${i}`, title: `Quote ${i}`, status: "sent",
          total: 100.0, reparented: false,
        })),
      },
    });
    _mount();
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy());
    await screen.findByTestId("lead-linked-quotes-panel");
    const viewAll = screen.getByTestId("lead-linked-quotes-view-all");
    expect(viewAll.textContent).toContain("15");
    fireEvent.click(viewAll);
    // TD-96-g1-web-view · Feb-2026 — "View all" link must now carry
    // ``&view=all`` so the QuotesList lead-scoped mixed-shape path
    // activates (BE guard at routers/quotes.py:434 drops ``doc_type=quote``
    // only when both ``lead_id`` AND ``view=all`` are set). Without
    // ``view=all``, QuotesList defaults ``view`` → "open" and the
    // reparented invoices stay hidden.
    expect(navigateMock).toHaveBeenCalledWith("/quotes?lead=lead-abc&view=all");
    // Regression guard — plain ``?lead=`` without ``&view=all`` must not
    // be routed to (would silently hide invoices).
    expect(navigateMock).not.toHaveBeenCalledWith("/quotes?lead=lead-abc");
  });

  it("does NOT render View all when items.length == total", async () => {
    _authMock.user = { role: "admin" };
    _wire({
      lead: LEAD_WITH_QUOTES,
      quotes: {
        total: 2, limit: 10,
        items: [
          { id: "q-1", title: "A", status: "sent", total: 1, reparented: false },
          { id: "q-2", title: "B", status: "sent", total: 1, reparented: false },
        ],
      },
    });
    _mount();
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy());
    await screen.findByTestId("lead-linked-quotes-panel");
    expect(screen.queryByTestId("lead-linked-quotes-view-all")).toBeNull();
  });

  it("does NOT render panel for non-admin roles", async () => {
    _authMock.user = { role: "manager" };
    _wire({
      lead: LEAD_WITH_QUOTES,
      quotes: {
        total: 2, limit: 10,
        items: [
          { id: "q-1", title: "A", status: "sent", total: 1, reparented: false },
        ],
      },
    });
    _mount();
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy());
    expect(screen.queryByTestId("lead-linked-quotes-panel")).toBeNull();
  });

  it("does NOT render panel when quotes_count = 0 (no fetch triggered)", async () => {
    _authMock.user = { role: "admin" };
    _wire({
      lead: { ...LEAD_WITH_QUOTES, quotes_count: 0 },
      quotes: { total: 0, limit: 10, items: [] },
    });
    _mount();
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy());
    expect(screen.queryByTestId("lead-linked-quotes-panel")).toBeNull();
  });
});
