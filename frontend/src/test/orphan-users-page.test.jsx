/**
 * Feb-2026 · Orphan Users admin page.
 *
 * Covers:
 * * Loading + empty state.
 * * Renders rows from GET /admin/orphan-customer-users.
 * * Repair click calls POST /admin/users/{uid}/create-customer-record
 *   and drops the row from the list on success.
 * * Reason label switches for stale_customer_id vs missing_customer_id.
 * * Refresh button calls GET again.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGet(...a),
    post: (...a) => apiPost(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    message: vi.fn(),
  },
}));

import OrphanUsersPage from "@/pages/settings/OrphanUsersPage";


function renderPage() {
  return render(<MemoryRouter><OrphanUsersPage /></MemoryRouter>);
}


beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
});


describe("OrphanUsersPage", () => {
  it("renders empty state when the API returns no orphans", async () => {
    apiGet.mockResolvedValueOnce({ users: [] });
    renderPage();
    expect(await screen.findByTestId("orphan-users-empty"))
      .toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/admin/orphan-customer-users");
  });

  it("renders rows from the API with correct reason labels", async () => {
    apiGet.mockResolvedValueOnce({
      users: [
        {
          id: "u-1",
          tenant_id: "t-1",
          name: "Missing Cid",
          email: "missing@example.com",
          phone: "5551110000",
          created_at: "2026-02-01",
          customer_id: null,
          reason: "missing_customer_id",
        },
        {
          id: "u-2",
          tenant_id: "t-1",
          name: "Stale Cid",
          email: "stale@example.com",
          phone: "5552220000",
          created_at: "2026-02-02",
          customer_id: "does-not-exist",
          reason: "stale_customer_id",
        },
      ],
    });
    renderPage();
    expect(await screen.findByTestId("orphan-users-row-u-1"))
      .toBeInTheDocument();
    expect(screen.getByTestId("orphan-users-reason-u-1"))
      .toHaveTextContent("No linked customer_id");
    expect(screen.getByTestId("orphan-users-reason-u-2"))
      .toHaveTextContent("Stale customer_id");
    expect(screen.getByTestId("orphan-users-email-u-1"))
      .toHaveTextContent("missing@example.com");
  });

  it("clicking Repair calls the repair endpoint and drops the row", async () => {
    apiGet.mockResolvedValueOnce({
      users: [
        {
          id: "u-1",
          tenant_id: "t-1",
          name: "Row One",
          email: "r1@example.com",
          reason: "missing_customer_id",
          customer_id: null,
        },
        {
          id: "u-2",
          tenant_id: "t-1",
          name: "Row Two",
          email: "r2@example.com",
          reason: "missing_customer_id",
          customer_id: null,
        },
      ],
    });
    apiPost.mockResolvedValueOnce({
      ok: true, was_already_linked: false, customer_id: "cust-new",
    });

    renderPage();
    const repairBtn = await screen.findByTestId("orphan-users-repair-u-1");
    fireEvent.click(repairBtn);
    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(
        "/admin/users/u-1/create-customer-record"
      );
    });
    await waitFor(() => {
      expect(screen.queryByTestId("orphan-users-row-u-1"))
        .not.toBeInTheDocument();
    });
    // Row two still there.
    expect(screen.getByTestId("orphan-users-row-u-2")).toBeInTheDocument();
  });

  it("shows the error banner when the API call fails", async () => {
    apiGet.mockRejectedValueOnce(new Error("Network blew up"));
    renderPage();
    expect(await screen.findByTestId("orphan-users-error"))
      .toHaveTextContent(/network blew up/i);
    // Empty state also renders since rows is [] after the catch.
    expect(await screen.findByTestId("orphan-users-empty"))
      .toBeInTheDocument();
  });

  it("Refresh button re-hits the GET endpoint", async () => {
    apiGet.mockResolvedValueOnce({ users: [] });
    renderPage();
    await screen.findByTestId("orphan-users-empty");
    apiGet.mockResolvedValueOnce({ users: [] });
    fireEvent.click(screen.getByTestId("orphan-users-refresh"));
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(2));
  });
});
