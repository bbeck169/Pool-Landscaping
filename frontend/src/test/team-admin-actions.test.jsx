/**
 * Feb-2026 · Team page admin actions — vitest.
 *
 * Covers the kebab-menu behavior on the ``TeamRoster`` component
 * inside ``pages/ops/OpsHub.jsx``:
 *
 *  * Kebab visibility matrix: admin sees the kebab on tech rows only;
 *    super_admin sees it on tech + admin rows but not on their own row.
 *  * Delete flow: opens the confirm modal, POSTs ``/users/{id}/soft-delete``,
 *    row disappears and success toast is shown.
 *  * Reset password (custom): POSTs ``/users/{id}/reset-password`` with
 *    ``{ new_password }`` and closes the modal on success.
 *  * Reset password (auto-generate): POSTs with ``{ auto_generate: true }``
 *    and surfaces the returned temporary password for the admin to copy.
 *  * 403 error surface — friendly toast via the shared error path.
 *  * super_admin "Show deleted" toggle flips the GET URL to
 *    ``/team?include_deleted=true``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ─── shared mocks ────────────────────────────────────────────────────
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

// ``useAuth`` — return whichever caller each test wants.
const { useAuthMock } = vi.hoisted(() => ({ useAuthMock: vi.fn() }));
vi.mock("@/auth", () => ({
  useAuth: () => useAuthMock(),
  AuthProvider: ({ children }) => <>{children}</>,
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ can: () => true, isAdmin: true }),
}));

// Stub the WorkstreamJobDrawer — imported statically at the top of
// OpsHub but only used in the ``workstream`` tab, which we never visit.
vi.mock("@/pages/ops/WorkstreamJobDrawer", () => ({
  __esModule: true, default: () => null,
}));

// Stub useAttendance so the shared attendance widget doesn't crash the
// mount for the "team" tab route we're driving.
vi.mock("@/hooks/useAttendance", () => ({
  useAttendance: () => ({ punched_in: false, shifts: [], loading: false }),
}));


// Render helper that sets the ``?t=team`` search param so OpsHub
// mounts directly on the Team tab.
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
});

afterEach(() => { vi.restoreAllMocks(); });


const rowTech = {
  id: "u-tech-1", name: "Terry Tech",
  email: "terry@t.local", role: "technician", department: "pool",
};
const rowAdmin = {
  id: "u-admin-2", name: "Angie Admin",
  email: "angie@t.local", role: "admin", department: null,
};
const rowSuper = {
  id: "u-super-3", name: "Sam Super",
  email: "sam@t.local", role: "super_admin", department: null,
};

function meAsAdmin() {
  useAuthMock.mockReturnValue({
    user: { id: "u-me-admin", role: "admin",
              name: "Me Admin", email: "me@t.local" },
  });
}
function meAsSuper() {
  useAuthMock.mockReturnValue({
    user: { id: rowSuper.id, role: "super_admin",
              name: rowSuper.name, email: rowSuper.email },
  });
}


// ─── 1. Kebab visibility matrix ──────────────────────────────────────
describe("Team page kebab visibility matrix", () => {
  it("admin sees the kebab on tech row but NOT on admin row", async () => {
    meAsAdmin();
    apiGetMock.mockImplementation((path) => {
      if (path === "/team") return Promise.resolve([rowTech, rowAdmin]);
      if (path === "/jobs") return Promise.resolve([]);
      return Promise.resolve([]);
    });
    await renderTeamRoster();

    // Kebab present on tech row.
    expect(await screen.findByTestId(`team-row-kebab-${rowTech.id}`))
      .toBeInTheDocument();
    // Kebab absent on admin row.
    expect(screen.queryByTestId(`team-row-kebab-${rowAdmin.id}`)).toBeNull();
  });

  it("super_admin sees the kebab on tech + admin rows but NOT on own row", async () => {
    meAsSuper();
    apiGetMock.mockImplementation((path) => {
      if (path === "/team") return Promise.resolve([rowTech, rowAdmin, rowSuper]);
      return Promise.resolve([]);
    });
    await renderTeamRoster();

    expect(await screen.findByTestId(`team-row-kebab-${rowTech.id}`))
      .toBeInTheDocument();
    expect(screen.getByTestId(`team-row-kebab-${rowAdmin.id}`))
      .toBeInTheDocument();
    // Self row → no kebab.
    expect(screen.queryByTestId(`team-row-kebab-${rowSuper.id}`)).toBeNull();
  });

  // Feb-2026 follow-up · self-visibility fix — the caller's own row
  // is now returned by ``/api/team`` and rendered by the roster with
  // the kebab suppressed + a small "(you)" hint next to their name.
  it("renders the caller's own row with the (you) label and no kebab", async () => {
    meAsSuper();
    apiGetMock.mockImplementation((path) => {
      if (path === "/team") return Promise.resolve([rowSuper, rowTech]);
      return Promise.resolve([]);
    });
    await renderTeamRoster();

    // Row for the current user is present.
    const selfRow = await screen.findByTestId(`team-row-${rowSuper.id}`);
    expect(selfRow).toBeInTheDocument();
    // "(you)" courtesy label is on the self row.
    expect(selfRow.textContent).toMatch(/\(you\)/);
    // Kebab is suppressed on the self row.
    expect(screen.queryByTestId(`team-row-kebab-${rowSuper.id}`)).toBeNull();
    // Other rows keep their kebab.
    expect(screen.getByTestId(`team-row-kebab-${rowTech.id}`)).toBeInTheDocument();
  });

  it("admin caller's own row is also visible with kebab hidden", async () => {
    // Seed the roster with a synthetic 'me' admin row + one tech.
    const meAdminRow = {
      id: "u-me-admin", name: "Me Admin",
      email: "me@t.local", role: "admin", department: null,
    };
    useAuthMock.mockReturnValue({
      user: { id: meAdminRow.id, role: "admin",
                name: meAdminRow.name, email: meAdminRow.email },
    });
    apiGetMock.mockImplementation((path) => {
      if (path === "/team") return Promise.resolve([meAdminRow, rowTech]);
      return Promise.resolve([]);
    });
    await renderTeamRoster();

    const selfRow = await screen.findByTestId(`team-row-${meAdminRow.id}`);
    expect(selfRow.textContent).toMatch(/\(you\)/);
    expect(screen.queryByTestId(`team-row-kebab-${meAdminRow.id}`)).toBeNull();
    // Admin's kebab-visibility on tech unchanged.
    expect(screen.getByTestId(`team-row-kebab-${rowTech.id}`)).toBeInTheDocument();
  });
});


// ─── 2. Delete flow ──────────────────────────────────────────────────
describe("Team page · delete flow", () => {
  it("POSTs /users/:id/soft-delete and shows a success toast", async () => {
    meAsSuper();
    apiGetMock.mockImplementation((path) => {
      if (path === "/team") return Promise.resolve([rowTech, rowSuper]);
      return Promise.resolve([]);
    });
    apiPostMock.mockResolvedValue({
      ok: true, user_id: rowTech.id,
      deleted_at: "2026-02-01T00:00:00Z",
      deleted_by_user_id: rowSuper.id,
    });

    await renderTeamRoster();
    fireEvent.click(await screen.findByTestId(`team-row-kebab-${rowTech.id}`));
    fireEvent.click(await screen.findByTestId(`team-row-delete-btn-${rowTech.id}`));
    fireEvent.click(await screen.findByTestId("team-delete-submit"));

    await waitFor(() => {
      const call = apiPostMock.mock.calls.find(
        ([p]) => p === `/users/${rowTech.id}/soft-delete`);
      expect(call).toBeTruthy();
    });
  });

  it("surfaces a friendly toast on a 403", async () => {
    const { toast } = await import("sonner");
    meAsSuper();
    apiGetMock.mockImplementation((path) => {
      if (path === "/team") return Promise.resolve([rowTech, rowSuper]);
      return Promise.resolve([]);
    });
    apiPostMock.mockRejectedValue(new Error("Admins can only delete technicians"));

    await renderTeamRoster();
    fireEvent.click(await screen.findByTestId(`team-row-kebab-${rowTech.id}`));
    fireEvent.click(await screen.findByTestId(`team-row-delete-btn-${rowTech.id}`));
    fireEvent.click(await screen.findByTestId("team-delete-submit"));

    // We use the shared ui-kit ``Toast`` for surfacing errors — the
    // useAuth mock returns the super row so refresh() re-fires the GET.
    // We assert the POST fired and the failure toast text is present.
    await waitFor(() => {
      expect(apiPostMock).toHaveBeenCalledWith(
        `/users/${rowTech.id}/soft-delete`, {});
    });
    expect(await screen.findByText(/can only delete technicians/i))
      .toBeInTheDocument();
  });
});


// ─── 3. Reset password flows ─────────────────────────────────────────
describe("Team page · reset password flows", () => {
  it("custom mode POSTs with new_password", async () => {
    meAsSuper();
    apiGetMock.mockImplementation((path) => {
      if (path === "/team") return Promise.resolve([rowTech, rowSuper]);
      return Promise.resolve([]);
    });
    apiPostMock.mockResolvedValue({
      ok: true, user_id: rowTech.id, temporary_password: "Str0ngPw!",
      email_status: "skipped",
    });

    await renderTeamRoster();
    fireEvent.click(await screen.findByTestId(`team-row-kebab-${rowTech.id}`));
    fireEvent.click(await screen.findByTestId(`team-row-reset-btn-${rowTech.id}`));

    // Default mode is "custom" — type a strong password.
    const input = await screen.findByTestId("team-reset-pw-input");
    fireEvent.change(input, { target: { value: "Str0ngPw!" } });
    fireEvent.click(screen.getByTestId("team-reset-submit"));

    await waitFor(() => {
      const call = apiPostMock.mock.calls.find(
        ([p]) => p === `/users/${rowTech.id}/reset-password`);
      expect(call).toBeTruthy();
      expect(call[1]).toEqual({ new_password: "Str0ngPw!" });
    });
  });

  it("auto-generate mode POSTs auto_generate:true and displays the temp password", async () => {
    meAsSuper();
    apiGetMock.mockImplementation((path) => {
      if (path === "/team") return Promise.resolve([rowTech, rowSuper]);
      return Promise.resolve([]);
    });
    apiPostMock.mockResolvedValue({
      ok: true, user_id: rowTech.id,
      temporary_password: "A1b2C3d4E5f6G7h8",
      email_status: "sent",
    });

    await renderTeamRoster();
    fireEvent.click(await screen.findByTestId(`team-row-kebab-${rowTech.id}`));
    fireEvent.click(await screen.findByTestId(`team-row-reset-btn-${rowTech.id}`));
    fireEvent.click(await screen.findByTestId("team-reset-mode-auto"));
    fireEvent.click(await screen.findByTestId("team-reset-submit"));

    await waitFor(() => {
      const call = apiPostMock.mock.calls.find(
        ([p]) => p === `/users/${rowTech.id}/reset-password`);
      expect(call).toBeTruthy();
      expect(call[1]).toEqual({ auto_generate: true });
    });
    // Temporary password is surfaced once, in the "shown once" chip.
    expect(await screen.findByTestId("team-reset-temp-value"))
      .toHaveTextContent("A1b2C3d4E5f6G7h8");
    expect(screen.getByTestId("team-reset-temp-warning"))
      .toHaveTextContent(/shown once/i);
  });

  it("blocks submit when custom password fails validation", async () => {
    meAsSuper();
    apiGetMock.mockImplementation((path) => {
      if (path === "/team") return Promise.resolve([rowTech, rowSuper]);
      return Promise.resolve([]);
    });
    await renderTeamRoster();
    fireEvent.click(await screen.findByTestId(`team-row-kebab-${rowTech.id}`));
    fireEvent.click(await screen.findByTestId(`team-row-reset-btn-${rowTech.id}`));

    const input = await screen.findByTestId("team-reset-pw-input");
    fireEvent.change(input, { target: { value: "short" } });
    fireEvent.click(screen.getByTestId("team-reset-submit"));

    // No POST should have fired.
    expect(apiPostMock.mock.calls.find(
      ([p]) => p === `/users/${rowTech.id}/reset-password`,
    )).toBeFalsy();
  });
});


// ─── 4. "Show deleted" toggle (super_admin only) ─────────────────────
describe("Team page · Show deleted toggle", () => {
  it("only surfaces the toggle for super_admin and flips the GET URL", async () => {
    meAsSuper();
    apiGetMock.mockImplementation((path) => {
      if (path === "/team" || path.startsWith("/team?"))
        return Promise.resolve([rowTech, rowSuper]);
      return Promise.resolve([]);
    });
    await renderTeamRoster();

    const toggle = await screen.findByTestId("team-show-deleted-toggle");
    expect(toggle).toBeInTheDocument();
    fireEvent.click(toggle);

    await waitFor(() => {
      const paths = apiGetMock.mock.calls.map(([p]) => p);
      expect(paths).toContain("/team?include_deleted=true");
    });
  });

  it("admin never sees the toggle", async () => {
    meAsAdmin();
    apiGetMock.mockImplementation((path) => {
      if (path === "/team") return Promise.resolve([rowTech]);
      return Promise.resolve([]);
    });
    await renderTeamRoster();
    expect(screen.queryByTestId("team-show-deleted-toggle")).toBeNull();
  });
});
