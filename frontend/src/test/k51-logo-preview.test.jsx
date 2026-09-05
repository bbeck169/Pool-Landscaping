/**
 * Phase K51 · Feb-2026 — Admin logo preview toggle in Branding
 * settings.
 *
 * Verifies the side-by-side chrome preview surface added to
 * ``BrandLogoSettings``:
 *   1. Standard render — both preview tiles are present, the navy
 *      tile is styled to `rgb(27, 31, 92)` (`#1B1F5C`) and the navy
 *      preview `<img>` receives the exact `brightness(0) invert(1)`
 *      filter that mirrors the live navy nav-bar chrome.
 *   2. No-logo edge case — the two chrome tiles still render, and
 *      each surfaces a placeholder ("No logo uploaded") without
 *      throwing. No contrast-warning affordance is shown.
 *   3. Contrast heuristic — when the sampled canvas reports the
 *      logo has ≥95% fully-opaque pixels (i.e. a solid block that
 *      would render as an opaque white rectangle under the navy
 *      chrome's `brightness(0) invert(1)` treatment), the warning
 *      affordance (`logo-preview-contrast-warning`) surfaces on
 *      the tile.
 *
 * Out of scope (unchanged by K51): the actual logo processing /
 * white-fill pipeline, mobile drawer chrome, portal logo behaviour,
 * and the primary nav-bar rendering. Those retain their own
 * regression tests.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";

// Mocks — align with existing ``brand-logo-uploader.test.jsx`` so the
// SUT resolves its collaborators without hitting the network.
const apiGet = vi.fn();
const apiDel = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => apiGet(...a), del: (...a) => apiDel(...a) },
  api_base: () => "https://api.example.com/api",
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/hooks/useTenantBrand", () => ({
  invalidateTenantBrand: () => {},
}));

import BrandLogoSettings from "@/pages/settings/BrandLogoSettings";

// Two microtask ticks — enough for the ``refresh()`` effect to
// resolve and paint the tenant-populated tree.
async function tick() {
  await act(async () => {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
  });
}

/**
 * Install a jsdom-friendly canvas stub. Real ``HTMLCanvasElement``
 * in jsdom returns ``null`` from ``getContext``, so the K51 contrast
 * heuristic short-circuits silently — great for tests A and B, but
 * we need to swap it in with a controllable alpha profile for test C.
 *
 * ``alpha255Ratio`` — fraction of sampled pixels reported as fully
 * opaque (α = 255). Values >= 0.95 trigger the warning.
 */
function installCanvasStub(alpha255Ratio) {
  const W = 32; const H = 32;
  const total = W * H;
  const opaqueCount = Math.round(alpha255Ratio * total);
  const bytes = new Uint8ClampedArray(total * 4);
  for (let i = 0; i < total; i += 1) {
    // R,G,B all mid-grey; only alpha varies so the heuristic is
    // deterministic and only alpha-driven (matches implementation).
    bytes[i * 4 + 0] = 128;
    bytes[i * 4 + 1] = 128;
    bytes[i * 4 + 2] = 128;
    bytes[i * 4 + 3] = i < opaqueCount ? 255 : 0;
  }
  const ctxStub = {
    drawImage: vi.fn(),
    getImageData: vi.fn(() => ({ data: bytes, width: W, height: H })),
  };
  const originalGetContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ctxStub);
  return () => { HTMLCanvasElement.prototype.getContext = originalGetContext; };
}

beforeEach(() => {
  apiGet.mockReset();
  apiDel.mockReset();
});

afterEach(() => {
  // Ensure no canvas stub leaks between tests — each test that
  // installs one is responsible for its own teardown, but be
  // defensive here too.
  vi.restoreAllMocks();
});

