/**
 * Phase I1.5.c · Feb-2026 — ``useTenantTheme`` hook contract test.
 *
 * Locks:
 *   1. Provider fetches ``GET /api/tenants/me/theme`` once on mount.
 *   2. ``theme`` exposes the API response after the fetch resolves.
 *   3. ``refetch()`` triggers a fresh GET.
 *   4. GET error → hook falls back to the client-side ``default``
 *      preset (no throw).
 *   5. ``applyOverride(next)`` swaps the working theme
 *      optimistically without a GET.
 *   6. Consumers rendered outside ``<TenantThemeProvider>`` receive
 *      the default preset with ``isLoading=false``.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import React from "react";
import { render, waitFor, act } from "@testing-library/react";

import { getClientPreset } from "@/theme/presets";


// ── API mock ────────────────────────────────────────────────────
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


// ── Test harness ────────────────────────────────────────────────
function Probe({ onValue }) {
  const v = useTenantTheme();
  React.useEffect(() => { onValue(v); }, [v, onValue]);
  return null;
}


function _apiHVAC() {
  return { ...getClientPreset("hvac"), preset: "hvac" };
}


function _apiPool() {
  return { ...getClientPreset("pool"), preset: "pool" };
}


beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockReset();
});


// ── 1. Mount fetch ──────────────────────────────────────────────
describe("useTenantTheme", () => {
  it("fetches /tenants/me/theme once on mount and exposes it", async () => {
    api.get.mockResolvedValueOnce(_apiHVAC());
    const seen = [];
    render(
      <TenantThemeProvider>
        <Probe onValue={(v) => seen.push(v)} />
      </TenantThemeProvider>
    );
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/tenants/me/theme");
    });
    await waitFor(() => {
      const last = seen[seen.length - 1];
      expect(last.theme.preset).toBe("hvac");
      expect(last.isLoading).toBe(false);
      expect(last.error).toBeNull();
    });
  });

  it("refetch() triggers a new GET and replaces the theme", async () => {
    api.get
      .mockResolvedValueOnce(_apiHVAC())
      .mockResolvedValueOnce(_apiPool());
    const seen = [];
    render(
      <TenantThemeProvider>
        <Probe onValue={(v) => seen.push(v)} />
      </TenantThemeProvider>
    );
    await waitFor(() => {
      expect(seen.some((s) => s.theme.preset === "hvac")).toBe(true);
    });
    await act(async () => {
      await seen[seen.length - 1].refetch();
    });
    await waitFor(() => {
      const last = seen[seen.length - 1];
      expect(last.theme.preset).toBe("pool");
    });
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("falls back to the default preset when the GET errors", async () => {
    api.get.mockRejectedValueOnce(new Error("boom"));
    const seen = [];
    render(
      <TenantThemeProvider>
        <Probe onValue={(v) => seen.push(v)} />
      </TenantThemeProvider>
    );
    await waitFor(() => {
      const last = seen[seen.length - 1];
      expect(last.isLoading).toBe(false);
    });
    const last = seen[seen.length - 1];
    expect(last.theme.preset).toBe("default");
    expect(last.error).toBeInstanceOf(Error);
  });

  it("applyOverride() swaps the theme without a GET", async () => {
    api.get.mockResolvedValueOnce(_apiHVAC());
    const seen = [];
    render(
      <TenantThemeProvider>
        <Probe onValue={(v) => seen.push(v)} />
      </TenantThemeProvider>
    );
    await waitFor(() => {
      expect(seen.some((s) => s.theme.preset === "hvac")).toBe(true);
    });
    const before = api.get.mock.calls.length;
    act(() => {
      seen[seen.length - 1].applyOverride(getClientPreset("plumbing"));
    });
    await waitFor(() => {
      expect(seen[seen.length - 1].theme.preset).toBe("plumbing");
    });
    // No extra GET.
    expect(api.get).toHaveBeenCalledTimes(before);
  });

  it("returns the default preset (no fetch) outside the provider", () => {
    const seen = [];
    render(<Probe onValue={(v) => seen.push(v)} />);
    const last = seen[seen.length - 1];
    expect(last.theme.preset).toBe("default");
    expect(last.isLoading).toBe(false);
    expect(api.get).not.toHaveBeenCalled();
  });
});
