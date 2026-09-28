/**
 * HARD-DELETE · HD-B · Feb-2026 — JobDetail "Move to Trash" tests.
 *
 * The delete button on JobDetail is inside the ``jd-admin-action-row``
 * container which itself is only rendered for ``isAdmin`` (admin +
 * super_admin). We exercise the shared HardDeleteModal in isolation
 * because JobDetail's mount graph pulls too many context providers
 * for a unit test — the modal's contract is what matters for HD-B.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";

const postMock = vi.fn();
const navigateMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(() => Promise.resolve({})),
    post: (...a) => postMock(...a),
    put: () => Promise.resolve({}),
    patch: () => Promise.resolve({}),
    del: () => Promise.resolve({}),
    delete: () => Promise.resolve({}),
    request: () => Promise.resolve({}),
  },
  TOKEN_KEY: "token",
  api_base: () => "/api",
}));

vi.mock("sonner", () => ({
  toast: {
    success: (m) => toastSuccess(m),
    error: (m) => toastError(m),
  },
}));

import HardDeleteModal from "@/components/hard_delete/HardDeleteModal";

function JobHarness({ role = "admin" }) {
  const [open, setOpen] = React.useState(false);
  const isAdmin = role === "admin" || role === "super_admin";
  return (
    <div>
      {isAdmin ? (
        <button data-testid="jd-hard-delete-btn" onClick={() => setOpen(true)}>
          Move to Trash
        </button>
      ) : null}
      <HardDeleteModal
        open={open}
        entityType="job"
        entityId="job-123"
        entityLabel="Weekly pool clean"
        testidPrefix="jd-hard-delete"
        onClose={() => setOpen(false)}
        onSuccess={() => {
          setOpen(false);
          setTimeout(() => navigateMock("/customers/cust-1"), 400);
        }}
        onBlocked={() => setOpen(false)}
      />
    </div>
  );
}

beforeEach(() => {
  postMock.mockReset();
  navigateMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
});
afterEach(cleanup);

describe("JobDetail · Move to Trash (HD-B)", () => {
  it("shows the button for admin, hides for technician", () => {
    const { rerender } = render(<JobHarness role="admin" />);
    expect(screen.getByTestId("jd-hard-delete-btn")).toBeInTheDocument();
    rerender(<JobHarness role="technician" />);
    expect(
      screen.queryByTestId("jd-hard-delete-btn")
    ).not.toBeInTheDocument();
  });

  it("opens modal, loads preview, gates 8-char reason", async () => {
    postMock.mockResolvedValue({
      ok: true,
      entity_type: "job",
      child_counts: { service_reports: 2, files: 1 },
      external_refs: [],
      would_block_purge: false,
    });
    render(<JobHarness role="admin" />);
    fireEvent.click(screen.getByTestId("jd-hard-delete-btn"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/hard-delete/job/job-123/preview-cascade",
        null
      )
    );
    const confirm = await screen.findByTestId("jd-hard-delete-confirm");
    expect(confirm).toBeDisabled();

    fireEvent.change(screen.getByTestId("jd-hard-delete-reason"), {
      target: { value: "customer canceled service" },
    });
    expect(confirm).not.toBeDisabled();
  });

  it("success — posts /soft, toasts, navigates to parent customer", async () => {
    postMock.mockImplementation((path) => {
      if (path.endsWith("/preview-cascade")) {
        return Promise.resolve({
          ok: true, child_counts: {}, external_refs: [],
          would_block_purge: false,
        });
      }
      return Promise.resolve({ ok: true });
    });
    render(<JobHarness role="admin" />);
    fireEvent.click(screen.getByTestId("jd-hard-delete-btn"));
    await screen.findByTestId("jd-hard-delete-confirm");
    fireEvent.change(screen.getByTestId("jd-hard-delete-reason"), {
      target: { value: "cleanup test data" },
    });
    fireEvent.click(screen.getByTestId("jd-hard-delete-confirm"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/hard-delete/job/job-123/soft",
        { reason: "cleanup test data" }
      )
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 500));
    expect(navigateMock).toHaveBeenCalledWith("/customers/cust-1");
  });
});
