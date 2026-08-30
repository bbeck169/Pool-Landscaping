/**
 * Brand logo uploader · Feb-2026 · TD-08 promoted.
 *
 * Verifies the ``BrandLogoSettings`` page:
 *   * Renders the placeholder preview when the tenant has no logo.
 *   * Renders the tenant logo when one is set.
 *   * Upload button opens the file picker; selecting a valid PNG shows
 *     a pre-save preview + Save + Cancel.
 *   * Oversized files (>2 MB) surface an inline error and NEVER fire
 *     the network call.
 *   * Unsupported MIME types surface an inline error and NEVER fire
 *     the network call.
 *   * On successful upload, ``fetch`` is called once with the correct
 *     ``POST`` + multipart body, the tenant-brand cache is invalidated
 *     (via a dispatched ``tenant-brand:updated`` window event), and the
 *     component re-fetches the tenant.
 *   * The Remove button only appears when a logo exists, and requires
 *     a confirm click before the DELETE fires.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";

// Mocks — api + toast + invalidateTenantBrand.
const apiGet = vi.fn();
const apiDel = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => apiGet(...a), del: (...a) => apiDel(...a) },
  api_base: () => "https://api.example.com/api",
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
const invalidateSpy = vi.fn();
vi.mock("@/hooks/useTenantBrand", () => ({
  invalidateTenantBrand: () => invalidateSpy(),
}));

import BrandLogoSettings from "@/pages/settings/BrandLogoSettings";

const originalFetch = global.fetch;
const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

function makeFile(name, mime, sizeBytes) {
  const buf = new Uint8Array(sizeBytes);
  return new File([buf], name, { type: mime });
}

async function tick() {
  await act(async () => {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  apiGet.mockReset();
  apiDel.mockReset();
  invalidateSpy.mockReset();
  URL.createObjectURL = vi.fn(() => "blob:preview-mock");
  URL.revokeObjectURL = vi.fn();
  global.fetch = vi.fn();
  window.localStorage.setItem("token", "TESTTOKEN");
});

afterEach(() => {
  global.fetch = originalFetch;
  URL.createObjectURL = originalCreateObjectURL;
  URL.revokeObjectURL = originalRevokeObjectURL;
  window.localStorage.removeItem("token");
});

describe("BrandLogoSettings", () => {
  it("renders the placeholder preview when tenant has no logo", async () => {
    apiGet.mockResolvedValueOnce({
      id: "t1", slug: "aquaterra", name: "PLV",
      logo_url: null, branding: { logo_url: null },
    });
    render(<BrandLogoSettings />);
    await tick();
    expect(screen.getByTestId("brand-logo-preview-empty")).toBeInTheDocument();
    // Remove button hidden when there's no custom logo.
    expect(screen.queryByTestId("brand-logo-remove-btn")).toBeNull();
    // Guidance text is present.
    expect(screen.getByTestId("brand-logo-guidance").textContent)
      .toMatch(/PNG.*SVG.*WebP.*2 MB/i);
  });

  it("renders the current logo when tenant has one set + shows Remove", async () => {
    apiGet.mockResolvedValueOnce({
      id: "t1", slug: "aquaterra", name: "PLV",
      logo_url: "/api/objects/poolcrm/t1/branding/logo/abc.png",
      branding: {
        logo_url: "/api/objects/poolcrm/t1/branding/logo/abc.png",
      },
    });
    render(<BrandLogoSettings />);
    await tick();
    const img = screen.getByTestId("brand-logo-preview-current");
    expect(img.getAttribute("src")).toBe(
      "https://api.example.com/api/objects/poolcrm/t1/branding/logo/abc.png",
    );
    expect(screen.getByTestId("brand-logo-remove-btn")).toBeInTheDocument();
  });

  it("oversized files surface an inline error and never call fetch", async () => {
    apiGet.mockResolvedValueOnce({ id: "t1", logo_url: null });
    render(<BrandLogoSettings />);
    await tick();
    const input = screen.getByTestId("brand-logo-file-input");
    const bigFile = makeFile("huge.png", "image/png", 2 * 1024 * 1024 + 10);
    fireEvent.change(input, { target: { files: [bigFile] } });
    await tick();
    expect(screen.getByTestId("brand-logo-error").textContent).toMatch(/too large/i);
    expect(global.fetch).not.toHaveBeenCalled();
    // No pending upload row rendered.
    expect(screen.queryByTestId("brand-logo-pending")).toBeNull();
  });

  it("unsupported MIME types surface an inline error and never call fetch", async () => {
    apiGet.mockResolvedValueOnce({ id: "t1", logo_url: null });
    render(<BrandLogoSettings />);
    await tick();
    const input = screen.getByTestId("brand-logo-file-input");
    const badFile = makeFile("brand.txt", "text/plain", 100);
    fireEvent.change(input, { target: { files: [badFile] } });
    await tick();
    expect(screen.getByTestId("brand-logo-error").textContent)
      .toMatch(/unsupported format/i);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("valid PNG selection renders pending preview + Save + Cancel", async () => {
    apiGet.mockResolvedValueOnce({ id: "t1", logo_url: null });
    render(<BrandLogoSettings />);
    await tick();
    const input = screen.getByTestId("brand-logo-file-input");
    const okFile = makeFile("logo.png", "image/png", 4321);
    fireEvent.change(input, { target: { files: [okFile] } });
    await tick();
    expect(screen.getByTestId("brand-logo-pending")).toBeInTheDocument();
    expect(screen.getByTestId("brand-logo-pending-name").textContent).toBe("logo.png");
    expect(screen.getByTestId("brand-logo-pending-meta").textContent).toMatch(/4\.2 KB/);
    expect(screen.getByTestId("brand-logo-save-btn")).toBeInTheDocument();
    expect(screen.getByTestId("brand-logo-cancel-btn")).toBeInTheDocument();
    // Preview <img> src is the mocked blob URL.
    expect(screen.getByTestId("brand-logo-preview-pending").getAttribute("src"))
      .toBe("blob:preview-mock");
  });

  it("successful upload POSTs to the endpoint, invalidates cache, and re-fetches tenant", async () => {
    apiGet
      .mockResolvedValueOnce({ id: "t1", logo_url: null })  // initial
      .mockResolvedValueOnce({                                // after refresh
        id: "t1",
        logo_url: "/api/objects/poolcrm/t1/branding/logo/new.png",
        branding: { logo_url: "/api/objects/poolcrm/t1/branding/logo/new.png" },
      });
    global.fetch.mockResolvedValueOnce({
      ok: true, status: 200,
      json: async () => ({
        logo_url: "/api/objects/poolcrm/t1/branding/logo/new.png",
        size_bytes: 4321, content_type: "image/png",
        updated_at: "2026-02-15T10:00:00Z",
      }),
    });
    const brandUpdateSpy = vi.fn();
    window.addEventListener("tenant-brand:updated", brandUpdateSpy);
    try {
      render(<BrandLogoSettings />);
      await tick();
      const input = screen.getByTestId("brand-logo-file-input");
      fireEvent.change(input, {
        target: { files: [makeFile("logo.png", "image/png", 4321)] },
      });
      await tick();
      fireEvent.click(screen.getByTestId("brand-logo-save-btn"));
      await waitFor(() => expect(global.fetch).toHaveBeenCalled());
      const [url, init] = global.fetch.mock.calls[0];
      expect(url).toBe("https://api.example.com/api/tenants/branding/logo");
      expect(init.method).toBe("POST");
      expect(init.headers.Authorization).toBe("Bearer TESTTOKEN");
      expect(init.body).toBeInstanceOf(FormData);
      // Cache was invalidated so the app-shell BrandLogo re-fetches.
      expect(invalidateSpy).toHaveBeenCalled();
      // Custom event dispatched with the new logo_url.
      await waitFor(() => expect(brandUpdateSpy).toHaveBeenCalled());
      const evt = brandUpdateSpy.mock.calls[0][0];
      expect(evt.detail.logo_url).toBe(
        "/api/objects/poolcrm/t1/branding/logo/new.png",
      );
      // Second /tenants/current refresh fired.
      expect(apiGet).toHaveBeenCalledTimes(2);
    } finally {
      window.removeEventListener("tenant-brand:updated", brandUpdateSpy);
    }
  });

  it("413 response surfaces 'File too large' inline", async () => {
    apiGet.mockResolvedValueOnce({ id: "t1", logo_url: null });
    global.fetch.mockResolvedValueOnce({
      ok: false, status: 413,
      json: async () => ({
        detail: { error_code: "file_too_large", message: "…" },
      }),
    });
    render(<BrandLogoSettings />);
    await tick();
    fireEvent.change(screen.getByTestId("brand-logo-file-input"), {
      target: { files: [makeFile("logo.png", "image/png", 2000)] },
    });
    await tick();
    fireEvent.click(screen.getByTestId("brand-logo-save-btn"));
    await waitFor(() => {
      expect(screen.getByTestId("brand-logo-error").textContent)
        .toMatch(/too large.*2 MB/i);
    });
  });

  it("Remove button opens confirm modal and only fires DELETE on confirm", async () => {
    apiGet
      .mockResolvedValueOnce({
        id: "t1",
        logo_url: "/api/objects/poolcrm/t1/branding/logo/abc.png",
        branding: {
          logo_url: "/api/objects/poolcrm/t1/branding/logo/abc.png",
        },
      })
      .mockResolvedValueOnce({ id: "t1", logo_url: null });
    apiDel.mockResolvedValueOnce({ cleared: true, logo_url: null });

    render(<BrandLogoSettings />);
    await tick();
    fireEvent.click(screen.getByTestId("brand-logo-remove-btn"));
    expect(screen.getByTestId("brand-logo-remove-modal")).toBeInTheDocument();
    // Cancel → no DELETE.
    fireEvent.click(screen.getByTestId("brand-logo-remove-cancel-btn"));
    await tick();
    expect(apiDel).not.toHaveBeenCalled();

    // Open again → confirm → DELETE fires.
    fireEvent.click(screen.getByTestId("brand-logo-remove-btn"));
    fireEvent.click(screen.getByTestId("brand-logo-remove-confirm-btn"));
    await waitFor(() => expect(apiDel).toHaveBeenCalledWith("/tenants/branding/logo"));
    expect(invalidateSpy).toHaveBeenCalled();
  });
});
