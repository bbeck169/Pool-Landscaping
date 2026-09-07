/**
 * Phase I1.7.d · Feb-2026 — Payments-BYO cards vitest suite.
 *
 * Pins:
 *   1. All 4 payment cards render (Square, PayPal, Authorize.Net, Lumino).
 *   2. Health dot renders on EVERY integration card (payments + AI + Maps + …).
 *   3. Save (with cap) PUTs /pay_{provider}.
 *   4. Cap-only edit (no secret in payload) doesn't submit blanked secrets.
 *   5. Test connection posts /test-connection and surfaces success/failure.
 *   6. Disconnect uses the shared confirm modal → DELETE /pay_{provider}.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";


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


const _PAY_SCHEMAS = [
  { provider_key: "pay_square", kind: "payments", connection_type: "api_key",
    models: [], fields: [
      { name: "access_token", required: true, secret: true, label: "Square Access Token" },
      { name: "location_id", required: true, secret: false, label: "Location ID" },
      { name: "environment", required: false, secret: false, label: "Environment" },
      { name: "webhook_signing_key", required: true, secret: true, label: "Webhook Signing Key" },
    ]},
  { provider_key: "pay_paypal", kind: "payments", connection_type: "api_key",
    models: [], fields: [
      { name: "client_id", required: true, secret: false, label: "PayPal Client ID" },
      { name: "client_secret", required: true, secret: true, label: "PayPal Client Secret" },
      { name: "environment", required: false, secret: false, label: "Environment" },
      { name: "webhook_id", required: true, secret: true, label: "Webhook ID" },
    ]},
  { provider_key: "pay_authnet", kind: "payments", connection_type: "api_key",
    models: [], fields: [
      { name: "api_login_id", required: true, secret: false, label: "API Login ID" },
      { name: "transaction_key", required: true, secret: true, label: "Transaction Key" },
      { name: "environment", required: false, secret: false, label: "Environment" },
      { name: "signature_key", required: true, secret: true, label: "Signature Key" },
    ]},
  { provider_key: "pay_lumino", kind: "payments", connection_type: "api_key",
    models: [], fields: [
      { name: "api_key", required: true, secret: true, label: "Lumino API Key" },
      { name: "account_id", required: true, secret: false, label: "Account ID" },
      { name: "environment", required: false, secret: false, label: "Environment" },
      { name: "webhook_secret", required: true, secret: true, label: "Webhook Secret" },
    ]},
];


const _mockRoutes = ({
  integrations = [], health = {}, payProviders = [],
} = {}) => {
  mockGet.mockImplementation(async (path) => {
    if (path === "/tenants/me/integrations")
      return { tenant_id: "tenant-i17d", integrations, health };
    if (path === "/tenants/me/integrations/schemas")
      return { sms: [], email: [], ai: [], maps: [], calendars: [],
                payments: _PAY_SCHEMAS };
    if (path === "/tenants/me/integrations/ai/usage") return { providers: [] };
    if (path === "/tenants/me/integrations/maps/usage") return { providers: [] };
    if (path === "/tenants/me/integrations/calendars/usage")
      return { providers: [], technicians: [] };
    if (path === "/tenants/me/integrations/payments/usage")
      return { tenant_id: "tenant-i17d", period_yyyymm: "202602",
                providers: payProviders };
    if (path === "/users?role=tech") return [];
    if (path === "/users") return [];
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
  window.localStorage.setItem("access_token", "x");
  window.localStorage.setItem("user",
    JSON.stringify({ id: "u1", role: "super_admin" }));
});


describe("Phase I1.7.d · Payments-BYO cards", () => {
  it("renders one card per payment provider", async () => {
    _mockRoutes();
    renderCard();
    await waitFor(() => {
      expect(screen.getByTestId("tenant-integration-pay_square")).toBeTruthy();
      expect(screen.getByTestId("tenant-integration-pay_paypal")).toBeTruthy();
      expect(screen.getByTestId("tenant-integration-pay_authnet")).toBeTruthy();
      expect(screen.getByTestId("tenant-integration-pay_lumino")).toBeTruthy();
    });
  });

  it("renders a health dot on every payment card", async () => {
    _mockRoutes({
      health: {
        pay_square:  { provider_key: "pay_square",  status: "ok",
                         checked_at: "2026-02-01T00:00Z",
                         consecutive_failures: 0, last_ok_at: "2026-02-01T00:00Z" },
        pay_paypal:  { provider_key: "pay_paypal",  status: "failed",
                         checked_at: "2026-02-01T00:00Z",
                         last_error: "probe HTTP 500",
                         consecutive_failures: 2 },
        // pay_authnet + pay_lumino intentionally missing → amber/unknown.
      },
    });
    renderCard();
    await waitFor(() => {
      // All 4 dots present.
      expect(screen.getByTestId("tenant-integration-pay_square-health-dot")).toBeTruthy();
      expect(screen.getByTestId("tenant-integration-pay_paypal-health-dot")).toBeTruthy();
      expect(screen.getByTestId("tenant-integration-pay_authnet-health-dot")).toBeTruthy();
      expect(screen.getByTestId("tenant-integration-pay_lumino-health-dot")).toBeTruthy();
    });
    // Data attribute reveals status independent of colour tokens.
    expect(screen.getByTestId("tenant-integration-pay_square-health-dot")
              .getAttribute("data-health-status")).toBe("ok");
    expect(screen.getByTestId("tenant-integration-pay_paypal-health-dot")
              .getAttribute("data-health-status")).toBe("failed");
    expect(screen.getByTestId("tenant-integration-pay_authnet-health-dot")
              .getAttribute("data-health-status")).toBe("unknown");
    expect(screen.getByTestId("tenant-integration-pay_lumino-health-dot")
              .getAttribute("data-health-status")).toBe("unknown");
  });

  it("save PUTs /pay_square with config + monthly_request_cap", async () => {
    _mockRoutes();
    mockPut.mockResolvedValue({ provider_key: "pay_square", saved: true,
                                    connected_account_id_masked: null });
    renderCard();
    const card = await screen.findByTestId("tenant-integration-pay_square");
    // Fill secrets + location.
    fireEvent.change(within(card).getByTestId(
      "tenant-integration-pay_square-field-access_token"),
      { target: { value: "sq_at_LIVE" } });
    fireEvent.change(within(card).getByTestId(
      "tenant-integration-pay_square-field-location_id"),
      { target: { value: "L001" } });
    fireEvent.change(within(card).getByTestId(
      "tenant-integration-pay_square-field-webhook_signing_key"),
      { target: { value: "whsec_sq" } });
    fireEvent.change(within(card).getByTestId(
      "tenant-integration-pay_square-cap-input"),
      { target: { value: "500" } });
    fireEvent.click(within(card).getByTestId(
      "tenant-integration-pay_square-save"));
    await waitFor(() => expect(mockPut).toHaveBeenCalled());
    const [path, payload] = mockPut.mock.calls[0];
    expect(path).toBe("/tenants/me/integrations/pay_square");
    expect(payload.config.access_token).toBe("sq_at_LIVE");
    expect(payload.config.location_id).toBe("L001");
    expect(payload.config.webhook_signing_key).toBe("whsec_sq");
    expect(payload.monthly_request_cap).toBe(500);
  });

  it("cap-only edit doesn't submit blanked-out secret fields", async () => {
    _mockRoutes({
      integrations: [{ provider_key: "pay_paypal", connected: true,
                          last_4: "abcd", last_used_at: null }],
      payProviders: [{ provider: "paypal", period_yyyymm: "202602",
                         charge_count: 0, refund_count: 0, ops_total: 0,
                         monthly_request_cap: 100, connected: true,
                         pct_used: 0, status: "ok" }],
    });
    mockPut.mockResolvedValue({ saved: true });
    renderCard();
    const card = await screen.findByTestId("tenant-integration-pay_paypal");
    // Leave secrets blank — only change cap.
    fireEvent.change(within(card).getByTestId(
      "tenant-integration-pay_paypal-cap-input"),
      { target: { value: "250" } });
    fireEvent.click(within(card).getByTestId(
      "tenant-integration-pay_paypal-save"));
    await waitFor(() => expect(mockPut).toHaveBeenCalled());
    const [, payload] = mockPut.mock.calls[0];
    // Neither secret field should appear in the config payload.
    expect(payload.config.client_secret).toBeUndefined();
    expect(payload.config.webhook_id).toBeUndefined();
    expect(payload.monthly_request_cap).toBe(250);
  });

  it("test-connection surfaces success toast", async () => {
    _mockRoutes({
      integrations: [{ provider_key: "pay_lumino", connected: true,
                          last_4: "abcd", last_used_at: null }],
    });
    mockPost.mockResolvedValue({
      provider_key: "pay_lumino", tenant_id: "t", ok: true,
      message: "mock", checked_at: "2026-02-01T00:00Z",
    });
    renderCard();
    const card = await screen.findByTestId("tenant-integration-pay_lumino");
    fireEvent.click(within(card).getByTestId(
      "tenant-integration-pay_lumino-test"));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/tenants/me/integrations/pay_lumino/test-connection",
    ));
    await waitFor(() => expect(mockToastSuccess).toHaveBeenCalled());
    expect(mockToastError).not.toHaveBeenCalled();
  });

  it("test-connection surfaces failure toast", async () => {
    _mockRoutes({
      integrations: [{ provider_key: "pay_authnet", connected: true,
                          last_4: "abcd", last_used_at: null }],
    });
    mockPost.mockResolvedValue({
      provider_key: "pay_authnet", tenant_id: "t", ok: false,
      message: "Authorize.Net authenticateTest failed.",
      checked_at: "2026-02-01T00:00Z",
    });
    renderCard();
    const card = await screen.findByTestId("tenant-integration-pay_authnet");
    fireEvent.click(within(card).getByTestId(
      "tenant-integration-pay_authnet-test"));
    await waitFor(() => expect(mockToastError).toHaveBeenCalled());
  });

  it("disconnect uses the shared confirm modal → DELETE /pay_{provider}", async () => {
    _mockRoutes({
      integrations: [{ provider_key: "pay_square", connected: true,
                          last_4: "abcd", last_used_at: null }],
    });
    mockDelete.mockResolvedValue({ removed: true, provider_key: "pay_square" });
    renderCard();
    const card = await screen.findByTestId("tenant-integration-pay_square");
    fireEvent.click(within(card).getByTestId(
      "tenant-integration-pay_square-disconnect"));
    // Confirm modal is rendered by ConfirmProvider.
    const confirmBtn = await screen.findByTestId("integrations-disconnect-confirm");
    fireEvent.click(confirmBtn);
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith(
      "/tenants/me/integrations/pay_square",
    ));
  });
});
