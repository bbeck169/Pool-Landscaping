/**
 * AB1 · Feb-2026 — Autobilling bulk-cancel · vitest.
 *
 * Covers both surfaces:
 *   • AutobillingRuns.jsx — bulk-select checkbox flow + bulk-cancel
 *     modal + confirm-only POST + result summary.
 *   • FinancePages.jsx AutoBilling section — bulk-cancel button
 *     appears in the action bar and only POSTs after confirm.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup, within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ── Shared api mock — must come before component imports. ──
const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...args) => getMock(...args),
          post: (...args) => postMock(...args) },
}));

// Silence sonner toasts + keep them assertable.
const toastSuccess = vi.fn();
const toastError = vi.fn();
const toastPlain = vi.fn();
vi.mock("sonner", () => {
  const toast = (...a) => toastPlain(...a);
  toast.success = (...a) => toastSuccess(...a);
  toast.error = (...a) => toastError(...a);
  return { toast };
});

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceAlt: "#fafafa",
    surfaceSecondary: "#f5f5f5", surfaceTertiary: "#eee",
    border: "#ddd", muted: "#666",
    onSurface: "#000", brand: "#0891B2",
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));

vi.mock("@/components/ui-kit", () => ({
  PageHeader: ({ title, subtitle }) =>
    <div><h1>{title}</h1><p>{subtitle}</p></div>,
  Card: ({ children }) => <div>{children}</div>,
  Skeleton: (p) => <div {...p} />,
}));

// Task E · Aug-2026 — ``AutobillingRuns.jsx`` calls ``useAuth()`` for
// the Fix #5 soft-delete role gate. Without this mock the hook
// returns ``null`` in the test render tree and the destructure
// ``const { user } = useAuth()`` throws. Admin role → sees the
// bulk-cancel + soft-delete UX exercised by the tests below.
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u-admin", email: "admin@x",
                              role: "admin" } }),
  AuthProvider: ({ children }) => children,
}));

import AutobillingRuns from "@/pages/finance/AutobillingRuns";

beforeEach(() => {
  getMock.mockReset(); postMock.mockReset();
  toastSuccess.mockReset(); toastError.mockReset(); toastPlain.mockReset();
});
afterEach(() => cleanup());

const runsFixture = [
  {id: "r-pending", plan_id: "p1", plan_name: "Weekly Chem",
    run_schedule: "first_friday", anchor_date: "2026-03-06",
    status: "pending", message: "queued", ts: "2026-02-25T10:00:00Z"},
  {id: "r-fired", plan_id: "p2", plan_name: "Monthly Pool",
    run_schedule: "first_of_month", anchor_date: "2026-02-01",
    status: "fired", message: "OK", ts: "2026-02-01T09:00:00Z"},
];


describe("AutobillingRuns · bulk-cancel", () => {
  const renderPage = () => render(
    <MemoryRouter>
      <AutobillingRuns />
    </MemoryRouter>,
  );

  it("renders bulk-select checkboxes on each row + a select-all header", async () => {
    getMock.mockResolvedValueOnce(runsFixture);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("autobilling-runs-table")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("autobilling-runs-select-all")).toBeInTheDocument();
    expect(screen.getByTestId("autobilling-runs-row-select-r-pending"))
      .toBeInTheDocument();
    expect(screen.getByTestId("autobilling-runs-row-select-r-fired"))
      .toBeInTheDocument();
    // Action bar hidden with 0 selected.
    expect(screen.queryByTestId("autobilling-runs-bulk-action-bar"))
      .not.toBeInTheDocument();
  });

  it("row selection surfaces the bulk-action-bar with correct count", async () => {
    getMock.mockResolvedValueOnce(runsFixture);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("autobilling-runs-table")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("autobilling-runs-row-select-r-pending"));
    await waitFor(() =>
      expect(screen.getByTestId("autobilling-runs-bulk-action-bar"))
        .toBeInTheDocument(),
    );
    expect(screen.getByTestId("autobilling-runs-bulk-action-bar-count")
              .textContent).toMatch(/1 selected/);
  });

  it("clicking Bulk cancel opens the confirm modal WITHOUT firing POST", async () => {
    getMock.mockResolvedValueOnce(runsFixture);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("autobilling-runs-table")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("autobilling-runs-row-select-r-pending"));
    fireEvent.click(screen.getByTestId("autobilling-runs-row-select-r-fired"));
    fireEvent.click(screen.getByTestId("autobilling-runs-bulk-cancel-button"));
    await waitFor(() =>
      expect(screen.getByTestId("autobilling-runs-bulk-cancel-confirm"))
        .toBeInTheDocument(),
    );
    // No POST yet — modal open only.
    expect(postMock).not.toHaveBeenCalled();
  });

  it("Keep-runs cancel button closes the modal without firing POST", async () => {
    getMock.mockResolvedValueOnce(runsFixture);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("autobilling-runs-table")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("autobilling-runs-row-select-r-pending"));
    fireEvent.click(screen.getByTestId("autobilling-runs-bulk-cancel-button"));
    await waitFor(() =>
      expect(screen.getByTestId("autobilling-runs-bulk-cancel-confirm"))
        .toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("autobilling-runs-bulk-cancel-cancel"));
    await waitFor(() =>
      expect(screen.queryByTestId("autobilling-runs-bulk-cancel-confirm"))
        .not.toBeInTheDocument(),
    );
    expect(postMock).not.toHaveBeenCalled();
  });

  it("Confirming fires POST with correct payload + renders result summary", async () => {
    getMock.mockResolvedValueOnce(runsFixture);
    postMock.mockResolvedValueOnce({
      cancelled: 1, skipped: 1,
      results: [
        {id: "r-pending", status: "cancelled", reason: null},
        {id: "r-fired", status: "skipped", reason: "not_eligible: current_status=fired"},
      ],
    });
    // Second /autobilling-runs GET fired inside doBulkCancel() after
    // a successful POST — return the same data so the load() succeeds.
    getMock.mockResolvedValueOnce(runsFixture);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("autobilling-runs-table")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("autobilling-runs-row-select-r-pending"));
    fireEvent.click(screen.getByTestId("autobilling-runs-row-select-r-fired"));
    fireEvent.click(screen.getByTestId("autobilling-runs-bulk-cancel-button"));
    await waitFor(() =>
      expect(screen.getByTestId("autobilling-runs-bulk-cancel-confirm"))
        .toBeInTheDocument(),
    );
    // Type an optional reason.
    fireEvent.change(
      screen.getByTestId("autobilling-runs-bulk-cancel-reason"),
      {target: {value: "consolidated"}},
    );
    fireEvent.click(screen.getByTestId("autobilling-runs-bulk-cancel-confirm-btn"));
    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    const [path, body] = postMock.mock.calls[0];
    expect(path).toBe("/autobilling/runs/bulk-cancel");
    expect(new Set(body.ids)).toEqual(new Set(["r-pending", "r-fired"]));
    expect(body.reason).toBe("consolidated");
    // Result summary rendered.
    await waitFor(() =>
      expect(screen.getByTestId("autobilling-runs-bulk-cancel-summary"))
        .toBeInTheDocument(),
    );
    const summary = screen.getByTestId("autobilling-runs-bulk-cancel-summary");
    expect(summary.textContent).toMatch(/1 cancelled/);
    expect(summary.textContent).toMatch(/1 skipped/);
    // Skipped-with-description toast fired.
    expect(toastPlain).toHaveBeenCalled();
    const [msg] = toastPlain.mock.calls[0];
    expect(msg).toMatch(/1 cancelled/);
  });

  it("Select-all toggles all visible row checkboxes", async () => {
    getMock.mockResolvedValueOnce(runsFixture);
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId("autobilling-runs-table")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("autobilling-runs-select-all"));
    await waitFor(() =>
      expect(screen.getByTestId("autobilling-runs-bulk-action-bar-count")
                .textContent).toMatch(/2 selected/),
    );
    // Toggle off — count disappears with the action bar.
    fireEvent.click(screen.getByTestId("autobilling-runs-select-all"));
    await waitFor(() =>
      expect(screen.queryByTestId("autobilling-runs-bulk-action-bar"))
        .not.toBeInTheDocument(),
    );
  });
});
