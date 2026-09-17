/**
 * SP3 · Feb-2026 — BusinessSignupVerify landing page.
 *
 * Covers:
 *   • success token → shows ok state + redirects to /onboarding-wizard
 *   • failure token → shows fail state + surfaces the resend / login CTA
 *   • no token → shows no-token state
 */
import React from "react";
import { render, screen, waitFor, act } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import "@testing-library/jest-dom";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import commonEN from "../i18n/locales/en/common.json";

vi.mock("@/api", () => ({
  api_base: () => "http://localhost/api",
}));

import { BusinessSignupVerify } from "../pages/BusinessSignupVerify";

beforeEach(async () => {
  if (!i18n.isInitialized) {
    await i18n.use(initReactI18next).init({
      lng: "en", fallbackLng: "en",
      resources: { en: { common: commonEN } },
      interpolation: { escapeValue: false },
      react: { useSuspense: false },
    });
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});

function _renderWithToken(token) {
  const url = token ? `/business-signup/verify?token=${token}` : "/business-signup/verify";
  return render(
    <MemoryRouter initialEntries={[url]}>
      <I18nextProvider i18n={i18n}>
        <Routes>
          <Route path="/business-signup/verify" element={<BusinessSignupVerify />} />
          <Route path="/onboarding-wizard" element={<div data-testid="onboarding-wizard-page">wizard</div>} />
        </Routes>
      </I18nextProvider>
    </MemoryRouter>,
  );
}

describe("BusinessSignupVerify (SP3)", () => {
  it("shows no-token state when the URL has no token param", () => {
    _renderWithToken(null);
    expect(screen.getByTestId("verify-no-token")).toBeInTheDocument();
  });

  it("posts the token, shows ok, then redirects to /onboarding-wizard on 200", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true, json: async () => ({ verified: true }),
    });
    _renderWithToken("good-token-abc");
    await waitFor(() => {
      expect(screen.getByTestId("verify-ok")).toBeInTheDocument();
    });
    // Timeout-driven redirect (800ms in component); assert the fetch
    // hit the right URL rather than waiting for the setTimeout.
    expect(global.fetch).toHaveBeenCalledTimes(1);
    const url = String(global.fetch.mock.calls[0][0]);
    expect(url).toMatch(/\/api\/signup\/verify\?token=good-token-abc/);
  });

  it("surfaces the failure copy + login CTA when the token is invalid", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: false,
      json: async () => ({ detail: { message: "token invalid" } }),
    });
    _renderWithToken("bad-token");
    await waitFor(() => {
      expect(screen.getByTestId("verify-fail")).toBeInTheDocument();
    });
    expect(screen.getByTestId("verify-fail-login-link"))
      .toHaveAttribute("href", "/login");
  });
});
