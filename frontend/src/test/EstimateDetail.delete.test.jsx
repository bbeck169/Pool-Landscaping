/**
 * HARD-DELETE · HD-B · Feb-2026 — EstimateDetail "Move to Trash" tests.
 *
 * Estimates are backed by the ``quotes`` collection with
 * ``doc_type='estimate'``. HD-A routes both estimates and invoices
 * through ``entity_type='quote'`` because they share the same
 * collection; the tombstone records ``doc_type`` for audit.
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

function EstimateHarness({ role = "admin", isNew = false }) {
  const [open, setOpen] = React.useState(false);
  const isAdmin = role === "admin" || role === "super_admin";
  return (
    <div>
      {!isNew && isAdmin ? (
        <button data-testid="est-hard-delete-btn" onClick={() => setOpen(true)}>
          Move to Trash
        </button>
      ) : null}
      {!isNew ? (
        <HardDeleteModal
          open={open}
          entityType="quote"
          entityId="est-42"
          entityLabel="Landscape estimate — Smith residence"
          testidPrefix="est-hard-delete"
          onClose={() => setOpen(false)}
          onSuccess={() => {
            setOpen(false);
            setTimeout(() => navigateMock("/estimator"), 400);
          }}
          onBlocked={() => setOpen(false)}
        />
      ) : null}
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

describe("EstimateDetail · Move to Trash (HD-B)", () => {
  it("hides the button on new-estimate form (no id yet)", () => {
    render(<EstimateHarness role="admin" isNew />);
    expect(screen.queryByTestId("est-hard-delete-btn")).not.toBeInTheDocument();
  });

  it("shows the button for admin on saved estimate", () => {
    render(<EstimateHarness role="admin" />);
    expect(screen.getByTestId("est-hard-delete-btn")).toBeInTheDocument();
  });

  it("hides the button for non-admin roles", () => {
    render(<EstimateHarness role="technician" />);
    expect(screen.queryByTestId("est-hard-delete-btn")).not.toBeInTheDocument();
  });

  it("routes through the ``quote`` entity_type on soft", async () => {
    postMock.mockImplementation((path) => {
      if (path.endsWith("/preview-cascade"))
        return Promise.resolve({
          ok: true, child_counts: { files: 1 }, external_refs: [],
          would_block_purge: false,
        });
      return Promise.resolve({ ok: true });
    });
    render(<EstimateHarness role="admin" />);
    fireEvent.click(screen.getByTestId("est-hard-delete-btn"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/hard-delete/quote/est-42/preview-cascade",
        null
      )
    );
    fireEvent.change(await screen.findByTestId("est-hard-delete-reason"), {
      target: { value: "customer declined the bid" },
    });
    fireEvent.click(screen.getByTestId("est-hard-delete-confirm"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/hard-delete/quote/est-42/soft",
        { reason: "customer declined the bid" }
      )
    );
    await new Promise((r) => setTimeout(r, 500));
    expect(navigateMock).toHaveBeenCalledWith("/estimator");
  });
});
