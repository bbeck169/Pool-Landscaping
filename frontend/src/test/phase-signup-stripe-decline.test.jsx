/**
 * SP3 · Feb-2026 — BusinessSignup Stripe decline path.
 *
 * Mocks ``@stripe/react-stripe-js`` so ``useStripe().createPaymentMethod``
 * returns an error. Confirms the error surfaces under the card element
 * and the form does NOT navigate away.
 */
import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import "@testing-library/jest-dom";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import commonEN from "../i18n/locales/en/common.json";

// Force the Elements branch by stubbing loadStripe to return a truthy value.
vi.mock("@stripe/stripe-js", () => ({
  loadStripe: vi.fn(() => Promise.resolve({ __mocked: "stripe" })),
}));

// The card element must return an error on createPaymentMethod.
const createPaymentMethodMock = vi.fn(async () => ({
  error: { message: "Your card was declined." },
  paymentMethod: null,
}));

vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }) => <>{children}</>,
  useStripe: () => ({ createPaymentMethod: createPaymentMethodMock }),
  useElements: () => ({ getElement: () => ({}) }),
  CardElement: () => <div data-testid="card-element-mock" />,
}));

vi.mock("@/api", () => ({
  api_base: () => "http://localhost/api",
}));
vi.mock("@/components/settings/TimezoneSelect", () => ({
  TimezoneSelect: ({ value, testid }) => (
    <input data-testid={testid || "tz-select"} value={value} readOnly />
  ),
}));

// Force publishable key so BusinessSignup renders Elements branch.
const _origEnv = process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY;
beforeEach(async () => {
  process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY = "pk_test_xyz";
  if (!i18n.isInitialized) {
    await i18n.use(initReactI18next).init({
      lng: "en", fallbackLng: "en",
      resources: { en: { common: commonEN } },
      interpolation: { escapeValue: false },
      react: { useSuspense: false },
    });
  }
});

import BusinessSignup from "../pages/BusinessSignup";

function _renderSignup() {
  return render(
    <MemoryRouter>
      <I18nextProvider i18n={i18n}>
        <BusinessSignup />
      </I18nextProvider>
    </MemoryRouter>,
  );
}

function _fillValidForm() {
  fireEvent.change(screen.getByTestId("signup-business-name"), {
    target: { value: "Decline Test LLC" },
  });
  fireEvent.change(screen.getByTestId("signup-admin-name"), {
    target: { value: "Card Declined" },
  });
  fireEvent.change(screen.getByTestId("signup-admin-email"), {
    target: { value: "decline@test.example" },
  });
  fireEvent.change(screen.getByTestId("signup-admin-password"), {
    target: { value: "correcthorse42battery" },
  });
  fireEvent.change(screen.getByTestId("signup-admin-phone"), {
    target: { value: "+15551234567" },
  });
}

describe("BusinessSignup · Stripe decline (SP3)", () => {
  it("surfaces the Stripe decline message under the card element and blocks submit", async () => {
    const fetchSpy = vi.spyOn(global, "fetch");
    _renderSignup();
    _fillValidForm();
    // Card element mock is rendered.
    expect(screen.queryByTestId("signup-card-element-wrap")).toBeInTheDocument();
    // Submit → createPaymentMethod returns error.
    await act(async () => {
      fireEvent.click(screen.getByTestId("signup-submit"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("signup-card-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("signup-card-error").textContent).toMatch(
      /declined/i,
    );
    // ``fetch`` must NOT have been called — we bail before signup POST.
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("submits pm_test_… when Stripe returns a valid payment method", async () => {
    createPaymentMethodMock.mockImplementationOnce(async () => ({
      error: null,
      paymentMethod: { id: "pm_test_ok_123" },
    }));
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        tenant_id: "t1", email_verification_sent_to: "decline@test.example",
      }),
    });
    _renderSignup();
    _fillValidForm();
    await act(async () => {
      fireEvent.click(screen.getByTestId("signup-submit"));
    });
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const [, opts] = fetchSpy.mock.calls[0];
    const bodyStr = opts?.body || "";
    const bodyObj = JSON.parse(String(bodyStr));
    expect(bodyObj.stripe_payment_method_id).toBe("pm_test_ok_123");
    fetchSpy.mockRestore();
  });
});

afterAll(() => {
  process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY = _origEnv;
});