describe("Phase K51 · BrandLogoSettings — chrome preview tiles", () => {
  it("renders both tiles side-by-side with the navy tile at rgb(27, 31, 92) and the correct filter", async () => {
    apiGet.mockResolvedValueOnce({
      id: "t1",
      slug: "aquaterra",
      name: "PLV",
      logo_url: "/api/objects/poolcrm/t1/branding/logo/abc.png",
      branding: {
        logo_url: "/api/objects/poolcrm/t1/branding/logo/abc.png",
      },
    });

    render(<BrandLogoSettings />);
    await tick();

    // Group container + both tiles present.
    expect(screen.getByTestId("logo-preview-chrome-group")).toBeInTheDocument();
    const lightTile = screen.getByTestId("logo-preview-light");
    const navyTile = screen.getByTestId("logo-preview-navy");
    expect(lightTile).toBeInTheDocument();
    expect(navyTile).toBeInTheDocument();

    // Navy tile chrome — MUST match the K50 nav-bar navy exactly.
    // React normalises the inline `#1B1F5C` to `rgb(27, 31, 92)`.
    expect(navyTile.style.backgroundColor).toBe("rgb(27, 31, 92)");

    // Light tile chrome — plain white.
    expect(lightTile.style.backgroundColor).toBe("rgb(255, 255, 255)");

    // Both tiles render the logo <img> resolved to the absolute URL.
    const lightImg = screen.getByTestId("logo-preview-light-img");
    const navyImg = screen.getByTestId("logo-preview-navy-img");
    const expectedSrc = "https://api.example.com/api/objects/poolcrm/t1/branding/logo/abc.png";
    expect(lightImg.getAttribute("src")).toBe(expectedSrc);
    expect(navyImg.getAttribute("src")).toBe(expectedSrc);

    // Navy tile logo MUST carry the app-shell white-fill filter so
    // the preview matches the live nav-bar treatment.
    expect(navyImg.style.filter).toBe("brightness(0) invert(1)");
    // Light tile logo MUST NOT carry the filter — we want to show
    // the raw asset as it appears on a light chrome.
    expect(lightImg.style.filter || "").toBe("");

    // With the default jsdom canvas (no stub), `getContext` returns
    // null → heuristic silently no-ops → no warning affordance.
    expect(screen.queryByTestId("logo-preview-contrast-warning")).toBeNull();
  });

  it("no-logo edge case renders placeholders in both tiles without errors and without a warning", async () => {
    apiGet.mockResolvedValueOnce({
      id: "t1",
      slug: "aquaterra",
      name: "PLV",
      logo_url: null,
      branding: { logo_url: null },
    });

    render(<BrandLogoSettings />);
    await tick();

    // Both tiles present.
    const lightTile = screen.getByTestId("logo-preview-light");
    const navyTile = screen.getByTestId("logo-preview-navy");
    expect(lightTile).toBeInTheDocument();
    expect(navyTile).toBeInTheDocument();

    // Navy tile keeps its chrome even when empty.
    expect(navyTile.style.backgroundColor).toBe("rgb(27, 31, 92)");

    // Empty-state placeholders on both tiles.
    const lightEmpty = screen.getByTestId("logo-preview-empty");
    const navyEmpty = screen.getByTestId("logo-preview-navy-empty");
    expect(lightEmpty).toBeInTheDocument();
    expect(navyEmpty).toBeInTheDocument();
    expect(lightEmpty.textContent).toMatch(/no logo/i);
    expect(navyEmpty.textContent).toMatch(/no logo/i);

    // No logo <img>s exist to run the heuristic against.
    expect(screen.queryByTestId("logo-preview-light-img")).toBeNull();
    expect(screen.queryByTestId("logo-preview-navy-img")).toBeNull();

    // No contrast-warning affordance in the empty state.
    expect(screen.queryByTestId("logo-preview-contrast-warning")).toBeNull();
  });

  it("surfaces the contrast-warning affordance when the sampled logo is ≥95% fully-opaque", async () => {
    const uninstall = installCanvasStub(1.0); // 100% opaque → warn
    try {
      apiGet.mockResolvedValueOnce({
        id: "t1",
        slug: "aquaterra",
        name: "PLV",
        logo_url: "/api/objects/poolcrm/t1/branding/logo/solid.png",
        branding: {
          logo_url: "/api/objects/poolcrm/t1/branding/logo/solid.png",
        },
      });

      render(<BrandLogoSettings />);
      await tick();

      // Warning must be absent before <img> load fires.
      expect(screen.queryByTestId("logo-preview-contrast-warning")).toBeNull();

      // Manually fire the navy tile's <img onLoad> — jsdom doesn't
      // load real images, so the heuristic wouldn't otherwise run.
      const navyImg = screen.getByTestId("logo-preview-navy-img");
      await act(async () => { fireEvent.load(navyImg); });

      // Warning affordance surfaces with actionable copy.
      const warn = await waitFor(() =>
        screen.getByTestId("logo-preview-contrast-warning"),
      );
      expect(warn).toBeInTheDocument();
      expect(warn.textContent).toMatch(/solid block|white rectangle|transparent/i);
    } finally {
      uninstall();
    }
  });

  it("does NOT surface the warning when the sampled logo has mostly-transparent pixels", async () => {
    const uninstall = installCanvasStub(0.10); // 10% opaque → safe
    try {
      apiGet.mockResolvedValueOnce({
        id: "t1",
        slug: "aquaterra",
        name: "PLV",
        logo_url: "/api/objects/poolcrm/t1/branding/logo/transparent.png",
        branding: {
          logo_url: "/api/objects/poolcrm/t1/branding/logo/transparent.png",
        },
      });

      render(<BrandLogoSettings />);
      await tick();

      const navyImg = screen.getByTestId("logo-preview-navy-img");
      await act(async () => { fireEvent.load(navyImg); });

      // The heuristic ran (canvas stub installed) but reported the
      // logo as mostly-transparent — NO warning affordance.
      expect(screen.queryByTestId("logo-preview-contrast-warning")).toBeNull();
    } finally {
      uninstall();
    }
  });
});
