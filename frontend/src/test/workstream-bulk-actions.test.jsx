/**
 * Feb-2026 · Workstream bulk-actions + inline-edit regression tests.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


let _postResolver;
const mockGet = vi.fn((path) => {
  if (path.startsWith("/workstream/jobs")) {
    return Promise.resolve({
      jobs: [
        {
          id: "j-1",
          title: "Weekly Service · Alpha",
          service_type: "Weekly Pool Service",
          status: "completed",
          customer_name: "Alpha Customer",
          technician_id: "tech-a",
          technician_name: "Alex Tech",
          scheduled_date: "2027-02-01",
        },
        {
          id: "j-2",
          title: "Repair · Beta",
          service_type: "Pump Repair",
          status: "completed",
          customer_name: "Beta Customer",
          technician_id: "tech-b",
          technician_name: "Bella Tech",
          scheduled_date: "2027-02-01",
        },
        {
          id: "j-3",
          title: "Landscape · Gamma",
          service_type: "Landscaping",
          status: "in_progress",
          customer_name: "Gamma Customer",
          technician_id: "tech-a",
          technician_name: "Alex Tech",
          scheduled_date: "2027-02-01",
        },
      ],
      count: 3,
    });
  }
  if (path.startsWith("/technicians")) return Promise.resolve([]);
  if (path.startsWith("/customers")) return Promise.resolve([]);
  return Promise.resolve({});
});
const mockPost = vi.fn(() => new Promise((resolve) => { _postResolver = resolve; }));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    put: vi.fn(() => Promise.resolve({})),
    del: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
  },
  TOKEN_KEY: "auth_token",
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  }),
}));

// Auth hook — swapped per test to exercise each role.
let _role = "super_admin";
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u-1", role: _role, name: "Super", email: "s@x.com" },
    loading: false,
  }),
}));


import WorkstreamPage from "@/pages/workstream/WorkstreamPage";


function mountPage(role) {
  _role = role;
  return render(
    <MemoryRouter initialEntries={["/workstream"]}>
      <WorkstreamPage />
    </MemoryRouter>,
  );
}


beforeEach(() => {
  mockGet.mockClear();
  mockPost.mockClear();
  _postResolver = null;
});


describe("Workstream · bulk-actions + inline-edit", () => {
  it("shows per-row checkbox + Pencil for super_admin", async () => {
    mountPage("super_admin");
    await waitFor(() => expect(screen.getByTestId("ws-job-j-1")).toBeTruthy());
    expect(screen.getByTestId("ws-select-j-1")).toBeTruthy();
    expect(screen.getByTestId("ws-select-j-2")).toBeTruthy();
    expect(screen.getByTestId("ws-edit-j-1")).toBeTruthy();
  });

  it("hides all bulk affordances for technician role — Forbidden banner instead", async () => {
    mountPage("technician");
    // The page renders <Forbidden> for non-admin/manager roles;
    // job cards / checkboxes / Pencils must NOT be present.
    await waitFor(() => {
      expect(screen.queryByTestId("ws-job-j-1")).toBeNull();
      expect(screen.queryByTestId("ws-select-j-1")).toBeNull();
      expect(screen.queryByTestId("ws-edit-j-1")).toBeNull();
      expect(screen.queryByTestId("ws-selection-toolbar")).toBeNull();
      expect(screen.queryByTestId("ws-selection-preselect-bar")).toBeNull();
    });
  });

  it("'Select all in view' selects all visible jobs and toolbar shows the count", async () => {
    mountPage("super_admin");
    await waitFor(() => expect(screen.getByTestId("ws-job-j-1")).toBeTruthy());
    // Pre-selection bar is visible (nothing picked yet).
    expect(screen.getByTestId("ws-selection-preselect-bar")).toBeTruthy();
    fireEvent.click(screen.getByTestId("ws-selection-preselect-select-all"));
    await waitFor(() => {
      expect(screen.getByTestId("ws-selection-toolbar")).toBeTruthy();
    });
    expect(screen.getByTestId("ws-selection-count").textContent)
      .toMatch(/3 selected/);
  });

  it("Delete flow calls /jobs/bulk-delete with the exact selected ids", async () => {
    mountPage("super_admin");
    await waitFor(() => expect(screen.getByTestId("ws-select-j-1")).toBeTruthy());
    fireEvent.click(screen.getByTestId("ws-select-j-1"));
    fireEvent.click(screen.getByTestId("ws-select-j-2"));
    await waitFor(() =>
      expect(screen.getByTestId("ws-selection-toolbar")).toBeTruthy());
    fireEvent.click(screen.getByTestId("ws-selection-delete"));
    await waitFor(() =>
      expect(screen.getByTestId("ws-bulk-delete-title").textContent)
        .toMatch(/Delete 2 jobs\?/));
    fireEvent.click(screen.getByTestId("ws-bulk-delete-confirm"));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    const [path, payload] = mockPost.mock.calls[0];
    expect(path).toBe("/jobs/bulk-delete");
    expect(new Set(payload.ids)).toEqual(new Set(["j-1", "j-2"]));
    // Cleanup — resolve the pending post so nothing hangs.
    _postResolver({ deleted_count: 2, deleted: ["j-1", "j-2"], failed: [] });
  });

  it("Pencil opens ScheduleJobEditModal with the correct job pre-loaded", async () => {
    mountPage("super_admin");
    await waitFor(() => expect(screen.getByTestId("ws-edit-j-2")).toBeTruthy());
    fireEvent.click(screen.getByTestId("ws-edit-j-2"));
    await waitFor(() =>
      expect(screen.getByTestId("schedule-job-edit-modal")).toBeTruthy());
    // The edit form's title input is seeded with the clicked job's title.
    const titleInput = screen.getByTestId("schedule-job-edit-title");
    expect(titleInput.value).toBe("Repair · Beta");
  });

  it("manager role sees checkbox + Pencil + toolbar (parity with admin)", async () => {
    mountPage("manager");
    await waitFor(() => expect(screen.getByTestId("ws-job-j-1")).toBeTruthy());
    expect(screen.getByTestId("ws-select-j-1")).toBeTruthy();
    expect(screen.getByTestId("ws-edit-j-1")).toBeTruthy();
    // Pre-selection bar renders because canBulk = true.
    expect(screen.getByTestId("ws-selection-preselect-bar")).toBeTruthy();
  });
});
