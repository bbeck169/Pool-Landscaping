/**
 * TD-seo-phase3 · Oct-2026 — PortalSeoTab vitest suite.
 *
 * Combines three layers:
 *   §1 Pure-function tests for _buildPatch (strips empty, parses JSON,
 *      splits service_areas, honors "no changes").
 *   §2 Source-regex locks for structural invariants (role list, endpoint
 *      URLs, data-testids, soft counters).
 *   §3 Component-mount shape tests via render(<PortalSeoTab />) with
 *      @/api + @/auth + sonner mocked (same proven pattern as
 *      brand-logo-last-changed.test.jsx).
 *
 * DOM-level Helmet-style reactivity is NOT exercised here per the
 * phase-2 postmortem (jsdom + rAF timing proved unreliable); pure
 * function coverage is the stable alternative.
 */
import React from "react";
import fs from "fs";
import path from "path";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// ─── Mocks (must be hoisted; vi.mock is hoisted automatically) ───
vi.mock("@/api", () => {
  const responses = {};
  const api = {
    get: vi.fn(async (path) => {
      if (path in responses) return responses[path];
      const err = new Error("not found"); err.status = 404; throw err;
    }),
    post: vi.fn(),
    patch: vi.fn(async (_p, body) => ({
      // Echo back the body in GET-shape so the component can re-sync.
      tenant_id: "t-1",
      ...body,
      service_areas: body?.service_areas || [],
      json_ld_overrides: body?.json_ld_overrides || {},
      twitter_card: body?.twitter_card || "summary_large_image",
    })),
    del: vi.fn(),
  };
  return { __esModule: true, default: api, api, __responses: responses };
});

let _mockUserRole = "admin";
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u-1", tenant_id: "t-1", role: _mockUserRole },
  }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// Theme is a plain object export — stub so we don't drag the full
// theme graph (which the vitest config warns can hang).
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f6f6f6",
    onSurface: "#111", onSurfaceSecondary: "#444",
    muted: "#888", border: "#ddd", brand: "#0066cc",
    searchIcon: "#333",
  },
}));

import PortalSeoTab, { _buildPatch } from "@/pages/settings/PortalSeoTab";
import * as apiMod from "@/api";
import { toast } from "sonner";

const SRC_PATH = path.resolve(
  __dirname, "..", "pages", "settings", "PortalSeoTab.jsx");
const SRC = fs.readFileSync(SRC_PATH, "utf8");


describe("TD-seo-phase3 · PortalSeoTab · §1 _buildPatch pure function", () => {
  it("strips empty string fields so BE exclude_none honors them", () => {
    const patch = _buildPatch({
      og_title: "",
      og_description: "   ",
      twitter_card: "summary",
      service_areas: "",
      json_ld_overrides: "",
    });
    expect(patch).toEqual({ twitter_card: "summary" });
  });

  it("includes only non-empty string fields", () => {
    const patch = _buildPatch({
      og_title: "Acme Pools",
      og_description: "Best pool co",
      og_image_url: "https://x.example/og.png",
      twitter_card: "summary_large_image",
      twitter_site: "@acme",
      canonical_base_url: "https://acme.com",
      meta_description_override: "override",
      service_areas: "",
      json_ld_overrides: "",
    });
    expect(patch).toEqual({
      og_title: "Acme Pools",
      og_description: "Best pool co",
      og_image_url: "https://x.example/og.png",
      twitter_card: "summary_large_image",
      twitter_site: "@acme",
      canonical_base_url: "https://acme.com",
      meta_description_override: "override",
    });
  });

  it("splits service_areas by comma OR newline and trims", () => {
    const patch = _buildPatch({
      service_areas: "Austin, TX\nRound Rock\n , Pflugerville ,",
      json_ld_overrides: "",
    });
    expect(patch.service_areas).toEqual(
      ["Austin", "TX", "Round Rock", "Pflugerville"]);
  });

  it("parses json_ld_overrides into a dict (never a string)", () => {
    const patch = _buildPatch({
      service_areas: "",
      json_ld_overrides: '{"priceRange":"$$","foo":1}',
    });
    expect(patch.json_ld_overrides).toEqual(
      { priceRange: "$$", foo: 1 });
  });

  it("drops json_ld_overrides when input is invalid JSON", () => {
    const patch = _buildPatch({
      service_areas: "",
      json_ld_overrides: "not json {{",
    });
    expect(patch.json_ld_overrides).toBeUndefined();
  });

  it("drops json_ld_overrides when parsed value is {} (no changes)", () => {
    const patch = _buildPatch({
      service_areas: "",
      json_ld_overrides: "{}",
    });
    expect(patch.json_ld_overrides).toBeUndefined();
  });
});


