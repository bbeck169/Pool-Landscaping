/**
 * Phase I1.7.b · Feb-2026 — Stale badge vitest suite.
 *
 * The stale badge appears when ``last_used_at`` is > 30 days old on
 * any connected provider row (Stripe, SMS, Email). It nudges tenants
 * to click Test connection before their next batch and surfaces
 * revoked tokens early.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";


const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();
const mockDelete = vi.fn();
const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    put: (...a) => mockPut(...a),
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


const _mockRoutes = (rows) => {
  mockGet.mockImplementation(async (path) => {
    if (path === "/tenants/me/integrations")
      return { tenant_id: "tenant-i17b", integrations: rows };
    if (path === "/tenants/me/integrations/schemas")
      return { sms: [], email: [] };
    return {};
  });
};


beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPut.mockReset();
  mockDelete.mockReset();
  mockToastSuccess.mockReset();
  mockToastError.mockReset();
  window.localStorage.setItem("user",
    JSON.stringify({ id: "admin", role: "admin", email: "a@example.com" }));
  vi.spyOn(window, "confirm").mockReturnValue(true);
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, assign: vi.fn(),
              pathname: "/settings/integrations", search: "", hash: "" },
  });
});


afterEach(() => { vi.restoreAllMocks(); window.localStorage.clear(); });


const _dayIso = (offsetDays) =>
  new Date(Date.now() - offsetDays * 24 * 60 * 60 * 1000).toISOString();


describe("Stale badge · I1.7.b (yellow > 30d)", () => {
  it("appears when Stripe last_used_at is older than 30 days", async () => {
    _mockRoutes([{
      provider_key: "stripe", connection_type: "oauth_stripe_connect",
      connected: true, last_4: "abcd",
      connected_account_id_masked: "acct_…9xyz",
      last_used_at: _dayIso(45),   // 45 days old
      connected_status: "connected", error_log_count: 0,
    }]);
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-stripe-stale")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-stripe-stale").textContent)
      .toMatch(/stale/i);
  });

  it("does NOT appear when last_used_at is within 30 days", async () => {
    _mockRoutes([{
      provider_key: "stripe", connection_type: "oauth_stripe_connect",
      connected: true, last_4: "abcd",
      connected_account_id_masked: "acct_…9xyz",
      last_used_at: _dayIso(10),   // 10 days old
      connected_status: "connected", error_log_count: 0,
    }]);
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-stripe-summary")).toBeTruthy(),
    );
    expect(screen.queryByTestId("tenant-integration-stripe-stale")).toBeNull();
  });

  it("does NOT appear on unconnected providers", async () => {
    _mockRoutes([]);
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-stripe")).toBeTruthy(),
    );
    expect(screen.queryByTestId("tenant-integration-stripe-stale")).toBeNull();
  });
});
