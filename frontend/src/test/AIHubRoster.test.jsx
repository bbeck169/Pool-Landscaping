/**
 * AIHUB-A · Feb-2026 — AI Hub Roster page tests.
 *
 * Locks:
 *   1. Renders one row per employee from ``GET /api/ai-ops/employees``.
 *   2. Sandbox banner surfaces when ANY row is unauthorized.
 *   3. Authorize toggle POSTs to ``/api/ai-employees/{id}/authorize``
 *      with the flipped ``authorized_for_public_use`` value.
 *   4. On successful flip, the row's badge updates from "Sandbox"
 *      to "Live" without a page refetch.
 *   5. Non-admin API failure surfaces inline (mirrors existing
 *      silent-empty guard) — the error banner renders.
 */
import React from "react";
import {
  render, screen, fireEvent, waitFor, within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
  },
}));

// Radix + realtime deps used by AiOpsPages — noop so we can mount
// the page without the full realtime bootstrap.
vi.mock("@/realtime/NotificationSocket", () => ({
  useRealtime: () => ({ subscribe: () => () => {} }),
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ can: () => true, role: "admin" }),
}));
// AIAvatar wraps Lottie — expensive to mount in vitest; stub to a
// simple img.  Doesn't affect the roster contract we test.
vi.mock("@/components/ai/AIAvatar", () => ({
  __esModule: true,
  default: ({ src, alt, testId }) => (
    <img src={src || ""} alt={alt} data-testid={testId} />
  ),
}));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

import {
  AiEmployeesList, AuthorizationBadge, AuthorizeToggle,
} from "@/pages/aiops/AiOpsPages";


// ══════════════════════════════════════════════════════════════
// Fixture — 3 employees, mix of authorized + sandbox
// ══════════════════════════════════════════════════════════════
function _row(overrides = {}) {
  return {
    id: `emp-${overrides.key || "x"}`,
    slug: overrides.key || "x",
    key: overrides.key || "x",
    name: "Sarah",
    human_name: "Sarah",
    codename: "NOVA",
    role: "CMO",
    role_title: "CMO",
    org_department: "marketing",
    hierarchy_order: 3,
    avatar_url: "/avatars/personas/nova.jpg",
    active: true,
    authorized_for_public_use: false,
    action_limit_monthly: 60000,
    ...overrides,
  };
}


// ══════════════════════════════════════════════════════════════
// AuthorizationBadge — presentational contract
// ══════════════════════════════════════════════════════════════
describe("AIHUB-A · AuthorizationBadge", () => {
  it("renders red Sandbox pill when authorized=false", () => {
    render(<AuthorizationBadge authorized={false} />);
    expect(screen.getByTestId("ai-hub-sandbox-pill")).toHaveTextContent(
      /Sandbox/,
    );
  });
  it("renders green Live pill when authorized=true", () => {
    render(<AuthorizationBadge authorized={true} />);
    expect(screen.getByTestId("ai-hub-authorized-pill")).toHaveTextContent(
      /Live/,
    );
  });
});


// ══════════════════════════════════════════════════════════════
// AuthorizeToggle — flip POST wiring
// ══════════════════════════════════════════════════════════════
describe("AIHUB-A · AuthorizeToggle", () => {
  it("POSTs to /ai-employees/{id}/authorize with flipped value", async () => {
    _apiMock.patch.mockClear();
    _apiMock.patch.mockResolvedValueOnce({
      id: "emp-nova", authorized_for_public_use: true,
    });
    const onFlip = vi.fn();
    render(
      <AuthorizeToggle
        employeeId="emp-nova"
        authorized={false}
        onFlip={onFlip}
      />,
    );
    const btn = screen.getByTestId("ai-hub-authorize-toggle-emp-nova");
    expect(btn).toHaveTextContent("Authorize");
    fireEvent.click(btn);
    await waitFor(() => {
      expect(_apiMock.patch).toHaveBeenCalledWith(
        "/ai-employees/emp-nova/authorize",
        { authorized_for_public_use: true },
      );
    });
    await waitFor(() => {
      expect(onFlip).toHaveBeenCalledWith(true);
    });
  });

  it("POSTs the OFF flip when currently authorized", async () => {
    _apiMock.patch.mockClear();
    _apiMock.patch.mockResolvedValueOnce({
      id: "emp-pulse", authorized_for_public_use: false,
    });
    const onFlip = vi.fn();
    render(
      <AuthorizeToggle
        employeeId="emp-pulse"
        authorized={true}
        onFlip={onFlip}
      />,
    );
    const btn = screen.getByTestId("ai-hub-authorize-toggle-emp-pulse");
    expect(btn).toHaveTextContent("Revoke");
    fireEvent.click(btn);
    await waitFor(() => {
      expect(_apiMock.patch).toHaveBeenCalledWith(
        "/ai-employees/emp-pulse/authorize",
        { authorized_for_public_use: false },
      );
    });
  });
});


