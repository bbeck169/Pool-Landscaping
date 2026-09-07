/**
 * Phase I1.7.b · Feb-2026 — SMS card vitest suite.
 *
 * Pins:
 *   1. SMS card renders a provider dropdown with twilio, textmagic,
 *      ringcentral.
 *   2. Selecting a provider renders its field schema — required
 *      fields marked; secret fields use type=password (no plaintext
 *      echo).
 *   3. Save posts PUT /api/tenants/me/integrations/{key} with the
 *      collected config.
 *   4. When already connected, Test connection posts
 *      /api/tenants/me/integrations/{key}/test and refreshes.
 *   5. Manager sees no save/test/disconnect controls.
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


const _SMS_SCHEMAS = [
  { provider_key: "twilio", kind: "sms", fields: [
    { name: "account_sid", required: true, secret: false, label: "Twilio Account SID" },
    { name: "auth_token",  required: true, secret: true,  label: "Auth Token" },
    { name: "from_number", required: true, secret: false, label: "From number" },
  ]},
  { provider_key: "textmagic", kind: "sms", fields: [
    { name: "username", required: true, secret: false, label: "TextMagic username" },
    { name: "api_key",  required: true, secret: true,  label: "API key" },
  ]},
  { provider_key: "ringcentral", kind: "sms", fields: [
    { name: "server_url", required: true, secret: false, label: "Server URL" },
    { name: "client_id",  required: true, secret: false, label: "Client ID" },
    { name: "client_secret", required: true, secret: true, label: "Client Secret" },
    { name: "jwt_token", required: true, secret: true, label: "JWT" },
    { name: "from_number", required: true, secret: false, label: "From number" },
  ]},
];


const _mockRoutes = (rows) => {
  mockGet.mockImplementation(async (path) => {
    if (path === "/tenants/me/integrations")
      return { tenant_id: "tenant-i17b", integrations: rows };
    if (path === "/tenants/me/integrations/schemas")
      return { sms: _SMS_SCHEMAS, email: [] };
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


describe("TenantIntegrationsCard · SMS card (I1.7.b)", () => {
  const _asAdmin = () => window.localStorage.setItem("user",
    JSON.stringify({ id: "admin", role: "admin", email: "admin@example.com" }));

  it("renders SMS provider dropdown + schema fields", async () => {
    _asAdmin();
    _mockRoutes([]);
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-sms")).toBeTruthy(),
    );
    const select = screen.getByTestId("tenant-integration-sms-provider-select");
    expect(select.tagName).toBe("SELECT");
    expect(Array.from(select.options).map((o) => o.value))
      .toEqual(["twilio", "textmagic", "ringcentral"]);
    // Default = twilio → its 3 fields rendered.
    expect(screen.getByTestId("tenant-integration-sms-field-account_sid")).toBeTruthy();
    expect(screen.getByTestId("tenant-integration-sms-field-auth_token")).toBeTruthy();
    expect(screen.getByTestId("tenant-integration-sms-field-from_number")).toBeTruthy();
    // Secret field is a password input.
    expect(
      screen.getByTestId("tenant-integration-sms-field-auth_token").getAttribute("type"),
    ).toBe("password");
  });

  it("switching provider re-renders the correct field schema", async () => {
    _asAdmin();
    _mockRoutes([]);
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-sms-provider-select")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("tenant-integration-sms-provider-select"),
      { target: { value: "textmagic" } });
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-sms-field-username")).toBeTruthy(),
    );
    // Twilio's field is gone.
    expect(screen.queryByTestId("tenant-integration-sms-field-account_sid")).toBeNull();
  });

  it("save posts PUT with the collected config", async () => {
    _asAdmin();
    _mockRoutes([]);
    mockPut.mockResolvedValue({ saved: true, provider_key: "twilio",
      connected_account_id_masked: "ACabc…1234" });
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-sms-field-account_sid")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("tenant-integration-sms-field-account_sid"),
      { target: { value: "AC1234567890" } });
    fireEvent.change(screen.getByTestId("tenant-integration-sms-field-auth_token"),
      { target: { value: "tok-xyz" } });
    fireEvent.change(screen.getByTestId("tenant-integration-sms-field-from_number"),
      { target: { value: "+15550001111" } });
    fireEvent.click(screen.getByTestId("tenant-integration-sms-save"));
    await waitFor(() =>
      expect(mockPut).toHaveBeenCalledWith(
        "/tenants/me/integrations/twilio",
        { config: { account_sid: "AC1234567890", auth_token: "tok-xyz", from_number: "+15550001111" } },
      ),
    );
    await waitFor(() => expect(mockToastSuccess).toHaveBeenCalled());
  });

  it("shows Connected summary and enables Test/Disconnect when a provider is saved", async () => {
    _asAdmin();
    _mockRoutes([{
      provider_key: "twilio", connection_type: "api_key",
      connected: true, last_4: "-xyz",
      connected_account_id_masked: "ACabc…1234",
      last_used_at: "2026-02-05T12:00:00Z",
      connected_status: "connected", error_log_count: 0,
    }]);
    mockPost.mockResolvedValue({ ok: true, message: "Twilio OK",
      provider_key: "twilio", tenant_id: "tenant-i17b",
      checked_at: "2026-02-05T12:34:56Z" });
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-sms-summary")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-sms-provider-key").textContent)
      .toBe("twilio");
    expect(screen.getByTestId("tenant-integration-sms-account").textContent)
      .toContain("ACabc");
    // Test button visible + wired.
    fireEvent.click(screen.getByTestId("tenant-integration-sms-test"));
    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith("/tenants/me/integrations/twilio/test"),
    );
  });

  it("managers see the SMS card but no save/test/disconnect controls", async () => {
    window.localStorage.setItem("user",
      JSON.stringify({ id: "m", role: "manager", email: "m@example.com" }));
    _mockRoutes([]);
    render(<TenantIntegrationsCard />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-sms")).toBeTruthy(),
    );
    expect(screen.queryByTestId("tenant-integration-sms-save")).toBeNull();
    expect(screen.queryByTestId("tenant-integration-sms-test")).toBeNull();
    expect(screen.queryByTestId("tenant-integration-sms-disconnect")).toBeNull();
    expect(screen.queryByTestId("tenant-integration-sms-provider-select")).toBeNull();
  });
});
