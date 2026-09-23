/**
 * Phase P42 · Feb-2026 — Team roster HARD DELETE UI contract.
 *
 * Distinct from the P23 soft-delete surface. Hard delete physically
 * removes the technician + linked login + pending invitations via
 * DELETE /api/technicians/{tech_id}/hard-delete. Job records are
 * preserved (only ``technician_id`` is nulled on future jobs).
 *
 * Coverage per spec:
 *   1. Kebab shows "Delete Permanently" only on rows with a linked
 *      technician profile (``technician_id`` set).
 *   2. Row confirm → DELETE fires + success message with the
 *      "N future jobs unassigned" copy on the shared ui-kit ``Toast``.
 *   3. Row cancel → no API call, row untouched.
 *   4. 400 ``cannot_delete_self`` → toast copy "You can't delete
 *      your own account. Ask another admin."
 *   5. 400 ``would_orphan_tenant_no_admin_remaining`` → toast copy
 *      "Can't delete — this would leave the tenant with no admin
 *      users."
 *
 * Bulk selection UI on this page is out of scope for P42. Backend
 * bulk endpoint is exercised by ``backend/tests/test_p42_technician_hard_delete.py``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));
vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(async () => true),
}));

const { apiGetMock, apiPostMock, apiPatchMock, apiDelMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(), apiPostMock: vi.fn(),
  apiPatchMock: vi.fn(), apiDelMock: vi.fn(),
}));
vi.mock("@/api", () => ({
  api: {
    get: apiGetMock, post: apiPostMock,
    patch: apiPatchMock, del: apiDelMock,
  },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

const { useAuthMock } = vi.hoisted(() => ({ useAuthMock: vi.fn() }));
vi.mock("@/auth", () => ({
  useAuth: () => useAuthMock(),
  AuthProvider: ({ children }) => <>{children}</>,
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ can: () => true, isAdmin: true }),
}));
vi.mock("@/pages/ops/WorkstreamJobDrawer", () => ({
  __esModule: true, default: () => null,
}));
vi.mock("@/hooks/useAttendance", () => ({
  useAttendance: () => ({ punched_in: false, shifts: [], loading: false }),
}));


async function renderTeamRoster() {
  const { default: OpsHub } = await import("@/pages/ops/OpsHub");
  return render(
    <MemoryRouter initialEntries={["/ops?t=team"]}>
      <OpsHub />
    </MemoryRouter>,
  );
}


beforeEach(() => {
  apiGetMock.mockReset();
  apiPostMock.mockReset();
  apiPatchMock.mockReset();
  apiDelMock.mockReset();
  useAuthMock.mockReset();
  // Default caller: super_admin (broad delete permissions).
  useAuthMock.mockReturnValue({
    user: { id: "actor-1", role: "super_admin", email: "actor@t" },
  });
});


// Two representative rows for the roster.
const TECH_ROW = {
  id: "user-tech-1", name: "Ethan Smith", email: "ethan@t",
  role: "technician", department: "pool",
  technician_id: "tech-ethan-1",
};
const ADMIN_ROW = {
  id: "user-admin-1", name: "Alex Admin", email: "alex@t",
  role: "admin", department: "both",
  technician_id: null,                       // no tech linkage
};


describe("Phase P42 · Team roster hard-delete UI", () => {

  it("test_kebab_shows_delete_permanently_only_on_tech_rows", async () => {
    apiGetMock.mockImplementation((path) => (
      path === "/team"
        ? Promise.resolve([TECH_ROW, ADMIN_ROW])
        : Promise.resolve([])
    ));
    await renderTeamRoster();
    await waitFor(() =>
      expect(screen.getByTestId(`team-row-${TECH_ROW.id}`)).toBeTruthy()
    );

    // Open the tech row's kebab — Delete Permanently is visible.
    fireEvent.click(screen.getByTestId(`team-row-kebab-${TECH_ROW.id}`));
    expect(
      screen.getByTestId(`team-row-hard-delete-btn-${TECH_ROW.id}`)
    ).toBeTruthy();
    // Existing soft-delete entry still there.
    expect(
      screen.getByTestId(`team-row-delete-btn-${TECH_ROW.id}`)
    ).toBeTruthy();

    // Admin row (no technician_id) — kebab renders but Delete
    // Permanently entry does NOT.
    fireEvent.click(screen.getByTestId(`team-row-kebab-${ADMIN_ROW.id}`));
    expect(
      screen.queryByTestId(`team-row-hard-delete-btn-${ADMIN_ROW.id}`)
    ).toBeNull();
  });

  it("test_row_confirm_calls_api_and_shows_success_toast_with_unassigned_count",
      async () => {
        apiGetMock.mockImplementation((path) => (
          path === "/team"
            ? Promise.resolve([TECH_ROW])
            : Promise.resolve([])
        ));
        apiDelMock.mockResolvedValue({
          deleted: true, tech_id: TECH_ROW.technician_id,
          linked_user_deleted: true, pending_invitations_deleted: 0,
          future_jobs_unassigned: 3, audit_id: "aud-1",
        });
        await renderTeamRoster();
        fireEvent.click(
          await screen.findByTestId(`team-row-kebab-${TECH_ROW.id}`)
        );
        fireEvent.click(
          await screen.findByTestId(
            `team-row-hard-delete-btn-${TECH_ROW.id}`
          )
        );
        // Modal is up with the consequence list.
        expect(screen.getByTestId("team-hard-delete-modal")).toBeTruthy();
        expect(screen.getByTestId("team-hard-delete-body").textContent)
          .toContain("technician profile");
        // Confirm.
        fireEvent.click(screen.getByTestId("team-hard-delete-submit"));

        await waitFor(() => {
          expect(apiDelMock).toHaveBeenCalledWith(
            `/technicians/${TECH_ROW.technician_id}/hard-delete`,
          );
        });
        // Local ui-kit ``Toast`` surfaces the success line.
        expect(await screen.findByText(
          /Ethan Smith permanently deleted\. 3 future jobs unassigned\./i,
        )).toBeInTheDocument();
      });

  it("test_row_cancel_leaves_row_intact_no_api_call", async () => {
    apiGetMock.mockImplementation((path) => (
      path === "/team"
        ? Promise.resolve([TECH_ROW])
        : Promise.resolve([])
    ));
    await renderTeamRoster();
    fireEvent.click(
      await screen.findByTestId(`team-row-kebab-${TECH_ROW.id}`)
    );
    fireEvent.click(
      await screen.findByTestId(`team-row-hard-delete-btn-${TECH_ROW.id}`)
    );
    fireEvent.click(await screen.findByTestId("team-hard-delete-cancel"));
    expect(apiDelMock).not.toHaveBeenCalled();
    expect(apiPostMock).not.toHaveBeenCalled();
    expect(
      screen.getByTestId(`team-row-${TECH_ROW.id}`)
    ).toBeTruthy();
  });

  it("test_self_delete_400_shows_specific_error_toast", async () => {
    apiGetMock.mockImplementation((path) => (
      path === "/team"
        ? Promise.resolve([TECH_ROW])
        : Promise.resolve([])
    ));
    // FastAPI HTTPException with a dict detail lands in the wrapped
    // fetch client as an error with ``detail`` on the thrown object.
    const err = new Error("Bad Request");
    err.detail = {
      code: "cannot_delete_self",
      tech_id: TECH_ROW.technician_id,
      message: "…",
    };
    apiDelMock.mockRejectedValue(err);
    await renderTeamRoster();
    fireEvent.click(
      await screen.findByTestId(`team-row-kebab-${TECH_ROW.id}`)
    );
    fireEvent.click(
      await screen.findByTestId(`team-row-hard-delete-btn-${TECH_ROW.id}`)
    );
    fireEvent.click(await screen.findByTestId("team-hard-delete-submit"));

    await waitFor(() => {
      expect(apiDelMock).toHaveBeenCalled();
    });
    expect(await screen.findByText(
      /You can't delete your own account/i,
    )).toBeInTheDocument();
    // Row still there — nothing was actually removed.
    expect(
      screen.getByTestId(`team-row-${TECH_ROW.id}`)
    ).toBeTruthy();
  });

  it("test_orphan_400_shows_specific_error_toast", async () => {
    apiGetMock.mockImplementation((path) => (
      path === "/team"
        ? Promise.resolve([TECH_ROW])
        : Promise.resolve([])
    ));
    const err = new Error("Bad Request");
    err.detail = {
      code: "would_orphan_tenant_no_admin_remaining",
      tech_id: TECH_ROW.technician_id,
      message: "…",
    };
    apiDelMock.mockRejectedValue(err);
    await renderTeamRoster();
    fireEvent.click(
      await screen.findByTestId(`team-row-kebab-${TECH_ROW.id}`)
    );
    fireEvent.click(
      await screen.findByTestId(`team-row-hard-delete-btn-${TECH_ROW.id}`)
    );
    fireEvent.click(await screen.findByTestId("team-hard-delete-submit"));

    await waitFor(() => {
      expect(apiDelMock).toHaveBeenCalled();
    });
    expect(await screen.findByText(
      /would leave the tenant with no admin users/i,
    )).toBeInTheDocument();
    expect(
      screen.getByTestId(`team-row-${TECH_ROW.id}`)
    ).toBeTruthy();
  });

});
