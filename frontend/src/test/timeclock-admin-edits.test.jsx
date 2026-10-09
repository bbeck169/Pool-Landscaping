/**
 * Phase 12 · Feb-2026 — Admin Punch Edits · vitest suite.
 *
 * Mocks ``@/api`` so no network traffic fires. Pins the 7 FE cases
 * from the Phase 12 brief:
 *
 *   1. Admin section visible for admin role, hidden for manager/tech.
 *   2. "Add Punch" opens modal.
 *   3. Save fires POST with correct payload (reason + admin_manual).
 *   4. Edit modal pre-populates existing values.
 *   5. Delete confirm dialog + fires DELETE.
 *   6. Overlapping-punch backend error displays inline.
 *   7. Audit log row expand reveals history entries.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor, within,
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


import AdminPunchEditsPanel from
  "@/components/timeclock/AdminPunchEditsPanel";


const _MEMBERS = [
  { user_id: "u-mike", name: "Mike Test" },
  { user_id: "u-carlos", name: "Carlos Test" },
];


const _SHIFT_A = {
  shift_id: "s-aaa",
  user_id: "u-mike",
  clock_in: "2026-02-15T15:00:00.000Z",
  clock_out: "2026-02-15T23:00:00.000Z",
  source: "admin_manual",
  job_id: null,
  edited_by: "admin-id",
  edited_at: "2026-02-15T23:05:00.000Z",
  edit_reason: "payroll fix",
  audit_log: [
    {
      action: "create", edited_by: "admin-id",
      edited_at: "2026-02-15T23:05:00.000Z",
      reason: "payroll fix", before: null,
      after: { clock_in: "2026-02-15T15:00:00.000Z",
                clock_out: "2026-02-15T23:00:00.000Z",
                source: "admin_manual", job_id: null },
    },
    {
      action: "edit", edited_by: "admin-id",
      edited_at: "2026-02-16T01:00:00.000Z",
      reason: "nudged clock_out",
      changes: {
        clock_out: {
          from: "2026-02-15T22:00:00.000Z",
          to: "2026-02-15T23:00:00.000Z",
        },
      },
    },
  ],
  deleted_at: null,
};


beforeEach(() => {
  apiGetImpl = vi.fn(async () => ({ items: [_SHIFT_A], count: 1 }));
  apiPostImpl = vi.fn(async () => _SHIFT_A);
  apiPatchImpl = vi.fn(async () => _SHIFT_A);
  apiDeleteImpl = vi.fn(async () => ({ ok: true }));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});


function _renderAs(role) {
  return render(
    <AdminPunchEditsPanel
      viewer={{ id: "actor", role }}
      teamMembers={_MEMBERS}
    />,
  );
}


describe("Phase 12 · AdminPunchEditsPanel", () => {
  // 1
  it("renders for admin role and hides for manager/tech", () => {
    const { unmount } = _renderAs("admin");
    expect(screen.getByTestId("admin-punch-edits-panel"))
      .toBeTruthy();
    unmount();
    cleanup();
    _renderAs("manager");
    expect(screen.queryByTestId("admin-punch-edits-panel"))
      .toBeNull();
    cleanup();
    _renderAs("technician");
    expect(screen.queryByTestId("admin-punch-edits-panel"))
      .toBeNull();
  });

  // 2
  it("opens the create modal when Add Punch is clicked", async () => {
    _renderAs("admin");
    await waitFor(() =>
      expect(apiGetImpl).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("admin-punch-add-btn"));
    expect(screen.getByTestId("admin-punch-modal"))
      .toBeTruthy();
    expect(screen.getByTestId("admin-punch-modal-user"))
      .toBeTruthy();
  });

  // 3
  it("Save fires POST with reason + admin_manual source",
      async () => {
        _renderAs("admin");
        await waitFor(() =>
          expect(apiGetImpl).toHaveBeenCalled());
        fireEvent.click(screen.getByTestId("admin-punch-add-btn"));
        fireEvent.change(
          screen.getByTestId("admin-punch-modal-user"),
          { target: { value: "u-mike" } },
        );
        fireEvent.change(
          screen.getByTestId("admin-punch-modal-clock-in"),
          { target: { value: "2026-02-18T09:00" } },
        );
        fireEvent.change(
          screen.getByTestId("admin-punch-modal-clock-out"),
          { target: { value: "2026-02-18T17:00" } },
        );
        fireEvent.change(
          screen.getByTestId("admin-punch-modal-reason"),
          { target: { value: "Tech forgot to clock out" } },
        );
        fireEvent.click(
          screen.getByTestId("admin-punch-modal-submit"));
        await waitFor(() =>
          expect(apiPostImpl).toHaveBeenCalled());
        const [path, body] = apiPostImpl.mock.calls[0];
        expect(path).toBe("/timeclock/admin/punches");
        expect(body.user_id).toBe("u-mike");
        expect(body.source).toBe("admin_manual");
        expect(body.reason).toBe("Tech forgot to clock out");
        expect(body.clock_in).toMatch(/T/);
        expect(body.clock_out).toMatch(/T/);
      });

  // 4
  it("Edit modal pre-populates existing values", async () => {
    _renderAs("admin");
    await waitFor(() =>
      expect(screen.getByTestId(`admin-punch-row-${_SHIFT_A.shift_id}`))
        .toBeTruthy());
    fireEvent.click(
      screen.getByTestId(`admin-punch-edit-${_SHIFT_A.shift_id}`));
    const inp = screen.getByTestId("admin-punch-modal-clock-in");
    expect(inp.value).toMatch(/2026-02-15/);
    const src = screen.getByTestId("admin-punch-modal-source");
    expect(src.value).toBe("admin_manual");
    // User select is locked in edit mode.
    const user = screen.getByTestId("admin-punch-modal-user");
    expect(user.disabled).toBe(true);
  });

  // 5
  it("Delete prompts for reason + confirmation then fires DELETE",
      async () => {
        const promptSpy = vi.spyOn(window, "prompt")
          .mockReturnValue("duplicate miss-punch");
        const confirmSpy = vi.spyOn(window, "confirm")
          .mockReturnValue(true);
        _renderAs("admin");
        await waitFor(() =>
          expect(screen.getByTestId(
            `admin-punch-row-${_SHIFT_A.shift_id}`,
          )).toBeTruthy());
        fireEvent.click(
          screen.getByTestId(`admin-punch-delete-${_SHIFT_A.shift_id}`));
        await waitFor(() =>
          expect(apiDeleteImpl).toHaveBeenCalled());
        const [path] = apiDeleteImpl.mock.calls[0];
        expect(path).toContain(
          `/timeclock/admin/punches/${_SHIFT_A.shift_id}`);
        expect(path).toContain("reason=duplicate");
        promptSpy.mockRestore();
        confirmSpy.mockRestore();
      });

  // 6
  it("Overlapping-punch backend error surfaces inline in modal",
      async () => {
        apiPostImpl = vi.fn(async () => {
          const err = new Error("Overlapping punch for this user");
          throw err;
        });
        _renderAs("admin");
        await waitFor(() => expect(apiGetImpl).toHaveBeenCalled());
        fireEvent.click(screen.getByTestId("admin-punch-add-btn"));
        fireEvent.change(
          screen.getByTestId("admin-punch-modal-user"),
          { target: { value: "u-mike" } },
        );
        fireEvent.change(
          screen.getByTestId("admin-punch-modal-clock-in"),
          { target: { value: "2026-02-18T09:00" } },
        );
        fireEvent.change(
          screen.getByTestId("admin-punch-modal-reason"),
          { target: { value: "overlap test" } },
        );
        fireEvent.click(screen.getByTestId("admin-punch-modal-submit"));
        await waitFor(() => {
          const err = screen.getByTestId("admin-punch-modal-error");
          expect(err.textContent.toLowerCase()).toContain("overlap");
        });
      });

  // 7
  it("Audit log expand reveals history entries", async () => {
    _renderAs("admin");
    await waitFor(() =>
      expect(screen.getByTestId(`admin-punch-row-${_SHIFT_A.shift_id}`))
        .toBeTruthy());
    fireEvent.click(
      screen.getByTestId(`admin-punch-expand-${_SHIFT_A.shift_id}`));
    const audit = screen.getByTestId(
      `admin-punch-audit-${_SHIFT_A.shift_id}`);
    expect(audit.textContent).toContain("create");
    expect(audit.textContent).toContain("edit");
    expect(audit.textContent.toLowerCase())
      .toContain("payroll fix");
  });
});
