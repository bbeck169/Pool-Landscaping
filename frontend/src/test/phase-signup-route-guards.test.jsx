/**
 * SP3 · Feb-2026 — Route-guard shape smoke for signup + onboarding pages.
 *
 * Rather than exercise the app-level guard directly (which pulls in
 * ~200 modules), we verify the CONTRACT:
 *   • BusinessSignup exists as the default export of its module.
 *   • BusinessSignupVerify + BusinessSignupVerifyEmailSent are the
 *     verify-landing + inbox-panel components.
 *   • OnboardingWizard exists and calls GET /signup-onboarding/state
 *     on mount (which is the state the guard checks).
 */
import React from "react";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import "@testing-library/jest-dom";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import commonEN from "../i18n/locales/en/common.json";

const apiGetMock = vi.fn(() => Promise.resolve({
  step: 1, completed: false, data: {
    business_name: "", phone: "", address: "",
    timezone: "America/Phoenix", country: "US",
    primary_industry: "pool", active_industries: ["pool"],
  },
}));
vi.mock("@/api", () => ({
  api: { get: (...a) => apiGetMock(...a), patch: vi.fn() },
  api_base: () => "http://localhost/api",
}));
vi.mock("@/components/settings/TimezoneSelect", () => ({
  TimezoneSelect: () => <input data-testid="tz-mock" />,
}));

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

describe("SP3 · route-guard-relevant components exist + call state", () => {
  it("BusinessSignup exports a default function component", async () => {
    const mod = await import("../pages/BusinessSignup");
    expect(typeof mod.default).toBe("function");
  });

  it("BusinessSignupVerify + BusinessSignupVerifyEmailSent both export", async () => {
    const mod = await import("../pages/BusinessSignupVerify");
    expect(typeof mod.BusinessSignupVerify).toBe("function");
    expect(typeof mod.BusinessSignupVerifyEmailSent).toBe("function");
  });

  it("OnboardingWizard hits GET /signup-onboarding/state on mount", async () => {
    const { default: OnboardingWizard } = await import("../pages/OnboardingWizard");
    render(
      <MemoryRouter>
        <I18nextProvider i18n={i18n}>
          <OnboardingWizard />
        </I18nextProvider>
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(apiGetMock).toHaveBeenCalledWith("/signup-onboarding/state");
    });
  });
});
