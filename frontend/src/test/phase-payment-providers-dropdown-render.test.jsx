/**
 * Feb-2026 · Payment Processors dropdown render.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";


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
    { success: () => {}, error: () => {}, message: () => {} }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (_k, def) => def }),
}));

import PaymentProvidersCard from "../components/settings/PaymentProvidersCard";


const _defaultAvailable = [
  { short_name: "stripe", provider_key: "pay_stripe",
    is_configured: true, requires_tenant_config: false },
  { short_name: "square", provider_key: "pay_square",
    is_configured: false, requires_tenant_config: true },
  { short_name: "lumino", provider_key: "pay_lumino",
    is_configured: false, requires_tenant_config: true },
];


describe("PaymentProvidersCard · render", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPatch.mockReset();
    mockPost.mockReset();
  });

  it("fetches settings on mount and renders both dropdowns", async () => {
    mockGet.mockImplementation((path) => {
      if (path.includes("/settings/payment-providers")) {
        return Promise.resolve({
          primary_provider: "stripe",
          backup_provider: null,
          available: _defaultAvailable,
        });
      }
      if (path.includes("/payment-audit")) {
        return Promise.resolve({ total: 0, rows: [] });
      }
      return Promise.resolve({});
    });

    render(<PaymentProvidersCard />);

    await waitFor(() =>
      expect(screen.getByTestId("payment-providers-primary-select"))
        .toBeInTheDocument(),
    );
    expect(screen.getByTestId("payment-providers-backup-select"))
      .toBeInTheDocument();
    // The backup select carries a "None" option.
    expect(screen.getByTestId("payment-providers-option-none"))
      .toBeInTheDocument();
  });

  it("marks configured providers with · Configured label and missing with · Missing keys", async () => {
    mockGet.mockImplementation((path) => {
      if (path.includes("/settings/payment-providers")) {
        return Promise.resolve({
          primary_provider: "stripe",
          backup_provider: null,
          available: _defaultAvailable,
        });
      }
      return Promise.resolve({ total: 0, rows: [] });
    });
    render(<PaymentProvidersCard />);

    const primary = await screen.findByTestId("payment-providers-primary-select");
    // Query the <option> children by their testid via querySelector —
    // testing-library's findByTestId doesn't scan into <option> elements
    // consistently across jsdom versions.
    const stripeOpt = primary.querySelector(
      '[data-testid="payment-providers-option-stripe"]',
    );
    expect(stripeOpt).not.toBeNull();
    expect(stripeOpt.textContent).toContain("Configured");
    const squareOpt = primary.querySelector(
      '[data-testid="payment-providers-option-square"]',
    );
    expect(squareOpt).not.toBeNull();
    expect(squareOpt.textContent).toContain("Missing keys");
  });

  it("hides the audit table when there are zero failover events", async () => {
    mockGet.mockImplementation((path) => {
      if (path.includes("/settings/payment-providers")) {
        return Promise.resolve({
          primary_provider: "stripe",
          backup_provider: null,
          available: _defaultAvailable,
        });
      }
      return Promise.resolve({ total: 0, rows: [] });
    });
    render(<PaymentProvidersCard />);

    await screen.findByTestId("payment-providers-primary-select");
    expect(screen.queryByTestId("payment-providers-audit-table"))
      .toBeNull();
  });

  it("renders the audit table when rows are present", async () => {
    mockGet.mockImplementation((path) => {
      if (path.includes("/settings/payment-providers")) {
        return Promise.resolve({
          primary_provider: "stripe",
          backup_provider: "lumino",
          available: _defaultAvailable,
        });
      }
      return Promise.resolve({
        total: 1,
        rows: [{
          id: "audrow_1",
          tenant_id: "t1",
          operation: "create_charge",
          primary_provider: "stripe",
          backup_provider: "lumino",
          error_from_primary: "ProviderTransientError: 5xx",
          resolution: "backup_used",
          timestamp: "2026-02-15T12:00:00Z",
        }],
      });
    });
    render(<PaymentProvidersCard />);

    await waitFor(() =>
      expect(screen.getByTestId("payment-providers-audit-table"))
        .toBeInTheDocument(),
    );
    expect(screen.getByTestId("payment-providers-audit-row-audrow_1"))
      .toBeInTheDocument();
  });
});
