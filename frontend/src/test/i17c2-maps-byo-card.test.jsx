/**
 * Phase I1.7.c.2 · Feb-2026 — Maps BYO card vitest suite.
 *
 * Pins:
 *   1. Renders one Maps card per provider (google, mapbox).
 *   2. Save posts PUT with api_key + non-secret fields + monthly_request_cap.
 *   3. Cap-only edit on connected provider sends PUT with blank api_key.
 *   4. Usage bar renders warn at status=warn, blocked at status=blocked.
 *   5. Disconnect flips the card back to disconnected state.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";


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


const _MAPS_SCHEMAS = [
  { provider_key: "maps_google", kind: "maps", models: [], fields: [
    { name: "api_key",     required: true,  secret: true,  label: "Google Maps API Key" },
    { name: "region_bias", required: false, secret: false, label: "Region bias (ISO country code)" },
  ]},
  { provider_key: "maps_mapbox", kind: "maps", models: [], fields: [
    { name: "api_key", required: true,  secret: true,  label: "Mapbox Access Token" },
    { name: "style",   required: false, secret: false, label: "Static map style" },
  ]},
];


const _mockRoutes = (rows, mapsProviders = []) => {
  mockGet.mockImplementation(async (path) => {
    if (path === "/tenants/me/integrations")
      return { tenant_id: "tenant-i17c2", integrations: rows };
    if (path === "/tenants/me/integrations/schemas")
      return { sms: [], email: [], ai: [], maps: _MAPS_SCHEMAS };
    if (path === "/tenants/me/integrations/ai/usage")
      return { tenant_id: "tenant-i17c2", period_yyyymm: "202602", providers: [] };
    if (path === "/tenants/me/integrations/maps/usage")
      return { tenant_id: "tenant-i17c2", period_yyyymm: "202602",
                providers: mapsProviders };
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
  window.localStorage.clear();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, assign: vi.fn(),
              pathname: "/settings/integrations", search: "", hash: "" },
  });
});


afterEach(() => { vi.restoreAllMocks(); });


describe("TenantIntegrationsCard · Maps BYO cards (I1.7.c.2)", () => {
  const _asAdmin = () => window.localStorage.setItem("user",
    JSON.stringify({ id: "admin", role: "admin", email: "admin@example.com" }));

  it("renders one Maps card per provider with the correct non-secret fields", async () => {
    _asAdmin();
    _mockRoutes([]);
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-maps_google")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-maps_mapbox")).toBeTruthy();
    // Google exposes region_bias; Mapbox exposes style.
    expect(screen.getByTestId("tenant-integration-maps_google-field-region_bias")).toBeTruthy();
    expect(screen.getByTestId("tenant-integration-maps_mapbox-field-style")).toBeTruthy();
    // api_key input is a password type for both.
    expect(
      screen.getByTestId("tenant-integration-maps_google-field-api_key").getAttribute("type"),
    ).toBe("password");
    expect(
      screen.getByTestId("tenant-integration-maps_mapbox-field-api_key").getAttribute("type"),
    ).toBe("password");
  });

  it("save posts PUT with api_key + non-secret + monthly_request_cap", async () => {
    _asAdmin();
    _mockRoutes([]);
    mockPut.mockResolvedValue({ saved: true, provider_key: "maps_google" });
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-maps_google-field-api_key")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("tenant-integration-maps_google-field-api_key"),
      { target: { value: "gmk-abc123" } });
    fireEvent.change(screen.getByTestId("tenant-integration-maps_google-field-region_bias"),
      { target: { value: "us" } });
    fireEvent.change(screen.getByTestId("tenant-integration-maps_google-cap-input"),
      { target: { value: "50000" } });
    fireEvent.click(screen.getByTestId("tenant-integration-maps_google-save"));
    await waitFor(() => expect(mockPut).toHaveBeenCalled());
    const [path, body] = mockPut.mock.calls[0];
    expect(path).toBe("/tenants/me/integrations/maps_google");
    expect(body.config.api_key).toBe("gmk-abc123");
    expect(body.config.region_bias).toBe("us");
    expect(body.monthly_request_cap).toBe(50000);
  });

  it("cap-only edit on connected maps provider sends PUT with blank api_key", async () => {
    _asAdmin();
    _mockRoutes(
      [{
        provider_key: "maps_google", connection_type: "api_key",
        connected: true, last_4: "ORIG",
        connected_account_id_masked: null,
        last_used_at: null, connected_status: "connected", error_log_count: 0,
      }],
      [{ provider: "google", period_yyyymm: "202602",
          geocode: 0, route: 0, static_map: 0, total: 0,
          monthly_request_cap: 10000,
          connected: true, pct_used: 0, status: "ok" }],
    );
    mockPut.mockResolvedValue({ saved: true, provider_key: "maps_google" });
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-maps_google-cap-input")).toBeTruthy(),
    );
    // Edit ONLY the cap — leave api_key blank on purpose.
    fireEvent.change(screen.getByTestId("tenant-integration-maps_google-cap-input"),
      { target: { value: "25000" } });
    fireEvent.click(screen.getByTestId("tenant-integration-maps_google-save"));
    await waitFor(() => expect(mockPut).toHaveBeenCalled());
    const [path, body] = mockPut.mock.calls[0];
    expect(path).toBe("/tenants/me/integrations/maps_google");
    expect(body.config.api_key).toBe("");
    expect(body.monthly_request_cap).toBe(25000);
  });

  it("shows warn banner when usage.status=warn (>=80% of cap)", async () => {
    _asAdmin();
    _mockRoutes(
      [{
        provider_key: "maps_google", connection_type: "api_key",
        connected: true, last_4: "WARN",
        connected_account_id_masked: null,
        last_used_at: "2026-02-05T12:00:00Z",
        connected_status: "connected", error_log_count: 0,
      }],
      [{ provider: "google", period_yyyymm: "202602",
          geocode: 60, route: 20, static_map: 5, total: 85,
          monthly_request_cap: 100,
          connected: true, pct_used: 0.85, status: "warn" }],
    );
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-maps_google-usage-warn")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-maps_google-usage-bar")).toBeTruthy();
    expect(screen.getByTestId("tenant-integration-maps_google-usage-breakdown").textContent)
      .toMatch(/geocode 60/);
  });

  it("shows blocked banner when usage.status=blocked (cap=0 or 100%)", async () => {
    _asAdmin();
    _mockRoutes(
      [{
        provider_key: "maps_mapbox", connection_type: "api_key",
        connected: true, last_4: "STOP",
        connected_account_id_masked: null,
        last_used_at: null, connected_status: "connected", error_log_count: 0,
      }],
      [{ provider: "mapbox", period_yyyymm: "202602",
          geocode: 0, route: 0, static_map: 0, total: 0,
          monthly_request_cap: 0,
          connected: true, pct_used: null, status: "blocked" }],
    );
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-maps_mapbox-usage-blocked")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-maps_mapbox-usage-label").textContent)
      .toContain("Blocked");
  });

  it("disconnect flips the maps card back to disconnected state", async () => {
    _asAdmin();
    let listCallCount = 0;
    mockGet.mockImplementation(async (path) => {
      if (path === "/tenants/me/integrations") {
        listCallCount += 1;
        return listCallCount === 1
          ? {
              tenant_id: "t", integrations: [{
                provider_key: "maps_google", connection_type: "api_key",
                connected: true, last_4: "GONE",
                connected_account_id_masked: null,
                last_used_at: null, connected_status: "connected",
                error_log_count: 0,
              }],
            }
          : { tenant_id: "t", integrations: [] };
      }
      if (path === "/tenants/me/integrations/schemas")
        return { sms: [], email: [], ai: [], maps: _MAPS_SCHEMAS };
      if (path === "/tenants/me/integrations/ai/usage")
        return { tenant_id: "t", period_yyyymm: "202602", providers: [] };
      if (path === "/tenants/me/integrations/maps/usage")
        return { tenant_id: "t", period_yyyymm: "202602",
                  providers: listCallCount >= 2 ? [] : [
                    { provider: "google", period_yyyymm: "202602",
                       geocode: 0, route: 0, static_map: 0, total: 0,
                       monthly_request_cap: 10000,
                       connected: true, pct_used: 0, status: "ok" }] };
      return {};
    });
    mockDelete.mockResolvedValue({ removed: true, provider_key: "maps_google" });
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-maps_google-status").textContent)
        .toMatch(/connected/i),
    );
    expect(screen.getByTestId("tenant-integration-maps_google-status").textContent)
      .not.toMatch(/not connected/i);
    fireEvent.click(screen.getByTestId("tenant-integration-maps_google-disconnect"));
    await waitFor(() =>
      expect(mockDelete).toHaveBeenCalledWith("/tenants/me/integrations/maps_google"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-maps_google-status").textContent)
        .toMatch(/not connected/i),
    );
    expect(screen.queryByTestId("tenant-integration-maps_google-disconnect")).toBeNull();
  });

  it("manager sees maps cards but no save/disconnect controls", async () => {
    window.localStorage.setItem("user",
      JSON.stringify({ id: "m", role: "manager", email: "m@example.com" }));
    _mockRoutes([]);
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-maps_google")).toBeTruthy(),
    );
    expect(screen.queryByTestId("tenant-integration-maps_google-save")).toBeNull();
    expect(screen.queryByTestId("tenant-integration-maps_google-field-api_key")).toBeNull();
  });
});
