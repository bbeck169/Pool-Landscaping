/**
 * Phase 26 · Feb-2026 — Review Department Suggestions modal vitest.
 *
 * Component: ``src/components/admin/SuggestDepartmentsModal.jsx``.
 *
 * Scenarios covered:
 *   1. Renders suggestion rows from the mocked GET-shape POST.
 *   2. "Select all" toggles every row + updates the counter.
 *   3. Apply button is disabled when zero rows are selected.
 *   4. Clicking Apply POSTs to
 *      ``/admin/apply-department-suggestions`` with the correct
 *      ``{applications: [{user_id, department}]}`` payload.
 *   5. Success toast on 200; error toast on 500.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach,
} from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// ── Shared mocks — MUST come before component import. ─────────────
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: { post: (...args) => postMock(...args) },
}));

const toastSuccess = vi.fn();
const toastError = vi.fn();
const toastPlain = vi.fn();
vi.mock("sonner", () => {
  const toast = (...a) => toastPlain(...a);
  toast.success = (...a) => toastSuccess(...a);
  toast.error = (...a) => toastError(...a);
  return { toast };
});

// Deferred import so the mocks resolve first.
import SuggestDepartmentsModal
  from "@/components/admin/SuggestDepartmentsModal";

// ── Fixtures ─────────────────────────────────────────────────────
const SUGGESTIONS_OK = {
  suggestions: [
    { user_id: "u-alpha", name: "Alpha Tech",
      current_department: null, suggested_department: "pool_tech",
      confidence: 0.9,
      signals: { pool_jobs: 18, landscape_jobs: 2, days_window: 90 } },
    { user_id: "u-beta",  name: "Beta Tech",
      current_department: "pool_tech", suggested_department: "landscape_tech",
      confidence: 0.8,
      signals: { pool_jobs: 4, landscape_jobs: 16, days_window: 90 } },
    { user_id: "u-gamma", name: "Gamma Tech",
      current_department: null, suggested_department: "both",
      confidence: 0.5,
      signals: { pool_jobs: 6, landscape_jobs: 6, days_window: 90 } },
  ],
  count: 3,
};

/** Route the mock: GET-suggestions on the load call, whatever the
 *  test wants for the apply call.  Both live on ``api.post`` per
 *  the component's implementation.
 */
function wireDefaultMocks({ applyResponse } = {}) {
  postMock.mockImplementation(async (url, body) => {
    if (url === "/admin/suggest-departments") return SUGGESTIONS_OK;
    if (url === "/admin/apply-department-suggestions") {
      return applyResponse ?? {
        applied: (body?.applications || []).length,
        failed: [],
      };
    }
    throw new Error(`unexpected url ${url}`);
  });
}

async function mount(props = {}) {
  const onClose = vi.fn();
  const onApplied = vi.fn();
  const utils = render(
    <SuggestDepartmentsModal
      open={true}
      onClose={onClose}
      onApplied={onApplied}
      {...props}
    />,
  );
  // Wait for the initial POST /admin/suggest-departments to resolve.
  await waitFor(() =>
    expect(screen.getByTestId("phase26-table")).toBeInTheDocument(),
  );
  return { ...utils, onClose, onApplied };
}

beforeEach(() => {
  postMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
  toastPlain.mockReset();
});

describe("Phase 26 · Review Department Suggestions modal", () => {
  it("renders suggestion rows from the mocked GET", async () => {
    wireDefaultMocks();
    await mount();
    expect(screen.getByTestId("phase26-row-u-alpha")).toBeInTheDocument();
    expect(screen.getByTestId("phase26-row-u-beta")).toBeInTheDocument();
    expect(screen.getByTestId("phase26-row-u-gamma")).toBeInTheDocument();
    expect(screen.getByText(/Alpha Tech/)).toBeInTheDocument();
    // Confidence rendered as a percent.
    expect(screen.getByText(/90%/)).toBeInTheDocument();
  });

  it("select-all toggles every row + updates the counter", async () => {
    wireDefaultMocks();
    await mount();
    // Two high-confidence rows (alpha 0.9, beta 0.8) are preselected;
    // gamma (0.5) is not.
    expect(screen.getByTestId("phase26-selected-count").textContent)
      .toMatch(/2 of 3 selected/);
    fireEvent.click(screen.getByTestId("phase26-toggle-all"));
    // First click → all 3 selected (partial → full).
    expect(screen.getByTestId("phase26-selected-count").textContent)
      .toMatch(/3 of 3 selected/);
    fireEvent.click(screen.getByTestId("phase26-toggle-all"));
    // Second click clears them all.
    expect(screen.getByTestId("phase26-selected-count").textContent)
      .toMatch(/0 of 3 selected/);
  });

  it("Apply button is disabled when zero rows are selected", async () => {
    wireDefaultMocks();
    await mount();
    // Clear preselection.
    fireEvent.click(screen.getByTestId("phase26-toggle-all"));
    fireEvent.click(screen.getByTestId("phase26-toggle-all"));
    expect(screen.getByTestId("phase26-apply")).toBeDisabled();
  });

  it("clicking Apply POSTs to /admin/apply-department-suggestions with the correct payload", async () => {
    wireDefaultMocks();
    const { onClose, onApplied } = await mount();
    // Pre-selection already has alpha (0.9) + beta (0.8). Add gamma
    // manually so we have 3 applications, then click Apply.
    fireEvent.click(screen.getByTestId("phase26-check-u-gamma"));
    fireEvent.click(screen.getByTestId("phase26-apply"));

    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/admin/apply-department-suggestions",
        expect.objectContaining({
          applications: expect.arrayContaining([
            { user_id: "u-alpha", department: "pool_tech" },
            { user_id: "u-beta",  department: "landscape_tech" },
            { user_id: "u-gamma", department: "both" },
          ]),
        }),
      ),
    );
    // The apply call resolved OK → onApplied + onClose both fire.
    await waitFor(() => expect(onApplied).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
  });

  it("shows a success toast when apply returns applied>0 and no failures", async () => {
    wireDefaultMocks();
    await mount();
    fireEvent.click(screen.getByTestId("phase26-apply"));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    const arg = toastSuccess.mock.calls[0][0];
    // "2 departments updated" — two preselected rows.
    expect(String(arg)).toMatch(/2 departments? updated/i);
    expect(toastError).not.toHaveBeenCalled();
  });

  it("shows an error toast when apply throws a 500-like error", async () => {
    // Load returns OK; apply throws.
    postMock.mockImplementation(async (url) => {
      if (url === "/admin/suggest-departments") return SUGGESTIONS_OK;
      throw new Error("Internal server error");
    });
    await mount();
    fireEvent.click(screen.getByTestId("phase26-apply"));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    const arg = toastError.mock.calls[0][0];
    expect(String(arg)).toMatch(/Internal server error/);
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
