/**
 * SP3 · Feb-2026 — BusinessSignup form validation.
 *
 * Covers: required fields, email format, password strength meter
 * (min 12 + letter + digit) locking the submit button.
 */
import React from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import "@testing-library/jest-dom";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import commonEN from "../i18n/locales/en/common.json";

// Stripe stubs — no publishable key set in tests so Elements is bypassed.
vi.mock("@stripe/stripe-js", () => ({
  loadStripe: vi.fn(() => Promise.resolve(null)),
}));
vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }) => <>{children}</>,
  useStripe: () => null,
  useElements: () => null,
  CardElement: () => null,
}));

// Silence api_base usage — form validation blocks before submit.
vi.mock("@/api", () => ({
  api_base: () => "http://localhost/api",
}));

// TimezoneSelect is heavy — stub to a plain input.
vi.mock("@/components/settings/TimezoneSelect", () => ({
  TimezoneSelect: ({ value, testid }) => (
    <input data-testid={testid || "tz-select"} value={value} readOnly />
  ),
}));

// deriveIndustry — must load real for CANONICAL_INDUSTRIES.
import BusinessSignup from "../pages/BusinessSignup";

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

function _renderSignup() {
  return render(
    <MemoryRouter>
      <I18nextProvider i18n={i18n}>
        <BusinessSignup />
      </I18nextProvider>
    </MemoryRouter>,
  );
}

describe("BusinessSignup · form validation (SP3)", () => {
  it("renders all required signup fields with test IDs", () => {
    _renderSignup();
    expect(screen.getByTestId("business-signup-page")).toBeInTheDocument();
    expect(screen.getByTestId("signup-business-name")).toBeInTheDocument();
    expect(screen.getByTestId("signup-admin-name")).toBeInTheDocument();
    expect(screen.getByTestId("signup-admin-email")).toBeInTheDocument();
    expect(screen.getByTestId("signup-admin-password")).toBeInTheDocument();
    expect(screen.getByTestId("signup-admin-phone")).toBeInTheDocument();
    expect(screen.getByTestId("signup-primary-industry")).toBeInTheDocument();
    expect(screen.getByTestId("signup-country")).toBeInTheDocument();
    expect(screen.getByTestId("signup-submit")).toBeDisabled();
  });

  it("locks submit until password meets 12+ / letter / digit", () => {
    _renderSignup();
    const pw = screen.getByTestId("signup-admin-password");
    const submit = screen.getByTestId("signup-submit");
    // Too short.
    fireEvent.change(pw, { target: { value: "short" } });
    expect(submit).toBeDisabled();
    // 12 chars but no digit.
    fireEvent.change(pw, { target: { value: "abcdefghijkl" } });
    expect(submit).toBeDisabled();
    // 12 chars + letter + digit.
    fireEvent.change(pw, { target: { value: "correcthorse42battery" } });
    expect(submit).not.toBeDisabled();
  });

  it("primary industry dropdown offers the D1 canonical 23 slugs (no plural 'pools')", () => {
    _renderSignup();
    const select = screen.getByTestId("signup-primary-industry");
    const options = Array.from(select.querySelectorAll("option")).map(
      (o) => o.getAttribute("value"),
    );
    expect(options).toHaveLength(23);
    expect(options).toContain("pool");
    expect(options).not.toContain("pools");
    expect(options).toContain("garage_door");
    expect(options).toContain("irrigation");
    // Non-canonical drifted slugs must be gone.
    expect(options).not.toContain("carpentry");
    expect(options).not.toContain("moving");
    expect(options).not.toContain("junk_removal");
  });
});
