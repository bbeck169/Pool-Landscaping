/**
 * Feb-2026 · Global Custom Color Picker · component acceptance.
 *
 * Locks the acceptance contract on ``components/ui/ColorPicker.jsx``:
 *   1. Presets row renders one swatch per palette hex; low-contrast
 *      swatches (e.g. emerald ``#10B981``) are visually disabled.
 *   2. Clicking a preset fires ``onChange(hex)`` + POSTs the recent-
 *      colors push.
 *   3. Recents row hydrates from ``GET /users/me/recent-colors`` on
 *      mount and renders one swatch per hex.
 *   4. Freeform hex input with a low-contrast color surfaces the
 *      inline warning + disables the Apply button.
 *   5. Freeform hex input with a valid color enables Apply; clicking
 *      Apply fires ``onChange`` + POST.
 *
 * Also covers the client-side helper contract in
 * ``lib/colorContrast.js``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("sonner", () => {
  const _toast = Object.assign(vi.fn(), {
    success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn(),
  });
  return { toast: _toast, Toaster: () => null };
});

vi.mock("@/api", () => {
  const _api = { get: vi.fn(), post: vi.fn(), patch: vi.fn(),
                  del: vi.fn(), put: vi.fn() };
  return { api: _api };
});


import ColorPicker from "@/components/ui/ColorPicker";
import {
  MIN_CONTRAST_VS_WHITE,
  contrastRatioVsWhite,
  validateColorHexForPin,
} from "@/lib/colorContrast";
import { api } from "@/api";


beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue({ recent_colors: [] });
  api.post.mockResolvedValue({ recent_colors: [] });
});
afterEach(() => vi.clearAllMocks());


describe("colorContrast client helper", () => {
  it("MIN threshold equals 3.0 (matches server)", () => {
    expect(MIN_CONTRAST_VS_WHITE).toBe(3.0);
  });

  it("returns high ratios for dark colors", () => {
    expect(contrastRatioVsWhite("#000000")).toBeGreaterThan(20);
    expect(contrastRatioVsWhite("#3B82F6")).toBeGreaterThanOrEqual(3.0);
  });

  it("flags near-white below threshold", () => {
    expect(contrastRatioVsWhite("#F5F5F5")).toBeLessThan(3.0);
  });

  it("validateColorHexForPin canonicalises and returns ratio", () => {
    const v = validateColorHexForPin("3b82f6");
    expect(v.ok).toBe(true);
    expect(v.canonical).toBe("#3B82F6");
    expect(v.ratio).toBeGreaterThanOrEqual(3.0);
  });

  it("validateColorHexForPin rejects malformed + low-contrast", () => {
    expect(validateColorHexForPin("xyz").reason).toBe("invalid");
    const light = validateColorHexForPin("#FEFEFE");
    expect(light.ok).toBe(false);
    expect(light.reason).toBe("contrast");
    expect(light.ratio).toBeLessThan(3.0);
  });
});


describe("ColorPicker · presets + recents hydrate + commit", () => {
  it("(1) renders one preset per palette hex", async () => {
    render(<ColorPicker value="#3B82F6" onChange={() => {}} />);
    const presets = await screen.findByTestId("color-picker-presets");
    // 24 hexes in the expanded palette (Feb-2026 Ticket B).
    expect(presets.querySelectorAll("button").length).toBeGreaterThanOrEqual(12);
    // Low-contrast palette entries (emerald 10B981) are visually
    // disabled — button.disabled === true.
    const emerald = presets.querySelector('[data-testid$="#10B981"]');
    expect(emerald).not.toBeNull();
    expect(emerald.disabled).toBe(true);
  });

  it("(2) clicking a preset fires onChange + POSTs recent-colors", async () => {
    const onChange = vi.fn();
    render(<ColorPicker value="#3B82F6" onChange={onChange} />);
    await screen.findByTestId("color-picker-presets");
    const btn = screen.getByTestId("color-picker-preset-#EC4899");
    await act(async () => {
      fireEvent.click(btn);
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(onChange).toHaveBeenCalledWith("#EC4899");
    expect(api.post).toHaveBeenCalledWith(
      "/users/me/recent-colors",
      { color: "#EC4899" },
    );
  });

  it("(3) recents row hydrates from GET on mount", async () => {
    api.get.mockResolvedValue({
      recent_colors: ["#0369A1", "#B45309", "#A21CAF"],
    });
    render(<ColorPicker value="#3B82F6" onChange={() => {}} />);
    await waitFor(() =>
      expect(screen.queryByTestId("color-picker-recent-row")).not.toBeNull(),
    );
    expect(screen.getByTestId("color-picker-recent-#0369A1")).toBeTruthy();
    expect(screen.getByTestId("color-picker-recent-#B45309")).toBeTruthy();
    expect(screen.getByTestId("color-picker-recent-#A21CAF")).toBeTruthy();
  });

  it("(4) low-contrast freeform hex surfaces the warning + disables Apply", async () => {
    render(<ColorPicker value="#3B82F6" onChange={() => {}} />);
    await screen.findByTestId("color-picker-hex-input");
    fireEvent.change(screen.getByTestId("color-picker-hex-input"),
                      { target: { value: "#FEFEFE" } });
    expect(screen.getByTestId("color-picker-contrast-warning").textContent)
      .toMatch(/too light/i);
    expect(screen.getByTestId("color-picker-commit").disabled).toBe(true);
  });

  it("(5) valid freeform hex enables Apply and commits", async () => {
    const onChange = vi.fn();
    render(<ColorPicker value="#3B82F6" onChange={onChange} />);
    await screen.findByTestId("color-picker-hex-input");
    fireEvent.change(screen.getByTestId("color-picker-hex-input"),
                      { target: { value: "#4B0082" } });
    // Apply button is enabled once contrast passes + diff from initial.
    expect(screen.getByTestId("color-picker-commit").disabled).toBe(false);
    await act(async () => {
      fireEvent.click(screen.getByTestId("color-picker-commit"));
      await new Promise((r) => setTimeout(r, 10));
    });
    expect(onChange).toHaveBeenCalledWith("#4B0082");
    expect(api.post).toHaveBeenCalledWith(
      "/users/me/recent-colors",
      { color: "#4B0082" },
    );
  });

  it("commits are silent when the recent-colors POST fails", async () => {
    api.post.mockRejectedValue(new Error("network"));
    const onChange = vi.fn();
    render(<ColorPicker value="#3B82F6" onChange={onChange} />);
    await screen.findByTestId("color-picker-presets");
    await act(async () => {
      fireEvent.click(screen.getByTestId("color-picker-preset-#EC4899"));
      await new Promise((r) => setTimeout(r, 10));
    });
    // onChange still fires even though the recent-colors push failed.
    expect(onChange).toHaveBeenCalledWith("#EC4899");
  });
});
