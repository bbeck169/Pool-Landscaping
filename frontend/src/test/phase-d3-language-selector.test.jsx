/**
 * Phase D3 · Feb 2026 — LanguageSelector wiring.
 *
 * Locks the contract:
 *   * Three options render (English / Español / Français).
 *   * Selecting "es" flips i18next AND writes localStorage.
 *   * Selecting "es" fires a ``PATCH /api/users/me`` with
 *     ``{locale: "es"}`` (fire-and-forget — errors don't block).
 */
import { describe, it, expect, beforeAll, beforeEach, vi } from "vitest";
import {
  render, screen, fireEvent, cleanup, waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom";


const patchMock = vi.fn(async () => ({ ok: true }));
vi.mock("@/api", () => ({
  api: {
    patch: patchMock,
    get: vi.fn(),
    post: vi.fn(),
  },
}));


let LanguageSelector;
let i18n;

beforeAll(async () => {
  const modI18n = await import("../i18n");
  i18n = modI18n.default;
  const mod = await import("../components/i18n/LanguageSelector");
  LanguageSelector = mod.default;
});

beforeEach(async () => {
  patchMock.mockClear();
  try { localStorage.removeItem("lang"); } catch { /* jsdom noop */ }
  await i18n.changeLanguage("en");
  cleanup();
});


describe("Phase D3 · LanguageSelector", () => {
  it("renders 3 options — English, Español, Français", () => {
    render(<LanguageSelector />);
    fireEvent.click(screen.getByTestId("language-selector-trigger"));
    // Menu is open.
    expect(screen.getByTestId("language-selector-menu")).toBeInTheDocument();
    for (const code of ["en", "es", "fr"]) {
      expect(
        screen.getByTestId(`language-selector-option-${code}`),
      ).toBeInTheDocument();
    }
    // Native-name labels.
    const menu = screen.getByTestId("language-selector-menu");
    expect(menu.textContent).toContain("English");
    expect(menu.textContent).toContain("Español");
    expect(menu.textContent).toContain("Français");
  });

  it("picking 'es' writes localStorage + fires PATCH /users/me", async () => {
    render(<LanguageSelector />);
    fireEvent.click(screen.getByTestId("language-selector-trigger"));
    fireEvent.click(screen.getByTestId("language-selector-option-es"));
    await waitFor(() => {
      expect(localStorage.getItem("lang")).toBe("es");
    });
    // i18next flipped.
    expect(i18n.language.slice(0, 2)).toBe("es");
    // Server-side persistence fired.
    expect(patchMock).toHaveBeenCalledWith(
      "/users/me", { locale: "es" },
    );
  });

  it("picking 'fr' updates i18n + PATCH, closes the menu", async () => {
    render(<LanguageSelector />);
    fireEvent.click(screen.getByTestId("language-selector-trigger"));
    fireEvent.click(screen.getByTestId("language-selector-option-fr"));
    await waitFor(() => {
      expect(localStorage.getItem("lang")).toBe("fr");
    });
    expect(i18n.language.slice(0, 2)).toBe("fr");
    // Menu re-closes after pick.
    expect(screen.queryByTestId("language-selector-menu"))
      .not.toBeInTheDocument();
    expect(patchMock).toHaveBeenCalledWith(
      "/users/me", { locale: "fr" },
    );
  });

  it("PATCH failure is swallowed — selection still applies locally", async () => {
    patchMock.mockRejectedValueOnce(new Error("network offline"));
    render(<LanguageSelector />);
    fireEvent.click(screen.getByTestId("language-selector-trigger"));
    fireEvent.click(screen.getByTestId("language-selector-option-es"));
    await waitFor(() => expect(localStorage.getItem("lang")).toBe("es"));
    expect(i18n.language.slice(0, 2)).toBe("es");
  });

  it("clicking the current language is a no-op", async () => {
    render(<LanguageSelector />);
    fireEvent.click(screen.getByTestId("language-selector-trigger"));
    fireEvent.click(screen.getByTestId("language-selector-option-en"));
    // No PATCH — current lang already ``en``.
    expect(patchMock).not.toHaveBeenCalled();
  });
});
