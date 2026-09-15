/**
 * Phase R1 · Feb-2026 — Recurring Jobs Bulk Hard Delete UI tests.
 *
 * Locks the acceptance behaviour on ``pages/admin/RecurringJobs.jsx``:
 *
 *   1. Header ``recurring-select-all`` toggles every visible row
 *      checkbox on + off.
 *   2. Toolbar bulk button reads
 *      ``recurring-bulk-hard-delete`` — disabled at count 0, label
 *      appends the running count when > 0.
 *   3. Confirmation modal (``recurring-bulk-hard-delete-modal``)
 *      keeps the primary "Permanently Delete" button DISABLED
 *      until the ack checkbox is ticked.
 *   4. Truthful toast — on a mocked partial-failure summary
 *      (``{templates_deleted:2, errors:1}``) the warning toast
 *      fires with the right copy; on a clean happy path the
 *      success toast fires.
 *
 * The mount uses the real component with ``@/api`` stubbed so we
 * exercise the checkbox / bulk-delete state machine end-to-end.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("sonner", () => {
  const _toast = Object.assign(vi.fn(), {
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    info:    vi.fn(),
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

// ChartJS / lucide-react auto-mock — the recurring page pulls in a
// couple of lucide icons; they render as inline SVGs so no shim
// needed.  CustomerCombobox needs a tenant + api hook though —
// stub it out entirely.
vi.mock("@/components/customers/CustomerCombobox", () => ({
  default: () => null,
}));
vi.mock("@/components/recurring/MonthlyNthWeekdaySelector", () => ({
  MonthlyNthWeekdaySelector: () => null,
}));

import RecurringJobs from "@/pages/admin/RecurringJobs";
import { api } from "@/api";
import { toast } from "sonner";


const _stubItems = [
  { id: "tpl-a", customer_name: "Alice",   service_type: "Pool Cleaning",
     frequency: "weekly", day_of_week: 0, price_cents: 12500,
     active: true, is_active: true, upcoming: [] },
  { id: "tpl-b", customer_name: "Bob",     service_type: "Landscape",
     frequency: "monthly", day_of_month: 15, price_cents: 8000,
     active: true, is_active: true, upcoming: [] },
  { id: "tpl-c", customer_name: "Charlie", service_type: "Pool Cleaning",
     frequency: "biweekly", day_of_week: 2, price_cents: 15000,
     active: false, is_active: true, upcoming: [] },
];


beforeEach(() => {
  api.get.mockImplementation((path) => {
    if (path.startsWith("/recurring-jobs")) {
      return Promise.resolve({ items: _stubItems });
    }
    if (path.startsWith("/customers")) return Promise.resolve([]);
    if (path.startsWith("/technicians")) return Promise.resolve([]);
    if (path.startsWith("/crews")) return Promise.resolve({ items: [] });
    return Promise.resolve({});
  });
  api.post.mockReset();
  Object.values(toast).forEach((fn) => { if (typeof fn === "function") fn.mockReset?.(); });
});
afterEach(() => vi.clearAllMocks());


async function _mount() {
  const view = render(<RecurringJobs />);
  await waitFor(() =>
    expect(screen.getByTestId("recurring-row-checkbox-tpl-a")).toBeTruthy(),
  );
  return view;
}


describe("RecurringJobs · Phase R1 bulk hard delete", () => {
  it("header select-all toggles every visible row checkbox on + off", async () => {
    await _mount();
    const selectAll = screen.getByTestId("recurring-select-all");
    fireEvent.click(selectAll);
    expect(screen.getByTestId("recurring-row-checkbox-tpl-a").checked).toBe(true);
    expect(screen.getByTestId("recurring-row-checkbox-tpl-b").checked).toBe(true);
    expect(screen.getByTestId("recurring-row-checkbox-tpl-c").checked).toBe(true);
    // Toggle off.
    fireEvent.click(selectAll);
    expect(screen.getByTestId("recurring-row-checkbox-tpl-a").checked).toBe(false);
    expect(screen.getByTestId("recurring-row-checkbox-tpl-b").checked).toBe(false);
    expect(screen.getByTestId("recurring-row-checkbox-tpl-c").checked).toBe(false);
  });

  it("bulk button is disabled at count 0, label shows count when > 0", async () => {
    await _mount();
    const btn = screen.getByTestId("recurring-bulk-hard-delete");
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain("Delete permanently");
    // Pick two rows.
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-a"));
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-b"));
    expect(btn.disabled).toBe(false);
    // Label now carries the running count.
    expect(btn.textContent).toMatch(/Delete permanently \(2\)/);
  });

  it("confirm button stays disabled until the ack checkbox is ticked", async () => {
    await _mount();
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-a"));
    fireEvent.click(screen.getByTestId("recurring-bulk-hard-delete"));
    await waitFor(() =>
      expect(screen.getByTestId("recurring-bulk-hard-delete-modal")).toBeTruthy(),
    );
    const confirmBtn = screen.getByTestId("recurring-bulk-hard-delete-confirm");
    expect(confirmBtn.disabled).toBe(true);
    // Tick the ack.
    fireEvent.click(screen.getByTestId("recurring-bulk-hard-delete-ack"));
    expect(confirmBtn.disabled).toBe(false);
    // Untick — button re-disables.
    fireEvent.click(screen.getByTestId("recurring-bulk-hard-delete-ack"));
    expect(confirmBtn.disabled).toBe(true);
  });

  it("clean happy-path fires the success toast with the truthful copy", async () => {
    api.post.mockResolvedValue({
      results: [
        { recurring_job_id: "tpl-a", status: "deleted", future_visits_deleted: 4 },
        { recurring_job_id: "tpl-b", status: "deleted", future_visits_deleted: 3 },
      ],
      summary: {
        templates_deleted: 2, future_visits_deleted: 7, errors: 0,
      },
    });
    await _mount();
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-a"));
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-b"));
    fireEvent.click(screen.getByTestId("recurring-bulk-hard-delete"));
    await waitFor(() =>
      expect(screen.getByTestId("recurring-bulk-hard-delete-modal")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("recurring-bulk-hard-delete-ack"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("recurring-bulk-hard-delete-confirm"));
      await new Promise((r) => setTimeout(r, 10));
    });
    // Endpoint hit with the selected ids.
    expect(api.post).toHaveBeenCalledWith(
      "/recurring-jobs/bulk-delete",
      { recurring_job_ids: ["tpl-a", "tpl-b"] },
    );
    // Success toast fired with truthful copy.
    expect(toast.success).toHaveBeenCalled();
    const msg = String(toast.success.mock.calls[0][0]);
    expect(msg).toContain("Deleted 2 templates");
    expect(msg).toContain("7 future visits");
    expect(toast.warning).not.toHaveBeenCalled();
  });

  it("partial-failure summary fires the warning toast, NOT success", async () => {
    api.post.mockResolvedValue({
      results: [
        { recurring_job_id: "tpl-a", status: "deleted",   future_visits_deleted: 4 },
        { recurring_job_id: "tpl-b", status: "deleted",   future_visits_deleted: 2 },
        { recurring_job_id: "tpl-c", status: "forbidden", future_visits_deleted: 0 },
      ],
      summary: {
        templates_deleted: 2, future_visits_deleted: 6, errors: 1,
      },
    });
    await _mount();
    fireEvent.click(screen.getByTestId("recurring-select-all"));
    fireEvent.click(screen.getByTestId("recurring-bulk-hard-delete"));
    await waitFor(() =>
      expect(screen.getByTestId("recurring-bulk-hard-delete-modal")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("recurring-bulk-hard-delete-ack"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("recurring-bulk-hard-delete-confirm"));
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(toast.warning).toHaveBeenCalled();
    const msg = String(toast.warning.mock.calls[0][0]);
    expect(msg).toMatch(/Deleted 2 of 3/);
    expect(msg).toMatch(/1 failed/);
    // Success toast must NOT fire on any per-id error.
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("Cancel closes the modal without hitting the endpoint", async () => {
    await _mount();
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-a"));
    fireEvent.click(screen.getByTestId("recurring-bulk-hard-delete"));
    await waitFor(() =>
      expect(screen.getByTestId("recurring-bulk-hard-delete-modal")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("recurring-bulk-hard-delete-cancel"));
    await waitFor(() =>
      expect(screen.queryByTestId("recurring-bulk-hard-delete-modal")).toBeNull(),
    );
    expect(api.post).not.toHaveBeenCalled();
  });
});
