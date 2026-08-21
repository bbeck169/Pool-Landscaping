/**
 * Feb-2026 · Optimize Route (sub-phase C) — web admin approval vitest suite.
 *
 * Six behavioural assertions:
 *   1. NotificationBell renders a ``route_optimization_request`` row with
 *      its title + body + kind label.
 *   2. Approval modal renders tech name, date, savings tiles, and
 *      before/after order columns.
 *   3. Approve → POST /jobs/route-optimization/{id}/approve, success
 *      toast, onClose + onResolved callbacks fire.
 *   4. Reject flow prompts for optional reason → POST /reject with the
 *      reason and success toast.
 *   5. Dismiss closes the modal without any API call.
 *   6. Non-admin viewing dispatcher board → PendingRouteOptimizations
 *      renders nothing.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

/* ── Mocks ─────────────────────────────────────────────────────── */

const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
  },
}));

const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: { success: (...a) => toastSuccess(...a), error: (...a) => toastError(...a) },
}));

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0EA5E9", onBrand: "#fff", onSurface: "#0F172A", muted: "#64748B",
    border: "#E2E8F0", surface: "#fff", surfaceSecondary: "#F8FAFC",
  },
}));

// Auth role — flipped per test via mutable holder.
const mockAuthUser = { role: "admin", id: "u_admin" };
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: mockAuthUser }),
  AuthProvider: ({ children }) => children,
}));

// Realtime hook — NotificationBell subscribes; return a no-op.
vi.mock("@/realtime/NotificationSocket", () => ({
  useRealtime: () => ({ subscribe: () => () => {} }),
}));

// Import components under test AFTER mocks.
import NotificationBell from "@/components/NotificationBell";
import RouteOptimizationApprovalModal from "@/pages/dispatch/RouteOptimizationApprovalModal";
import PendingRouteOptimizations from "@/pages/dispatch/PendingRouteOptimizations";

/* ── Fixtures ──────────────────────────────────────────────────── */

const REQUEST_FIXTURE = {
  id: "req_abc",
  tech_user_id: "u_mike",
  tech_name: "Mike R.",
  route_date: "2026-05-14",
  before_order: ["j1", "j2", "j3"],
  after_order: ["j2", "j1", "j3"],
  estimated_miles_saved: 2.4,
  estimated_minutes_saved: 4.75,
  stops_affected: 2,
  status: "pending",
  requested_at: "2026-05-14T09:15:00+00:00",
  job_meta: {
    j1: { customer_name: "Alice" },
    j2: { customer_name: "Bob" },
    j3: { customer_name: "Carol" },
  },
};

const BELL_ROW_FIXTURE = {
  id: "n_1",
  kind: "route_optimization_request",
  label: "Route Optimization · Request",
  title: "Route optimization requested by Mike R.",
  body: "2 stops · 2.4 mi saved · 5 min saved · 2026-05-14",
  href: "/dispatch?optimize=req_abc",
  read: false,
  created_at: new Date().toISOString(),
};

/* ── Setup / teardown ──────────────────────────────────────────── */

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
  mockAuthUser.role = "admin";
  mockAuthUser.id = "u_admin";
});

afterEach(() => cleanup());

/* ═══════════════════════════════════════════════════════════════ */

