/**
 * Phase A1 · Feb-2026 — Proactive Intelligence · AlertBell vitest suite.
 *
 * Scope
 * -----
 * Covers the AlertBell top-nav component's user-facing contract:
 *   1. Role gating — renders null for tech/customer/manager; renders
 *      the bell button for admin and super_admin.
 *   2. Unread-count badge shows numeric value, "99+" for large
 *      counts, and hides when the count is 0.
 *   3. Clicking the bell opens the dropdown; alerts are rendered
 *      with title, body, severity icon.
 *   4. Empty state renders when the API returns zero unread alerts.
 *   5. "Mark read" and "Dismiss" each POST to the correct endpoint,
 *      remove the row locally, and decrement the badge.
 *   6. "View" deep-links via react-router (job takes priority, then
 *      customer, disabled when neither is present) and also marks
 *      the alert as read.
 *   7. "See all alerts" navigates to /admin/intelligence/alerts.
 *
 * Mocking strategy — ``vi.mock`` on the api client + auth hook.
 * MSW-free by design; A1 scope is component behavior, not the
 * network layer.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";


const getMock  = vi.fn();
const postMock = vi.fn();
const navigateMock = vi.fn();
let authRole = "admin";

vi.mock("@/api", () => ({
  api: {
    get: (...args)  => getMock(...args),
    post: (...args) => postMock(...args),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: authRole } }),
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff",
    surfaceSecondary: "#F4F4F5",
    border: "#E4E4E7",
    muted: "#71717A",
    onSurface: "#09090B",
    brand: "#0284C7",
    onBrand: "#FFFFFF",
  },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});


import AlertBell from "@/components/nav/AlertBell";


const _ALERT_JOB = {
  id:          "alert-job-1",
  severity:    "urgent",
  category:    "missed_service",
  title:       "Missed service · Sunbelt Pools",
  body:        "Route T-3 skipped yesterday.",
  customer_id: "cust-1",
  job_id:      "job-1",
  created_at:  new Date().toISOString(),
};
const _ALERT_CUSTOMER = {
  id:          "alert-cust-1",
  severity:    "recommended",
  category:    "chemistry_upsell",
  title:       "Chemistry upsell",
  body:        "TA out of range for 3 consecutive visits.",
  customer_id: "cust-2",
  job_id:      null,
  created_at:  new Date().toISOString(),
};
const _ALERT_INFO_ONLY = {
  id:          "alert-info-1",
  severity:    "info",
  category:    "renewal_due",
  title:       "Contract renewal soon",
  body:        "Warranty renewal window opens in 30 days.",
  customer_id: null,
  job_id:      null,
  created_at:  new Date().toISOString(),
};


function mkApiResponse(items, unreadCount, next_before = null) {
  return { items, unread_count: unreadCount, next_before };
}

function _render() {
  return render(
    <MemoryRouter>
      <AlertBell />
    </MemoryRouter>,
  );
}


beforeEach(() => {
  authRole = "admin";
  getMock.mockReset();
  postMock.mockReset();
  navigateMock.mockReset();
});

afterEach(() => cleanup());


describe("AlertBell · role gating", () => {
  it("renders null for a technician session", async () => {
    authRole = "technician";
    getMock.mockResolvedValue(mkApiResponse([], 0));
    const { container } = _render();
    expect(container.firstChild).toBeNull();
    // And never fetches — the bell short-circuits at the role check.
    expect(getMock).not.toHaveBeenCalled();
  });

  it("renders null for a customer session", async () => {
    authRole = "customer";
    getMock.mockResolvedValue(mkApiResponse([], 0));
    const { container } = _render();
    expect(container.firstChild).toBeNull();
    expect(getMock).not.toHaveBeenCalled();
  });

  it("renders null for a manager session (backend contract match)", async () => {
    authRole = "manager";
    getMock.mockResolvedValue(mkApiResponse([], 0));
    const { container } = _render();
    expect(container.firstChild).toBeNull();
    expect(getMock).not.toHaveBeenCalled();
  });

  it("renders the bell for an admin session", async () => {
    authRole = "admin";
    getMock.mockResolvedValue(mkApiResponse([], 0));
    _render();
    expect(await screen.findByTestId("alert-bell-root")).toBeInTheDocument();
    expect(screen.getByTestId("alert-bell-btn")).toBeInTheDocument();
  });

  it("renders the bell for a super_admin session", async () => {
    authRole = "super_admin";
    getMock.mockResolvedValue(mkApiResponse([], 0));
    _render();
    expect(await screen.findByTestId("alert-bell-root")).toBeInTheDocument();
  });
});


describe("AlertBell · unread-count badge", () => {
  it("hides the badge when the unread count is 0", async () => {
    getMock.mockResolvedValue(mkApiResponse([], 0));
    _render();
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    expect(screen.queryByTestId("alert-bell-badge")).toBeNull();
  });

  it("shows a numeric badge when 1 <= count <= 99", async () => {
    getMock.mockResolvedValue(mkApiResponse([_ALERT_JOB], 7));
    _render();
    const badge = await screen.findByTestId("alert-bell-badge");
    expect(badge.textContent).toBe("7");
  });

  it("shows '99+' when the unread count exceeds 99", async () => {
    getMock.mockResolvedValue(mkApiResponse([_ALERT_JOB], 250));
    _render();
    const badge = await screen.findByTestId("alert-bell-badge");
    expect(badge.textContent).toBe("99+");
  });

  it("polls GET /intelligence/alerts on mount with the unread-only query", async () => {
    getMock.mockResolvedValue(mkApiResponse([], 0));
    _render();
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    expect(getMock.mock.calls[0][0]).toBe(
      "/intelligence/alerts?unread_only=true&limit=10",
    );
  });
});


describe("AlertBell · dropdown", () => {
  it("opens the dropdown on bell click and renders each alert row", async () => {
    getMock.mockResolvedValue(
      mkApiResponse([_ALERT_JOB, _ALERT_CUSTOMER, _ALERT_INFO_ONLY], 3),
    );
    _render();
    fireEvent.click(await screen.findByTestId("alert-bell-btn"));
    expect(await screen.findByTestId("alert-bell-dropdown"))
      .toBeInTheDocument();
    expect(await screen.findByTestId("alert-bell-row-0"))
      .toBeInTheDocument();
    expect(screen.getByTestId("alert-bell-row-1")).toBeInTheDocument();
    expect(screen.getByTestId("alert-bell-row-2")).toBeInTheDocument();
    expect(screen.getByTestId("alert-bell-title-0").textContent)
      .toBe(_ALERT_JOB.title);
  });

  it("renders the empty state when zero unread alerts are returned", async () => {
    getMock.mockResolvedValue(mkApiResponse([], 0));
    _render();
    fireEvent.click(await screen.findByTestId("alert-bell-btn"));
    expect(await screen.findByTestId("alert-bell-empty"))
      .toBeInTheDocument();
    expect(screen.queryByTestId("alert-bell-list")).toBeNull();
  });

  it("closes the dropdown when the close button is clicked", async () => {
    getMock.mockResolvedValue(mkApiResponse([_ALERT_JOB], 1));
    _render();
    fireEvent.click(await screen.findByTestId("alert-bell-btn"));
    expect(await screen.findByTestId("alert-bell-dropdown"))
      .toBeInTheDocument();
    fireEvent.click(screen.getByTestId("alert-bell-close"));
    expect(screen.queryByTestId("alert-bell-dropdown")).toBeNull();
  });
});


describe("AlertBell · row actions", () => {
  it("Mark read POSTs to the correct endpoint and drops the row", async () => {
    getMock.mockResolvedValue(
      mkApiResponse([_ALERT_JOB, _ALERT_CUSTOMER], 2),
    );
    postMock.mockResolvedValue({});
    _render();
    fireEvent.click(await screen.findByTestId("alert-bell-btn"));
    fireEvent.click(await screen.findByTestId("alert-bell-mark-read-0"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        `/intelligence/alerts/${_ALERT_JOB.id}/read`,
      ),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("alert-bell-title-0").textContent)
        .toBe(_ALERT_CUSTOMER.title),
    );
    // Badge decremented locally without waiting for a re-poll.
    const badge = screen.getByTestId("alert-bell-badge");
    expect(badge.textContent).toBe("1");
  });

  it("Dismiss POSTs to the correct endpoint and drops the row", async () => {
    getMock.mockResolvedValue(
      mkApiResponse([_ALERT_JOB, _ALERT_CUSTOMER], 2),
    );
    postMock.mockResolvedValue({});
    _render();
    fireEvent.click(await screen.findByTestId("alert-bell-btn"));
    fireEvent.click(await screen.findByTestId("alert-bell-dismiss-0"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        `/intelligence/alerts/${_ALERT_JOB.id}/dismiss`,
      ),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("alert-bell-title-0").textContent)
        .toBe(_ALERT_CUSTOMER.title),
    );
    expect(screen.getByTestId("alert-bell-badge").textContent).toBe("1");
  });
});


describe("AlertBell · deep-link (View)", () => {
  it("prefers job_id over customer_id and marks the alert read", async () => {
    getMock.mockResolvedValue(mkApiResponse([_ALERT_JOB], 1));
    postMock.mockResolvedValue({});
    _render();
    fireEvent.click(await screen.findByTestId("alert-bell-btn"));
    fireEvent.click(await screen.findByTestId("alert-bell-view-0"));
    expect(navigateMock).toHaveBeenCalledWith(`/jobs/${_ALERT_JOB.job_id}`);
    // View also fires the read-mark POST.
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        `/intelligence/alerts/${_ALERT_JOB.id}/read`,
      ),
    );
  });

  it("falls back to customer_id when job_id is absent", async () => {
    getMock.mockResolvedValue(mkApiResponse([_ALERT_CUSTOMER], 1));
    postMock.mockResolvedValue({});
    _render();
    fireEvent.click(await screen.findByTestId("alert-bell-btn"));
    fireEvent.click(await screen.findByTestId("alert-bell-view-0"));
    expect(navigateMock).toHaveBeenCalledWith(
      `/customers/${_ALERT_CUSTOMER.customer_id}`,
    );
  });

  it("disables View when neither job_id nor customer_id is present", async () => {
    getMock.mockResolvedValue(mkApiResponse([_ALERT_INFO_ONLY], 1));
    _render();
    fireEvent.click(await screen.findByTestId("alert-bell-btn"));
    const viewBtn = await screen.findByTestId("alert-bell-view-0");
    expect(viewBtn).toBeDisabled();
  });

  it("'See all alerts' navigates to /admin/intelligence/alerts", async () => {
    getMock.mockResolvedValue(mkApiResponse([_ALERT_JOB], 1));
    _render();
    fireEvent.click(await screen.findByTestId("alert-bell-btn"));
    fireEvent.click(await screen.findByTestId("alert-bell-see-all"));
    expect(navigateMock).toHaveBeenCalledWith("/admin/intelligence/alerts");
  });
});
