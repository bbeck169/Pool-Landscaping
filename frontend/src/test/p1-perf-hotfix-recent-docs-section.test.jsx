/**
 * P1 PERF-HOTFIX · Feb-2026 — RecentDocsSection calls
 * ``/quotes?...&limit=5&slim=1`` and unwraps the Shape-A envelope.
 *
 * Pins three contracts on the customer-profile Overview tab's
 * RecentDocsSection:
 *
 *   1. **URL contract** — both parallel ``api.get`` calls include
 *      ``limit=5`` AND ``slim=1``. Without these, the pre-hotfix
 *      regression returns (unbounded doc fetch; dominant payload).
 *   2. **Envelope unwrap** — when the server returns the Shape-A
 *      envelope ``{rows, limit, offset, has_more, total_count}``,
 *      the component extracts ``rows`` and renders. No client-side
 *      ``.slice(0, 5)`` — the server already capped the window.
 *   3. **Legacy-shape fallback** — if an upstream proxy somehow
 *      strips the envelope and returns a bare array, the client
 *      renders defensively without blowing up.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { RecentDocsSection } from "@/pages/customers/CustomerDetail";


const _wrap = (ui) => (
  <MemoryRouter initialEntries={["/customers/x"]}>{ui}</MemoryRouter>
);


const _ENVELOPE = (rows, total_count = rows.length, has_more = false) => ({
  rows,
  limit: 5,
  offset: 0,
  has_more,
  total_count,
});


function _row(id, kind) {
  return {
    id,
    doc_type: kind,
    status: "sent",
    payment_status: "unpaid",
    invoice_number: `INV-${id}`,
    total: 100,
    customer_name: "Test Customer",
    created_at: "2026-02-15T12:00:00+00:00",
    // Slim projection — line_items + pdf_cache absent.
  };
}


function _mkApi(responses) {
  // Returns the right fulfilled payload for the URL via a map.
  const get = vi.fn((url) => {
    const match = Object.entries(responses).find(([frag]) =>
      url.includes(frag),
    );
    if (!match) {
      return Promise.reject(new Error(`no stub for ${url}`));
    }
    return Promise.resolve(match[1]);
  });
  return { get, patch: vi.fn(), post: vi.fn() };
}


describe("P1 PERF-HOTFIX · RecentDocsSection URL + envelope contract", () => {
  beforeEach(() => { cleanup(); });

  it("Case 1 — both API calls include ``limit=5`` and ``slim=1``", async () => {
    const api = _mkApi({
      "doc_type=invoice": _ENVELOPE([_row("i1", "invoice")]),
      "doc_type=quote":   _ENVELOPE([_row("q1", "quote")]),
    });
    render(_wrap(<RecentDocsSection customerId="cust-1" api={api} />));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    const urls = api.get.mock.calls.map((c) => c[0]);
    for (const url of urls) {
      expect(url).toMatch(/customer_id=cust-1/);
      expect(url).toMatch(/\blimit=5\b/);
      expect(url).toMatch(/\bslim=1\b/);
    }
    // One for each doc_type.
    expect(urls.some((u) => u.includes("doc_type=invoice"))).toBe(true);
    expect(urls.some((u) => u.includes("doc_type=quote"))).toBe(true);
  });

  it("Case 2 — Shape-A envelope: rows unwrapped and rendered", async () => {
    const api = _mkApi({
      "doc_type=invoice": _ENVELOPE([
        _row("i1", "invoice"),
        _row("i2", "invoice"),
      ], 42, true),
      "doc_type=quote": _ENVELOPE([
        _row("q1", "quote"),
      ], 7, false),
    });
    const { container } = render(_wrap(
      <RecentDocsSection customerId="cust-2" api={api} />,
    ));
    await waitFor(() => {
      // Two API calls done.
      expect(api.get).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      // Rows from the envelope's ``rows`` key are rendered.
      // RecentDocsList uses data-testid={prefix}-row-{id} per row.
      expect(container.querySelector(
        '[data-testid="cd-recent-invoices-row-i1"]',
      )).toBeTruthy();
      expect(container.querySelector(
        '[data-testid="cd-recent-invoices-row-i2"]',
      )).toBeTruthy();
      expect(container.querySelector(
        '[data-testid="cd-recent-estimates-row-q1"]',
      )).toBeTruthy();
    });
  });

  it("Case 3 — legacy bare-array response still renders (defensive fallback)", async () => {
    // Simulate a proxy stripping the envelope and returning the
    // bare array shape (pre-hotfix contract). Component must
    // tolerate it without blowing up.
    const api = _mkApi({
      "doc_type=invoice": [_row("i-legacy", "invoice")],
      "doc_type=quote":   [_row("q-legacy", "quote")],
    });
    const { container } = render(_wrap(
      <RecentDocsSection customerId="cust-3" api={api} />,
    ));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    await waitFor(() => {
      expect(container.querySelector(
        '[data-testid="cd-recent-invoices-row-i-legacy"]',
      )).toBeTruthy();
      expect(container.querySelector(
        '[data-testid="cd-recent-estimates-row-q-legacy"]',
      )).toBeTruthy();
    });
  });

  it("Case 4 — malformed response (object with no ``rows``) renders empty state, no crash", async () => {
    const api = _mkApi({
      "doc_type=invoice": { unexpected_shape: true },
      "doc_type=quote":   { also_bad: true },
    });
    const { container } = render(_wrap(
      <RecentDocsSection customerId="cust-4" api={api} />,
    ));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    // No crash, no row content. Empty-state div renders inside
    // each list.
    expect(container.querySelector(
      '[data-testid="cd-recent-docs-section"]',
    )).toBeTruthy();
    expect(container.querySelectorAll(
      '[data-testid^="cd-recent-invoices-row-"], [data-testid^="cd-recent-estimates-row-"]',
    ).length).toBe(0);
  });
});