describe("TD-seo-phase3 · PortalSeoTab · §2 source-regex locks", () => {
  it("role list mirrors backend require_admin (admin+super_admin+owner)", () => {
    expect(SRC).toMatch(
      /_PORTAL_SEO_ROLES\s*=\s*\[\s*"admin"\s*,\s*"super_admin"\s*,\s*"owner"\s*\]/);
  });

  it("GET endpoint URL = /admin/portal-seo/{tenantId}", () => {
    expect(SRC).toMatch(
      /api\.get\(\s*`\/admin\/portal-seo\/\$\{tenantId\}`\s*\)/);
  });

  it("PATCH endpoint URL = /admin/portal-seo/{tenantId}", () => {
    expect(SRC).toMatch(
      /api\.patch\(\s*`\/admin\/portal-seo\/\$\{tenantId\}`\s*,/);
  });

  it("twitter card options match backend _TWITTER_CARD_TYPES enum", () => {
    expect(SRC).toMatch(/"summary"/);
    expect(SRC).toMatch(/"summary_large_image"/);
    expect(SRC).toMatch(/"app"/);
    expect(SRC).toMatch(/"player"/);
  });

  it("exposes all required field testids", () => {
    const ids = [
      "portal-seo-tab",
      "portal-seo-og-title",
      "portal-seo-og-desc",
      "portal-seo-og-image-url",
      "portal-seo-twitter-card",
      "portal-seo-twitter-site",
      "portal-seo-canonical-base-url",
      "portal-seo-meta-desc",
      "portal-seo-service-areas",
      "portal-seo-json-ld",
      "portal-seo-save-btn",
      "portal-seo-reset-btn",
    ];
    for (const id of ids) {
      expect(SRC).toContain(`"${id}"`);
    }
  });

  it("soft counter thresholds match SEO best-practice (160 chars)", () => {
    expect(SRC).toMatch(/_OG_DESC_SOFT_HINT\s*=\s*160/);
    expect(SRC).toMatch(/_META_DESC_SOFT_HINT\s*=\s*160/);
  });
});


describe("TD-seo-phase3 · PortalSeoTab · §3 component mount shape", () => {
  beforeEach(() => {
    _mockUserRole = "admin";
    apiMod.default.get.mockClear();
    apiMod.default.patch.mockClear();
    toast.success.mockClear();
    toast.error.mockClear();
    // Reset the mock response map.
    for (const k of Object.keys(apiMod.__responses)) delete apiMod.__responses[k];
  });

  it("renders denied placeholder for non-admin role", async () => {
    _mockUserRole = "technician";
    render(<PortalSeoTab />);
    expect(await screen.findByTestId("portal-seo-denied")).toBeDefined();
    // GET must NOT be called for an unauthorized role.
    expect(apiMod.default.get).not.toHaveBeenCalled();
  });

  it("renders denied placeholder for manager (below admin tier)", async () => {
    _mockUserRole = "manager";
    render(<PortalSeoTab />);
    expect(await screen.findByTestId("portal-seo-denied")).toBeDefined();
  });

  it("renders denied placeholder for customer", async () => {
    _mockUserRole = "customer";
    render(<PortalSeoTab />);
    expect(await screen.findByTestId("portal-seo-denied")).toBeDefined();
  });

  it("populates form from GET response for admin", async () => {
    apiMod.__responses["/admin/portal-seo/t-1"] = {
      tenant_id: "t-1",
      og_title: "Hello Pools",
      og_description: "Pool co",
      og_image_url: "https://x.example/og.png",
      twitter_card: "summary",
      twitter_site: "@h",
      canonical_base_url: "https://hello.com",
      meta_description_override: "meta over",
      service_areas: ["Austin", "TX"],
      json_ld_overrides: { priceRange: "$$" },
    };
    render(<PortalSeoTab />);
    const title = await screen.findByTestId("portal-seo-og-title");
    expect(title.value).toBe("Hello Pools");
    const card = screen.getByTestId("portal-seo-twitter-card");
    expect(card.value).toBe("summary");
    const areas = screen.getByTestId("portal-seo-service-areas");
    expect(areas.value).toBe("Austin, TX");
    const jsonLd = screen.getByTestId("portal-seo-json-ld");
    expect(jsonLd.value).toContain('"priceRange": "$$"');
    expect(apiMod.default.get).toHaveBeenCalledWith("/admin/portal-seo/t-1");
  });

  it("Save calls PATCH with only non-empty fields", async () => {
    apiMod.__responses["/admin/portal-seo/t-1"] = {
      tenant_id: "t-1",
      og_title: "Original",
      twitter_card: "summary_large_image",
      service_areas: [],
      json_ld_overrides: {},
    };
    render(<PortalSeoTab />);
    const title = await screen.findByTestId("portal-seo-og-title");
    fireEvent.change(title, { target: { value: "New Title" } });
    const saveBtn = screen.getByTestId("portal-seo-save-btn");
    fireEvent.click(saveBtn);
    await waitFor(() => {
      expect(apiMod.default.patch).toHaveBeenCalled();
    });
    const [url, body] = apiMod.default.patch.mock.calls[0];
    expect(url).toBe("/admin/portal-seo/t-1");
    expect(body.og_title).toBe("New Title");
    expect(body.twitter_card).toBe("summary_large_image");
    expect(body.service_areas).toBeUndefined();  // empty array stripped
    expect(body.json_ld_overrides).toBeUndefined();  // {} stripped
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
  });

  it("reset clears unsaved edits back to GET response values", async () => {
    apiMod.__responses["/admin/portal-seo/t-1"] = {
      tenant_id: "t-1",
      og_title: "ServerTitle",
      twitter_card: "summary_large_image",
      service_areas: [],
      json_ld_overrides: {},
    };
    render(<PortalSeoTab />);
    const title = await screen.findByTestId("portal-seo-og-title");
    fireEvent.change(title, { target: { value: "DirtyEdit" } });
    expect(title.value).toBe("DirtyEdit");
    fireEvent.click(screen.getByTestId("portal-seo-reset-btn"));
    await waitFor(() => expect(title.value).toBe("ServerTitle"));
  });

  it("invalid JSON on blur surfaces an inline error", async () => {
    apiMod.__responses["/admin/portal-seo/t-1"] = {
      tenant_id: "t-1",
      twitter_card: "summary_large_image",
      service_areas: [],
      json_ld_overrides: {},
    };
    render(<PortalSeoTab />);
    const jsonLd = await screen.findByTestId("portal-seo-json-ld");
    fireEvent.change(jsonLd, { target: { value: "not json {{" } });
    fireEvent.blur(jsonLd);
    expect(await screen.findByTestId("portal-seo-json-err")).toBeDefined();
  });

  it("invalid OG image URL surfaces inline error", async () => {
    apiMod.__responses["/admin/portal-seo/t-1"] = {
      tenant_id: "t-1",
      twitter_card: "summary_large_image",
      service_areas: [],
      json_ld_overrides: {},
    };
    render(<PortalSeoTab />);
    const url = await screen.findByTestId("portal-seo-og-image-url");
    fireEvent.change(url, { target: { value: "not-a-url" } });
    expect(await screen.findByTestId("portal-seo-og-image-url-err")).toBeDefined();
  });

  it("Save PATCH error surfaces an error toast", async () => {
    apiMod.__responses["/admin/portal-seo/t-1"] = {
      tenant_id: "t-1",
      twitter_card: "summary_large_image",
      service_areas: [],
      json_ld_overrides: {},
    };
    apiMod.default.patch.mockImplementationOnce(async () => {
      const e = new Error("Validation failed"); e.status = 400; throw e;
    });
    render(<PortalSeoTab />);
    const title = await screen.findByTestId("portal-seo-og-title");
    fireEvent.change(title, { target: { value: "X" } });
    fireEvent.click(screen.getByTestId("portal-seo-save-btn"));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });
});
