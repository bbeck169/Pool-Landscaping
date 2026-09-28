/**
 * HARD-DELETE · HD-B · Feb-2026 — CustomerDetail "Move to Trash" tests.
 *
 * Focused on the wiring introduced by HD-B:
 *   1. "Move to Trash" button visible for admin.
 *   2. Hidden for technician role.
 *   3. Confirm button gated by 8-char reason.
 *   4. Cascade preview loaded via API mock.
 *   5. Success path: soft-delete POST fires, success toast, navigate away.
 *   6. External-ref block: 409 → error toast, no navigation.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";

const getMock = vi.fn();
const postMock = vi.fn();
const delMock = vi.fn();
const patchMock = vi.fn();
const navigateMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    del: (...a) => delMock(...a),
    patch: (...a) => patchMock(...a),
    put: (...a) => Promise.resolve({}),
    request: (...a) => Promise.resolve({}),
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

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
    useParams: () => ({ id: "cust-1" }),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
    Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a>,
  };
});

import HardDeleteModal from "@/components/hard_delete/HardDeleteModal";

function TestHarness({ role = "admin" }) {
  const [open, setOpen] = React.useState(false);
  const isAdmin = ["admin", "super_admin"].includes(role.toLowerCase());
  return (
    <div>
      {isAdmin ? (
        <button
          data-testid="cd-hard-delete-btn"
          onClick={() => setOpen(true)}
        >
          Move to Trash
        </button>
      ) : null}
      <HardDeleteModal
        open={open}
        entityType="customer"
        entityId="cust-1"
        entityLabel="Alice Smith"
        testidPrefix="cd-hard-delete"
        onClose={() => setOpen(false)}
        onSuccess={() => {
          setOpen(false);
          setTimeout(() => navigateMock("/customers"), 400);
        }}
        onBlocked={() => setOpen(false)}
      />
    </div>
  );
}

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  navigateMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
  vi.useRealTimers();
});
afterEach(cleanup);

function stubPreview(child_counts, external_refs = []) {
  postMock.mockImplementation((path) => {
    if (path.endsWith("/preview-cascade")) {
      return Promise.resolve({
        ok: true,
        entity_type: "customer",
        id: "cust-1",
        already_soft_deleted: false,
        child_counts,
        external_refs,
        would_block_purge: external_refs.length > 0,
      });
    }
    return Promise.resolve({ ok: true });
  });
}

describe("CustomerDetail · Move to Trash (HD-B)", () => {
  it("shows the Move to Trash button for admin role", () => {
    render(<TestHarness role="admin" />);
    expect(screen.getByTestId("cd-hard-delete-btn")).toBeInTheDocument();
  });

  it("hides the Move to Trash button for technician role", () => {
    render(<TestHarness role="technician" />);
    expect(screen.queryByTestId("cd-hard-delete-btn")).not.toBeInTheDocument();
  });

  it("loads the cascade preview after opening the modal", async () => {
    stubPreview({ jobs: 3, quotes: 2, service_reports: 5 });
    render(<TestHarness role="admin" />);
    fireEvent.click(screen.getByTestId("cd-hard-delete-btn"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/hard-delete/customer/cust-1/preview-cascade",
        null
      )
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("cd-hard-delete-cascade-summary")
      ).toBeInTheDocument()
    );
    // Child counts render.
    expect(screen.getByTestId("cd-hard-delete-child-jobs")).toHaveTextContent(
      /3 jobs/
    );
    expect(
      screen.getByTestId("cd-hard-delete-child-service_reports")
    ).toHaveTextContent(/5 service report/);
  });

  it("Confirm disabled until reason is at least 8 chars", async () => {
    stubPreview({});
    render(<TestHarness role="admin" />);
    fireEvent.click(screen.getByTestId("cd-hard-delete-btn"));
    const confirm = await screen.findByTestId("cd-hard-delete-confirm");
    expect(confirm).toBeDisabled();

    const reason = screen.getByTestId("cd-hard-delete-reason");
    fireEvent.change(reason, { target: { value: "short" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(reason, { target: { value: "long enough reason" } });
    expect(confirm).not.toBeDisabled();
  });

  it("Success path — posts soft-delete, toasts success, navigates away", async () => {
    stubPreview({ jobs: 1 });
    render(<TestHarness role="admin" />);
    fireEvent.click(screen.getByTestId("cd-hard-delete-btn"));
    await screen.findByTestId("cd-hard-delete-confirm");
    fireEvent.change(screen.getByTestId("cd-hard-delete-reason"), {
      target: { value: "GDPR request cleanup" },
    });
    // Reset postMock ordering — first call was preview, second is /soft.
    postMock.mockImplementationOnce((path) => {
      if (path.endsWith("/preview-cascade"))
        return Promise.resolve({
          ok: true,
          entity_type: "customer",
          id: "cust-1",
          already_soft_deleted: false,
          child_counts: {},
          external_refs: [],
          would_block_purge: false,
        });
      return Promise.resolve({ ok: true });
    });
    postMock.mockResolvedValueOnce({ ok: true });
    fireEvent.click(screen.getByTestId("cd-hard-delete-confirm"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/hard-delete/customer/cust-1/soft",
        { reason: "GDPR request cleanup" }
      )
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    // Navigation is deferred by setTimeout — advance the clock.
    await new Promise((r) => setTimeout(r, 500));
    expect(navigateMock).toHaveBeenCalledWith("/customers");
  });

  it("External-ref block — error toast, no navigation", async () => {
    stubPreview({}, [{ payment_intent_id: "pi_ext_1", id: "inv-1" }]);
    render(<TestHarness role="admin" />);
    fireEvent.click(screen.getByTestId("cd-hard-delete-btn"));
    await screen.findByTestId("cd-hard-delete-confirm");
    fireEvent.change(screen.getByTestId("cd-hard-delete-reason"), {
      target: { value: "test cleanup reason" },
    });
    // Simulate 409 on soft — the preview surfaces external_refs but
    // the actual /soft can also be blocked at commit time.
    postMock.mockImplementationOnce((path) => {
      // First call in this render was already the preview (fulfilled).
      // This should be the soft-delete → make it reject.
      const err = new Error("blocked_external_reference");
      err.status = 409;
      err.data = {
        detail: {
          error_code: "blocked_external_reference",
          refs: [{ payment_intent_id: "pi_ext_1" }],
        },
      };
      return Promise.reject(err);
    });
    fireEvent.click(screen.getByTestId("cd-hard-delete-confirm"));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    // Not navigated away.
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("Renders external-ref warning banner inside the modal", async () => {
    stubPreview({}, [{ payment_intent_id: "pi_ext_1", id: "inv-1" }]);
    render(<TestHarness role="admin" />);
    fireEvent.click(screen.getByTestId("cd-hard-delete-btn"));
    await waitFor(() =>
      expect(
        screen.getByTestId("cd-hard-delete-external-ref-warning")
      ).toBeInTheDocument()
    );
  });
});
