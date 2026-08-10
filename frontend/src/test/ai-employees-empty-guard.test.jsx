/**
 * Aug-2026 · AI Employees silent-empty guard.
 *
 * Contract (Fix #2-followup):
 *   • When ``/ai-ops/employees`` succeeds → grid renders rows, no
 *     error banner. (Regression guard on the pre-existing happy path.)
 *   • When ``/ai-ops/employees`` rejects (network, 5xx, non-auth 401) →
 *     an inline ``ai-employees-error`` banner renders, grid stays
 *     empty (i.e. we DON'T pretend the tenant has zero AI employees).
 *   • The 401 auth-token case is intentionally NOT covered here — it's
 *     already handled upstream by the api.js interceptor (Fix A), which
 *     redirects to /login before the component's ``.catch`` ever fires.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...args) => getMock(...args), post: vi.fn() },
}));

// AIAvatar pulls in lottie-react — mock it out to a noop so the test
// stays focused on the error/empty branches.
vi.mock("lottie-react", () => ({
  __esModule: true,
  default: () => <span data-testid="lottie-mock" />,
}));

// Realtime notification socket does an outbound connection on mount —
// stub the hook out entirely.
vi.mock("@/realtime/NotificationSocket", () => ({
  useRealtime: () => null,
  NotificationSocket: ({ children }) => children,
}));

// Bulk-select toolkit has non-trivial state — no coverage needed here.
vi.mock("@/components/bulk-select/BulkSelectToolkit", () => ({
  useBulkSelect: () => ({ selected: new Set(), toggle: vi.fn(), clear: vi.fn() }),
  BulkSelectAll: () => null,
  BulkSelectRow: () => null,
  BulkActionBar: () => null,
  BulkConfirmModal: () => null,
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ can: () => true }),
}));

import { AiEmployeesList } from "@/pages/aiops/AiOpsPages";

function renderPage() {
  return render(
    <MemoryRouter>
      <AiEmployeesList />
    </MemoryRouter>,
  );
}

describe("AiEmployeesList · silent-empty guard · Fix #2-followup", () => {
  beforeEach(() => {
    getMock.mockReset();
  });
  afterEach(() => {
    getMock.mockReset();
  });

  it("renders the row grid when the API succeeds (regression guard)", async () => {
    getMock.mockResolvedValueOnce([
      {
        id: "e1", slug: "billy", name: "Billy", role: "Billing concierge",
        active: true, avatar_url: "/avatars/personas/billy.jpg",
      },
      {
        id: "e2", slug: "buddy", name: "Buddy", role: "Growth analytics",
        active: true, avatar_url: "/avatars/personas/buddy.jpg",
      },
    ]);

    await act(async () => { renderPage(); });

    await waitFor(() => {
      expect(screen.getByTestId("ai-emp-billy")).toBeInTheDocument();
      expect(screen.getByTestId("ai-emp-buddy")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("ai-employees-error")).not.toBeInTheDocument();
  });

  it("renders inline error banner when the fetch rejects with a network error", async () => {
    getMock.mockRejectedValueOnce(
      new Error("Network error — check your connection and try again."),
    );

    await act(async () => { renderPage(); });

    const banner = await screen.findByTestId("ai-employees-error");
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toMatch(/network error/i);
    // No cards rendered — we did NOT fall back to a silent empty grid.
    expect(document.querySelectorAll('[data-testid^="ai-emp-"]').length).toBe(0);
  });

  it("renders inline error banner when the fetch rejects with a 5xx", async () => {
    const err = new Error("Request failed (500)");
    err.status = 500;
    getMock.mockRejectedValueOnce(err);

    await act(async () => { renderPage(); });

    const banner = await screen.findByTestId("ai-employees-error");
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toMatch(/Request failed/);
  });

  it("falls back to a friendly default when the error has no message", async () => {
    // Pathological path: an object rejection with no ``message`` field.
    getMock.mockRejectedValueOnce({});

    await act(async () => { renderPage(); });

    const banner = await screen.findByTestId("ai-employees-error");
    expect(banner.textContent).toMatch(/Couldn't load AI Employees/);
  });
});
