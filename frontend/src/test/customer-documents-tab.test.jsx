/**
 * Feb-2026 · Customer detail — unified "Sent documents" tab.
 *
 * Verifies the ship contract of ``CustomerDocumentsTab``:
 *
 *   1. Fan-out fetch merges quotes + invoices + estimator +
 *      legacy estimates and sorts by date desc.
 *   2. Type filter chips toggle rows in/out.
 *   3. Status filter narrows the list.
 *   4. Empty state renders when the merged list is empty.
 *   5. Resend button appears only for invoice + estimator rows.
 *   6. Clicking Resend calls the correct endpoint.
 *   7. Clicking PDF opens ``/api/quotes/{id}/pdf`` in a new tab
 *      for quotes/invoices only.
 *   8. View row link routes to ``/quotes/{id}`` for quote/invoice
 *      and ``/estimator/estimates/{id}`` for estimate rows.
 *   9. Response-shape normaliser tolerates both bare arrays and
 *      the ``{items, total}`` shape.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn().mockResolvedValue({ ok: true }),
  },
}));

// The tab imports theme's ``money`` helper — provide a
// pass-through so we can assert on the raw number in the DOM.
vi.mock("@/theme", async () => {
  const actual = await vi.importActual("@/theme");
  return {
    ...actual,
    money: (n) => `$${Number(n).toFixed(2)}`,
  };
});

const _API_ROUTES = {
  quotes: (cid) => `/quotes?customer_id=${cid}&doc_type=quote`,
  invoices: (cid) => `/quotes?customer_id=${cid}&doc_type=invoice`,
  estimator: (cid) => `/estimator/estimates?customer_id=${cid}`,
  legacy: (cid) => `/estimates?customer_id=${cid}`,
};

// Sample data covering all 4 sources + interesting statuses.
const _SAMPLE = {
  quotes: [
    { id: "q1", number: "Q-001", title: "Pool refurb quote", total: 1200,
      status: "sent",     created_at: "2026-02-05T00:00:00Z" },
    { id: "q2", number: "Q-002", title: "Deck refinish",     total: 450,
      status: "accepted", created_at: "2026-02-06T00:00:00Z" },
  ],
  invoices: [
    { id: "i1", number: "INV-100", title: "Feb service block", total: 275,
      status: "sent", payment_status: "unpaid",
      created_at: "2026-02-07T00:00:00Z" },
    { id: "i2", number: "INV-099", title: "Jan service block", total: 275,
      status: "sent", payment_status: "paid",
      created_at: "2026-02-01T00:00:00Z" },
  ],
  estimator: [
    { id: "e1", number: "E-1", title: "Auto-cover estimate", total: 800,
      status: "sent", sent_at: "2026-02-08T00:00:00Z" },
  ],
  legacy: [
    { id: "leg1", number: "L-1", title: "Legacy 2025 estimate", total: 500,
      status: "draft", created_at: "2026-01-15T00:00:00Z" },
  ],
};

async function _wireApi(overrides = {}) {
  const { api } = await import("@/api");
  const routes = {
    [_API_ROUTES.quotes("cid1")]: _SAMPLE.quotes,
    [_API_ROUTES.invoices("cid1")]: _SAMPLE.invoices,
    [_API_ROUTES.estimator("cid1")]: { items: _SAMPLE.estimator, total: 1 },
    [_API_ROUTES.legacy("cid1")]: _SAMPLE.legacy,
    ...overrides,
  };
  api.get.mockImplementation((path) => {
    if (path in routes) return Promise.resolve(routes[path]);
    return Promise.resolve([]);
  });
  api.post.mockResolvedValue({ ok: true });
  return api;
}

async function _mount(customerId = "cid1") {
  const { default: CustomerDocumentsTab } = await import(
    "@/components/customers/CustomerDocumentsTab"
  );
  return render(
    <MemoryRouter>
      <CustomerDocumentsTab customerId={customerId} />
    </MemoryRouter>,
  );
}

beforeEach(async () => {
  const { api } = await import("@/api");
  api.get.mockReset();
  api.post.mockReset();
});

describe("CustomerDocumentsTab (Feb-2026)", () => {
  it("fetches from all 4 sources and renders a unified list", async () => {
    await _wireApi();
    await _mount();
    // Wait for the table to render.
    const list = await screen.findByTestId("customer-docs-list");
    expect(list).toBeInTheDocument();
    // 2 quotes + 2 invoices + 1 estimator + 1 legacy = 6 rows.
    const rows = within(list).getAllByTestId(/^customer-docs-row-/);
    expect(rows).toHaveLength(6);
    // Default sort: newest first — estimator row (2026-02-08) leads.
    expect(rows[0].getAttribute("data-testid")).toBe("customer-docs-row-e1");
  });

  it("shows the empty state when everything is empty", async () => {
    await _wireApi({
      [_API_ROUTES.quotes("cid1")]: [],
      [_API_ROUTES.invoices("cid1")]: [],
      [_API_ROUTES.estimator("cid1")]: { items: [], total: 0 },
      [_API_ROUTES.legacy("cid1")]: [],
    });
    await _mount();
    expect(await screen.findByTestId("customer-docs-empty")).toBeInTheDocument();
  });

  it("Type filter toggle removes rows of the deselected type", async () => {
    await _wireApi();
    await _mount();
    await screen.findByTestId("customer-docs-list");
    // Turn off Invoice + Estimate → 2 quotes only.
    fireEvent.click(screen.getByTestId("customer-docs-filter-type-invoice"));
    fireEvent.click(screen.getByTestId("customer-docs-filter-type-estimate"));
    await waitFor(() => {
      const rows = screen.getAllByTestId(/^customer-docs-row-/);
      expect(rows.length).toBe(2);
      rows.forEach((r) => expect(r.getAttribute("data-doc-type")).toBe("quote"));
    });
  });

  it("Status filter narrows the list", async () => {
    await _wireApi();
    await _mount();
    await screen.findByTestId("customer-docs-list");
    fireEvent.change(screen.getByTestId("customer-docs-filter-status"), {
      target: { value: "paid" },
    });
    await waitFor(() => {
      const rows = screen.getAllByTestId(/^customer-docs-row-/);
      // Only the paid invoice (INV-099) matches.
      expect(rows.length).toBe(1);
      expect(rows[0].getAttribute("data-testid")).toBe("customer-docs-row-i2");
    });
  });

  it("Resend appears only on invoice + estimator rows", async () => {
    await _wireApi();
    await _mount();
    await screen.findByTestId("customer-docs-list");
    // Invoice row has Resend.
    expect(screen.getByTestId("customer-docs-action-resend-i1")).toBeInTheDocument();
    // Estimator row has Resend.
    expect(screen.getByTestId("customer-docs-action-resend-e1")).toBeInTheDocument();
    // Quote row does NOT have Resend.
    expect(screen.queryByTestId("customer-docs-action-resend-q1")).toBeNull();
    // Legacy-estimate row does NOT have Resend.
    expect(screen.queryByTestId("customer-docs-action-resend-leg1")).toBeNull();
  });

  it("Resend on an invoice POSTs to /quotes/{id}/send-reminder", async () => {
    const api = await _wireApi();
    await _mount();
    await screen.findByTestId("customer-docs-list");
    fireEvent.click(screen.getByTestId("customer-docs-action-resend-i1"));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/quotes/i1/send-reminder"),
    );
  });

  it("Resend on an estimator estimate POSTs to /estimator/estimates/{id}/send-to-customer", async () => {
    const api = await _wireApi();
    await _mount();
    await screen.findByTestId("customer-docs-list");
    fireEvent.click(screen.getByTestId("customer-docs-action-resend-e1"));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/estimator/estimates/e1/send-to-customer",
      ),
    );
  });

  it("PDF opens /api/quotes/{id}/pdf for quotes and invoices", async () => {
    await _wireApi();
    const spy = vi.spyOn(window, "open").mockImplementation(() => null);
    await _mount();
    await screen.findByTestId("customer-docs-list");
    fireEvent.click(screen.getByTestId("customer-docs-action-pdf-q1"));
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining("/api/quotes/q1/pdf"),
      "_blank",
      "noopener,noreferrer",
    );
    fireEvent.click(screen.getByTestId("customer-docs-action-pdf-i1"));
    expect(spy).toHaveBeenLastCalledWith(
      expect.stringContaining("/api/quotes/i1/pdf"),
      "_blank",
      "noopener,noreferrer",
    );
    spy.mockRestore();
  });

  it("PDF button is hidden on estimate rows", async () => {
    await _wireApi();
    await _mount();
    await screen.findByTestId("customer-docs-list");
    expect(screen.queryByTestId("customer-docs-action-pdf-e1")).toBeNull();
    expect(screen.queryByTestId("customer-docs-action-pdf-leg1")).toBeNull();
  });

  it("View routes to /quotes/{id} for quote/invoice and /estimator/estimates/{id} for estimate", async () => {
    await _wireApi();
    await _mount();
    await screen.findByTestId("customer-docs-list");
    const viewQ = screen.getByTestId("customer-docs-action-view-q1");
    expect(viewQ.getAttribute("href")).toBe("/quotes/q1");
    const viewI = screen.getByTestId("customer-docs-action-view-i1");
    expect(viewI.getAttribute("href")).toBe("/quotes/i1");
    const viewE = screen.getByTestId("customer-docs-action-view-e1");
    expect(viewE.getAttribute("href")).toBe("/estimator/estimates/e1");
    const viewLeg = screen.getByTestId("customer-docs-action-view-leg1");
    expect(viewLeg.getAttribute("href")).toBe("/estimator/estimates/leg1");
  });

  it("Response-shape normaliser handles both array and {items} responses", async () => {
    // /estimator returns {items,total}; /quotes returns array — the
    // "fetches from all 4 sources" test already exercises this. This
    // spec adds the reverse — /quotes returning an object shape by
    // mistake — the tab must not crash.
    await _wireApi({
      [_API_ROUTES.quotes("cid1")]: { items: _SAMPLE.quotes, total: 2 },
      [_API_ROUTES.invoices("cid1")]: [],
      [_API_ROUTES.estimator("cid1")]: [],
      [_API_ROUTES.legacy("cid1")]: [],
    });
    await _mount();
    const list = await screen.findByTestId("customer-docs-list");
    expect(within(list).getAllByTestId(/^customer-docs-row-/)).toHaveLength(2);
  });
});
