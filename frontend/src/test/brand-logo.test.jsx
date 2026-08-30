/**
 * Feb-2026 UI Polish Addendum — BrandLogo component tests.
 *
 * Verifies:
 *   • Default fallback renders `/brand/logo.png` when tenant has
 *     no branding.logo_url.
 *   • Tenant `branding.logo_url` overrides the local asset.
 *   • Legacy `tenant.logo_url` (top-level) is honoured when
 *     `branding` is absent.
 *   • The image is wrapped in a `<Link to="/">` with the correct
 *     data-testid so the shell can be driven by testing agents.
 *   • Icon variant vs. full variant swap the correct fallback.
 */
import React from "react";
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock the api client BEFORE importing the SUT so the module-scope
// cache in useTenantBrand consumes our mocked payload.
vi.mock("@/api", () => ({
  api: { get: vi.fn() },
}));

import { api } from "@/api";
import { BrandLogo } from "@/components/branding/BrandLogo";
import { invalidateTenantBrand } from "@/hooks/useTenantBrand";

function renderIn(node) {
  return render(<MemoryRouter>{node}</MemoryRouter>);
}

// Waits one microtask tick — enough for the useTenantBrand cache to
// resolve without paying for RTL's slower waitFor polling.
async function tick() {
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

describe("BrandLogo", () => {
  beforeEach(() => {
    invalidateTenantBrand();
    api.get.mockReset();
  });

  afterEach(() => {
    invalidateTenantBrand();
  });

  it("renders local /brand/logo.png fallback when tenant has no branding", async () => {
    api.get.mockResolvedValueOnce({ id: "t1", slug: "aquaterra", name: "Pool & Landscaping" });
    renderIn(<BrandLogo />);
    await tick();
    const img = screen.getByTestId("brand-logo-img");
    expect(img.getAttribute("src")).toBe("/brand/logo.png");
  });

  it("uses branding.logo_url when tenant provides it", async () => {
    api.get.mockResolvedValueOnce({
      id: "t1", slug: "aquaterra", name: "PLV",
      branding: { logo_url: "https://cdn.example.com/plv-logo.png" },
    });
    renderIn(<BrandLogo />);
    await tick();
    const img = screen.getByTestId("brand-logo-img");
    expect(img.getAttribute("src")).toBe("https://cdn.example.com/plv-logo.png");
  });

  it("falls back to legacy top-level logo_url when branding is missing", async () => {
    api.get.mockResolvedValueOnce({
      id: "t1", slug: "aquaterra", name: "PLV",
      logo_url: "https://cdn.example.com/legacy.png",
    });
    renderIn(<BrandLogo />);
    await tick();
    const img = screen.getByTestId("brand-logo-img");
    expect(img.getAttribute("src")).toBe("https://cdn.example.com/legacy.png");
  });

  it("wraps the image in a Link to '/' by default", async () => {
    api.get.mockResolvedValueOnce({});
    renderIn(<BrandLogo />);
    await tick();
    const link = screen.getByTestId("brand-logo-link");
    expect(link.tagName.toLowerCase()).toBe("a");
    expect(link.getAttribute("href")).toBe("/");
    // Motion polish — the hover-scale utility is present on the
    // wrapping link.
    expect(link.className).toMatch(/hover:scale-\[1\.02\]/);
    expect(link.className).toMatch(/focus-visible:ring-2/);
  });

  it("icon variant swaps to /brand/logo-icon.png fallback", async () => {
    api.get.mockResolvedValueOnce({});
    renderIn(<BrandLogo variant="icon" />);
    await tick();
    const img = screen.getByTestId("brand-logo-img");
    expect(img.getAttribute("src")).toBe("/brand/logo-icon.png");
  });

  it("respects an explicit testId override", async () => {
    api.get.mockResolvedValueOnce({});
    renderIn(<BrandLogo testId="topbar-logo" />);
    await tick();
    expect(screen.getByTestId("topbar-logo")).toBeInTheDocument();
    expect(screen.getByTestId("topbar-logo-img")).toBeInTheDocument();
  });
});
