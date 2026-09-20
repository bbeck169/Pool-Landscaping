/**
 * F1.3 · F1.4 · F1.5 · Feb-2026 — Categories + Leads polish vitest.
 *
 * F1.3 — DELETE-text gate on >20 bulk hard-delete.
 * F1.4 — is_default seed badge for created_by_user_id === "system:seed".
 * F1.5 — drag-drop reorder POSTs /reorder with the new order.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach }
       from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, cleanup, fireEvent, waitFor, within }
       from "@testing-library/react";


const getMock   = vi.fn();
const postMock  = vi.fn();
const patchMock = vi.fn();


vi.mock("@/api", () => ({
  api: {
    get:   (...a) => getMock(...a),
    post:  (...a) => postMock(...a),
    patch: (...a) => patchMock(...a),
    put:   (...a) => postMock(...a),
  },
  TOKEN_KEY: "token",
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
  }),
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}));


// ═══════════════════════════════════════════════════════════════════
// F1.4 · is_default seed badge on CategoriesAdmin.
// ═══════════════════════════════════════════════════════════════════
import CategoriesAdmin from "@/pages/pricebook/CategoriesAdmin";

function _renderCategoriesAdmin() {
  return render(<MemoryRouter><CategoriesAdmin /></MemoryRouter>);
}


beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  patchMock.mockReset();
});
afterEach(() => cleanup());


describe("CategoriesAdmin · F1.4 seed badge", () => {
  it("renders 'Default' badge for system:seed rows only", async () => {
    getMock.mockResolvedValue([
      { id: "seed-1", name: "Pool", is_archived: false,
        sort_order: 0, color: "#0284C7",
        created_by_user_id: "system:seed" },
      { id: "user-1", name: "Custom Category", is_archived: false,
        sort_order: 1, color: "#DC2626",
        created_by_user_id: "user-abc" },
    ]);
    _renderCategoriesAdmin();
    await waitFor(() =>
      expect(screen.getByTestId("income-category-row-seed-1"))
        .toBeInTheDocument());
    expect(screen.getByTestId("income-category-seed-badge-seed-1"))
      .toBeInTheDocument();
    expect(screen.queryByTestId("income-category-seed-badge-user-1"))
      .toBeNull();
  });
});


describe("CategoriesAdmin · F1.5 drag handle rendered", () => {
  it("renders a drag handle for every row", async () => {
    getMock.mockResolvedValue([
      { id: "a", name: "A", is_archived: false, sort_order: 0,
        color: "#123456", created_by_user_id: "system:seed" },
      { id: "b", name: "B", is_archived: false, sort_order: 1,
        color: "#654321", created_by_user_id: "system:seed" },
    ]);
    _renderCategoriesAdmin();
    await waitFor(() =>
      expect(screen.getByTestId("income-category-row-a"))
        .toBeInTheDocument());
    expect(screen.getByTestId("income-category-drag-a")).toBeInTheDocument();
    expect(screen.getByTestId("income-category-drag-b")).toBeInTheDocument();
  });
});


// ═══════════════════════════════════════════════════════════════════
// F1.3 · DELETE-text gate on LeadsDashboardPage bulk hard-delete.
// ═══════════════════════════════════════════════════════════════════
import LeadsDashboardPage from "@/pages/leads/LeadsDashboardPage";

function _renderLeads() {
  return render(<MemoryRouter><LeadsDashboardPage /></MemoryRouter>);
}


function _mkLeads(n) {
  return Array.from({ length: n }, (_, i) => ({
    id: `l${i}`, name: `L${i}`, email: `l${i}@ex.test`,
    status: "new", source: "manual",
    created_at: "2026-02-20T00:00:00Z",
  }));
}


describe("LeadsDashboardPage · F1.3 DELETE-text gate", () => {
  it("gate is hidden when <=20 leads selected", async () => {
    getMock.mockResolvedValue({ rows: _mkLeads(21) });
    _renderLeads();
    await waitFor(() =>
      expect(screen.getByTestId("bulk-select-all")).toBeInTheDocument());
    // Select 20 rows only.
    for (let i = 0; i < 20; i++) {
      fireEvent.click(screen.getByTestId(`bulk-select-row-l${i}`));
    }
    fireEvent.click(screen.getByTestId("bulk-hard-delete-button"));
    await waitFor(() =>
      expect(screen.getByTestId("bulk-hard-delete-confirm"))
        .toBeInTheDocument());
    fireEvent.click(screen.getByTestId("bulk-hard-delete-ack"));
    expect(screen.queryByTestId("bulk-hard-delete-text-gate")).toBeNull();
    // Confirm button enabled once ack ticked (no text needed).
    expect(screen.getByTestId("bulk-hard-delete-confirm-btn"))
      .not.toBeDisabled();
  });

  it("gate is required when >20 leads selected", async () => {
    getMock.mockResolvedValue({ rows: _mkLeads(25) });
    _renderLeads();
    await waitFor(() =>
      expect(screen.getByTestId("bulk-select-all")).toBeInTheDocument());
    // Select all 25.
    fireEvent.click(screen.getByTestId("bulk-select-all"));
    fireEvent.click(screen.getByTestId("bulk-hard-delete-button"));
    await waitFor(() =>
      expect(screen.getByTestId("bulk-hard-delete-text-gate"))
        .toBeInTheDocument());
    fireEvent.click(screen.getByTestId("bulk-hard-delete-ack"));
    // Ack ticked but no text → still disabled.
    expect(screen.getByTestId("bulk-hard-delete-confirm-btn"))
      .toBeDisabled();
    // Wrong text → still disabled.
    fireEvent.change(screen.getByTestId("bulk-hard-delete-text-input"),
                       { target: { value: "delete" } });
    expect(screen.getByTestId("bulk-hard-delete-confirm-btn"))
      .toBeDisabled();
    // Exact match unlocks it.
    fireEvent.change(screen.getByTestId("bulk-hard-delete-text-input"),
                       { target: { value: "DELETE" } });
    expect(screen.getByTestId("bulk-hard-delete-confirm-btn"))
      .not.toBeDisabled();
  });
});
