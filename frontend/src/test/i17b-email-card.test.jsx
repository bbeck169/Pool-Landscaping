/**
 * Phase I1.7.b · Feb-2026 — Email card vitest suite.
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
import { ConfirmProvider } from "@/components/ui/confirm-dialog";


const renderCard = () => render(
  <ConfirmProvider>
    <TenantIntegrationsCard />
  </ConfirmProvider>,
);


const _EMAIL_SCHEMAS = [
  { provider_key: "resend", kind: "email", fields: [
    { name: "api_key",   required: true, secret: true,  label: "Resend API key" },
    { name: "from_addr", required: true, secret: false, label: "Default From address" },
  ]},
  { provider_key: "sendgrid", kind: "email", fields: [
    { name: "api_key", required: true, secret: true,  label: "SendGrid API key" },
    { name: "from_addr", required: true, secret: false, label: "Verified sender address" },
  ]},
  { provider_key: "smtp", kind: "email", fields: [
    { name: "host", required: true, secret: false, label: "SMTP host" },
    { name: "port", required: true, secret: false, label: "SMTP port" },
    { name: "username", required: true, secret: false, label: "SMTP username" },
    { name: "password", required: true, secret: true,  label: "SMTP password" },
    { name: "from_addr", required: true, secret: false, label: "Default From address" },
  ]},
];


const _mockRoutes = (rows) => {
  mockGet.mockImplementation(async (path) => {
    if (path === "/tenants/me/integrations")
      return { tenant_id: "tenant-i17b", integrations: rows };
    if (path === "/tenants/me/integrations/schemas")
      return { sms: [], email: _EMAIL_SCHEMAS };
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
  // I1.7.c.2.followup · Feb-2026 — no more window.confirm spy.
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, assign: vi.fn(),
              pathname: "/settings/integrations", search: "", hash: "" },
  });
});


afterEach(() => { vi.restoreAllMocks(); });


describe("TenantIntegrationsCard · Email card (I1.7.b)", () => {
  const _asAdmin = () => window.localStorage.setItem("user",
    JSON.stringify({ id: "admin", role: "admin", email: "admin@example.com" }));

  it("renders Email provider dropdown + schema fields", async () => {
    _asAdmin();
    _mockRoutes([]);
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-email")).toBeTruthy(),
    );
    const select = screen.getByTestId("tenant-integration-email-provider-select");
    expect(Array.from(select.options).map((o) => o.value))
      .toEqual(["resend", "sendgrid", "smtp"]);
    // Default = resend → api_key + from_addr.
    expect(screen.getByTestId("tenant-integration-email-field-api_key")).toBeTruthy();
    expect(screen.getByTestId("tenant-integration-email-field-from_addr")).toBeTruthy();
    // Secret field is a password input.
    expect(
      screen.getByTestId("tenant-integration-email-field-api_key").getAttribute("type"),
    ).toBe("password");
  });

  it("switching provider to smtp reveals SMTP-specific fields", async () => {
    _asAdmin();
    _mockRoutes([]);
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-email-provider-select")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("tenant-integration-email-provider-select"),
      { target: { value: "smtp" } });
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-email-field-host")).toBeTruthy(),
    );
    expect(screen.getByTestId("tenant-integration-email-field-password")
      .getAttribute("type")).toBe("password");
  });

  it("save posts PUT with the collected email config", async () => {
    _asAdmin();
    _mockRoutes([]);
    mockPut.mockResolvedValue({ saved: true, provider_key: "resend",
      connected_account_id_masked: "hello…l.com" });
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-email-field-api_key")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("tenant-integration-email-field-api_key"),
      { target: { value: "re_test_key" } });
    fireEvent.change(screen.getByTestId("tenant-integration-email-field-from_addr"),
      { target: { value: "hello@example.com" } });
    fireEvent.click(screen.getByTestId("tenant-integration-email-save"));
    await waitFor(() =>
      expect(mockPut).toHaveBeenCalledWith(
        "/tenants/me/integrations/resend",
        { config: { api_key: "re_test_key", from_addr: "hello@example.com" } },
      ),
    );
    await waitFor(() => expect(mockToastSuccess).toHaveBeenCalled());
  });

  it("connected state hides plaintext password from the DOM", async () => {
    _asAdmin();
    _mockRoutes([{
      provider_key: "smtp", connection_type: "api_key",
      connected: true, last_4: "d321",
      connected_account_id_masked: "hello…l.com",
      last_used_at: "2026-02-01T12:00:00Z",
      connected_status: "connected", error_log_count: 0,
    }]);
    const { container } = render(
      <ConfirmProvider>
        <TenantIntegrationsCard />
      </ConfirmProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-email-summary")).toBeTruthy(),
    );
    // Once the connected provider is smtp, the form should re-render
    // with SMTP-specific fields — including the password input.
    await waitFor(() =>
      expect(screen.getByTestId("tenant-integration-email-field-password")).toBeTruthy(),
    );
    const pw = screen.getByTestId("tenant-integration-email-field-password");
    expect(pw.value).toBe("");
    expect(container.textContent).not.toMatch(/PLAINTEXT/i);
  });

  // I1.7.c.2.followup · Task A · Feb-2026 — Modal interaction tests
  // for the email disconnect flow.
  describe("Email disconnect confirmation modal · Task A", () => {
    const _connectedResend = [{
      provider_key: "resend", connection_type: "api_key",
      connected: true, last_4: "y_ab",
      connected_account_id_masked: "hello…l.com",
      last_used_at: "2026-02-05T12:00:00Z",
      connected_status: "connected", error_log_count: 0,
    }];

    it("Email disconnect click opens the in-app modal (no window.confirm)", async () => {
      _asAdmin();
      _mockRoutes(_connectedResend);
      renderCard();
      await waitFor(() =>
        expect(screen.getByTestId("tenant-integration-email-disconnect")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId("tenant-integration-email-disconnect"));
      await waitFor(() =>
        expect(screen.getByTestId("integrations-disconnect-confirm")).toBeTruthy(),
      );
      expect(screen.getByTestId("integrations-disconnect-cancel")).toBeTruthy();
      expect(mockDelete).not.toHaveBeenCalled();
    });

    it("Email modal · Confirm fires DELETE", async () => {
      _asAdmin();
      _mockRoutes(_connectedResend);
      mockDelete.mockResolvedValue({ removed: true, provider_key: "resend" });
      renderCard();
      await waitFor(() =>
        expect(screen.getByTestId("tenant-integration-email-disconnect")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId("tenant-integration-email-disconnect"));
      await waitFor(() =>
        expect(screen.getByTestId("integrations-disconnect-confirm")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId("integrations-disconnect-confirm"));
      await waitFor(() =>
        expect(mockDelete).toHaveBeenCalledWith("/tenants/me/integrations/resend"),
      );
    });

    it("Email modal · Cancel closes it and does NOT fire DELETE", async () => {
      _asAdmin();
      _mockRoutes(_connectedResend);
      renderCard();
      await waitFor(() =>
        expect(screen.getByTestId("tenant-integration-email-disconnect")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId("tenant-integration-email-disconnect"));
      await waitFor(() =>
        expect(screen.getByTestId("integrations-disconnect-cancel")).toBeTruthy(),
      );
      fireEvent.click(screen.getByTestId("integrations-disconnect-cancel"));
      await waitFor(() =>
        expect(screen.queryByTestId("integrations-disconnect-confirm")).toBeNull(),
      );
      expect(mockDelete).not.toHaveBeenCalled();
    });
  });
});
