/**
 * MTH-B · Feb-2026 — AI Rules page shell.
 *
 * Locks:
 *   1. Renders three tabs for super-admin, two tabs for admin.
 *   2. Platform Defaults tab is HIDDEN (not just disabled) for admin.
 *   3. Master switch card mounts on the Rules tab.
 *   4. Tenant surface fetches ``GET /api/tenant-ai-rules`` on mount.
 *   5. 403 forbidden view for non-admin roles.
 */
import React from "react";
import { render, screen, within, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

// TimezoneSelect makes a network call on mount — stub to a noop.
vi.mock("@/components/settings/TimezoneSelect", () => ({
  TimezoneSelect: ({ value, testid }) => (
    <select data-testid={testid || "tenant-timezone-picker"} value={value} onChange={() => {}}>
      <option value={value}>{value}</option>
    </select>
  ),
}));

const _authMock = vi.hoisted(() => ({ user: { role: "admin" } }));
vi.mock("@/auth", () => ({
  useAuth: () => _authMock,
}));

import AIRulesPage from "@/pages/admin/AIRulesPage";

const RESOLVED = {
  tenant_id: "t1",
  master_ai_send_live_comms: false,
  rules: {
    tone_voice: { style: "friendly", custom_directive: "" },
    auto_action_allowlist: {
      "marco.clock_in": "admin_approval",
      "casey.draft_outreach_reply": "auto",
    },
    employee_enable_disable: { marco_executive: true, nova: true },
    working_hours: {
      enabled: true,
      timezone: "America/Los_Angeles",
      windows: [{ day: "mon", start: "08:00", end: "17:00" }],
    },
    escalation_rules: [
      {
        keyword: "refund",
        is_regex: false,
        target_role: "admin",
        sla_minutes: 5,
        notify_channel: "email",
      },
    ],
  },
  override_map: {},
  action_inventory: ["marco.clock_in", "casey.draft_outreach_reply"],
  employee_keys: ["marco_executive", "nova"],
  revision_number: 3,
  last_updated_at: "2026-02-01T10:00:00Z",
  last_updated_by_name: "admin@example.com",
  last_update_reason: "initial setup",
};

function setupApi() {
  _apiMock.get.mockImplementation((p) => {
    if (p === "/tenant-ai-rules") return Promise.resolve(RESOLVED);
    if (p === "/ai-employees") return Promise.resolve([]);
    if (p === "/platform-ai-rules") return Promise.resolve(RESOLVED);
    if (p === "/tenants") return Promise.resolve([{ id: "t1" }, { id: "t2" }]);
    if (p.startsWith("/tenant-ai-rules/revisions"))
      return Promise.resolve({ count: 0, revisions: [] });
    return Promise.reject(Object.assign(new Error("not-mocked"), { status: 404 }));
  });
}

describe("MTH-B · AIRulesPage shell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupApi();
    _authMock.user = { role: "admin" };
  });

  it("renders Rules and Revisions tabs; hides Platform Defaults for admin", async () => {
    render(
      <MemoryRouter>
        <AIRulesPage />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("ai-rules-tab-rules")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("ai-rules-tab-revisions")).toBeInTheDocument();
    // Platform Defaults tab must be hidden entirely for admin.
    expect(
      screen.queryByTestId("ai-rules-tab-platform"),
    ).not.toBeInTheDocument();
  });

  it("renders all three tabs for super_admin", async () => {
    _authMock.user = { role: "super_admin" };
    render(
      <MemoryRouter>
        <AIRulesPage />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("ai-rules-tab-platform")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("ai-rules-tab-rules")).toBeInTheDocument();
    expect(screen.getByTestId("ai-rules-tab-revisions")).toBeInTheDocument();
  });

  it("mounts master-switch card + fetches resolved rules", async () => {
    render(
      <MemoryRouter>
        <AIRulesPage />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("ai-rules-master-switch-card"),
      ).toBeInTheDocument(),
    );
    // SANDBOX pill because master_ai_send_live_comms=false.
    expect(screen.getByTestId("ai-rules-master-switch-pill").textContent).toBe(
      "SANDBOX",
    );
    expect(_apiMock.get).toHaveBeenCalledWith("/tenant-ai-rules");
  });

  it("renders forbidden banner for non-admin roles", () => {
    _authMock.user = { role: "technician" };
    render(
      <MemoryRouter>
        <AIRulesPage />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("ai-rules-forbidden")).toBeInTheDocument();
  });
});
