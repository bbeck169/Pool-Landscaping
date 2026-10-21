/**
 * TD-96-g2 · Feb-2026 — LeadDetail Linked-Quotes panel gates on
 * ``linked_quotes_count`` so the panel stays visible after close-won
 * reparent (``recipient_type`` flips to "customer" so ``quotes_count``
 * drops to 0, but ``converted_from_lead_id`` retention keeps
 * ``linked_quotes_count`` non-zero).
 *
 * Locks three invariants on top of the pre-existing
 * ``LeadDetailLinkedQuotes.test.jsx`` suite:
 *
 *   1. Panel renders when ``quotes_count=0`` AND ``linked_quotes_count>0``
 *      (THE regression TD-96-g2 fixes).
 *   2. Panel hides when both counts are 0 (brand-new lead — no fetch).
 *   3. Backwards-compat: panel renders when ``linked_quotes_count`` is
 *      absent from the payload (mid-deploy / stale cache) but
 *      ``quotes_count > 0``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, cleanup, waitFor }
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


const BASE_LEAD = {
  id: "lead-abc", name: "Larry Lead",
  phone: "480-555-0001", email: "larry@example.com",
  service_address: "100 Palo Verde Way", address: "100 Palo Verde Way",
  status: "new", source: "admin_manual",
  timeline: [], notes: "",
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


describe("TD-96-g2 · LeadDetail Linked-Quotes · linked_quotes_count gate", () => {
  it("renders panel when quotes_count=0 AND linked_quotes_count>0 (reparented regression)", async () => {
    _authMock.user = { role: "admin" };
    _wire({
      lead: { ...BASE_LEAD, quotes_count: 0, linked_quotes_count: 2 },
      quotes: {
        total: 2, limit: 10,
        items: [
          { id: "q-rep-1", title: "Pool build", status: "accepted",
            total: 500.0, reparented: true },
          { id: "q-rep-2", title: "Add-on pump", status: "sent",
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
    // Both rows render.
    expect(screen.getByTestId("lead-linked-quote-row-q-rep-1")).toBeTruthy();
    expect(screen.getByTestId("lead-linked-quote-row-q-rep-2")).toBeTruthy();
  });

  it("hides panel when both quotes_count=0 AND linked_quotes_count=0 (no fetch)", async () => {
    _authMock.user = { role: "admin" };
    const quotesFetch = vi.fn();
    getMock.mockImplementation((url) => {
      if (url.includes("/communications")) {
        return Promise.resolve({ items: [], next_cursor: null, has_more: false });
      }
      if (url.includes("/quotes?")) {
        quotesFetch(url);
        return Promise.resolve({ total: 0, limit: 10, items: [] });
      }
      return Promise.resolve({
        ...BASE_LEAD, quotes_count: 0, linked_quotes_count: 0,
      });
    });
    _mount();
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy());
    // Give the useEffect a chance to fire — but it shouldn't fetch.
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId("lead-linked-quotes-panel")).toBeNull();
    expect(quotesFetch).not.toHaveBeenCalled();
  });

  it("backwards-compat: panel renders when linked_quotes_count absent but quotes_count>0", async () => {
    _authMock.user = { role: "admin" };
    _wire({
      // No linked_quotes_count key — simulates mid-deploy / stale cache.
      lead: { ...BASE_LEAD, quotes_count: 1 },
      quotes: {
        total: 1, limit: 10,
        items: [
          { id: "q-legacy", title: "Legacy quote", status: "sent",
            total: 100.0, reparented: false },
        ],
      },
    });
    _mount();
    await waitFor(() =>
      expect(screen.queryByTestId("lead-detail-page")).toBeTruthy());
    const panel = await screen.findByTestId("lead-linked-quotes-panel");
    expect(panel).toBeTruthy();
    expect(screen.getByTestId("lead-linked-quote-row-q-legacy")).toBeTruthy();
  });
});
