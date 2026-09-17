/**
 * SP3-hotfix · Feb-2026 — BusinessSignup MUST render without crashing
 * when ``REACT_APP_STRIPE_PUBLISHABLE_KEY`` is unset (preview pod).
 *
 * Regression guard for the P0 tester repro:
 *   "Could not find Elements context; You need to wrap the part of
 *    your app that calls useStripe() in an <Elements> provider."
 *
 * Root cause the fix addresses:
 *   The previous SP3 revision called ``useStripe()`` at the top of
 *   ``SignupFormInner``. When ``stripePromise`` was null the outer
 *   component returned ``<SignupFormInner />`` WITHOUT an <Elements>
 *   provider, so the hook threw and the whole page went blank.
 *
 * This test simulates the preview-pod env (no publishable key set)
 * and asserts:
 *   • The page renders — form, all fields, submit button visible.
 *   • No React error boundary / thrown-error surfaces.
 *   • Submit dispatches with the placeholder ``pm_pending_frontend_ship``
 *     token (not a real Stripe payment method id).
 */
import React from "react";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import "@testing-library/jest-dom";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import commonEN from "../i18n/locales/en/common.json";

// ── Preview-pod env: NO publishable key ───────────────────────────
const _origEnv = process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY;
beforeEach(async () => {
  delete process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY;
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
  process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY = _origEnv;
});

// loadStripe MUST NOT be invoked in this branch — assert that later.
const loadStripeMock = vi.fn(() => Promise.resolve(null));
vi.mock("@stripe/stripe-js", () => ({
  loadStripe: (...a) => loadStripeMock(...a),
}));

// Real <Elements> from @stripe/react-stripe-js is stubbed to a
// transparent wrapper so we don't need a network round-trip. The
// hooks stubbed here would throw in the OLD implementation because
// the outer component wouldn't wrap in <Elements> at all. In the
// NEW implementation the wrapper is always present, so hooks
// resolve fine when SignupCardField mounts — and SignupCardField
// itself is only rendered when stripeKeyLoaded is true (i.e. never
// in this test).
vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }) => <div data-testid="mock-elements-wrap">{children}</div>,
  useStripe: () => null,
  useElements: () => null,
  CardElement: () => <div data-testid="mock-card-el" />,
}));

vi.mock("@/api", () => ({
  api_base: () => "http://localhost/api",
}));
vi.mock("@/components/settings/TimezoneSelect", () => ({
  TimezoneSelect: ({ value, testid }) => (
    <input data-testid={testid || "tz-select"} value={value} readOnly />
  ),
}));

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
    target: { value: "Preview Pod LLC" },
  });
  fireEvent.change(screen.getByTestId("signup-admin-name"), {
    target: { value: "Preview Admin" },
  });
  fireEvent.change(screen.getByTestId("signup-admin-email"), {
    target: { value: "preview@test.example" },
  });
  fireEvent.change(screen.getByTestId("signup-admin-password"), {
    target: { value: "correcthorse42battery" },
  });
  fireEvent.change(screen.getByTestId("signup-admin-phone"), {
    target: { value: "+15551234567" },
  });
}


describe("BusinessSignup · no-publishable-key sandbox fallback (SP3-hotfix)", () => {
  it("renders the full form when REACT_APP_STRIPE_PUBLISHABLE_KEY is unset (no useStripe crash)", () => {
    // If the OLD code path fired, this render call would throw
    // "Could not find Elements context" and the assertion below
    // would never execute. Rendering + all-testids-present == fix.
    _renderSignup();
    expect(screen.getByTestId("business-signup-page")).toBeInTheDocument();
    expect(screen.getByTestId("signup-business-name")).toBeInTheDocument();
    expect(screen.getByTestId("signup-admin-name")).toBeInTheDocument();
    expect(screen.getByTestId("signup-admin-email")).toBeInTheDocument();
    expect(screen.getByTestId("signup-admin-password")).toBeInTheDocument();
    expect(screen.getByTestId("signup-admin-phone")).toBeInTheDocument();
    expect(screen.getByTestId("signup-primary-industry")).toBeInTheDocument();
    expect(screen.getByTestId("signup-country")).toBeInTheDocument();
    expect(screen.getByTestId("signup-submit")).toBeInTheDocument();
    // Placeholder card widget renders (not the real CardElement).
    expect(screen.getByTestId("signup-card-placeholder")).toBeInTheDocument();
    expect(screen.queryByTestId("signup-card-element-wrap")).not.toBeInTheDocument();
    // ``loadStripe`` was never invoked in the no-key branch.
    expect(loadStripeMock).not.toHaveBeenCalled();
    // Belt-and-suspenders: the <Elements> wrapper IS present even
    // in the no-key branch (so the child hook path is always safe).
    expect(screen.getByTestId("mock-elements-wrap")).toBeInTheDocument();
  });

  it("submit dispatches with the placeholder token when no Stripe key is configured", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        tenant_id: "t1",
        email_verification_sent_to: "preview@test.example",
      }),
    });
    _renderSignup();
    _fillValidForm();
    await act(async () => {
      fireEvent.click(screen.getByTestId("signup-submit"));
    });
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/signup$/);
    const bodyObj = JSON.parse(String(opts?.body || "{}"));
    // Placeholder token — NOT a real ``pm_test_…`` id — proves the
    // Stripe path was skipped without crashing.
    expect(bodyObj.stripe_payment_method_id).toBe("pm_pending_frontend_ship");
    // The rest of the payload survived the no-key branch intact.
    expect(bodyObj.primary_industry).toBe("pool");
    expect(bodyObj.business_name).toBe("Preview Pod LLC");
    expect(bodyObj.admin_email).toBe("preview@test.example");
    fetchSpy.mockRestore();
  });
});
