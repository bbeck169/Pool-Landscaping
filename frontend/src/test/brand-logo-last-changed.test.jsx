/**
 * Feb-2026 Enhancement — BrandLogoSettings "Last changed" line.
 *
 * Verifies:
 *   1. Renders "Last changed <relative> by <name>" when both
 *      ``logo_updated_at`` and ``logo_updated_by_name`` are set.
 *   2. Hides the line entirely when the fields are missing.
 *   3. Hides when only one field is set (partial data — never
 *      render half a sentence).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("@/api", () => {
  const responses = {};
  const api = {
    get: vi.fn(async (path) => responses[path] ?? null),
    post: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
  };
  const api_base = () => "https://x.example/api";
  return {
    __esModule: true,
    default: api,
    api,
    api_base,
    __responses: responses,
  };
});
vi.mock("@/hooks/useTenantBrand", () => ({
  invalidateTenantBrand: vi.fn(),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import BrandLogoSettings from "@/pages/settings/BrandLogoSettings";
import * as apiMod from "@/api";


describe("BrandLogoSettings · last-changed line", () => {
  beforeEach(() => {
    apiMod.default.get.mockClear();
  });

  it("renders when logo_updated_at + logo_updated_by_name are present", async () => {
    apiMod.__responses["/tenants/current"] = {
      id: "t-1", slug: "acme", name: "Acme Pools",
      branding: { logo_url: "/api/objects/foo.png" },
      logo_url: "/api/objects/foo.png",
      logo_updated_at: new Date(Date.now() - 3600 * 1000 * 2).toISOString(),
      logo_updated_by: "u-1",
      logo_updated_by_name: "Brian Beckman",
    };
    render(<BrandLogoSettings />);
    const line = await screen.findByTestId("brand-logo-last-changed");
    expect(line).toBeDefined();
    expect(line.textContent).toMatch(/Last changed/);
    expect(line.textContent).toMatch(/Brian Beckman/);
    // Relative time formatter should emit a human phrase
    const relative = screen.getByTestId("brand-logo-last-changed-relative");
    expect(relative.textContent.length).toBeGreaterThan(0);
    expect(relative.textContent).not.toBe("Invalid Date");
  });

  it("hides the line when tenant has never uploaded a logo", async () => {
    apiMod.__responses["/tenants/current"] = {
      id: "t-1", slug: "acme", name: "Acme Pools",
      branding: { logo_url: null },
      logo_url: null,
      logo_updated_at: null,
      logo_updated_by: null,
      logo_updated_by_name: null,
    };
    render(<BrandLogoSettings />);
    // Wait for the initial fetch to resolve.
    await waitFor(() => {
      expect(apiMod.default.get).toHaveBeenCalledWith("/tenants/current");
    });
    expect(screen.queryByTestId("brand-logo-last-changed")).toBeNull();
  });

  it("hides the line if actor name failed to resolve (partial data)", async () => {
    apiMod.__responses["/tenants/current"] = {
      id: "t-1", slug: "acme", name: "Acme Pools",
      branding: { logo_url: "/api/objects/foo.png" },
      logo_url: "/api/objects/foo.png",
      logo_updated_at: new Date().toISOString(),
      logo_updated_by: "u-ghost",
      logo_updated_by_name: null,   // deleted user
    };
    render(<BrandLogoSettings />);
    await waitFor(() => {
      expect(apiMod.default.get).toHaveBeenCalledWith("/tenants/current");
    });
    expect(screen.queryByTestId("brand-logo-last-changed")).toBeNull();
  });
});
