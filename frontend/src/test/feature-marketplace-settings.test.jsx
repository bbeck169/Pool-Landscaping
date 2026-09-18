/**
 * Sprint 3c · Feb-2026 · Feature Marketplace Vitest coverage.
 *
 * Locks the acceptance behaviour on the SettingsHub tab:
 *   1. Non-admins see the forbidden card.
 *   2. All 4 tiles render with correct pricing + status pills.
 *   3. Not-configured tiles have a disabled button.
 *   4. Enable click surfaces confirm modal + submits POST /enable.
 *   5. Disable click surfaces confirm modal + submits POST /disable.
 *   6. Scheduled-cancel tiles show the cancels_at date and a
 *      disabled "Scheduled" button.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("sonner", () => {
  const _toast = Object.assign(vi.fn(), {
    success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn(),
  });
  return { toast: _toast, Toaster: () => null };
});

vi.mock("@/api", () => {
  const _api = {
    get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn(),
  };
  return { api: _api };
});

const _authState = { user: { role: "admin", id: "u1" } };
vi.mock("@/auth", () => ({ useAuth: () => _authState }));

import FeatureMarketplaceSettings from "@/pages/settings/FeatureMarketplaceSettings";
import { api } from "@/api";
import { toast } from "sonner";


const DEFAULT_MARKETPLACE = {
  features: [
    {
      feature_key: "zillow_data",
      display_name: "Zillow Data",
      description: "Enrich records with Zestimate + property details.",
      monthly_price_cents: 4900,
      billing_cadence: "monthly",
      icon: "home",
      enabled: false,
      billing_status: null,
      cancels_at: null,
      enabled_at: null,
      availability: "available",
    },
    {
      feature_key: "seo_heatmap",
      display_name: "SEO Rank Heatmap",
      description: "Grid-based local rank tracking.",
      monthly_price_cents: 9900,
      billing_cadence: "monthly",
      icon: "map",
      enabled: true,
      billing_status: "active",
      cancels_at: null,
      enabled_at: "2026-02-01T00:00:00Z",
      availability: "already_enabled",
    },
    {
      feature_key: "ai_analytics",
      display_name: "AI Analytics",
      description: "AI-generated churn, revenue anomaly, forecast.",
      monthly_price_cents: 4900,
      billing_cadence: "monthly",
      icon: "trending-up",
      enabled: true,
      billing_status: "cancelled_end_of_cycle",
      cancels_at: "2026-02-28T00:00:00Z",
      enabled_at: "2026-01-15T00:00:00Z",
      availability: "already_enabled",
    },
    {
      feature_key: "ai_copilot",
      display_name: "AI Copilot",
      description: "Persistent AI Employees with approval-first actions.",
      monthly_price_cents: 14900,
      billing_cadence: "monthly",
      icon: "bot",
      enabled: false,
      billing_status: null,
      cancels_at: null,
      enabled_at: null,
      availability: "not_configured",
    },
  ],
};


beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  Object.values(toast).forEach((fn) => {
    if (typeof fn === "function") fn.mockReset?.();
  });
  _authState.user = { role: "admin", id: "u1" };
});
afterEach(() => vi.clearAllMocks());


describe("FeatureMarketplaceSettings · Sprint 3c", () => {
  it("non-admin sees forbidden card, no tiles", () => {
    _authState.user = { role: "technician", id: "u2" };
    render(<FeatureMarketplaceSettings />);
    expect(screen.getByTestId("feature-marketplace-forbidden")).toBeTruthy();
    expect(screen.queryByTestId("feature-tile-grid")).toBeNull();
    expect(api.get).not.toHaveBeenCalled();
  });

  it("admin loads and renders 4 tiles with correct state", async () => {
    api.get.mockResolvedValue(DEFAULT_MARKETPLACE);
    render(<FeatureMarketplaceSettings />);
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/tenants/mine/feature-marketplace"),
    );
    // Tiles present:
    expect(screen.getByTestId("feature-tile-zillow_data")).toBeTruthy();
    expect(screen.getByTestId("feature-tile-seo_heatmap")).toBeTruthy();
    expect(screen.getByTestId("feature-tile-ai_analytics")).toBeTruthy();
    expect(screen.getByTestId("feature-tile-ai_copilot")).toBeTruthy();
    // Prices:
    expect(screen.getByTestId("feature-tile-price-zillow_data").textContent)
      .toContain("$49");
    expect(screen.getByTestId("feature-tile-price-seo_heatmap").textContent)
      .toContain("$99");
    expect(screen.getByTestId("feature-tile-price-ai_copilot").textContent)
      .toContain("$149");
    // Status pills:
    expect(screen.getByTestId("feature-tile-status-zillow_data").textContent)
      .toContain("Available");
    expect(screen.getByTestId("feature-tile-status-seo_heatmap").textContent)
      .toContain("Enabled");
    expect(screen.getByTestId("feature-tile-status-ai_analytics").textContent)
      .toContain("Cancels");
    expect(screen.getByTestId("feature-tile-status-ai_copilot").textContent)
      .toContain("Not configured");
  });

  it("not-configured tiles have disabled button", async () => {
    api.get.mockResolvedValue(DEFAULT_MARKETPLACE);
    render(<FeatureMarketplaceSettings />);
    await waitFor(() =>
      expect(screen.getByTestId("feature-tile-ai_copilot")).toBeTruthy(),
    );
    const btn = screen.getByTestId("feature-tile-button-ai_copilot");
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain("Not configured");
  });

  it("scheduled-cancel tile has disabled 'Scheduled' button", async () => {
    api.get.mockResolvedValue(DEFAULT_MARKETPLACE);
    render(<FeatureMarketplaceSettings />);
    await waitFor(() =>
      expect(screen.getByTestId("feature-tile-ai_analytics")).toBeTruthy(),
    );
    const btn = screen.getByTestId("feature-tile-button-ai_analytics");
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain("Scheduled");
  });

  it("Enable button opens modal and submits POST /enable", async () => {
    api.get.mockResolvedValue(DEFAULT_MARKETPLACE);
    api.post.mockResolvedValue({
      status: "enabled",
      ...DEFAULT_MARKETPLACE.features[0],
      enabled: true, billing_status: "active",
      availability: "already_enabled",
    });
    render(<FeatureMarketplaceSettings />);
    await waitFor(() =>
      expect(screen.getByTestId("feature-tile-zillow_data")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("feature-tile-button-zillow_data"));
    await waitFor(() =>
      expect(screen.getByTestId("feature-enable-modal")).toBeTruthy(),
    );
    // Modal copy mentions prorated charge.
    expect(screen.getByTestId("feature-enable-modal").textContent)
      .toMatch(/prorated/i);
    fireEvent.click(screen.getByTestId("feature-enable-confirm"));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/tenants/mine/feature-marketplace/zillow_data/enable",
      );
    });
    expect(toast.success).toHaveBeenCalled();
  });

  it("Disable button opens modal and submits POST /disable", async () => {
    api.get.mockResolvedValue(DEFAULT_MARKETPLACE);
    api.post.mockResolvedValue({
      status: "scheduled_cancel",
      ...DEFAULT_MARKETPLACE.features[1],
      billing_status: "cancelled_end_of_cycle",
      cancels_at: "2026-03-01T00:00:00Z",
    });
    render(<FeatureMarketplaceSettings />);
    await waitFor(() =>
      expect(screen.getByTestId("feature-tile-seo_heatmap")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("feature-tile-button-seo_heatmap"));
    await waitFor(() =>
      expect(screen.getByTestId("feature-disable-modal")).toBeTruthy(),
    );
    // Modal copy mentions end-of-cycle access.
    expect(screen.getByTestId("feature-disable-modal").textContent)
      .toMatch(/end of the current billing cycle/i);
    fireEvent.click(screen.getByTestId("feature-disable-confirm"));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/tenants/mine/feature-marketplace/seo_heatmap/disable",
      );
    });
    expect(toast.success).toHaveBeenCalled();
  });

  it("Enable failure surfaces toast error", async () => {
    api.get.mockResolvedValue(DEFAULT_MARKETPLACE);
    api.post.mockRejectedValueOnce({
      response: { data: { detail: {
        detail: "no_active_subscription",
        message: "tenant has no active Stripe subscription",
      } } },
    });
    render(<FeatureMarketplaceSettings />);
    await waitFor(() =>
      expect(screen.getByTestId("feature-tile-zillow_data")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("feature-tile-button-zillow_data"));
    await waitFor(() =>
      expect(screen.getByTestId("feature-enable-modal")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("feature-enable-confirm"));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });
});
