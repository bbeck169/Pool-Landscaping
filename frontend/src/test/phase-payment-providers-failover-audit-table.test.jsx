/**
 * Feb-2026 · Payment Processors Test Connection + failover audit table.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";


const mockGet = vi.fn();
const mockPatch = vi.fn();
const mockPost = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    patch: (...a) => mockPatch(...a),
    post: (...a) => mockPost(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(() => {},
    { success: () => {}, error: () => {} }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (_k, def) => def }),
}));

import PaymentProvidersCard from "../components/settings/PaymentProvidersCard";


const _availableConfigured = [
  { short_name: "stripe", provider_key: "pay_stripe",
    is_configured: true, requires_tenant_config: false },
  { short_name: "lumino", provider_key: "pay_lumino",
    is_configured: false, requires_tenant_config: true },
];


describe("PaymentProvidersCard · Test Connection + audit", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPatch.mockReset();
    mockPost.mockReset();
    mockGet.mockImplementation((path) => {
      if (path.includes("/settings/payment-providers")) {
        return Promise.resolve({
          primary_provider: "stripe",
          backup_provider: null,
          available: _availableConfigured,
        });
      }
      return Promise.resolve({ total: 0, rows: [] });
    });
  });

  it("Test Connection button next to Primary is enabled when configured", async () => {
    render(<PaymentProvidersCard />);
    await screen.findByTestId("payment-providers-primary-select");
    const btn = screen.getByTestId("payment-providers-test-stripe");
    expect(btn).not.toBeDisabled();
  });

  it("Test Connection posts and renders latency on success", async () => {
    mockPost.mockResolvedValue({
      ok: true, provider: "stripe", latency_ms: 128, error: null,
    });
    render(<PaymentProvidersCard />);
    const btn = await screen.findByTestId("payment-providers-test-stripe");
    fireEvent.click(btn);
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      "/tenants/mine/payment-providers/test", { provider: "stripe" },
    ));
    const result = await screen.findByTestId(
      "payment-providers-test-result-stripe",
    );
    expect(result.textContent).toMatch(/128ms/);
    expect(result.textContent).toMatch(/Connected/);
  });

  it("Test Connection renders error message on failure", async () => {
    mockPost.mockResolvedValue({
      ok: false, provider: "stripe", latency_ms: 88,
      error: "AuthError: bad api key",
    });
    render(<PaymentProvidersCard />);
    const btn = await screen.findByTestId("payment-providers-test-stripe");
    fireEvent.click(btn);
    const result = await screen.findByTestId(
      "payment-providers-test-result-stripe",
    );
    expect(result.textContent).toMatch(/AuthError/);
  });

  it("Test Connection button is disabled for unconfigured providers", async () => {
    // Switch primary to lumino which is unconfigured in this fixture.
    render(<PaymentProvidersCard />);
    const primary = await screen.findByTestId("payment-providers-primary-select");
    fireEvent.change(primary, { target: { value: "lumino" } });
    const btn = screen.getByTestId("payment-providers-test-lumino");
    expect(btn).toBeDisabled();
  });

  it("renders the failover audit table when the server returns rows", async () => {
    mockGet.mockImplementation((path) => {
      if (path.includes("/settings/payment-providers")) {
        return Promise.resolve({
          primary_provider: "stripe",
          backup_provider: "lumino",
          available: _availableConfigured,
        });
      }
      return Promise.resolve({
        total: 2,
        rows: [
          { id: "row_a", tenant_id: "t1", operation: "create_charge",
            primary_provider: "stripe", backup_provider: "lumino",
            error_from_primary: "ProviderTransientError",
            resolution: "backup_used",
            timestamp: "2026-02-15T12:00:00Z" },
          { id: "row_b", tenant_id: "t1", operation: "create_charge",
            primary_provider: "stripe", backup_provider: "lumino",
            error_from_primary: "primary_unconfigured",
            resolution: "static_config",
            timestamp: "2026-02-14T12:00:00Z" },
        ],
      });
    });
    render(<PaymentProvidersCard />);
    await waitFor(() =>
      expect(screen.getByTestId("payment-providers-audit-row-row_a"))
        .toBeInTheDocument(),
    );
    expect(screen.getByTestId("payment-providers-audit-row-row_b"))
      .toBeInTheDocument();
  });
});