// ══════════════════════════════════════════════════════════════
// AiEmployeesList — roster contract
// ══════════════════════════════════════════════════════════════
describe("AIHUB-A · AiEmployeesList", () => {
  it("renders one row per employee from GET /ai-ops/employees", async () => {
    _apiMock.get.mockClear();
    _apiMock.get.mockResolvedValueOnce([
      _row({ key: "marco_executive", human_name: "MARCO",
                codename: "MARCO", role_title: "Executive Assistant",
                org_department: "executive", hierarchy_order: 1,
                authorized_for_public_use: true }),
      _row({ key: "nova", human_name: "Sarah", codename: "NOVA",
                role_title: "CMO", org_department: "marketing" }),
      _row({ key: "brian", human_name: "Ben", codename: "BRIAN",
                role_title: "Scheduling Coordinator",
                org_department: "operations", hierarchy_order: 16 }),
    ]);
    render(<MemoryRouter><AiEmployeesList /></MemoryRouter>);
    await waitFor(() => {
      expect(screen.getByTestId("ai-emp-name-emp-marco_executive"))
        .toHaveTextContent("MARCO");
    });
    expect(screen.getByTestId("ai-emp-name-emp-nova"))
      .toHaveTextContent("Sarah");
    expect(screen.getByTestId("ai-emp-name-emp-brian"))
      .toHaveTextContent("Ben");
    // Roles + codenames + departments.
    expect(screen.getByTestId("ai-emp-role-emp-nova"))
      .toHaveTextContent("CMO");
    expect(screen.getByTestId("ai-emp-codename-emp-nova"))
      .toHaveTextContent("NOVA");
    expect(screen.getByTestId("ai-emp-department-emp-nova"))
      .toHaveTextContent(/marketing/i);
  });

  it("shows the Sandbox banner when ANY row is unauthorized", async () => {
    _apiMock.get.mockClear();
    _apiMock.get.mockResolvedValueOnce([
      _row({ key: "nova", authorized_for_public_use: false }),
      _row({ key: "pulse", authorized_for_public_use: true }),
    ]);
    render(<MemoryRouter><AiEmployeesList /></MemoryRouter>);
    await waitFor(() => {
      expect(screen.getByTestId("ai-hub-sandbox-banner"))
        .toBeInTheDocument();
    });
  });

  it("hides the Sandbox banner when ALL rows are authorized", async () => {
    _apiMock.get.mockClear();
    _apiMock.get.mockResolvedValueOnce([
      _row({ key: "nova", authorized_for_public_use: true }),
      _row({ key: "pulse", authorized_for_public_use: true }),
    ]);
    render(<MemoryRouter><AiEmployeesList /></MemoryRouter>);
    await waitFor(() => {
      expect(screen.getByTestId("ai-employees-list")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("ai-hub-sandbox-banner")).toBeNull();
  });

  it("flipping one row's toggle updates only that row's badge in-place", async () => {
    _apiMock.get.mockClear();
    _apiMock.patch.mockClear();
    _apiMock.get.mockResolvedValueOnce([
      _row({ key: "nova", authorized_for_public_use: false }),
      _row({ key: "pulse", authorized_for_public_use: false }),
    ]);
    _apiMock.patch.mockResolvedValueOnce({
      id: "emp-nova", authorized_for_public_use: true,
    });
    render(<MemoryRouter><AiEmployeesList /></MemoryRouter>);
    await waitFor(() => {
      expect(screen.getByTestId("ai-emp-nova")).toBeInTheDocument();
    });
    // Both rows start in Sandbox.
    const novaCard = screen.getByTestId("ai-emp-nova");
    const pulseCard = screen.getByTestId("ai-emp-pulse");
    expect(within(novaCard).getByTestId("ai-hub-sandbox-pill")).toBeInTheDocument();
    expect(within(pulseCard).getByTestId("ai-hub-sandbox-pill")).toBeInTheDocument();

    // Flip nova.
    fireEvent.click(
      screen.getByTestId("ai-hub-authorize-toggle-emp-nova"),
    );
    await waitFor(() => {
      expect(within(novaCard).getByTestId("ai-hub-authorized-pill"))
        .toBeInTheDocument();
    });
    // Pulse unchanged.
    expect(within(pulseCard).getByTestId("ai-hub-sandbox-pill"))
      .toBeInTheDocument();
  });

  it("surfaces fetch error inline (silent-empty guard)", async () => {
    _apiMock.get.mockClear();
    _apiMock.get.mockRejectedValueOnce(new Error("network is down"));
    render(<MemoryRouter><AiEmployeesList /></MemoryRouter>);
    await waitFor(() => {
      expect(screen.getByTestId("ai-employees-error"))
        .toHaveTextContent(/network is down/);
    });
  });
});
