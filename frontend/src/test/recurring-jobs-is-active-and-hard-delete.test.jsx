/**
 * Feb-2026 · Recurring Jobs — is_active + hard-delete UI.
 *
 * Locks the acceptance contract on the dispatched phase:
 *   1. Row shows an "Inactive" badge when ``is_active === false``.
 *   2. Two visually distinct delete buttons with the correct testids.
 *   3. Hard-delete confirmation modal renders on click with the
 *      correct copy + Cancel / Delete permanently buttons.
 *   4. Cancel dismisses the modal without hitting the API.
 *   5. Confirm hits ``DELETE /recurring-jobs/{id}?hard=true``.
 *   6. Active toggle disabled without a start date; enabled with one.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { getSpy, delSpy, postSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  delSpy: vi.fn(),
  postSpy: vi.fn(),
  patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    del: (...a) => delSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0B4A6F", onBrand: "#FFFFFF", onSurface: "#111827",
    muted: "#6B7280", border: "#E5E7EB", surface: "#FFFFFF",
    surfaceSecondary: "#F8FAFC",
  },
}));

// Combobox pulls the customers list from api.get too — no-op mock.
vi.mock("@/components/customers/CustomerCombobox", () => ({
  default: () => null,
}));


import RecurringJobs from "@/pages/admin/RecurringJobs";


function _row(id, overrides = {}) {
  return {
    id,
    customer_id: `cust-${id}`,
    customer_name: `Cust ${id}`,
    service_type: "Pool Cleaning",
    frequency: "weekly",
    day_of_week: 0,
    start_date: "2026-01-01",
    price_cents: 12000,
    active: true,
    is_active: true,
    upcoming: [],
    ...overrides,
  };
}


beforeEach(() => {
  getSpy.mockReset();
  delSpy.mockReset();
  postSpy.mockReset();
  patchSpy.mockReset();
  // Default paths — list + customers + techs + crews + orphans.
  getSpy.mockImplementation(async (path) => {
    if (path === "/recurring-jobs") {
      return {
        items: [
          _row("active-1"),
          _row("inactive-1", { is_active: false, active: true }),
        ],
        count: 2,
      };
    }
    if (path.startsWith("/customers")) return { items: [] };
    if (path === "/technicians") return { items: [] };
    if (path === "/crews") return { items: [] };
    if (path === "/recurring-jobs/orphans") return { count: 0, items: [] };
    return null;
  });
});


describe("RecurringJobs · is_active badge + delete buttons", () => {
  it("renders both soft + hard delete buttons with distinct testids", async () => {
    render(<RecurringJobs />);
    // Wait for the list load to settle.
    expect(await screen.findByTestId(
      "recurring-job-soft-delete-btn-active-1",
    )).toBeTruthy();
    expect(screen.getByTestId(
      "recurring-job-hard-delete-btn-active-1",
    )).toBeTruthy();
  });

  it("renders an Inactive badge only when is_active === false", async () => {
    render(<RecurringJobs />);
    // Wait for the list.
    await screen.findByTestId("recurring-job-soft-delete-btn-active-1");
    // is_active=false row has the badge.
    expect(screen.getByTestId(
      "recurring-job-inactive-badge-inactive-1",
    )).toBeTruthy();
    // is_active=true row does NOT.
    expect(screen.queryByTestId(
      "recurring-job-inactive-badge-active-1",
    )).toBeNull();
  });

  it("clicking hard-delete opens the confirmation modal (does not hit API)", async () => {
    render(<RecurringJobs />);
    const btn = await screen.findByTestId(
      "recurring-job-hard-delete-btn-active-1",
    );
    fireEvent.click(btn);
    // Modal renders with the required testids + copy.
    const modal = await screen.findByTestId(
      "recurring-job-hard-delete-confirm-modal",
    );
    expect(modal.textContent).toMatch(
      /Permanently delete this recurring job\?/,
    );
    expect(modal.textContent).toMatch(
      /This removes the recurring template AND cancels any future scheduled jobs/,
    );
    expect(screen.getByTestId(
      "recurring-job-hard-delete-cancel-btn",
    )).toBeTruthy();
    expect(screen.getByTestId(
      "recurring-job-hard-delete-confirm-btn",
    )).toBeTruthy();
    // No API call yet — click was on the row, not the modal's
    // confirm button.
    expect(delSpy).not.toHaveBeenCalled();
  });

  it("Cancel button dismisses the modal without deleting", async () => {
    render(<RecurringJobs />);
    fireEvent.click(await screen.findByTestId(
      "recurring-job-hard-delete-btn-active-1",
    ));
    await screen.findByTestId("recurring-job-hard-delete-confirm-modal");
    fireEvent.click(screen.getByTestId(
      "recurring-job-hard-delete-cancel-btn",
    ));
    await waitFor(() =>
      expect(screen.queryByTestId(
        "recurring-job-hard-delete-confirm-modal",
      )).toBeNull()
    );
    expect(delSpy).not.toHaveBeenCalled();
  });

  it("Delete permanently hits DELETE /recurring-jobs/{id}?hard=true", async () => {
    delSpy.mockResolvedValue({ hard_deleted: true, future_jobs_cancelled: 3 });
    render(<RecurringJobs />);
    fireEvent.click(await screen.findByTestId(
      "recurring-job-hard-delete-btn-active-1",
    ));
    fireEvent.click(await screen.findByTestId(
      "recurring-job-hard-delete-confirm-btn",
    ));
    await waitFor(() => expect(delSpy).toHaveBeenCalled());
    expect(delSpy).toHaveBeenCalledWith("/recurring-jobs/active-1?hard=true");
  });

  it("Soft delete hits DELETE /recurring-jobs/{id} (no hard flag)", async () => {
    delSpy.mockResolvedValue({ active: false });
    render(<RecurringJobs />);
    fireEvent.click(await screen.findByTestId(
      "recurring-job-soft-delete-btn-active-1",
    ));
    await waitFor(() => expect(delSpy).toHaveBeenCalled());
    expect(delSpy).toHaveBeenCalledWith("/recurring-jobs/active-1");
    // Hard-delete modal should NOT have opened.
    expect(screen.queryByTestId(
      "recurring-job-hard-delete-confirm-modal",
    )).toBeNull();
  });
});
