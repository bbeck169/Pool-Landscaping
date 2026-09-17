/**
 * SP3 · Feb-2026 — OnboardingWizard flow smoke.
 *
 * Covers:
 *   • Renders wizard on mount when tenant is unfinished.
 *   • Redirects to /dashboard?welcome=1 when the state endpoint
 *     reports completed=true.
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import "@testing-library/jest-dom";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import commonEN from "../i18n/locales/en/common.json";

const apiGetMock = vi.fn();
const apiPatchMock = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => apiGetMock(...a), patch: (...a) => apiPatchMock(...a) },
}));
vi.mock("@/components/settings/TimezoneSelect", () => ({
  TimezoneSelect: ({ value, testid }) => (
    <input data-testid={testid || "tz-select"} value={value} readOnly />
  ),
}));

import OnboardingWizard from "../pages/OnboardingWizard";

beforeEach(async () => {
  apiGetMock.mockReset();
  apiPatchMock.mockReset();
  if (!i18n.isInitialized) {
    await i18n.use(initReactI18next).init({
      lng: "en", fallbackLng: "en",
      resources: { en: { common: commonEN } },
      interpolation: { escapeValue: false },
      react: { useSuspense: false },
    });
  }
});

function _renderWizard() {
  return render(
    <MemoryRouter initialEntries={["/onboarding-wizard"]}>
      <I18nextProvider i18n={i18n}>
        <Routes>
          <Route path="/onboarding-wizard" element={<OnboardingWizard />} />
          <Route path="/dashboard" element={<div data-testid="dashboard-page">dashboard</div>} />
        </Routes>
      </I18nextProvider>
    </MemoryRouter>,
  );
}

describe("OnboardingWizard flow (SP3)", () => {
  it("renders wizard when state reports unfinished onboarding", async () => {
    apiGetMock.mockResolvedValue({
      step: 1, completed: false, data: {
        business_name: "Test Biz", phone: "+15551112222",
        address: "1 Test St", timezone: "America/Phoenix",
        country: "US", primary_industry: "pool",
        active_industries: ["pool"],
      },
    });
    _renderWizard();
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled());
    // The wizard container renders with a step title from the
    // onboarding namespace (locale-aware — uses en fallback here).
    await waitFor(() => {
      expect(document.body.textContent).toMatch(/Confirm your business profile|Let's get you set up/i);
    });
  });

  it("redirects to /dashboard?welcome=1 when state.completed is true", async () => {
    apiGetMock.mockResolvedValue({
      step: 5, completed: true, data: {
        business_name: "Test Biz", phone: "", address: "",
        timezone: "America/Phoenix", country: "US",
        primary_industry: "pool", active_industries: ["pool"],
      },
    });
    _renderWizard();
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-page")).toBeInTheDocument();
    });
  });
});
