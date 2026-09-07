/**
 * Phase I1.5.c · Feb-2026 — Tenant theme CSS-var overlay tests.
 *
 * Locks:
 *   1. ``writeTenantCssVars`` emits every slot as a
 *      ``--tenant-<name>`` custom property on the target element.
 *   2. Fill slots (menu.bg, tiles.bg, etc.) also emit a
 *      ``--tenant-<name>-css`` variant carrying the full CSS
 *      gradient / solid string, so shorthand ``background:`` rules
 *      can pick it up.
 *   3. ``clearTenantCssVars`` removes every var it wrote.
 *   4. ``tenantCssVar(path, fallback)`` returns the
 *      ``"var(--tenant-<name>, <fallback>)"`` form so consumers
 *      can drop it into an inline style with a colocated default.
 *   5. Provider mount writes CSS vars onto
 *      ``document.documentElement``; refetch updates them in
 *      place; applyOverride flips them optimistically.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import React from "react";
import { render, waitFor, act } from "@testing-library/react";

import {
  TENANT_VAR_SPEC,
  writeTenantCssVars,
  clearTenantCssVars,
  tenantCssVar,
} from "@/theme/tenantVars";
import { getClientPreset } from "@/theme/presets";


// ── API mock (same shape as the hook test) ─────────────────────
vi.mock("@/api", () => {
  const api = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  };
  return { __esModule: true, api, default: api };
});


import { TenantThemeProvider, useTenantTheme } from "@/hooks/useTenantTheme";
import { api } from "@/api";


// Reset the html style between tests so a stray property doesn't
// leak into the next assertion.
beforeEach(() => {
  clearTenantCssVars(document.documentElement);
  vi.clearAllMocks();
  api.get.mockReset();
});
afterEach(() => {
  clearTenantCssVars(document.documentElement);
});


// ── 1. writeTenantCssVars ───────────────────────────────────────
describe("writeTenantCssVars", () => {
  it("writes --tenant-<name> for every slot in TENANT_VAR_SPEC", () => {
    const el = document.createElement("div");
    writeTenantCssVars(el, getClientPreset("hvac"));
    for (const spec of TENANT_VAR_SPEC) {
      const v = el.style.getPropertyValue(`--tenant-${spec.name}`);
      expect(v).not.toBe("");
      // Solid slots surface a hex; fill slots that are solid also
      // surface a hex (the -css variant carries the shorthand).
      expect(v).toMatch(/^#[0-9a-fA-F]{6}$/);
    }
  });

  it("writes the -css variant for fill slots as a gradient string", () => {
    const el = document.createElement("div");
    // Build a theme with a gradient in menu.bg.
    const theme = getClientPreset("default");
    theme.menu.bg = {
      mode: "gradient",
      gradient: { from: "#123456", to: "#abcdef", angle: 45 },
    };
    writeTenantCssVars(el, theme);
    const css = el.style.getPropertyValue("--tenant-menu-bg-css");
    expect(css).toBe("linear-gradient(45deg, #123456 0%, #abcdef 100%)");
    // Solid variant stays empty when the slot is gradient — we
    // intentionally don't fabricate a solid from a gradient.
    expect(el.style.getPropertyValue("--tenant-menu-bg")).toBe("");
  });

  it("no-ops safely when the theme or element is missing", () => {
    expect(() => writeTenantCssVars(null, {})).not.toThrow();
    expect(() => writeTenantCssVars(document.createElement("div"), null))
      .not.toThrow();
  });
});


// ── 2. clearTenantCssVars ───────────────────────────────────────
describe("clearTenantCssVars", () => {
  it("removes every var it wrote", () => {
    const el = document.createElement("div");
    writeTenantCssVars(el, getClientPreset("hvac"));
    clearTenantCssVars(el);
    for (const spec of TENANT_VAR_SPEC) {
      expect(el.style.getPropertyValue(`--tenant-${spec.name}`)).toBe("");
      expect(el.style.getPropertyValue(`--tenant-${spec.name}-css`)).toBe("");
    }
  });
});


// ── 3. tenantCssVar helper ──────────────────────────────────────
describe("tenantCssVar", () => {
  it("returns var(--tenant-<name>, <fallback>) with the caller's default", () => {
    expect(tenantCssVar("tiles.bg", "#1B1F5C"))
      .toBe("var(--tenant-tiles-bg, #1B1F5C)");
  });

  it("supports the -css variant for fill slots", () => {
    expect(tenantCssVar("menu.bg", "#000000", "css"))
      .toBe("var(--tenant-menu-bg-css, #000000)");
  });

  it("falls back to the module default when no fallback is passed", () => {
    // TENANT_VAR_DEFAULTS pins the pre-refactor hex for every slot.
    const out = tenantCssVar("menu.bg");
    expect(out).toMatch(/^var\(--tenant-menu-bg, #[0-9A-Fa-f]{6}\)$/);
  });
});


// ── 4. Provider integration — DOM vars flip on refetch ─────────
function _stubHTMLStyle() {
  // Nothing to stub — jsdom already implements style.setProperty
  // on documentElement. Kept as a placeholder in case a future
  // env needs it.
}


describe("TenantThemeProvider · DOM overlay", () => {
  beforeEach(_stubHTMLStyle);

  it("writes CSS vars to <html> once the initial fetch resolves", async () => {
    api.get.mockResolvedValueOnce(getClientPreset("hvac"));
    render(<TenantThemeProvider><div /></TenantThemeProvider>);
    await waitFor(() => {
      const v = document.documentElement.style
        .getPropertyValue("--tenant-menu-bg");
      expect(v).toBe("#1e40af");  // hvac menu.bg
    });
  });

  it("refetch replaces the vars in place", async () => {
    api.get
      .mockResolvedValueOnce(getClientPreset("hvac"))
      .mockResolvedValueOnce(getClientPreset("pool"));

    let captured;
    function Consumer() {
      const v = useTenantTheme();
      React.useEffect(() => { captured = v; });
      return null;
    }
    render(
      <TenantThemeProvider><Consumer /></TenantThemeProvider>
    );
    await waitFor(() => {
      expect(document.documentElement.style
        .getPropertyValue("--tenant-menu-bg")).toBe("#1e40af");
    });
    await act(async () => { await captured.refetch(); });
    await waitFor(() => {
      expect(document.documentElement.style
        .getPropertyValue("--tenant-menu-bg")).toBe("#155e75");  // pool
    });
  });

  it("applyOverride flips vars without a GET", async () => {
    api.get.mockResolvedValueOnce(getClientPreset("hvac"));
    let captured;
    function Consumer() {
      const v = useTenantTheme();
      React.useEffect(() => { captured = v; });
      return null;
    }
    render(
      <TenantThemeProvider><Consumer /></TenantThemeProvider>
    );
    await waitFor(() => {
      expect(document.documentElement.style
        .getPropertyValue("--tenant-menu-bg")).toBe("#1e40af");
    });
    const before = api.get.mock.calls.length;
    act(() => { captured.applyOverride(getClientPreset("plumbing")); });
    await waitFor(() => {
      expect(document.documentElement.style
        .getPropertyValue("--tenant-menu-bg")).toBe("#1e3a8a");  // plumbing
    });
    expect(api.get).toHaveBeenCalledTimes(before);
  });
});
