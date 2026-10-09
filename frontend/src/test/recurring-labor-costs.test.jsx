/**
 * Phase 11 · Feb-2026 — Recurring labor costs admin page tests.
 *
 * Lightweight unit tests on the page component + modal. Mocks the
 * ``@/api`` surface so no network traffic fires. Pins the brief
 * cases 1-5 for the FE.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";


let apiGetImpl = vi.fn();
let apiPostImpl = vi.fn();
let apiPatchImpl = vi.fn();
let apiDeleteImpl = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGetImpl(...a),
    post: (...a) => apiPostImpl(...a),
    patch: (...a) => apiPatchImpl(...a),
    delete: (...a) => apiDeleteImpl(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));


import RecurringLaborCostsPage from
  "@/pages/admin/RecurringLaborCostsPage";


const _ROWS = [
  {
    id: "rlc-1",
    label: "Office Manager — Jane Smith",
    monthly_amount: "4500.00",
    start_date: "2026-01-01",
    end_date: null,
    status: "active",
    notes: null,
  },
  {
    id: "rlc-2",
    label: "Bookkeeper (part-time)",
    monthly_amount: "1200.00",
    start_date: "2025-11-01",
    end_date: "2026-02-28",
    status: "inactive",
    notes: "wrapping up",
  },
];


function _resetMocks() {
  apiGetImpl = vi.fn().mockResolvedValue(_ROWS);
  apiPostImpl = vi.fn().mockResolvedValue({ id: "rlc-new" });
  apiPatchImpl = vi.fn().mockResolvedValue({});
  apiDeleteImpl = vi.fn().mockResolvedValue({ ok: true });
}


describe("Phase 11 · RecurringLaborCostsPage", () => {
  beforeEach(() => { _resetMocks(); });
  afterEach(() => cleanup());

  it("1. Renders the page with the existing rows after fetch", async () => {
    render(<RecurringLaborCostsPage />);
    expect(screen.getByTestId("recurring-labor-costs-page")).toBeTruthy();
    expect(screen.getByTestId("rlc-new-btn")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByTestId("rlc-row-rlc-1")).toBeTruthy(),
    );
    expect(screen.getByTestId("rlc-row-rlc-2")).toBeTruthy();
    expect(apiGetImpl).toHaveBeenCalledWith(
      "/recurring-labor-costs?include_inactive=true",
    );
    // Row contents.
    expect(screen.getByTestId("rlc-row-rlc-1").textContent)
      .toContain("Office Manager");
    expect(screen.getByTestId("rlc-row-rlc-1").textContent)
      .toContain("$4,500.00");
  });

  it("2. New button opens create modal, POST fires correct payload", async () => {
    render(<RecurringLaborCostsPage />);
    await waitFor(() =>
      expect(screen.getByTestId("rlc-row-rlc-1")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("rlc-new-btn"));
    expect(screen.getByTestId("recurring-labor-cost-modal")).toBeTruthy();

    fireEvent.change(screen.getByTestId("rlc-label-input"), {
      target: { value: "New Hire" },
    });
    const monthly = screen.getByTestId("rlc-monthly-input");
    fireEvent.focus(monthly);
    fireEvent.change(monthly, { target: { value: "4500.50" } });
    fireEvent.blur(monthly);
    fireEvent.change(screen.getByTestId("rlc-start-date-input"), {
      target: { value: "2026-03-01" },
    });
    fireEvent.click(screen.getByTestId("rlc-modal-save-btn"));

    await waitFor(() => expect(apiPostImpl).toHaveBeenCalled());
    const [url, body] = apiPostImpl.mock.calls[0];
    expect(url).toBe("/recurring-labor-costs");
    expect(body.label).toBe("New Hire");
    expect(body.monthly_amount).toBe("4500.50");
    expect(body.start_date).toBe("2026-03-01");
    expect(body.status).toBe("active");
  });

  it("3. Edit modal pre-populates existing values", async () => {
    render(<RecurringLaborCostsPage />);
    await waitFor(() =>
      expect(screen.getByTestId("rlc-row-rlc-1")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("rlc-row-edit-btn-rlc-1"));
    expect(screen.getByTestId("recurring-labor-cost-modal")).toBeTruthy();
    expect(screen.getByTestId("rlc-label-input").value).toBe(
      "Office Manager — Jane Smith");
    expect(screen.getByTestId("rlc-monthly-input").value).toBe("4500.00");
    expect(screen.getByTestId("rlc-start-date-input").value).toBe(
      "2026-01-01");
  });

  it("4. Inactivate action confirms + fires DELETE", async () => {
    const confirmSpy = vi.spyOn(window, "confirm")
      .mockReturnValue(true);
    render(<RecurringLaborCostsPage />);
    await waitFor(() =>
      expect(screen.getByTestId("rlc-row-rlc-1")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("rlc-row-inactivate-btn-rlc-1"));
    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => expect(apiDeleteImpl).toHaveBeenCalled());
    expect(apiDeleteImpl.mock.calls[0][0]).toBe(
      "/recurring-labor-costs/rlc-1");
    confirmSpy.mockRestore();
  });

  it("5. DecimalInput accepts 4500.50 verbatim", async () => {
    render(<RecurringLaborCostsPage />);
    await waitFor(() =>
      expect(screen.getByTestId("rlc-row-rlc-1")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("rlc-new-btn"));
    const monthly = screen.getByTestId("rlc-monthly-input");
    fireEvent.focus(monthly);
    fireEvent.change(monthly, { target: { value: "4500.50" } });
    expect(monthly.value).toBe("4500.50");
  });

  it("6. Inactive-only rows surface the active-count summary correctly", async () => {
    render(<RecurringLaborCostsPage />);
    await waitFor(() =>
      expect(screen.getByTestId("rlc-row-rlc-1")).toBeTruthy(),
    );
    // 1 active, 2 total — fixture shape.
    expect(screen.getByText(/1 active · 2 total/)).toBeTruthy();
  });

  it("7. Empty-state renders when the fetch returns nothing", async () => {
    apiGetImpl = vi.fn().mockResolvedValue([]);
    render(<RecurringLaborCostsPage />);
    await waitFor(() =>
      expect(screen.getByTestId("rlc-empty-state")).toBeTruthy(),
    );
  });
});