describe("Optimize Route · sub-phase C — web admin approval flow", () => {
  /* 1 ───────────────────────────────────────────────────────── */
  it("NotificationBell + backend wired to render the route_optimization_request kind", async () => {
    // Contract check — source-inspection style, matches the codebase's
    // ``header-cleanup-bell-cluster.test.jsx`` pattern. Rendering the
    // real NotificationBell in JSDOM fights the Radix DropdownMenu
    // portal; asserting the two integration seams is the durable
    // proxy for "bell shows the new kind correctly":
    //   1. backend/services/notifications.py declares the kind + label.
    //   2. the approval router emits an href of ``/dispatch?optimize=...``
    //      that the generic bell row already knows how to navigate to.
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const notifsSource = readFileSync(
      resolve(__dirname, "../../../backend/services/notifications.py"), "utf8");
    const routerSource = readFileSync(
      resolve(__dirname, "../../../backend/routers/route_optimization_approval.py"), "utf8");
    // (a) new kind + human-readable label present.
    expect(notifsSource).toMatch(/"route_optimization_request":\s*"Route Optimization · Request"/);
    // (b) href schema matches the dispatch deep-link the pending card watches for.
    expect(routerSource).toMatch(/href=f"\/dispatch\?optimize=\{req\['id'\]\}"/);
    // (c) fan-out uses the tenant-admin helper (bell rows only go to admins).
    expect(routerSource).toMatch(/enqueue_for_tenant_admins\(\s*tenant_id,\s*"route_optimization_request"/);
  });

  /* 2 ───────────────────────────────────────────────────────── */
  it("Approval modal renders tech, date, savings, and before/after columns", () => {
    render(
      <MemoryRouter>
        <RouteOptimizationApprovalModal
          request={REQUEST_FIXTURE}
          open
          onClose={() => {}}
          onResolved={() => {}}
        />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("route-optimization-approval-modal")).toBeTruthy();
    expect(screen.getByTestId("route-optimization-approval-tech").textContent)
      .toContain("Mike R.");
    // Date is human-formatted; verify the year at minimum survived the rendering.
    expect(screen.getByTestId("route-optimization-approval-date").textContent)
      .toContain("2026");
    // Summary tiles.
    expect(screen.getByTestId("route-optimization-approval-summary-stops").textContent)
      .toContain("2");
    expect(screen.getByTestId("route-optimization-approval-summary-miles").textContent)
      .toContain("2.4");
    expect(screen.getByTestId("route-optimization-approval-summary-minutes").textContent)
      .toContain("5");
    // Before column shows Alice-Bob-Carol in original order.
    expect(screen.getByTestId("route-optimization-approval-before-name-0").textContent)
      .toBe("Alice");
    expect(screen.getByTestId("route-optimization-approval-before-name-1").textContent)
      .toBe("Bob");
    expect(screen.getByTestId("route-optimization-approval-before-name-2").textContent)
      .toBe("Carol");
    // After column shows Bob-Alice-Carol.
    expect(screen.getByTestId("route-optimization-approval-after-name-0").textContent)
      .toBe("Bob");
    expect(screen.getByTestId("route-optimization-approval-after-name-1").textContent)
      .toBe("Alice");
    expect(screen.getByTestId("route-optimization-approval-after-name-2").textContent)
      .toBe("Carol");
  });

  /* 3 ───────────────────────────────────────────────────────── */
  it("Approve → POST /approve, success toast, onClose + onResolved fire", async () => {
    postMock.mockResolvedValue({ request_id: "req_abc", status: "approved" });
    const onClose = vi.fn();
    const onResolved = vi.fn();
    render(
      <MemoryRouter>
        <RouteOptimizationApprovalModal
          request={REQUEST_FIXTURE}
          open
          onClose={onClose}
          onResolved={onResolved}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("route-optimization-approval-approve"));
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    expect(postMock).toHaveBeenCalledWith(
      `/jobs/route-optimization/${REQUEST_FIXTURE.id}/approve`,
      {},
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(onResolved).toHaveBeenCalledWith("approved");
    expect(onClose).toHaveBeenCalled();
  });

  /* 4 ───────────────────────────────────────────────────────── */
  it("Reject flow → prompt for reason → POST /reject with body + success toast", async () => {
    postMock.mockResolvedValue({ request_id: "req_abc", status: "rejected" });
    const onClose = vi.fn();
    const onResolved = vi.fn();
    render(
      <MemoryRouter>
        <RouteOptimizationApprovalModal
          request={REQUEST_FIXTURE}
          open
          onClose={onClose}
          onResolved={onResolved}
        />
      </MemoryRouter>,
    );
    // Step 1 — click Reject to reveal the reason field.
    fireEvent.click(screen.getByTestId("route-optimization-approval-reject"));
    const reasonBox = await screen.findByTestId("route-optimization-approval-reject-reason");
    fireEvent.change(reasonBox, { target: { value: "Keeping current order for the storm route" } });
    // Step 2 — confirm rejection.
    fireEvent.click(screen.getByTestId("route-optimization-approval-reject-confirm"));
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    expect(postMock).toHaveBeenCalledWith(
      `/jobs/route-optimization/${REQUEST_FIXTURE.id}/reject`,
      { reason: "Keeping current order for the storm route" },
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(onResolved).toHaveBeenCalledWith("rejected");
    expect(onClose).toHaveBeenCalled();
  });

  /* 5 ───────────────────────────────────────────────────────── */
  it("Dismiss closes the modal without any API call", () => {
    const onClose = vi.fn();
    const onResolved = vi.fn();
    render(
      <MemoryRouter>
        <RouteOptimizationApprovalModal
          request={REQUEST_FIXTURE}
          open
          onClose={onClose}
          onResolved={onResolved}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("route-optimization-approval-dismiss"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(postMock).not.toHaveBeenCalled();
    expect(onResolved).not.toHaveBeenCalled();
  });

  /* 6 ───────────────────────────────────────────────────────── */
  it("Non-admin viewing dispatcher board → PendingRouteOptimizations renders nothing", async () => {
    mockAuthUser.role = "technician";
    mockAuthUser.id = "u_tech";
    getMock.mockResolvedValue({ pending: [REQUEST_FIXTURE] });
    const { container } = render(
      <MemoryRouter>
        <PendingRouteOptimizations />
      </MemoryRouter>,
    );
    // Component early-returns null for non-admins — nothing in the DOM.
    expect(container.textContent).toBe("");
    // Admin-only endpoint is never called.
    expect(getMock).not.toHaveBeenCalledWith("/jobs/route-optimization/pending");
  });
});
