/**
 * Phase K39a · Feb-2026 — MapsProviderGate + provider resolver tests.
 *
 * Covers:
 *   1. Default (no env vars) → provider="google", GoogleGate renders.
 *   2. provider=here + key present → HereGate renders (no fallback tile).
 *   3. provider=here + empty key → falls back to google + fires
 *      console.warn ONCE.
 *   4. Snapshot regression: MapsProviderGate under google resolves
 *      to <APIProvider>, matching the pre-K39a wrapper shape.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";

import { _computeProvider } from "@/lib/maps/provider";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.resetModules();
});

describe("K39a · provider resolver", () => {
  it("defaults to google when no env is set", () => {
    expect(_computeProvider({})).toBe("google");
  });

  it("returns here when flag=here + key present", () => {
    expect(
      _computeProvider({
        REACT_APP_MAPS_PROVIDER: "here",
        REACT_APP_HERE_API_KEY: "test-key",
      }),
    ).toBe("here");
  });

  it("falls back to google + warns once when flag=here + empty key", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.resetModules();
    const mod = await import("@/lib/maps/provider");
    const p = mod._computeProvider({
      REACT_APP_MAPS_PROVIDER: "here",
      REACT_APP_HERE_API_KEY: "",
    });
    expect(p).toBe("google");
    expect(warnSpy).toHaveBeenCalledTimes(1);
    const first = warnSpy.mock.calls[0][0];
    expect(first).toMatch(/REACT_APP_HERE_API_KEY/);
    // Second call in the same module lifetime does NOT re-warn.
    mod._computeProvider({
      REACT_APP_MAPS_PROVIDER: "here",
      REACT_APP_HERE_API_KEY: "",
    });
    expect(warnSpy).toHaveBeenCalledTimes(1);
  });
});

describe("K39a · MapsProviderGate", () => {
  it("wraps children in the Google APIProvider under provider=google (default)", async () => {
    vi.resetModules();
    vi.doMock("@/lib/maps/provider", () => ({
      useMapsProvider: () => "google",
      _computeProvider: () => "google",
    }));
    vi.doMock("@vis.gl/react-google-maps", () => ({
      APIProvider: ({ children, apiKey }) => (
        <div data-testid="google-apiprovider" data-key={apiKey}>
          {children}
        </div>
      ),
      Map: () => null,
      AdvancedMarker: () => null,
      InfoWindow: () => null,
      Pin: () => null,
      useMap: () => null,
      useMapsLibrary: () => null,
    }));
    const { default: Gate } = await import("@/lib/maps/MapsProviderGate");
    const { getByTestId } = render(
      <Gate apiKey="fake-google-key">
        <div data-testid="child">hi</div>
      </Gate>,
    );
    expect(getByTestId("google-apiprovider")).toBeTruthy();
    expect(getByTestId("google-apiprovider").dataset.key).toBe("fake-google-key");
    expect(getByTestId("child").textContent).toBe("hi");
  });

  it("renders the HERE gate under provider=here + key present", async () => {
    vi.resetModules();
    vi.doMock("@/lib/maps/provider", () => ({
      useMapsProvider: () => "here",
      _computeProvider: () => "here",
    }));
    const { default: Gate } = await import("@/lib/maps/MapsProviderGate");
    const { getByTestId, queryByTestId } = render(
      <Gate>
        <div data-testid="child">hi</div>
      </Gate>,
    );
    expect(getByTestId("child").textContent).toBe("hi");
    // No fallback tile — the fallback logic lives inside <Map>, not the gate.
    expect(queryByTestId("maps-here-fallback")).toBeNull();
  });

  it("snapshot regression: google-mode gate renders the pre-K39a wrapper shape", async () => {
    vi.resetModules();
    vi.doMock("@/lib/maps/provider", () => ({
      useMapsProvider: () => "google",
      _computeProvider: () => "google",
    }));
    vi.doMock("@vis.gl/react-google-maps", () => ({
      APIProvider: ({ children, apiKey, libraries }) => (
        <div
          data-testid="google-apiprovider"
          data-key={apiKey}
          data-libs={JSON.stringify(libraries || [])}
        >
          {children}
        </div>
      ),
      Map: () => null,
      AdvancedMarker: () => null,
      InfoWindow: () => null,
      Pin: () => null,
      useMap: () => null,
      useMapsLibrary: () => null,
    }));
    const { default: Gate } = await import("@/lib/maps/MapsProviderGate");
    const { container } = render(
      <Gate apiKey="AIza-fake" libraries={["marker", "geometry"]}>
        <span>Dispatch shell child</span>
      </Gate>,
    );
    // Byte-identical to pre-K39a: APIProvider with apiKey + libraries
    // wrapping the shell subtree.
    expect(container.firstChild).toMatchInlineSnapshot(`
      <div
        data-key="AIza-fake"
        data-libs="["marker","geometry"]"
        data-testid="google-apiprovider"
      >
        <span>
          Dispatch shell child
        </span>
      </div>
    `);
  });

  it("HERE adapter <Map> renders the 'Map unavailable' fallback tile when no key is present", async () => {
    // Clear the key so hereAdapter's Map init errors out with
    // ``no-key`` and mounts the fallback per K39a §4 (never throws).
    const prev = process.env.REACT_APP_HERE_API_KEY;
    process.env.REACT_APP_HERE_API_KEY = "";
    try {
      vi.resetModules();
      const { Map } = await import("@/lib/maps/hereAdapter");
      const { findByTestId } = render(<Map />);
      const fb = await findByTestId("maps-here-fallback");
      expect(fb).toBeTruthy();
      expect(fb.textContent).toMatch(/Map unavailable/);
    } finally {
      process.env.REACT_APP_HERE_API_KEY = prev;
    }
  });
});
