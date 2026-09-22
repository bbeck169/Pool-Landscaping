/**
 * Phase R2 · Feb-2026 — Recurring Jobs · Customer search UI tests.
 *
 * Locks the acceptance behaviour on ``pages/admin/RecurringJobs.jsx``:
 *
 *   1. Typing a substring into ``recurring-search-input`` filters
 *      the rendered rows to those whose customer identity contains
 *      that substring (case-insensitive across name / company /
 *      email / phone).
 *   2. Clicking ``recurring-search-clear`` empties the input AND
 *      restores every row.
 *   3. ``recurring-select-all`` under an active filter checks ONLY
 *      the filtered rows — the bulk button's count matches the
 *      filtered length, never the raw list length.
 *
 * The mount uses the real component with ``@/api`` stubbed so we
 * exercise the debounce + memoised filter + bulk-select interplay
 * end-to-end.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("sonner", () => {
  const _toast = Object.assign(vi.fn(), {
    success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn(),
  });
  return { toast: _toast, Toaster: () => null };
});

vi.mock("@/api", () => {
  const _api = {
    get:   vi.fn(),
    post:  vi.fn(),
    patch: vi.fn(),
    del:   vi.fn(),
    put:   vi.fn(),
  };
  return { api: _api };
});

vi.mock("@/components/customers/CustomerCombobox", () => ({
  default: () => null,
}));
vi.mock("@/components/recurring/MonthlyNthWeekdaySelector", () => ({
  MonthlyNthWeekdaySelector: () => null,
}));

// eslint-disable-next-line import/first
import RecurringJobs from "@/pages/admin/RecurringJobs";
// eslint-disable-next-line import/first
import { api } from "@/api";


const _stubItems = [
  { id: "tpl-a",
    customer_name: "Alice Ackerman",
    customer_company_name: "",
    customer_email: "alice@example.com",
    customer_phone: "+15555550001",
    service_type: "Pool Cleaning", frequency: "weekly", day_of_week: 0,
    price_cents: 12500, active: true, is_active: true, upcoming: [] },
  { id: "tpl-b",
    customer_name: "Bob Barker",
    customer_company_name: "Barker LLC",
    customer_email: "bob@barker.co",
    customer_phone: "+15555550002",
    service_type: "Landscape", frequency: "monthly", day_of_month: 15,
    price_cents: 8000, active: true, is_active: true, upcoming: [] },
  { id: "tpl-c",
    customer_name: "Charlie Chen",
    customer_company_name: "",
    customer_email: "charlie@example.com",
    customer_phone: "+15555550003",
    service_type: "Pool Cleaning", frequency: "biweekly", day_of_week: 2,
    price_cents: 15000, active: false, is_active: true, upcoming: [] },
];


beforeEach(() => {
  api.get.mockImplementation((path) => {
    if (path.startsWith("/recurring-jobs")) {
      return Promise.resolve({ items: _stubItems });
    }
    if (path.startsWith("/customers")) return Promise.resolve({ items: [] });
    if (path.startsWith("/technicians")) return Promise.resolve([]);
    if (path.startsWith("/crews")) return Promise.resolve({ items: [] });
    return Promise.resolve({});
  });
  api.post.mockReset();
  api.patch.mockReset();
  api.del.mockReset();
});


async function _tick(ms = 300) {
  // Wait past the 250ms debounce.
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
}


describe("Recurring Jobs · Phase R2 customer search", () => {
  it("filters the list by customer name (case-insensitive)", async () => {
    render(<MemoryRouter><RecurringJobs /></MemoryRouter>);
    // All three rows render initially.
    await waitFor(() => {
      expect(screen.getByTestId("recurring-job-row-tpl-a")).toBeInTheDocument();
      expect(screen.getByTestId("recurring-job-row-tpl-b")).toBeInTheDocument();
      expect(screen.getByTestId("recurring-job-row-tpl-c")).toBeInTheDocument();
    });
    const input = screen.getByTestId("recurring-search-input");
    fireEvent.change(input, { target: { value: "alice" } });
    await _tick();

    // Only Alice's row remains.
    expect(screen.queryByTestId("recurring-job-row-tpl-a")).toBeInTheDocument();
    expect(screen.queryByTestId("recurring-job-row-tpl-b")).toBeNull();
    expect(screen.queryByTestId("recurring-job-row-tpl-c")).toBeNull();

    // Case-insensitive — capital A still finds Alice.
    fireEvent.change(input, { target: { value: "ALICE" } });
    await _tick();
    expect(screen.queryByTestId("recurring-job-row-tpl-a")).toBeInTheDocument();

    // Company name / email also match.
    fireEvent.change(input, { target: { value: "barker" } });
    await _tick();
    expect(screen.queryByTestId("recurring-job-row-tpl-b")).toBeInTheDocument();
    expect(screen.queryByTestId("recurring-job-row-tpl-a")).toBeNull();
  });

  it("clear-button empties the input and restores the full list", async () => {
    render(<MemoryRouter><RecurringJobs /></MemoryRouter>);
    await waitFor(() => screen.getByTestId("recurring-job-row-tpl-a"));

    fireEvent.change(screen.getByTestId("recurring-search-input"),
                       { target: { value: "alice" } });
    await _tick();
    expect(screen.queryByTestId("recurring-job-row-tpl-b")).toBeNull();

    // The clear "×" button only appears when the input is non-empty.
    const clearBtn = screen.getByTestId("recurring-search-clear");
    fireEvent.click(clearBtn);
    await _tick();

    // All three rows are back.
    expect(screen.getByTestId("recurring-job-row-tpl-a")).toBeInTheDocument();
    expect(screen.getByTestId("recurring-job-row-tpl-b")).toBeInTheDocument();
    expect(screen.getByTestId("recurring-job-row-tpl-c")).toBeInTheDocument();
    // Clear button is gone (input is empty now).
    expect(screen.queryByTestId("recurring-search-clear")).toBeNull();
  });

  it("select-all-on-page respects the active search filter", async () => {
    render(<MemoryRouter><RecurringJobs /></MemoryRouter>);
    await waitFor(() => screen.getByTestId("recurring-job-row-tpl-a"));

    // Filter to just Bob.
    fireEvent.change(screen.getByTestId("recurring-search-input"),
                       { target: { value: "bob" } });
    await _tick();
    expect(screen.queryByTestId("recurring-job-row-tpl-a")).toBeNull();
    expect(screen.queryByTestId("recurring-job-row-tpl-c")).toBeNull();

    // Toggle the header select-all — should select ONLY Bob.
    fireEvent.click(screen.getByTestId("recurring-select-all"));
    // Bulk button label carries the running count.
    const bulkBtn = screen.getByTestId("recurring-bulk-hard-delete");
    expect(bulkBtn.textContent).toMatch(/\(1\)/);

    // Sanity — clearing the search must NOT drop the selection
    // (we never un-selected Bob), but the count still reads 1.
    fireEvent.click(screen.getByTestId("recurring-search-clear"));
    await _tick();
    expect(screen.getByTestId("recurring-bulk-hard-delete").textContent)
      .toMatch(/\(1\)/);
  });
});
