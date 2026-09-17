/**
 * Feb-2026 · P1 · Recurring Jobs · Auto-Activate + Bulk Activate UI.
 *
 * Locks the acceptance behaviour on ``pages/admin/RecurringJobs.jsx``:
 *
 *   1. Toolbar button ``recurring-bulk-activate`` renders always,
 *      disabled at count 0, label appends running count when > 0.
 *   2. Clicking with N rows selected POSTs to
 *      ``/recurring-jobs/bulk-activate`` with those ids.
 *   3. > 100 selected rows slice into 100-sized batches (multiple
 *      POST calls) so the client never hits the server-side cap.
 *   4. Truthful toast: clean happy-path → success with
 *      "N activated · M visits generated". Mixed batch with
 *      ``skipped_no_start_date`` reports the skipped count. Any
 *      ``failed > 0`` fires warning (not success).
 *   5. After a successful bulk activate, the selection clears.
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
     active: false, is_active: false, upcoming: [] },
  { id: "tpl-b", customer_name: "Bob",     service_type: "Landscape",
     frequency: "monthly", day_of_month: 15, price_cents: 8000,
     active: false, is_active: false, upcoming: [] },
  { id: "tpl-c", customer_name: "Charlie", service_type: "Pool Cleaning",
     frequency: "biweekly", day_of_week: 2, price_cents: 15000,
     active: true, is_active: true, upcoming: [] },
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
  Object.values(toast).forEach((fn) => {
    if (typeof fn === "function") fn.mockReset?.();
  });
});
afterEach(() => vi.clearAllMocks());


async function _mount() {
  const view = render(<RecurringJobs />);
  await waitFor(() =>
    expect(screen.getByTestId("recurring-row-checkbox-tpl-a")).toBeTruthy(),
  );
  return view;
}


describe("RecurringJobs · P1 Bulk Activate + Instant Generation", () => {
  it("button renders always, disabled at count 0, label shows count > 0", async () => {
    await _mount();
    const btn = screen.getByTestId("recurring-bulk-activate");
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain("Bulk Activate");
    // Pick two rows.
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-a"));
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-b"));
    expect(btn.disabled).toBe(false);
    expect(btn.textContent).toMatch(/Bulk Activate \(2\)/);
  });

  it("clean happy-path POSTs the selected ids and fires success toast", async () => {
    api.post.mockResolvedValue({
      activated: 2,
      already_active: 0,
      failed: 0,
      results: [
        { id: "tpl-a", status: "activated",
          generated_count: 3, skipped_no_start_date: false },
        { id: "tpl-b", status: "activated",
          generated_count: 2, skipped_no_start_date: false },
      ],
    });
    await _mount();
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-a"));
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-b"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("recurring-bulk-activate"));
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(api.post).toHaveBeenCalledWith(
      "/recurring-jobs/bulk-activate",
      { recurring_job_ids: ["tpl-a", "tpl-b"] },
    );
    expect(toast.success).toHaveBeenCalled();
    const msg = String(toast.success.mock.calls[0][0]);
    expect(msg).toMatch(/2 activated/);
    expect(msg).toMatch(/5 visits generated/);
    expect(toast.warning).not.toHaveBeenCalled();
  });

  it("mixed batch reports skipped_no_start_date + already_active", async () => {
    api.post.mockResolvedValue({
      activated: 1,
      already_active: 1,
      failed: 0,
      results: [
        { id: "tpl-a", status: "activated",
          generated_count: 0, skipped_no_start_date: true },
        { id: "tpl-c", status: "already_active",
          generated_count: 2, skipped_no_start_date: false },
      ],
    });
    await _mount();
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-a"));
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-c"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("recurring-bulk-activate"));
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(toast.success).toHaveBeenCalled();
    const msg = String(toast.success.mock.calls[0][0]);
    expect(msg).toMatch(/1 activated/);
    expect(msg).toMatch(/1 already active/);
    expect(msg).toMatch(/1 skipped \(missing start date\)/);
  });

  it("any failed > 0 fires warning toast, not success", async () => {
    api.post.mockResolvedValue({
      activated: 1,
      already_active: 0,
      failed: 1,
      results: [
        { id: "tpl-a", status: "activated",
          generated_count: 3, skipped_no_start_date: false },
        { id: "tpl-b", status: "failed",
          generated_count: 0, skipped_no_start_date: false,
          error: "not_found" },
      ],
    });
    await _mount();
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-a"));
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-b"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("recurring-bulk-activate"));
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(toast.warning).toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    const msg = String(toast.warning.mock.calls[0][0]);
    expect(msg).toMatch(/1 activated/);
    expect(msg).toMatch(/1 failed/);
  });

  it("payloads > 100 slice into 100-sized batches client-side", async () => {
    // Craft a page with 105 stub rows so the client MUST slice.
    const bigItems = Array.from({ length: 105 }, (_, i) => ({
      id: `tpl-big-${i}`, customer_name: `Cust ${i}`,
      service_type: "Pool Cleaning", frequency: "weekly", day_of_week: 0,
      price_cents: 10000, active: false, is_active: false, upcoming: [],
    }));
    api.get.mockImplementation((path) => {
      if (path.startsWith("/recurring-jobs")) {
        return Promise.resolve({ items: bigItems });
      }
      return Promise.resolve([]);
    });
    api.post.mockResolvedValue({
      activated: 0, already_active: 0, failed: 0, results: [],
    });
    render(<RecurringJobs />);
    await waitFor(() =>
      expect(screen.getByTestId("recurring-row-checkbox-tpl-big-0")).toBeTruthy(),
    );
    // Select-all in view (105 rows).
    fireEvent.click(screen.getByTestId("recurring-select-all"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("recurring-bulk-activate"));
      await new Promise((r) => setTimeout(r, 20));
    });
    // Client sliced into two batches (100 + 5).
    expect(api.post).toHaveBeenCalledTimes(2);
    const firstCall = api.post.mock.calls[0];
    const secondCall = api.post.mock.calls[1];
    expect(firstCall[0]).toBe("/recurring-jobs/bulk-activate");
    expect(firstCall[1].recurring_job_ids.length).toBe(100);
    expect(secondCall[1].recurring_job_ids.length).toBe(5);
  });

  it("clears the selection after a successful bulk activate", async () => {
    api.post.mockResolvedValue({
      activated: 1, already_active: 0, failed: 0,
      results: [{ id: "tpl-a", status: "activated",
                  generated_count: 1, skipped_no_start_date: false }],
    });
    await _mount();
    fireEvent.click(screen.getByTestId("recurring-row-checkbox-tpl-a"));
    expect(screen.getByTestId("recurring-row-checkbox-tpl-a").checked).toBe(true);
    await act(async () => {
      fireEvent.click(screen.getByTestId("recurring-bulk-activate"));
      await new Promise((r) => setTimeout(r, 10));
    });
    await waitFor(() =>
      expect(screen.getByTestId("recurring-row-checkbox-tpl-a").checked).toBe(false),
    );
  });
});
