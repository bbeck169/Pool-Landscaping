/**
 * Phase I1.5.b · Feb-2026 — Theme editor UI contract test.
 *
 * Covers the flows called out in the phase brief:
 *   1. Editor renders all 5 surface sections.
 *   2. Solid-only slots do NOT expose the mode toggle.
 *   3. Solid → gradient mode toggle flips the slot shape.
 *   4. Color picker updates the live preview in real time.
 *   5. Preset picker enumerates every preset returned by the API.
 *   6. "Apply preset" opens a confirm modal → POST with ``{key}``.
 *   7. Discard reverts working state to server state.
 *   8. Save button disabled when the preview endpoint returns errors.
 *   9. Save button posts the working theme via PUT.
 *
 * The ``@/api`` module is fully mocked here so no server round-trip
 * happens — matches the SubscriptionCreateModal pattern already used
 * across the suite.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import React from "react";
import { MemoryRouter } from "react-router-dom";
import {
  render, screen, fireEvent, waitFor, act,
} from "@testing-library/react";


// ── API mock ────────────────────────────────────────────────────
const _default_theme = () => {
  const s = (h) => ({ mode: "solid", solid: h });
  return {
    preset: "default",
    menu: { bg: s("#0f172a"), text: s("#ffffff") },
    rail: { bg: s("#0f172a"), text: s("#ffffff") },
    tiles: { bg: s("#ffffff"), text: s("#0f172a"), border: s("#e5e7eb") },
    buttons: { bg: s("#166534"), text: s("#ffffff") },
    accents: {
      primary:     s("#166534"),
      secondary:   s("#0f172a"),
      text:        s("#0f172a"),
      link:        s("#0f172a"),
      focus_ring:  s("#166534"),
      badge_bg:    s("#dcfce7"),
      badge_text:  s("#14532d"),
    },
  };
};

const _presets_response = () => ({
  presets: [
    { key: "default",        name: "Default",        theme: _default_theme() },
    { key: "pool_landscape", name: "Pool Landscape", theme: _default_theme() },
    { key: "pool",           name: "Pool",           theme: _default_theme() },
    { key: "hvac",           name: "Hvac",           theme: _default_theme() },
  ],
});

const _api_state = { previewResult: { valid: true, errors: [] } };

vi.mock("@/api", () => {
  const api = {
    get: vi.fn(async (path) => {
      if (path === "/tenants/me/theme") return _default_theme();
      if (path === "/theme-presets") return _presets_response();
      return null;
    }),
    post: vi.fn(async (path, body) => {
      if (path === "/tenants/me/theme/preview") return _api_state.previewResult;
      if (path === "/tenants/me/theme/apply-preset") {
        return { ..._default_theme(), preset: body.key };
      }
      return { ok: true };
    }),
    put: vi.fn(async (_path, body) => body),
    patch: vi.fn(),
    delete: vi.fn(),
  };
  return { __esModule: true, api, default: api };
});


// ── sonner mock (no-op toasts) ─────────────────────────────────
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));


import ThemeSettings from "@/pages/settings/ThemeSettings";
import { api } from "@/api";


function renderPage() {
  return render(
    <MemoryRouter>
      <ThemeSettings />
    </MemoryRouter>
  );
}


async function _flushLoad() {
  // Two microtask ticks for the Promise.all → dispatch → setState.
  await screen.findByTestId("theme-settings-page");
}


async function _flushPreviewDebounce() {
  // The editor debounces preview at 400 ms.
  await act(async () => {
    await new Promise((r) => setTimeout(r, 450));
  });
}


beforeEach(() => {
  _api_state.previewResult = { valid: true, errors: [] };
  // Radix Select calls scrollIntoView on the highlighted item —
  // jsdom doesn't implement it. Stub globally for this suite.
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = vi.fn();
  }
  // Radix Select also uses hasPointerCapture on the trigger —
  // jsdom doesn't implement pointer capture either.
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = vi.fn(() => false);
    Element.prototype.releasePointerCapture = vi.fn();
  }
});


// ── 1. All 5 sections render ────────────────────────────────────
describe("Phase I1.5.b · Theme editor", () => {
  it("renders all 5 surface sections", async () => {
    renderPage();
    await _flushLoad();
    for (const key of ["menu", "rail", "tiles", "buttons", "accents"]) {
      expect(screen.getByTestId(`theme-section-${key}`)).toBeInTheDocument();
    }
  });

  it("hides mode toggle on solid-only slots (menu.text)", async () => {
    renderPage();
    await _flushLoad();
    expect(
      screen.queryByTestId("theme-slot-menu-text-mode-toggle")
    ).not.toBeInTheDocument();
    // But menu.bg has the toggle (fill slot).
    expect(
      screen.getByTestId("theme-slot-menu-bg-mode-toggle")
    ).toBeInTheDocument();
  });

  it("flips slot to gradient mode when the toggle is clicked", async () => {
    renderPage();
    await _flushLoad();
    // menu.bg starts as solid.
    expect(
      screen.queryByTestId("theme-slot-menu-bg-grad-preview")
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("theme-slot-menu-bg-mode-gradient"));

    expect(
      screen.getByTestId("theme-slot-menu-bg-grad-preview")
    ).toBeInTheDocument();
    // Warning banner appears on gradient slots.
    expect(
      screen.getByTestId("theme-slot-menu-bg-grad-warning")
    ).toBeInTheDocument();
  });

  it("updates live preview when a solid color changes", async () => {
    renderPage();
    await _flushLoad();
    const preview = screen.getByTestId("theme-preview-nav");
    // Initial menu.bg = #0f172a (default). Change to #123456 which
    // jsdom serializes as rgb(18, 52, 86).
    const picker = screen.getByTestId("theme-slot-menu-bg-solid-picker");
    fireEvent.change(picker, { target: { value: "#123456" } });

    expect(preview).toHaveStyle({ background: "rgb(18, 52, 86)" });
  });

  it("preset picker enumerates every preset returned by the API", async () => {
    renderPage();
    await _flushLoad();
    // Open the shadcn Select dropdown.
    fireEvent.click(screen.getByTestId("theme-preset-select"));
    await waitFor(() =>
      expect(screen.getByTestId("theme-preset-option-hvac")).toBeInTheDocument()
    );
    for (const k of ["default", "pool_landscape", "pool", "hvac"]) {
      expect(
        screen.getByTestId(`theme-preset-option-${k}`)
      ).toBeInTheDocument();
    }
  });

  it("Apply preset opens confirm modal and POSTs {key: '...'}", async () => {
    renderPage();
    await _flushLoad();
    // Click Apply preset → modal opens.
    fireEvent.click(screen.getByTestId("theme-apply-preset-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("theme-apply-preset-modal")).toBeInTheDocument()
    );
    // Confirm → POST fires with the selected key (starts as "default").
    fireEvent.click(screen.getByTestId("theme-apply-preset-confirm"));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/tenants/me/theme/apply-preset",
        { key: "default" },
      );
    });
  });

  it("Discard reverts working state to server state", async () => {
    renderPage();
    await _flushLoad();
    const picker = screen.getByTestId("theme-slot-menu-bg-solid-picker");
    fireEvent.change(picker, { target: { value: "#ff00ff" } });
    // Discard becomes enabled once dirty.
    const discardBtn = screen.getByTestId("theme-discard-btn");
    expect(discardBtn).not.toBeDisabled();

    fireEvent.click(discardBtn);
    // Back to server default (#0f172a → rgb(15, 23, 42)).
    expect(screen.getByTestId("theme-preview-nav")).toHaveStyle({
      background: "rgb(15, 23, 42)",
    });
  });

  it("Save is disabled when preview reports errors, enabled otherwise", async () => {
    renderPage();
    await _flushLoad();
    const saveBtn = screen.getByTestId("theme-save-btn");
    // Initially not dirty → disabled.
    expect(saveBtn).toBeDisabled();

    // Poison the mock so preview reports an error.
    _api_state.previewResult = {
      valid: false,
      errors: [{
        code: "CONTRAST_FAIL",
        path: "tiles.text",
        message: "Low contrast",
        computed_ratio: 1.23,
      }],
    };
    fireEvent.change(
      screen.getByTestId("theme-slot-menu-bg-solid-picker"),
      { target: { value: "#aabbcc" } },
    );
    await _flushPreviewDebounce();
    // Dirty but preview invalid → still disabled.
    expect(saveBtn).toBeDisabled();
    expect(screen.getByTestId("theme-error-summary")).toBeInTheDocument();

    // Un-poison → next change should enable save.
    _api_state.previewResult = { valid: true, errors: [] };
    fireEvent.change(
      screen.getByTestId("theme-slot-menu-bg-solid-picker"),
      { target: { value: "#0f172a" } },
    );
    // Even without waiting we need the debounced preview to
    // clear errors before Save re-enables.
    await _flushPreviewDebounce();
    // Now dirty (color changed and back — still counts as dirty
    // because reducer stringify-compares) and no errors.
    // The button state is derived from ``dirty && !hasErrors``.
    // Since the reducer marks non-equal-to-base as dirty, and we
    // ended at the base color, it might be clean. Assert we can
    // change to a different value and get enabled.
    fireEvent.change(
      screen.getByTestId("theme-slot-menu-bg-solid-picker"),
      { target: { value: "#123456" } },
    );
    await _flushPreviewDebounce();
    expect(saveBtn).not.toBeDisabled();
  });

  it("Save PUTs the working theme", async () => {
    renderPage();
    await _flushLoad();
    fireEvent.change(
      screen.getByTestId("theme-slot-menu-bg-solid-picker"),
      { target: { value: "#123456" } },
    );
    await _flushPreviewDebounce();
    fireEvent.click(screen.getByTestId("theme-save-btn"));
    await waitFor(() => {
      const putCalls = api.put.mock.calls.filter(
        (c) => c[0] === "/tenants/me/theme"
      );
      expect(putCalls.length).toBeGreaterThan(0);
      const body = putCalls[0][1];
      expect(body.menu.bg.solid).toBe("#123456");
    });
  });
});
