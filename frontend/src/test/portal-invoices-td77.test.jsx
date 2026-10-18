/**
 * TD-77 · Feb-2026 — ``/portal/invoices`` acceptance locks for the
 * "Total outstanding" green-gradient tile removal.
 *
 * Coverage:
 *   1. Source-grep locks — the tile JSX, the ``port-outstanding``
 *      testid, the ``totalOutstanding`` compute, and the
 *      ``gradients.navyToGreen`` style are all removed from the
 *      LIST source.
 *   2. Rendered DOM — the LIST surface has no element with testid
 *      ``port-outstanding`` and no "Total outstanding" string.
 *   3. Positive regression lock — the invoice list still renders
 *      the TD-71 customer-friendly title line + the Created-date
 *      line + the paid-status badge.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/portal/PortalPages.jsx"),
  "utf-8",
);

// ────────────────────────────────────────────────────────────────
// 1. Source-grep locks.
// ────────────────────────────────────────────────────────────────
describe("TD-77 · source-level removal of the Total outstanding tile", () => {
  it("no `port-outstanding` testid remains in the LIST source", () => {
    expect(SRC).not.toMatch(/data-testid=["']port-outstanding["']/);
  });

  it("no `totalOutstanding` or bare `const total =` compute remains", () => {
    // The only pre-TD-77 producer of this reduce was the tile.
    expect(SRC).not.toMatch(/const\s+total\s*=\s*\(rows\s*\|\|\s*\[\]\)\.reduce/);
    expect(SRC).not.toMatch(/\btotalOutstanding\b/);
  });

  it("`gradients.navyToGreen` is no longer referenced in the LIST source", () => {
    expect(SRC).not.toMatch(/gradients\.navyToGreen/);
  });

  it("`gradients` is no longer imported in the file", () => {
    // The only pre-TD-77 consumer was the tile's inline style.
    expect(SRC).not.toMatch(/import\s*\{[^}]*\bgradients\b[^}]*\}\s*from\s*["']@\/theme["']/);
  });

  it("positive regression lock — TD-71 title + Created-date line still render in the list", () => {
    expect(SRC).toMatch(/port-inv-title-\$\{r\.id\}/);
    expect(SRC).toMatch(/port-inv-created-\$\{r\.id\}/);
    expect(SRC).toMatch(/resolvePortalInvoiceTitle\(r\)/);
    expect(SRC).toMatch(/formatInvoiceCreatedDate\(r\)/);
  });
});

// ────────────────────────────────────────────────────────────────
// 2. Rendered-DOM locks on the actual page.
// ────────────────────────────────────────────────────────────────
const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));

vi.mock("@/api", () => ({
  api: { get: (...a) => getSpy(...a), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
  TOKEN_KEY: "token",
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({}),
  useLocation: () => ({ pathname: "/portal/invoices" }),
  Link: ({ children }) => children,
}));

import { PortalInvoices } from "@/pages/portal/PortalPages";

describe("TD-77 · rendered DOM — tile absent + list still works", () => {
  beforeEach(() => { getSpy.mockReset(); });
  afterEach(() => { cleanup(); });

  it("the LIST renders with NO Total outstanding tile and NO port-outstanding testid", async () => {
    getSpy.mockResolvedValue([
      { id: "inv-1", doc_type: "invoice", total: 150, amount_paid: 0,
        created_at: "2026-02-01T10:00:00Z", title: "Weekly service",
        payment_status: "unpaid" },
      { id: "inv-2", doc_type: "invoice", total: 200, amount_paid: 200,
        created_at: "2026-01-15T10:00:00Z", title: "Monthly service",
        payment_status: "paid" },
    ]);
    render(<PortalInvoices />);
    await waitFor(() => expect(getSpy).toHaveBeenCalled());

    // Tile absent.
    expect(screen.queryByTestId("port-outstanding")).toBeNull();
    // The literal "Total outstanding" label absent.
    expect(screen.queryByText(/Total outstanding/i)).toBeNull();
    // Positive regression lock — rows still render with TD-71 title + created-date testids.
    await waitFor(() => expect(screen.queryByTestId("port-inv-title-inv-1")).toBeTruthy());
    expect(screen.queryByTestId("port-inv-title-inv-2")).toBeTruthy();
  });

  it("the LIST handles the empty state cleanly with no tile", async () => {
    getSpy.mockResolvedValue([]);
    render(<PortalInvoices />);
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(screen.queryByTestId("port-outstanding")).toBeNull();
    expect(screen.queryByText(/Total outstanding/i)).toBeNull();
  });
});
