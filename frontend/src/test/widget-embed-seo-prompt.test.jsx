/**
 * Feb-2026 F4 Enhancement — WidgetEmbedPage SEO onboarding banner.
 *
 * Verifies:
 *   1. Banner renders when the backend reports
 *      ``should_show_seo_prompt: true``.
 *   2. Banner hides when the backend reports false.
 *   3. "Turn on public map" CTA fires PATCH with
 *      ``{auto_enqueue_public_checkins: true}`` and dismisses the
 *      banner.
 *   4. "Dismiss" X-button fires PATCH with a
 *      ``widget_embed_seo_prompt_dismissed_at`` ISO string and
 *      dismisses the banner.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/api", () => {
  const responses = {};
  const api = {
    get: vi.fn(async (path) => responses[path] ?? null),
    post: vi.fn(),
    patch: vi.fn(async () => ({})),
    del: vi.fn(),
  };
  return { __esModule: true, default: api, api, __responses: responses };
});
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin", tenant: { slug: "acme" } } }),
}));
vi.mock("@/components/layout/SafeScrollContainer", () => ({
  __esModule: true,
  default: ({ children, ...props }) => <div {...props}>{children}</div>,
}));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f8fafc", onSurface: "#111",
    muted: "#6b7280", border: "#e5e7eb", brand: "#2563EB", error: "#dc2626",
  },
}));

import WidgetEmbedPage from "@/pages/admin/WidgetEmbedPage";
import * as apiMod from "@/api";


describe("WidgetEmbedPage · SEO onboarding banner", () => {
  beforeEach(() => {
    apiMod.default.get.mockClear();
    apiMod.default.patch.mockClear();
    apiMod.default.patch.mockResolvedValue({
      auto_enqueue_public_checkins: true,
    });
    apiMod.__responses["/tenants/current"] = {
      id: "t-1", slug: "acme", name: "Acme Pools",
    };
  });

  it("renders the banner when should_show_seo_prompt=true", async () => {
    apiMod.__responses["/tenants/settings/widget-embed"] = {
      auto_enqueue_public_checkins: false,
      widget_embed_seo_prompt_dismissed_at: null,
      has_recent_completed_jobs: true,
      should_show_seo_prompt: true,
    };
    render(<WidgetEmbedPage />);
    const banner = await screen.findByTestId("widget-embed-seo-prompt");
    expect(banner).toBeDefined();
    expect(banner.textContent).toMatch(/Turn on the public check-ins map/i);
    expect(banner.textContent).toMatch(/schema\.org/i);
    expect(screen.getByTestId("widget-embed-seo-prompt-cta")).toBeDefined();
    expect(screen.getByTestId("widget-embed-seo-prompt-dismiss")).toBeDefined();
  });

  it("hides the banner when should_show_seo_prompt=false", async () => {
    apiMod.__responses["/tenants/settings/widget-embed"] = {
      auto_enqueue_public_checkins: true,
      widget_embed_seo_prompt_dismissed_at: null,
      has_recent_completed_jobs: true,
      should_show_seo_prompt: false,
    };
    render(<WidgetEmbedPage />);
    await waitFor(() => {
      expect(apiMod.default.get).toHaveBeenCalledWith(
        "/tenants/settings/widget-embed",
      );
    });
    expect(screen.queryByTestId("widget-embed-seo-prompt")).toBeNull();
  });

  it("CTA fires PATCH auto_enqueue=true and dismisses the banner", async () => {
    apiMod.__responses["/tenants/settings/widget-embed"] = {
      auto_enqueue_public_checkins: false,
      widget_embed_seo_prompt_dismissed_at: null,
      has_recent_completed_jobs: true,
      should_show_seo_prompt: true,
    };
    render(<WidgetEmbedPage />);
    const cta = await screen.findByTestId("widget-embed-seo-prompt-cta");
    fireEvent.click(cta);
    await waitFor(() => {
      expect(apiMod.default.patch).toHaveBeenCalledWith(
        "/tenants/settings/widget-embed",
        { auto_enqueue_public_checkins: true },
      );
    });
    await waitFor(() => {
      expect(screen.queryByTestId("widget-embed-seo-prompt")).toBeNull();
    });
  });

  it("Dismiss X-button fires PATCH with a dismissed_at ISO and hides", async () => {
    apiMod.__responses["/tenants/settings/widget-embed"] = {
      auto_enqueue_public_checkins: false,
      widget_embed_seo_prompt_dismissed_at: null,
      has_recent_completed_jobs: true,
      should_show_seo_prompt: true,
    };
    render(<WidgetEmbedPage />);
    const x = await screen.findByTestId("widget-embed-seo-prompt-dismiss");
    fireEvent.click(x);
    await waitFor(() => {
      expect(apiMod.default.patch).toHaveBeenCalled();
    });
    const [path, body] = apiMod.default.patch.mock.calls[0];
    expect(path).toBe("/tenants/settings/widget-embed");
    expect(body).toHaveProperty("widget_embed_seo_prompt_dismissed_at");
    // Assert body carries a well-formed ISO string.
    expect(() => new Date(body.widget_embed_seo_prompt_dismissed_at).toISOString())
      .not.toThrow();
    await waitFor(() => {
      expect(screen.queryByTestId("widget-embed-seo-prompt")).toBeNull();
    });
  });
});
