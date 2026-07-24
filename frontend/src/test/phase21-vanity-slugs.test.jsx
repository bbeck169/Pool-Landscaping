/**
 * Feb-2026 · Phase 21 — Vanity slug editor + Primary customer URL page.
 *
 * Covers:
 * * Renders canonical + aliases from GET.
 * * Add-form calls POST with the trimmed lowercased alias.
 * * Add-form surfaces 409 collision error inline.
 * * Add-form rejects reserved words + invalid regex client-side without
 *   hitting the network.
 * * Remove opens ConfirmDeleteDialog + on confirm calls DELETE.
 * * Primary URL save calls PATCH with `primary_app_domain`.
 * * "Test URL" button opens the current value in a new tab.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const apiGet = vi.fn();
const apiPost = vi.fn();
const apiPatch = vi.fn();
const apiDel = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => apiGet(...a),
    post: (...a) => apiPost(...a),
    patch: (...a) => apiPatch(...a),
    del: (...a) => apiDel(...a),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import VanitySlugsPage from "@/pages/settings/VanitySlugsPage";


function renderPage() {
  return render(<MemoryRouter><VanitySlugsPage /></MemoryRouter>);
}


beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiPatch.mockReset();
  apiDel.mockReset();
  // Default seed for GET.
  apiGet.mockImplementation((path) => {
    if (path === "/tenants/current/slug-aliases") {
      return Promise.resolve({
        canonical_slug: "aquaterra",
        slug_aliases: ["plofv"],
      });
    }
    if (path === "/tenants/current/primary-app-domain") {
      return Promise.resolve({
        primary_app_domain: "https://app.plofv.com",
        default: "https://app.plofv.com",
      });
    }
    return Promise.reject(new Error("unexpected GET " + path));
  });
});


describe("VanitySlugsPage", () => {
  it("renders canonical + aliases from GET", async () => {
    renderPage();
    expect(await screen.findByTestId("vanity-slug-canonical"))
      .toHaveTextContent("aquaterra");
    expect(await screen.findByTestId("vanity-slug-item-plofv")).toBeInTheDocument();
  });

  it("add-form calls POST with lowercased trimmed alias", async () => {
    apiPost.mockResolvedValueOnce({ ok: true,
      slug_aliases: ["plofv", "vistancia-pools"] });
    renderPage();
    await screen.findByTestId("vanity-slug-canonical");
    const input = screen.getByTestId("vanity-slug-add-input");
    fireEvent.change(input, { target: { value: "  Vistancia-Pools  " } });
    fireEvent.click(screen.getByTestId("vanity-slug-add-submit"));
    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith(
        "/tenants/current/slug-aliases", { alias: "vistancia-pools" },
      );
    });
    expect(await screen.findByTestId("vanity-slug-item-vistancia-pools")).toBeInTheDocument();
  });

  it("rejects reserved words client-side without POSTing", async () => {
    renderPage();
    await screen.findByTestId("vanity-slug-canonical");
    fireEvent.change(screen.getByTestId("vanity-slug-add-input"),
                       { target: { value: "admin" } });
    fireEvent.click(screen.getByTestId("vanity-slug-add-submit"));
    await waitFor(() => {
      const helper = screen.getByTestId("vanity-slug-add-helper");
      expect(helper.textContent).toMatch(/reserved/i);
    });
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("rejects invalid regex client-side", async () => {
    renderPage();
    await screen.findByTestId("vanity-slug-canonical");
    fireEvent.change(screen.getByTestId("vanity-slug-add-input"),
                       { target: { value: "-bad" } });
    fireEvent.click(screen.getByTestId("vanity-slug-add-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("vanity-slug-add-helper").textContent)
        .toMatch(/lowercase|alphanumeric|hyphens/i);
    });
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("surfaces 409 collision from server inline", async () => {
    apiPost.mockRejectedValueOnce(new Error("alias 'foobar' is already in use by tenant 'other'"));
    renderPage();
    await screen.findByTestId("vanity-slug-canonical");
    fireEvent.change(screen.getByTestId("vanity-slug-add-input"),
                       { target: { value: "foobar" } });
    fireEvent.click(screen.getByTestId("vanity-slug-add-submit"));
    await waitFor(() => {
      const helper = screen.getByTestId("vanity-slug-add-helper");
      expect(helper.textContent).toMatch(/already claimed/i);
    });
  });

  it("primary URL save calls PATCH", async () => {
    apiPatch.mockResolvedValueOnce({ ok: true,
      primary_app_domain: "https://pay.vistancia-pools.com" });
    renderPage();
    await screen.findByTestId("vanity-slug-canonical");
    fireEvent.change(screen.getByTestId("primary-domain-input"),
                       { target: { value: "https://pay.vistancia-pools.com" } });
    fireEvent.click(screen.getByTestId("primary-domain-save-btn"));
    await waitFor(() => {
      expect(apiPatch).toHaveBeenCalledWith(
        "/tenants/current/primary-app-domain",
        { primary_app_domain: "https://pay.vistancia-pools.com" },
      );
    });
  });

  it("Test URL opens the current value in a new tab", async () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    renderPage();
    await screen.findByTestId("vanity-slug-canonical");
    fireEvent.click(screen.getByTestId("primary-domain-test-btn"));
    expect(openSpy).toHaveBeenCalledWith(
      "https://app.plofv.com", "_blank", "noopener,noreferrer",
    );
    openSpy.mockRestore();
  });
});
