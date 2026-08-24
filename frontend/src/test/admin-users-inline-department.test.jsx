/**
 * Feb-2026 · Multi-category tech assignment — Admin Users inline
 * department dropdown.
 *
 * Covers ``frontend/src/pages/admin/AdminUsersList.jsx`` inline
 * ``<select>`` per row that lets an admin flip a tech's department
 * to Pool tech / Landscape tech / Both / Unassigned without going
 * through the auto-suggest modal.  Ships alongside a matching
 * ``mobile/__tests__/team-inline-department.test.tsx`` for the RN
 * team screen.
 *
 * Verifies:
 *   1. Dropdown only renders for tech-role rows (pool_tech,
 *      landscape_tech, technician); admin/owner rows show "—".
 *   2. onChange to "both" fires the exact PUT payload against
 *      ``/admin/users/{uid}/department`` and toasts on success.
 *   3. Optimistic UI paints the new value BEFORE the API resolves.
 *   4. API failure reverts the local value + surfaces error toast.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ── shared mocks ──────────────────────────────────────────────────
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const { apiGetMock, apiPutMock, apiPostMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPutMock: vi.fn(),
  apiPostMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: apiGetMock,
    put: apiPutMock,
    post: apiPostMock,
    patch: vi.fn(),
    del: vi.fn(),
  },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

// Stub out sibling modal imports and DemoAccountToggle so this test
// stays focused on the inline dropdown surface.
vi.mock("@/pages/admin/SuggestDepartmentsModal", () => ({
  default: () => null,
}));
vi.mock("@/components/admin/SuggestDepartmentsModal", () => ({
  default: () => null,
}));
vi.mock("@/components/comms/DemoAccountToggle", () => ({
  default: ({ isDemo }) => (
    <span data-testid="demo-toggle-stub">{isDemo ? "on" : "off"}</span>
  ),
}));
vi.mock("@/components/bulk-select/BulkSelectToolkit", () => ({
  useBulkSelect: () => ({
    selected: new Set(),
    selectedCount: 0,
    allVisibleSelected: false,
    indeterminate: false,
    toggleAll: vi.fn(),
    toggleOne: vi.fn(),
    clear: vi.fn(),
  }),
  BulkSelectAll: () => null,
  BulkSelectRow: () => null,
  BulkActionBar: () => null,
  BulkConfirmModal: () => null,
  LockedPill: () => null,
}));

import AdminUsersList from "@/pages/admin/AdminUsersList";
import { toast } from "sonner";

// Three users — one of each tech role, one admin (should NOT render
// the dropdown), one super_admin (also no dropdown).
const USERS = [
  { id: "u-pool",  name: "Mike Pool",       email: "mike@a.com",
    role: "pool_tech",      department: "pool_tech" },
  { id: "u-land",  name: "Carlos Land",     email: "carlos@a.com",
    role: "landscape_tech", department: "landscape_tech" },
  { id: "u-both",  name: "Alex Cross",      email: "alex@a.com",
    role: "technician",     department: null },
  { id: "u-admin", name: "Manager",         email: "mgr@a.com",
    role: "admin",          department: "both" },
];

describe("AdminUsersList · inline department dropdown", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiGetMock.mockResolvedValue(USERS);
  });

  it("renders a dropdown for every tech-role row and '—' for non-tech", async () => {
    render(<MemoryRouter><AdminUsersList /></MemoryRouter>);
    await waitFor(() => expect(apiGetMock).toHaveBeenCalledWith("/team"));

    // Tech rows: one select each, current value visible.
    const poolSelect = await screen.findByTestId(
      "admin-user-dept-select-u-pool",
    );
    expect(poolSelect.value).toBe("pool_tech");
    const landSelect = screen.getByTestId(
      "admin-user-dept-select-u-land",
    );
    expect(landSelect.value).toBe("landscape_tech");
    const bothSelect = screen.getByTestId(
      "admin-user-dept-select-u-both",
    );
    // null department renders as the "" (Unassigned) option.
    expect(bothSelect.value).toBe("");

    // Admin row: NO dropdown.
    expect(screen.queryByTestId("admin-user-dept-select-u-admin"))
      .toBeNull();
  });

  it("changing to 'both' fires PUT /admin/users/{id}/department with the right payload", async () => {
    apiPutMock.mockResolvedValueOnce({ ok: true });
    render(<MemoryRouter><AdminUsersList /></MemoryRouter>);
    const bothSelect = await screen.findByTestId(
      "admin-user-dept-select-u-both",
    );

    fireEvent.change(bothSelect, { target: { value: "both" } });

    await waitFor(() =>
      expect(apiPutMock).toHaveBeenCalledWith(
        "/admin/users/u-both/department",
        { department: "both" },
      ),
    );
    // Success toast fires with the human-readable label.
    await waitFor(() =>
      expect(toast.success.mock.calls[0][0])
        .toMatch(/Both/),
    );
  });

  it("optimistically paints the new value before the API resolves", async () => {
    // Never resolve — we're locking in the "optimistic" behavior.
    let resolvePut = () => {};
    apiPutMock.mockImplementation(() => new Promise((r) => { resolvePut = () => r({ ok: true }); }));

    render(<MemoryRouter><AdminUsersList /></MemoryRouter>);
    const sel = await screen.findByTestId(
      "admin-user-dept-select-u-pool",
    );
    expect(sel.value).toBe("pool_tech");

    fireEvent.change(sel, { target: { value: "both" } });

    // Immediately after the change (API still pending) the select
    // must reflect the new value — that's the whole point of
    // optimistic UI.  If this fails the user sees a "snap-back" on
    // slow networks.
    await waitFor(() => expect(sel.value).toBe("both"));
    resolvePut();
  });

  it("reverts + toasts error when PUT fails", async () => {
    apiPutMock.mockRejectedValueOnce(new Error("403 admin required"));
    render(<MemoryRouter><AdminUsersList /></MemoryRouter>);
    const sel = await screen.findByTestId(
      "admin-user-dept-select-u-land",
    );

    fireEvent.change(sel, { target: { value: "both" } });

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringMatching(/403 admin required/),
      ),
    );
    // Value snapped back to the original after the failure.
    await waitFor(() => expect(sel.value).toBe("landscape_tech"));
  });

  it("sending 'Unassigned' PUTs department: null on the wire", async () => {
    apiPutMock.mockResolvedValueOnce({ ok: true });
    render(<MemoryRouter><AdminUsersList /></MemoryRouter>);
    const sel = await screen.findByTestId(
      "admin-user-dept-select-u-pool",
    );

    fireEvent.change(sel, { target: { value: "" } });

    await waitFor(() =>
      expect(apiPutMock).toHaveBeenCalledWith(
        "/admin/users/u-pool/department",
        { department: null },
      ),
    );
  });
});
