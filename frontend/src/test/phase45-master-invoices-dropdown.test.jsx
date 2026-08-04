/**
 * Phase 45 · Feb 2026 — Master Invoices "Payers (customers)" picker.
 *
 * Regression + behaviour guard for the pill-grid → searchable
 * multi-select swap. The state contract (a Set<string> of customer
 * ids) is unchanged, so any downstream flow that inspected
 * `pickedCustomers` off the DOM still sees the same shape via the
 * preserved `master-payer-${id}` testid on the option rows.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock the api module — the create page fetches invoices + customers
// on mount; return deterministic fixtures.
const _customers = [
  { id: "c1", name: "Alice Anderson" },
  { id: "c2", name: "Bob Baker" },
  { id: "c3", name: "Carol Chen" },
  { id: "c4", name: "Dan Davis" },
];

vi.mock("@/api", () => ({
  api: {
    get: vi.fn((path) => {
      if (path === "/customers") return Promise.resolve(_customers);
      if (path.startsWith("/quotes")) return Promise.resolve([]);
      return Promise.resolve([]);
    }),
    post: vi.fn(() => Promise.resolve({ id: "m-new" })),
    del: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
  },
}));

import { MasterInvoiceNew } from "@/pages/invoices/MasterInvoice";

const renderPage = () =>
  render(
    <MemoryRouter>
      <MasterInvoiceNew />
    </MemoryRouter>
  );

const openDropdown = async () => {
  const trigger = await screen.findByTestId("master-payer-trigger");
  fireEvent.click(trigger);
  return await screen.findByTestId("master-payer-dropdown");
};

describe("Phase 45 · Master Invoices — payer multi-select", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the searchable multi-select trigger, not a flat pill grid", async () => {
    renderPage();
    // The new picker container must exist.
    expect(await screen.findByTestId("master-payer-multiselect")).toBeInTheDocument();
    expect(await screen.findByTestId("master-payer-trigger")).toBeInTheDocument();
    // Regression guard: no option button rendered outside the popover
    // (i.e. the old always-visible pill grid is gone).
    await waitFor(() => {
      expect(screen.queryByTestId("master-payer-c1")).not.toBeInTheDocument();
    });
    // Counter reads 0 initially.
    expect(screen.getByTestId("master-payer-counter")).toHaveTextContent("0 selected");
  });

  it("opens the dropdown and lists every customer as an option", async () => {
    renderPage();
    await openDropdown();
    for (const c of _customers) {
      expect(screen.getByTestId(`master-payer-${c.id}`)).toBeInTheDocument();
    }
  });

  it("search filters the option list case-insensitively", async () => {
    renderPage();
    await openDropdown();
    const input = screen.getByTestId("master-payer-search");
    fireEvent.change(input, { target: { value: "car" } });
    // Only Carol Chen matches.
    expect(screen.getByTestId("master-payer-c3")).toBeInTheDocument();
    expect(screen.queryByTestId("master-payer-c1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("master-payer-c2")).not.toBeInTheDocument();
    expect(screen.queryByTestId("master-payer-c4")).not.toBeInTheDocument();
  });

  it("selecting an option adds a chip and increments the counter", async () => {
    renderPage();
    await openDropdown();
    fireEvent.click(screen.getByTestId("master-payer-c2"));
    // Chip appears above the trigger.
    expect(await screen.findByTestId("master-payer-chip-c2")).toBeInTheDocument();
    // aria-selected flips on the option row.
    await waitFor(() => {
      expect(screen.getByTestId("master-payer-c2")).toHaveAttribute("aria-selected", "true");
    });
    // Counter updates.
    expect(screen.getByTestId("master-payer-counter")).toHaveTextContent("1 selected");
  });

  it("removing a chip drops the selection", async () => {
    renderPage();
    await openDropdown();
    fireEvent.click(screen.getByTestId("master-payer-c2"));
    await screen.findByTestId("master-payer-chip-c2");
    fireEvent.click(screen.getByTestId("master-payer-chip-remove-c2"));
    await waitFor(() => {
      expect(screen.queryByTestId("master-payer-chip-c2")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("master-payer-counter")).toHaveTextContent("0 selected");
  });

  it("select-all-filtered adds every visible customer; clear all wipes selections", async () => {
    renderPage();
    await openDropdown();
    // Filter to two customers (both names contain "a" — Alice, Baker, Davis, Anderson…).
    fireEvent.change(screen.getByTestId("master-payer-search"), { target: { value: "chen" } });
    fireEvent.click(screen.getByTestId("master-payer-select-all"));
    await waitFor(() => {
      expect(screen.getByTestId("master-payer-counter")).toHaveTextContent("1 selected");
    });
    // Now clear the search, select all remaining filtered (which is all 4).
    fireEvent.change(screen.getByTestId("master-payer-search"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("master-payer-select-all"));
    await waitFor(() => {
      expect(screen.getByTestId("master-payer-counter")).toHaveTextContent("4 selected");
    });
    // Clear all wipes the whole set.
    fireEvent.click(screen.getByTestId("master-payer-clear-inline"));
    await waitFor(() => {
      expect(screen.getByTestId("master-payer-counter")).toHaveTextContent("0 selected");
    });
  });

  it("renders the empty state when the search matches nothing", async () => {
    renderPage();
    await openDropdown();
    fireEvent.change(screen.getByTestId("master-payer-search"), { target: { value: "zzz-none" } });
    const empty = await screen.findByTestId("master-payer-empty");
    expect(empty.textContent).toMatch(/no customers match/i);
    expect(empty.textContent).toContain("zzz-none");
  });

  it("preserves the 'Pick at least 1 invoice' guard by keeping the submit button testid", async () => {
    renderPage();
    // The label + submit button testids must remain untouched — the
    // multi-select swap is presentation-only.
    expect(await screen.findByTestId("master-label")).toBeInTheDocument();
    expect(await screen.findByTestId("master-submit")).toBeInTheDocument();
  });
});
