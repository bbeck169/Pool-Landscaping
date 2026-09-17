/**
 * Feb-2026 · Ticket #3 + #4 · Org Notifications + AI Configuration UI.
 *
 * Locks the acceptance behaviour on the two new SettingsHub tabs:
 *   1. Non-admins see a "Admin access required" card, no toggles.
 *   2. Admins load defaults from GET; toggles reflect the payload.
 *   3. Flipping a toggle fires a single-field PATCH and a success toast.
 *   4. AI persona name saves on Save-button click (or blur) with toast.
 *   5. PATCH failures revert the optimistic UI update.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("sonner", () => {
  const _toast = Object.assign(vi.fn(), {
    success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn(),
  });
  return { toast: _toast, Toaster: () => null };
});

vi.mock("@/api", () => {
  const _api = { get: vi.fn(), post: vi.fn(), patch: vi.fn(),
                  del: vi.fn(), put: vi.fn() };
  return { api: _api };
});

// Mock useAuth so tests can toggle the admin role easily.
const _authState = { user: { role: "admin", id: "u1" } };
vi.mock("@/auth", () => ({
  useAuth: () => _authState,
}));

import OrgNotificationsSettings from "@/pages/settings/OrgNotificationsSettings";
import AIConfigurationSettings from "@/pages/settings/AIConfigurationSettings";
import { api } from "@/api";
import { toast } from "sonner";


beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  Object.values(toast).forEach((fn) => {
    if (typeof fn === "function") fn.mockReset?.();
  });
  _authState.user = { role: "admin", id: "u1" };
});
afterEach(() => vi.clearAllMocks());


describe("OrgNotificationsSettings · Ticket #3", () => {
  it("non-admin sees forbidden card, no toggles", async () => {
    _authState.user = { role: "technician", id: "u2" };
    render(<OrgNotificationsSettings />);
    expect(screen.getByTestId("org-notifications-forbidden")).toBeTruthy();
    expect(screen.queryByTestId("notif-toggle-lead_confirmation")).toBeNull();
    expect(api.get).not.toHaveBeenCalled();
  });

  it("admin loads defaults from GET and renders 4 toggles", async () => {
    api.get.mockResolvedValue({
      lead_confirmation: true, tech_on_my_way: true,
      job_completion_summary: true, warranty_expiration: true,
    });
    render(<OrgNotificationsSettings />);
    await waitFor(() =>
      expect(screen.getByTestId("notif-toggle-lead_confirmation")).toBeTruthy(),
    );
    expect(api.get).toHaveBeenCalledWith("/tenants/mine/settings/notifications");
    for (const key of ["lead_confirmation", "tech_on_my_way",
                        "job_completion_summary", "warranty_expiration"]) {
      const btn = screen.getByTestId(`notif-toggle-${key}`);
      expect(btn.getAttribute("aria-pressed")).toBe("true");
    }
  });

  it("flip fires single-field PATCH + success toast", async () => {
    api.get.mockResolvedValue({
      lead_confirmation: true, tech_on_my_way: true,
      job_completion_summary: true, warranty_expiration: true,
    });
    api.patch.mockResolvedValue({
      lead_confirmation: false, tech_on_my_way: true,
      job_completion_summary: true, warranty_expiration: true,
    });
    render(<OrgNotificationsSettings />);
    await waitFor(() =>
      expect(screen.getByTestId("notif-toggle-lead_confirmation")).toBeTruthy(),
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("notif-toggle-lead_confirmation"));
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(api.patch).toHaveBeenCalledWith(
      "/tenants/mine/settings/notifications",
      { lead_confirmation: false },
    );
    expect(toast.success).toHaveBeenCalled();
    const btn = screen.getByTestId("notif-toggle-lead_confirmation");
    expect(btn.getAttribute("aria-pressed")).toBe("false");
  });

  it("PATCH failure reverts optimistic UI + fires error toast", async () => {
    api.get.mockResolvedValue({
      lead_confirmation: true, tech_on_my_way: true,
      job_completion_summary: true, warranty_expiration: true,
    });
    api.patch.mockRejectedValue(new Error("network boom"));
    render(<OrgNotificationsSettings />);
    await waitFor(() =>
      expect(screen.getByTestId("notif-toggle-tech_on_my_way")).toBeTruthy(),
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("notif-toggle-tech_on_my_way"));
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(toast.error).toHaveBeenCalled();
    // Revert — still True.
    expect(screen.getByTestId("notif-toggle-tech_on_my_way")
      .getAttribute("aria-pressed")).toBe("true");
  });
});


describe("AIConfigurationSettings · Ticket #4", () => {
  it("non-admin sees forbidden card", async () => {
    _authState.user = { role: "technician", id: "u2" };
    render(<AIConfigurationSettings />);
    expect(screen.getByTestId("ai-config-forbidden")).toBeTruthy();
    expect(api.get).not.toHaveBeenCalled();
  });

  it("admin loads persona + toggles from GET", async () => {
    api.get.mockResolvedValue({
      persona_name: "Ask AquaTerra",
      kb_uploads_enabled: true,
      analytics_enabled: false,
    });
    render(<AIConfigurationSettings />);
    await waitFor(() =>
      expect(screen.getByTestId("ai-persona-name-input")).toBeTruthy(),
    );
    expect(screen.getByTestId("ai-persona-name-input").value)
      .toBe("Ask AquaTerra");
    expect(screen.getByTestId("ai-toggle-kb_uploads_enabled")
      .getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("ai-toggle-analytics_enabled")
      .getAttribute("aria-pressed")).toBe("false");
  });

  it("persona save button fires PATCH with trimmed value + toast", async () => {
    api.get.mockResolvedValue({
      persona_name: "Old Name",
      kb_uploads_enabled: true,
      analytics_enabled: true,
    });
    api.patch.mockResolvedValue({
      persona_name: "New Name",
      kb_uploads_enabled: true,
      analytics_enabled: true,
    });
    render(<AIConfigurationSettings />);
    await waitFor(() =>
      expect(screen.getByTestId("ai-persona-name-input")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("ai-persona-name-input"),
                      { target: { value: "  New Name  " } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("ai-persona-name-save"));
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(api.patch).toHaveBeenCalledWith(
      "/tenants/mine/settings/ai",
      { persona_name: "New Name" },
    );
    expect(toast.success).toHaveBeenCalled();
  });

  it("KB uploads toggle flip fires single-field PATCH", async () => {
    api.get.mockResolvedValue({
      persona_name: "X", kb_uploads_enabled: true, analytics_enabled: true,
    });
    api.patch.mockResolvedValue({
      persona_name: "X", kb_uploads_enabled: false, analytics_enabled: true,
    });
    render(<AIConfigurationSettings />);
    await waitFor(() =>
      expect(screen.getByTestId("ai-toggle-kb_uploads_enabled")).toBeTruthy(),
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("ai-toggle-kb_uploads_enabled"));
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(api.patch).toHaveBeenCalledWith(
      "/tenants/mine/settings/ai",
      { kb_uploads_enabled: false },
    );
    expect(toast.success).toHaveBeenCalled();
    expect(screen.getByTestId("ai-toggle-kb_uploads_enabled")
      .getAttribute("aria-pressed")).toBe("false");
  });

  it("analytics toggle flip fires single-field PATCH", async () => {
    api.get.mockResolvedValue({
      persona_name: "X", kb_uploads_enabled: true, analytics_enabled: true,
    });
    api.patch.mockResolvedValue({
      persona_name: "X", kb_uploads_enabled: true, analytics_enabled: false,
    });
    render(<AIConfigurationSettings />);
    await waitFor(() =>
      expect(screen.getByTestId("ai-toggle-analytics_enabled")).toBeTruthy(),
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("ai-toggle-analytics_enabled"));
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(api.patch).toHaveBeenCalledWith(
      "/tenants/mine/settings/ai",
      { analytics_enabled: false },
    );
  });
});
