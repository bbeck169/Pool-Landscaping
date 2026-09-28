/**
 * HARD-DELETE · HD-B · Feb-2026 — Service Report per-row delete tests.
 *
 * Service reports have no dedicated admin detail page in the web
 * frontend. HD-B ships the "Move to Trash" affordance as an inline
 * per-row action on ``AdminServiceReportsList``. This test drives
 * the HardDeleteModal in isolation with the same testid convention
 * used by the list (``asr-hard-delete-modal-<id>-*``).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";

const postMock = vi.fn();
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

function ServiceReportRow({ role = "admin" }) {
  const [target, setTarget] = React.useState(null);
  const isAdmin = role === "admin" || role === "super_admin";
  return (
    <table>
      <tbody>
        <tr>
          <td>Report 1</td>
          <td>
            {isAdmin ? (
              <button
                data-testid="asr-hard-delete-sr-42"
                onClick={() =>
                  setTarget({ id: "sr-42", customer_name: "Alice Smith" })
                }
              >
                Trash
              </button>
            ) : null}
          </td>
        </tr>
      </tbody>
      {target ? (
        <HardDeleteModal
          open={!!target}
          entityType="service_report"
          entityId={target.id}
          entityLabel={target.customer_name}
          testidPrefix={`asr-hard-delete-modal-${target.id}`}
          onClose={() => setTarget(null)}
          onSuccess={() => setTarget(null)}
          onBlocked={() => setTarget(null)}
        />
      ) : null}
    </table>
  );
}

beforeEach(() => {
  postMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
});
afterEach(cleanup);

describe("ServiceReport · row-level Move to Trash (HD-B)", () => {
  it("shows per-row Trash button for admin", () => {
    render(<ServiceReportRow role="admin" />);
    expect(screen.getByTestId("asr-hard-delete-sr-42")).toBeInTheDocument();
  });

  it("hides Trash button for tech", () => {
    render(<ServiceReportRow role="technician" />);
    expect(
      screen.queryByTestId("asr-hard-delete-sr-42")
    ).not.toBeInTheDocument();
  });

  it("opens modal, previews, and successfully deletes", async () => {
    postMock.mockImplementation((path) => {
      if (path.endsWith("/preview-cascade"))
        return Promise.resolve({
          ok: true, child_counts: { files: 1, photos: 4 },
          external_refs: [], would_block_purge: false,
        });
      return Promise.resolve({ ok: true });
    });
    render(<ServiceReportRow role="admin" />);
    fireEvent.click(screen.getByTestId("asr-hard-delete-sr-42"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/hard-delete/service_report/sr-42/preview-cascade",
        null
      )
    );
    fireEvent.change(
      await screen.findByTestId("asr-hard-delete-modal-sr-42-reason"),
      { target: { value: "duplicate report" } }
    );
    fireEvent.click(
      screen.getByTestId("asr-hard-delete-modal-sr-42-confirm")
    );
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/hard-delete/service_report/sr-42/soft",
        { reason: "duplicate report" }
      )
    );
    expect(toastSuccess).toHaveBeenCalled();
  });
});
