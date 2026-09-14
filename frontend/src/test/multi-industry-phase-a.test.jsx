/**
 * Phase Feb-2026 · Multi-industry Phase A — enum + useIndustries hook.
 *
 * Verifies:
 *   1. Frontend enum has 25 entries + parity to labels.
 *   2. useIndustries returns safe defaults on cold mount.
 *   3. useIndustries returns industries + hasIndustry after fetch.
 *   4. Cache prevents duplicate fetches across mounts.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";

const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: { get: (...a) => getSpy(...a) },
}));

import {
  INDUSTRIES,
  INDUSTRY_LABELS,
  DEFAULT_INDUSTRY,
  isValidIndustry,
} from "@/config/industries";
import {
  useIndustries,
  invalidateIndustries,
} from "@/hooks/useIndustries";

function HookProbe() {
  const { industries, hasIndustry, loaded } = useIndustries();
  return (
    <div>
      <div data-testid="industries">{industries.join(",")}</div>
      <div data-testid="has-pools">{String(hasIndustry("pools"))}</div>
      <div data-testid="has-hvac">{String(hasIndustry("hvac"))}</div>
      <div data-testid="loaded">{String(loaded)}</div>
    </div>
  );
}

describe("Multi-industry Phase A · config", () => {
  it("exposes exactly 25 industries", () => {
    expect(INDUSTRIES.length).toBe(25);
  });

  it("pools is the historical default and first entry", () => {
    expect(INDUSTRIES[0]).toBe("pools");
    expect(DEFAULT_INDUSTRY).toBe("pools");
  });

  it("every slug has a label and vice-versa", () => {
    const labelKeys = Object.keys(INDUSTRY_LABELS);
    expect([...labelKeys].sort()).toEqual([...INDUSTRIES].sort());
    for (const slug of INDUSTRIES) {
      expect(INDUSTRY_LABELS[slug]).toBeTruthy();
    }
  });

  it("slug shape is lowercase-snake", () => {
    for (const slug of INDUSTRIES) {
      expect(slug).toMatch(/^[a-z0-9_]+$/);
    }
  });

  it("isValidIndustry sanity", () => {
    expect(isValidIndustry("pools")).toBe(true);
    expect(isValidIndustry("bogus")).toBe(false);
    expect(isValidIndustry(null)).toBe(false);
    expect(isValidIndustry(undefined)).toBe(false);
  });
});

describe("Multi-industry Phase A · useIndustries hook", () => {
  beforeEach(() => {
    getSpy.mockReset();
    invalidateIndustries();
  });

  it("returns safe defaults synchronously on cold mount", () => {
    // Make the fetch never resolve (Promise that stays pending)
    getSpy.mockReturnValue(new Promise(() => {}));
    render(<HookProbe />);
    expect(screen.getByTestId("industries").textContent).toBe("");
    expect(screen.getByTestId("has-pools").textContent).toBe("false");
    expect(screen.getByTestId("loaded").textContent).toBe("false");
  });

  it("returns industries + hasIndustry after tenant fetch settles", async () => {
    getSpy.mockResolvedValue({
      industries: ["pools", "landscaping"],
      slug: "aquaterra",
    });
    render(<HookProbe />);
    await waitFor(() =>
      expect(screen.getByTestId("industries").textContent)
        .toBe("pools,landscaping")
    );
    expect(screen.getByTestId("has-pools").textContent).toBe("true");
    expect(screen.getByTestId("has-hvac").textContent).toBe("false");
    expect(screen.getByTestId("loaded").textContent).toBe("true");
  });

  it("caches the tenant fetch — a second mount reuses the result", async () => {
    getSpy.mockResolvedValue({ industries: ["pools"] });
    const { unmount } = render(<HookProbe />);
    await waitFor(() =>
      expect(screen.getByTestId("industries").textContent).toBe("pools")
    );
    unmount();
    render(<HookProbe />);
    await waitFor(() =>
      expect(screen.getByTestId("industries").textContent).toBe("pools")
    );
    // Only ONE network call across both mounts.
    expect(getSpy).toHaveBeenCalledTimes(1);
  });

  it("returns empty industries when tenant fetch errors out", async () => {
    getSpy.mockRejectedValue(new Error("boom"));
    render(<HookProbe />);
    await waitFor(() =>
      expect(screen.getByTestId("loaded").textContent).toBe("true")
    );
    expect(screen.getByTestId("industries").textContent).toBe("");
    expect(screen.getByTestId("has-pools").textContent).toBe("false");
  });

  it("handles malformed industries field (not an array)", async () => {
    getSpy.mockResolvedValue({ industries: "not-an-array" });
    render(<HookProbe />);
    await waitFor(() =>
      expect(screen.getByTestId("loaded").textContent).toBe("true")
    );
    expect(screen.getByTestId("industries").textContent).toBe("");
    expect(screen.getByTestId("has-pools").textContent).toBe("false");
  });
});
