/**
 * CP-2 · Feb-2026 — Customer Profile · Recent Invoices + Recent
 * Estimates sections.
 *
 * Mount-level vitest against the ``RecentDocsSection`` named export
 * from ``CustomerDetail.jsx``.  Full-page mount is intractable
 * (~3000-line component, dozens of children) so the CP-2 brief's
 * five behavioural criteria are proved against the isolated
 * sub-component with the ``api`` injection point.  The real
 * production page mounts <RecentDocsSection customerId={id} /> with
 * no explicit ``api`` prop so it falls through to the imported
 * ``api`` client — asserted structurally below so the production
 * wiring stays locked.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  cleanup,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { RecentDocsSection } from "@/pages/customers/CustomerDetail";

afterEach(cleanup);

/* ── fixture helpers ───────────────────────────────────────────── */
const _mkInvoices = (count) =>
  Array.from({ length: count }).map((_, i) => ({
    id: `inv-${i}`,
    doc_type: "invoice",
    invoice_number: `INV-${1000 + i}`,
    created_at: `2026-02-${String(i + 1).padStart(2, "0")}T12:00:00Z`,
    total: 100 + i,
    status: "sent",
  }));

const _mkQuotes = (count) =>
  Array.from({ length: count }).map((_, i) => ({
    id: `quote-${i}`,
    doc_type: "quote",
    quote_number: `Q-${2000 + i}`,
    created_at: `2026-02-${String(i + 1).padStart(2, "0")}T10:00:00Z`,
    total: 500 + i,
    status: "accepted",
  }));

function _mkApi({ invoices, estimates, invoicesRejects = false }) {
  return {
    get: vi.fn((p) => {
      if (p.includes("doc_type=invoice")) {
        return invoicesRejects
          ? Promise.reject(new Error("boom"))
          : Promise.resolve(invoices);
      }
      if (p.includes("doc_type=quote")) {
        return Promise.resolve(estimates);
      }
      return Promise.resolve([]);
    }),
  };
}

const _wrap = (ui) => render(<MemoryRouter>{ui}</MemoryRouter>);

/* ── behavioural assertions (5) ────────────────────────────────── */
describe("CP-2 · RecentDocsSection · behavioural contract", () => {
  it("a. renders 5 invoice rows when 5 invoices are returned", async () => {
    const api = _mkApi({ invoices: _mkInvoices(5), estimates: [] });
    _wrap(<RecentDocsSection customerId="c-1" api={api} />);
    await waitFor(() =>
      expect(screen.getByTestId("cd-recent-invoices-list")).toBeTruthy(),
    );
    const rows = screen.getAllByTestId(/^cd-recent-invoices-row-inv-\d+$/);
    expect(rows).toHaveLength(5);
    // ZZ-A wave 2 · Feb-2026 — The ``RecentDocsSection``
    // perf-opt pass (``CustomerDetail.jsx:2794-2802``) added
    // ``&limit=5&slim=1`` to both the invoice + estimate GETs so
    // the response payload drops ~30x on wide customer accounts
    // (118KB → 3.2KB preview). The old exact-string
    // ``toHaveBeenCalledWith("/quotes?doc_type=invoice&customer_id=c-1")``
    // assertion predates that; widened to ``stringContaining``
    // so the perf-opt params + any future append-only params
    // (e.g. ``&cursor=…``) don't retrigger this stale lock.
    expect(api.get).toHaveBeenCalledWith(
      expect.stringContaining("/quotes?doc_type=invoice&customer_id=c-1"),
    );
  });

  it("b. renders 3 invoice rows when 3 invoices are returned", async () => {
    const api = _mkApi({ invoices: _mkInvoices(3), estimates: [] });
    _wrap(<RecentDocsSection customerId="c-1" api={api} />);
    await waitFor(() =>
      expect(screen.getByTestId("cd-recent-invoices-list")).toBeTruthy(),
    );
    const rows = screen.getAllByTestId(/^cd-recent-invoices-row-inv-\d+$/);
    expect(rows).toHaveLength(3);
  });

  it("c. renders empty-state copy when 0 docs are returned (both sections)", async () => {
    const api = _mkApi({ invoices: [], estimates: [] });
    _wrap(<RecentDocsSection customerId="c-1" api={api} />);
    await waitFor(() =>
      expect(screen.getByTestId("cd-recent-invoices-empty")).toBeTruthy(),
    );
    expect(
      screen.getByTestId("cd-recent-invoices-empty").textContent,
    ).toContain("No recent invoices");
    expect(
      screen.getByTestId("cd-recent-estimates-empty").textContent,
    ).toContain("No recent estimates");
  });

  it("d. row click navigates to /invoices/{id} and /quotes/{id} via <Link to=...>", async () => {
    const api = _mkApi({ invoices: _mkInvoices(1), estimates: _mkQuotes(1) });
    _wrap(<RecentDocsSection customerId="c-1" api={api} />);
    await waitFor(() =>
      expect(screen.getByTestId("cd-recent-invoices-link-inv-0")).toBeTruthy(),
    );
    const invLink = screen.getByTestId("cd-recent-invoices-link-inv-0");
    expect(invLink.getAttribute("href")).toBe("/invoices/inv-0");
    const qLink = screen.getByTestId("cd-recent-estimates-link-quote-0");
    expect(qLink.getAttribute("href")).toBe("/quotes/quote-0");
  });

  it("e. an invoice fetch error does NOT blank the estimates section", async () => {
    const api = _mkApi({
      invoices: [],
      estimates: _mkQuotes(2),
      invoicesRejects: true,
    });
    _wrap(<RecentDocsSection customerId="c-1" api={api} />);
    await waitFor(() =>
      expect(screen.getByTestId("cd-recent-estimates-list")).toBeTruthy(),
    );
    // Estimates still render.
    const qRows = screen.getAllByTestId(/^cd-recent-estimates-row-quote-\d+$/);
    expect(qRows).toHaveLength(2);
    // Invoices fall through to the empty-state (silent failure → []).
    expect(screen.getByTestId("cd-recent-invoices-empty")).toBeTruthy();
  });
});

/* ── structural lock: production mount site + endpoint reuse ───── */
describe("CP-2 · structural wiring in CustomerDetail.jsx", () => {
  const SRC = fs.readFileSync(
    path.resolve(process.cwd(), "src/pages/customers/CustomerDetail.jsx"),
    "utf-8",
  );

  it("Overview stack mounts <RecentDocsSection customerId={id} /> (no api prop → real client)", () => {
    expect(SRC).toMatch(/<RecentDocsSection customerId=\{id\} \/>/);
    // No api prop at the production mount site — RecentDocsSection
    // defaults to the imported ``api`` client when ``apiProp`` is
    // undefined.
    expect(SRC).not.toMatch(/<RecentDocsSection[^>]*api=/);
  });

  it("backend endpoint reused — no new /customers/{id}/recent-docs route invented", () => {
    // Reuses the existing GET /api/quotes?doc_type=&customer_id=
    // endpoint (``backend/routers/quotes.py:252``).  CP-2 brief:
    // "If a usable endpoint exists → use it, no backend changes."
    expect(SRC).toMatch(
      /\/quotes\?doc_type=invoice&customer_id=\$\{customerId\}/,
    );
    expect(SRC).toMatch(
      /\/quotes\?doc_type=quote&customer_id=\$\{customerId\}/,
    );
    expect(SRC).not.toMatch(/\/recent-docs/);
  });

  it("Promise.allSettled isolates the two fetches — one failure never blanks the other", () => {
    expect(SRC).toMatch(/Promise\.allSettled\(\[/);
  });
});
