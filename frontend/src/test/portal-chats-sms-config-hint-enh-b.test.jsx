/**
 * K9 Enhancement B · Feb-2026 — Admin Customer Inbox missing-SMS-config
 * hint banner.
 *
 * Pins the contract that ``PortalChatsPage`` (rendered as the admin
 * Customer Inbox when ``isAdmin=true``) surfaces a yellow warning
 * banner + deep-link when either ``tenant.admin_sms_notify_to`` or
 * ``tenant.rc_sms_from_number`` is missing on the tenant returned by
 * ``GET /tenants/current``.  Also covers negative cases:
 *   - Both set  → banner NOT rendered.
 *   - Customer viewer (not admin) → banner NEVER rendered (even if the
 *     tenant response somehow leaks config gaps).
 *   - Endpoint failure → banner NOT rendered (silent fail).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ── Hoisted API mock ────────────────────────────────────────────
const { getSpy, postSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(), postSpy: vi.fn(), patchSpy: vi.fn(),
}));
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
  },
  TOKEN_KEY: "access_token",
}));

// Auth mock — swapped per test to toggle admin/customer viewer.
const authState = { user: { id: "admin-A", role: "admin", name: "Admin" } };
vi.mock("@/auth", () => ({ useAuth: () => authState }));

// Suppress attachment-tile network path.
vi.mock("@/components/chat/ChatAttachmentTile", async (importOriginal) => {
  const mod = await importOriginal();
  return { ...mod, ChatAttachmentTile: () => <span data-testid="tile" /> };
});

import PortalChatsPage from "@/pages/portal/PortalChatsPage";

const _seedApi = ({ threads = [], tenant = {} } = {}) => {
  getSpy.mockImplementation((path) => {
    if (path === "/portal/chats") return Promise.resolve(threads);
    if (path === "/tenants/current") return Promise.resolve(tenant);
    return Promise.resolve({});
  });
};

const _render = () => render(
  <MemoryRouter><PortalChatsPage /></MemoryRouter>,
);

beforeEach(() => {
  getSpy.mockReset(); postSpy.mockReset(); patchSpy.mockReset();
  authState.user = { id: "admin-A", role: "admin", name: "Admin" };
  global.localStorage.setItem("access_token", "test-token");
});
afterEach(() => cleanup());


describe("PortalChatsPage · K9 Enhancement B — SMS config hint banner", () => {
  it("renders the BOTH-missing banner when neither field is set", async () => {
    _seedApi({ tenant: { id: "t-1",
                          admin_sms_notify_to: null,
                          rc_sms_from_number: null } });
    _render();
    const hint = await screen.findByTestId("portal-chats-sms-config-hint");
    expect(hint).toBeTruthy();
    expect(hint.textContent).toMatch(/wired up/i);
    expect(hint.textContent).toMatch(/Neither/i);
    // The "both-missing" variant links to the combined CTA.
    const link = screen.getByTestId("portal-chats-sms-config-hint-link-both");
    expect(link.getAttribute("href")).toBe("/settings/notifications");
  });

  it("renders the ADMIN-phone-missing banner when only admin_sms_notify_to is null", async () => {
    _seedApi({ tenant: { id: "t-1",
                          admin_sms_notify_to: null,
                          rc_sms_from_number: "+16025550111" } });
    _render();
    const hint = await screen.findByTestId("portal-chats-sms-config-hint");
    expect(hint.textContent).toMatch(/Admin phone missing/i);
    const link = screen.getByTestId("portal-chats-sms-config-hint-link-admin");
    expect(link.getAttribute("href")).toBe("/settings/notifications");
    // Sanity: the OTHER-variant links are NOT rendered.
    expect(screen.queryByTestId("portal-chats-sms-config-hint-link-from")).toBeNull();
    expect(screen.queryByTestId("portal-chats-sms-config-hint-link-both")).toBeNull();
  });

  it("renders the FROM-number-missing banner when only rc_sms_from_number is null", async () => {
    _seedApi({ tenant: { id: "t-1",
                          admin_sms_notify_to: "+16028874400",
                          rc_sms_from_number: null } });
    _render();
    const hint = await screen.findByTestId("portal-chats-sms-config-hint");
    expect(hint.textContent).toMatch(/Outbound SMS/i);
    const link = screen.getByTestId("portal-chats-sms-config-hint-link-from");
    expect(link.getAttribute("href")).toBe("/settings/notifications");
    expect(screen.queryByTestId("portal-chats-sms-config-hint-link-admin")).toBeNull();
  });

  it("does NOT render the banner when both fields are set", async () => {
    _seedApi({ tenant: { id: "t-1",
                          admin_sms_notify_to: "+16028874400",
                          rc_sms_from_number: "+16025550111" } });
    _render();
    // Wait one microtask for the effect to complete + set state.
    await waitFor(() => expect(getSpy).toHaveBeenCalledWith("/tenants/current"));
    // Then confirm the hint is absent.
    expect(screen.queryByTestId("portal-chats-sms-config-hint")).toBeNull();
  });

  it("does NOT render the banner when the viewer is a customer (not admin)", async () => {
    authState.user = { id: "cust-A", role: "customer",
                        customer_id: "c-A", name: "Cust A" };
    _seedApi({ tenant: { id: "t-1",
                          admin_sms_notify_to: null,
                          rc_sms_from_number: null } });
    _render();
    await waitFor(() => expect(getSpy).toHaveBeenCalledWith("/portal/chats"));
    // /tenants/current MUST NOT have been fetched by a customer viewer
    // — the effect is gated on ``isAdmin``.
    expect(getSpy).not.toHaveBeenCalledWith("/tenants/current");
    expect(screen.queryByTestId("portal-chats-sms-config-hint")).toBeNull();
  });

  it("does NOT render the banner when /tenants/current errors out", async () => {
    getSpy.mockImplementation((path) => {
      if (path === "/portal/chats") return Promise.resolve([]);
      if (path === "/tenants/current") return Promise.reject(new Error("boom"));
      return Promise.resolve({});
    });
    _render();
    await waitFor(() => expect(getSpy).toHaveBeenCalledWith("/tenants/current"));
    expect(screen.queryByTestId("portal-chats-sms-config-hint")).toBeNull();
  });
});
