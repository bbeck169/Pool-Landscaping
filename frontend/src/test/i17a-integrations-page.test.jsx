/**
 * Phase I1.7.a · Feb-2026 — TenantIntegrationsCard vitest suite.
 *
 * Pins:
 *   1. Renders a grid with the Stripe card + "Coming soon"
 *      placeholders (SMS, Email, AI, Maps, Calendars, Storage).
 *   2. GET /tenants/me/integrations is called on mount.
 *   3. Connect Stripe (admin) → GET /integrations/stripe/connect-link
 *      then full-page redirect to the returned URL.
 *   4. Test connection → POST /tenants/me/integrations/stripe/test,
 *      shows success toast on ok=true.
 *   5. Disconnect → DELETE /tenants/me/integrations/stripe when the
 *      user confirms.
 *   6. Non-admin (role=manager) does NOT render Connect / Test /
 *      Disconnect buttons.
 *   7. Response body is scanned — NO plaintext token pattern ever
 *      shows up on screen (belt-and-suspenders lock on the
 *      encryption-boundary guarantee).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";


const mockGet = vi.fn();
const mockPost = vi.fn();
const mockDelete = vi.fn();
const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    delete: (...a) => mockDelete(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(
    (...a) => mockToastSuccess(...a),
    { success: (...a) => mockToastSuccess(...a),
      error: (...a) => mockToastError(...a) },
  ),
}));

import TenantIntegrationsCard from "@/components/settings/TenantIntegrationsCard";


const _seedList = (overrides = []) => ({
  tenant_id: "tenant-i17a-vitest",
  integrations: overrides,
});


const _asAdmin = () => {
  window.localStorage.setItem("user", JSON.stringify({
    id: "user-i17a-admin", role: "admin", email: "admin@example.com",
  }));
};


const _asManager = () => {
  window.localStorage.setItem("user", JSON.stringify({
    id: "user-i17a-mgr", role: "manager", email: "mgr@example.com",
  }));
};


beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockDelete.mockReset();
  mockToastSuccess.mockReset();
  mockToastError.mockReset();
  window.localStorage.clear();
  // Silence window.confirm for the disconnect path.
  vi.spyOn(window, "confirm").mockReturnValue(true);
  // JSDOM doesn't implement navigation — stub location.assign so the
  // Stripe connect redirect doesn't blow up the test.
  Object.defineProperty(window, "location", {
    configurable: true,
    value: {
      ...window.location,
      assign: vi.fn(),
      pathname: "/settings/integrations",
      search: "",
      hash: "",
    },
  });
});


afterEach(() => {
  vi.restoreAllMocks();
});


describe("TenantIntegrationsCard · I1.7.a", () => {
  it("renders Stripe + coming-soon placeholders and loads the list", async () => {
    _asAdmin();
    mockGet.mockResolvedValue(_seedList());
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integrations-card")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-stripe")).toBeTruthy();
    ["sms", "email", "ai", "maps", "calendars", "storage"].forEach((k) => {
      expect(screen.getByTestId(`tenant-integration-${k}`)).toBeTruthy();
      expect(screen.getByTestId(`tenant-integration-${k}-status`).textContent)
        .toMatch(/coming soon/i);
    });
    expect(mockGet).toHaveBeenCalledWith("/tenants/me/integrations");
  });

  it("connect-stripe hits the backend and redirects to the returned URL", async () => {
    _asAdmin();
    mockGet
      .mockResolvedValueOnce(_seedList())
      .mockResolvedValueOnce({ url: "https://connect.stripe.com/oauth/authorize?client_id=ca_x&state=abc", state: "abc" });
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-stripe-connect")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("tenant-integration-stripe-connect"));
    await waitFor(() =>
      expect(mockGet).toHaveBeenCalledWith("/integrations/stripe/connect-link"),
    );
    await waitFor(() =>
      expect(window.location.assign).toHaveBeenCalledWith(
        expect.stringContaining("connect.stripe.com"),
      ),
    );
  });

  it("renders masked account + last_4 when Stripe is connected — never plaintext", async () => {
    _asAdmin();
    const connectedRow = {
      provider_key: "stripe",
      connection_type: "oauth_stripe_connect",
      connected: true,
      last_4: "beef",
      connected_account_id_masked: "acct_…9xyz",
      last_used_at: "2026-02-01T12:00:00Z",
      connected_status: "connected",
      error_log_count: 0,
      last_error: null,
    };
    mockGet.mockResolvedValue(_seedList([connectedRow]));
    const { container } = render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-stripe-summary")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-stripe-account").textContent)
      .toBe("acct_…9xyz");
    expect(screen.getByTestId("tenant-integration-stripe-last4").textContent)
      .toBe("••••beef");
    // Belt-and-braces: nothing rendered contains a plaintext ``sk_``.
    expect(container.textContent).not.toMatch(/sk_(test|live)_[A-Za-z0-9]/);
  });

  it("test-connection posts and surfaces a success toast on ok=true", async () => {
    _asAdmin();
    mockGet.mockResolvedValue(_seedList([{
      provider_key: "stripe", connection_type: "oauth_stripe_connect",
      connected: true, last_4: "abcd",
      connected_account_id_masked: "acct_…1234",
      connected_status: "connected", error_log_count: 0,
    }]));
    mockPost.mockResolvedValue({
      provider_key: "stripe", tenant_id: "tenant-i17a-vitest", ok: true,
      connected_account_id_masked: "acct_…1234",
      message: "Stripe Account.retrieve returned OK.",
      checked_at: "2026-02-01T12:34:56Z",
    });
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-stripe-test")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("tenant-integration-stripe-test"));
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith("/tenants/me/integrations/stripe/test"),
    );
    await waitFor(() =>
      expect(mockToastSuccess).toHaveBeenCalled(),
    );
  });

  it("disconnect calls DELETE and refreshes the list", async () => {
    _asAdmin();
    mockGet
      .mockResolvedValueOnce(_seedList([{
        provider_key: "stripe", connection_type: "oauth_stripe_connect",
        connected: true, last_4: "abcd",
        connected_account_id_masked: "acct_…1234",
        connected_status: "connected", error_log_count: 0,
      }]))
      .mockResolvedValueOnce(_seedList([]));
    mockDelete.mockResolvedValue({ removed: true, provider_key: "stripe" });
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-stripe-disconnect")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("tenant-integration-stripe-disconnect"));
    await waitFor(() =>
      expect(mockDelete).toHaveBeenCalledWith("/tenants/me/integrations/stripe"),
    );
    await waitFor(() =>
      expect(mockToastSuccess).toHaveBeenCalled(),
    );
  });

  it("managers see the Stripe card but no write buttons", async () => {
    _asManager();
    mockGet.mockResolvedValue(_seedList());
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-stripe")).toBeTruthy(),
    );
    expect(screen.queryByTestId("tenant-integration-stripe-connect")).toBeNull();
    expect(screen.queryByTestId("tenant-integration-stripe-test")).toBeNull();
    expect(screen.queryByTestId("tenant-integration-stripe-disconnect")).toBeNull();
  });
});
