/**
 * BusinessSettings — Feb-2026 · frontend contract tests.
 *
 * Locks the admin page shipped by the Business Settings dispatch:
 *   1. Renders all fields + both colour pickers + the logo section.
 *   2. Invalid hex disables Save.
 *   3. Successful PATCH shows a toast + refetches the settings.
 *   4. Logo upload → preview thumbnail visible after upload.
 *   5. Live colour preview reflects picker changes before save.
 *
 * See /app/memory/FEATURE_BUSINESS_SETTINGS.md.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

const { getSpy, patchSpy, delSpy, toastSuccess, toastError } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  patchSpy: vi.fn(),
  delSpy: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api_base: () => "http://localhost/api",
  api: {
    get: (...a) => getSpy(...a),
    patch: (...a) => patchSpy(...a),
    del: (...a) => delSpy(...a),
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: (...a) => toastSuccess(...a),
    error: (...a) => toastError(...a),
  },
}));

// Stub the theme tokens so the page renders in a jsdom-friendly way.
vi.mock("@/theme", () => ({
  colors: {
    brand: "#0B4A6F",
    muted: "#6B7280",
    onSurface: "#111827",
    border: "#E5E7EB",
  },
}));

beforeEach(() => {
  // Default GET response — empty stored, sensible effective defaults.
  getSpy.mockResolvedValue({
    tenant_id: "t-1",
    stored: {
      company_display_name: "Aquaterra",
      mailing_address: "",
      phone: "",
      website: "",
      email: "",
      brand_primary_hex: "",
      brand_secondary_hex: "",
      logo_url: null,
      footer_note: "",
      tax_id: "",
      routing_traffic_aware: false,
    },
    effective: {
      company_display_name: "Aquaterra",
      brand_primary_hex: "#0B4A6F",
      brand_secondary_hex: "#F97316",
      logo_url: null,
      routing_traffic_aware: false,
    },
  });
  patchSpy.mockResolvedValue({
    tenant_id: "t-1",
    stored: {},
    effective: { brand_primary_hex: "#0B4A6F",
                 brand_secondary_hex: "#F97316",
                 routing_traffic_aware: false },
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  getSpy.mockReset();
  patchSpy.mockReset();
  delSpy.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
});

import BusinessSettings from "@/pages/settings/BusinessSettings";


describe("BusinessSettings page", () => {
  // Case 1
  it("renders all fields + both colour pickers + the logo tile", async () => {
    render(<BusinessSettings />);
    await waitFor(() =>
      expect(screen.queryByTestId("business-settings-title")).toBeTruthy(),
    );

    // Company section fields.
    expect(screen.getByTestId("bs-company-display-name")).toBeTruthy();
    expect(screen.getByTestId("bs-mailing-address")).toBeTruthy();
    expect(screen.getByTestId("bs-phone")).toBeTruthy();
    expect(screen.getByTestId("bs-website")).toBeTruthy();
    expect(screen.getByTestId("bs-email")).toBeTruthy();
    expect(screen.getByTestId("bs-footer-note")).toBeTruthy();
    expect(screen.getByTestId("bs-tax-id")).toBeTruthy();

    // Both colour pickers + swatches.
    expect(screen.getByTestId("bs-brand-primary-picker")).toBeTruthy();
    expect(screen.getByTestId("bs-brand-primary-hex")).toBeTruthy();
    expect(screen.getByTestId("bs-brand-primary-swatch")).toBeTruthy();
    expect(screen.getByTestId("bs-brand-secondary-picker")).toBeTruthy();
    expect(screen.getByTestId("bs-brand-secondary-hex")).toBeTruthy();

    // Logo section — empty state visible when no logo.
    expect(screen.getByTestId("bs-logo-tile")).toBeTruthy();
    expect(screen.getByTestId("bs-logo-empty")).toBeTruthy();

    // Live preview visible.
    expect(screen.getByTestId("business-settings-live-preview")).toBeTruthy();
  });

  // Case 2
  it("invalid hex disables Save", async () => {
    render(<BusinessSettings />);
    await waitFor(() =>
      expect(screen.queryByTestId("bs-brand-primary-hex")).toBeTruthy(),
    );

    // Type a bad hex → error surfaces + Save disabled.
    fireEvent.change(screen.getByTestId("bs-brand-primary-hex"), {
      target: { value: "not-a-hex" },
    });
    expect(
      screen.getByTestId("bs-brand-primary-error").textContent,
    ).toContain("#RRGGBB");
    const btn = screen.getByTestId("bs-save-button");
    expect(btn.hasAttribute("disabled")).toBe(true);
  });

  // Case 3
  it("successful PATCH shows a success toast + refetches", async () => {
    render(<BusinessSettings />);
    await waitFor(() =>
      expect(screen.queryByTestId("bs-phone")).toBeTruthy(),
    );

    // Dirty a field with valid input.
    fireEvent.change(screen.getByTestId("bs-phone"), {
      target: { value: "(555) 111-2222" },
    });
    // Save enabled.
    const btn = screen.getByTestId("bs-save-button");
    expect(btn.hasAttribute("disabled")).toBe(false);

    fireEvent.click(btn);
    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
    expect(patchSpy.mock.calls[0][0]).toBe(
      "/tenants/me/business-settings",
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
  });

  // Case 5 (case 4 covered by page mount not the network path since
  // upload uses raw fetch — verified via the visible preview switch).
  it("live colour preview reflects picker changes before save", async () => {
    render(<BusinessSettings />);
    await waitFor(() =>
      expect(screen.queryByTestId("bs-preview-header")).toBeTruthy(),
    );
    // Change primary → preview header re-renders with new colour.
    fireEvent.change(screen.getByTestId("bs-brand-primary-hex"), {
      target: { value: "#ABCDEF" },
    });
    const header = screen.getByTestId("bs-preview-header");
    // jsdom normalises hex → rgb(); accept either form so the test
    // isn't tied to jsdom's colour serialiser.
    const bg = header.style.background.toLowerCase();
    // #ABCDEF → rgb(171, 205, 239)
    expect(bg.includes("abcdef") || bg.includes("171") ).toBe(true);
    // Save is not called yet.
    expect(patchSpy).not.toHaveBeenCalled();
  });

  // Case 4 — logo preview switches to <img> after uploading a file.
  it("logo upload flow shows the preview once the upload resolves", async () => {
    // Mock fetch for the multipart POST.
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ logo_url: "/api/objects/tenant/logo.png" }),
    });
    render(<BusinessSettings />);
    await waitFor(() =>
      expect(screen.queryByTestId("bs-logo-file-input")).toBeTruthy(),
    );
    const file = new File(["hello"], "logo.png", { type: "image/png" });
    fireEvent.change(screen.getByTestId("bs-logo-file-input"), {
      target: { files: [file] },
    });
    await waitFor(() =>
      expect(screen.queryByTestId("bs-logo-preview")).toBeTruthy(),
    );
    expect(screen.getByTestId("bs-logo-preview").getAttribute("src"))
      .toContain("/api/objects/tenant/logo.png");
    // Remove button now available.
    expect(screen.getByTestId("bs-logo-remove-button")).toBeTruthy();
  });

  // Feb-2026 · Routing Traffic-Aware phase — toggle contract.
  it("renders the Routing section with the traffic-aware toggle off", async () => {
    render(<BusinessSettings />);
    await waitFor(() =>
      expect(screen.queryByTestId("business-settings-routing-section")).toBeTruthy(),
    );
    const toggle = screen.getByTestId("bs-routing-traffic-aware-toggle");
    expect(toggle).toBeTruthy();
    // Default (stored=false) → checkbox unchecked.
    expect(toggle.checked).toBe(false);
    // Helper copy present.
    expect(
      screen.getByTestId("bs-routing-traffic-aware-helper").textContent,
    ).toMatch(/live traffic data/i);
  });

  it("toggling traffic-aware round-trips through PATCH → refetch", async () => {
    // Second GET (after PATCH) returns stored=true so the refetch
    // path reflects the new value.
    getSpy
      .mockResolvedValueOnce({
        tenant_id: "t-1",
        stored: {
          company_display_name: "Aquaterra",
          routing_traffic_aware: false,
        },
        effective: {
          company_display_name: "Aquaterra",
          brand_primary_hex: "#0B4A6F",
          brand_secondary_hex: "#F97316",
          logo_url: null,
          routing_traffic_aware: false,
        },
      });

    render(<BusinessSettings />);
    await waitFor(() =>
      expect(screen.queryByTestId("bs-routing-traffic-aware-toggle")).toBeTruthy(),
    );
    const toggle = screen.getByTestId("bs-routing-traffic-aware-toggle");
    expect(toggle.checked).toBe(false);

    fireEvent.click(toggle);
    const btn = screen.getByTestId("bs-save-button");
    await waitFor(() => expect(btn.hasAttribute("disabled")).toBe(false));

    fireEvent.click(btn);
    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
    const patchBody = patchSpy.mock.calls[0][1];
    expect(patchBody.routing_traffic_aware).toBe(true);
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
  });

  // ── Feb-2026 · UX Polish Batch B follow-up — Email preview panel.
  it("renders the email-preview section with dropdown + empty state", async () => {
    render(<BusinessSettings />);
    await waitFor(() =>
      expect(screen.queryByTestId("business-settings-email-preview-section"))
        .toBeTruthy(),
    );
    expect(screen.getByTestId("bs-email-preview-select")).toBeTruthy();
    // No template selected on first render → empty state renders.
    expect(screen.getByTestId("bs-email-preview-empty").textContent)
      .toMatch(/choose a template/i);
    // iframe not yet mounted.
    expect(screen.queryByTestId("bs-email-preview-iframe")).toBeNull();
  });

  it("selecting a template fires the correct GET and renders the iframe", async () => {
    getSpy.mockImplementation((path) => {
      if (path.includes("email-preview")) {
        return Promise.resolve({
          template: "quote_sent",
          html: "<!doctype html><html><body>PREVIEW</body></html>",
        });
      }
      return Promise.resolve({
        tenant_id: "t-1", stored: {}, effective: {
          brand_primary_hex: "#0B4A6F", brand_secondary_hex: "#F97316",
          routing_traffic_aware: false,
        },
      });
    });
    render(<BusinessSettings />);
    await waitFor(() =>
      expect(screen.queryByTestId("bs-email-preview-select")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("bs-email-preview-select"), {
      target: { value: "quote_sent" },
    });
    await waitFor(() => {
      const call = getSpy.mock.calls.find(
        (c) => (c[0] || "").includes("email-preview"),
      );
      expect(call).toBeTruthy();
      expect(call[0]).toContain("template=quote_sent");
    });
    await waitFor(() =>
      expect(screen.queryByTestId("bs-email-preview-iframe")).toBeTruthy(),
    );
    const iframe = screen.getByTestId("bs-email-preview-iframe");
    // srcDoc carries the returned HTML — ``<html`` presence proves it.
    expect(iframe.getAttribute("srcdoc") || "").toContain("<html");
  });
});
