/**
 * TD-96-g1-invoices · Feb-2026 — QuotesList mixed-shape ship.
 *
 * Operator D1(ii) EXPAND lands two FE changes beyond the BE
 * ``doc_type=quote`` relaxation:
 *
 *   1. ``fetchRows`` drops the ``doc_type=quote`` query param
 *      when ``?lead=<lid>`` is on the URL AND the view is ``all``.
 *      Standalone views keep the quote-only scope.
 *   2. Row ``onClick`` routes invoice-shaped rows to
 *      ``/invoices/${id}`` and keeps quote-shaped rows on
 *      ``/quotes/${id}``.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
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

vi.mock("@/components/customers/CustomerFilterBar", () => ({
  __esModule: true, default: () => null,
}));

vi.mock("@/components/quotes/QuotesBulkToolbar", () => ({
  __esModule: true, default: () => null,
}));

vi.mock("@/components/customer", () => ({
  CustomerLink: ({ name }) => <span>{name}</span>,
}));

// Spy on react-router-dom's useNavigate so we can assert row-click
// routing for invoice-shaped vs quote-shaped rows.
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});


import QuotesList from "@/pages/quotes/QuotesList";


function _wire({ leadRow, rows = [] }) {
  getMock.mockImplementation((url) => {
    if (url.startsWith("/leads/")) {
      return leadRow
        ? Promise.resolve(leadRow)
        : Promise.reject(new Error("404"));
    }
    if (url.startsWith("/quotes")) {
      return Promise.resolve(rows);
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


describe("TD-96-g1-invoices · fetchRows doc_type scoping", () => {
  it("DROPS doc_type=quote when ?lead=<lid> AND view=all are both set", async () => {
    _wire({
      leadRow: { id: "lead-abc", name: "Mixed Lead" },
      rows: [],
    });
    _mount("/quotes?lead=lead-abc&view=all");

    await waitFor(() => {
      const calls = getMock.mock.calls.map((c) => c[0]);
      const quotesCall = calls.find((u) => u.startsWith("/quotes?"));
      expect(quotesCall).toBeTruthy();
      // ``doc_type=quote`` must be ABSENT.
      expect(quotesCall).not.toContain("doc_type=quote");
      // ``lead_id`` + ``view=all`` must be present.
      expect(quotesCall).toContain("lead_id=lead-abc");
      expect(quotesCall).toContain("view=all");
    });
  });

  it("KEEPS doc_type=quote when ?lead=<lid> but view is a lifecycle (open)", async () => {
    _wire({
      leadRow: { id: "lead-xyz", name: "Lifecycle Lead" },
      rows: [],
    });
    _mount("/quotes?lead=lead-xyz&view=open");

    await waitFor(() => {
      const calls = getMock.mock.calls.map((c) => c[0]);
      const quotesCall = calls.find((u) => u.startsWith("/quotes?"));
      expect(quotesCall).toBeTruthy();
      // Lifecycle views stay quote-only.
      expect(quotesCall).toContain("doc_type=quote");
      expect(quotesCall).toContain("lead_id=lead-xyz");
      expect(quotesCall).toContain("view=open");
    });
  });

  it("KEEPS doc_type=quote when view=all but no ?lead= scope", async () => {
    _wire({ leadRow: null, rows: [] });
    _mount("/quotes?view=all");

    await waitFor(() => {
      const calls = getMock.mock.calls.map((c) => c[0]);
      const quotesCall = calls.find((u) => u.startsWith("/quotes?"));
      expect(quotesCall).toBeTruthy();
      // Standalone "All" tab stays quote-only.
      expect(quotesCall).toContain("doc_type=quote");
      expect(quotesCall).not.toContain("lead_id=");
    });
  });
});


describe("TD-96-g1-invoices · row click routing by doc_type", () => {
  it("quote-shaped row routes to /quotes/${id}", async () => {
    _wire({
      leadRow: { id: "lead-abc", name: "Mixed Lead" },
      rows: [
        { id: "q-100", doc_type: "quote", title: "Pool quote",
          status: "sent", total: 500, customer_name: "Alice" },
      ],
    });
    _mount("/quotes?lead=lead-abc&view=all");
    const row = await screen.findByTestId("quote-row-q-100");
    fireEvent.click(row);
    expect(navigateMock).toHaveBeenCalledWith("/quotes/q-100");
    expect(navigateMock).not.toHaveBeenCalledWith("/invoices/q-100");
  });

  it("invoice-shaped row routes to /invoices/${id} (SINGULAR check)", async () => {
    _wire({
      leadRow: { id: "lead-abc", name: "Mixed Lead" },
      rows: [
        { id: "inv-200", doc_type: "invoice", title: "Converted invoice",
          status: "sent", total: 750, customer_name: "Alice" },
      ],
    });
    _mount("/quotes?lead=lead-abc&view=all");
    const row = await screen.findByTestId("quote-row-inv-200");
    fireEvent.click(row);
    expect(navigateMock).toHaveBeenCalledWith("/invoices/inv-200");
    // Guard against regression — must NOT route to /quotes/.
    expect(navigateMock).not.toHaveBeenCalledWith("/quotes/inv-200");
  });

  it("mixed list routes each row to the correct detail page", async () => {
    _wire({
      leadRow: { id: "lead-abc", name: "Mixed Lead" },
      rows: [
        { id: "q-100",   doc_type: "quote",   title: "Q",
          status: "sent", total: 500, customer_name: "Alice" },
        { id: "inv-200", doc_type: "invoice", title: "I",
          status: "sent", total: 750, customer_name: "Alice" },
      ],
    });
    _mount("/quotes?lead=lead-abc&view=all");
    await screen.findByTestId("quote-row-q-100");

    fireEvent.click(screen.getByTestId("quote-row-q-100"));
    fireEvent.click(screen.getByTestId("quote-row-inv-200"));

    expect(navigateMock).toHaveBeenCalledWith("/quotes/q-100");
    expect(navigateMock).toHaveBeenCalledWith("/invoices/inv-200");
  });
});
