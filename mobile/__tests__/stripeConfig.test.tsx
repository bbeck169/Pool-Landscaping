/**
 * stripeConfig.test.tsx — Phase K23 · Tests for Stripe-not-configured fallback.
 */
import React from "react";
import { render } from "@testing-library/react-native";

/* ── Mocks ───────────────────────────────────────────── */

jest.mock("@expo/vector-icons", () => ({
  Ionicons: "Ionicons",
}));

jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff",
    surfaceSecondary: "#f5f5f5",
    onSurface: "#111",
    muted: "#888",
    brand: "#2563EB",
    border: "#ddd",
    divider: "#eee",
    error: "#DC2626",
    success: "#16A34A",
    surfaceTertiary: "#eee",
  },
  spacing: { sm: 4, md: 8, lg: 16, xl: 24, "2xl": 32, "3xl": 48 },
  radius: { md: 8, lg: 12 },
  font: {
    regular: "System",
    medium: "System",
    semibold: "System",
    bold: "System",
  },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 16, xl: 18 },
}));

/* ── Import under test ───────────────────────────────── */

import {
  StripeUnconfiguredNotice,
  StripeUnconfiguredBanner,
} from "@/src/lib/stripeConfig";

/* ── Tests ───────────────────────────────────────────── */

describe("StripeUnconfiguredNotice", () => {
  it("renders with default message and testID", () => {
    const { getByTestId, getByText } = render(<StripeUnconfiguredNotice />);
    expect(getByTestId("stripe-unconfigured-notice")).toBeTruthy();
    expect(getByText("Stripe payments not configured")).toBeTruthy();
    expect(
      getByText("Contact support to enable card payments."),
    ).toBeTruthy();
  });

  it("renders custom message", () => {
    const { getByText } = render(
      <StripeUnconfiguredNotice message="Ask your admin to set up Stripe." />,
    );
    expect(getByText("Ask your admin to set up Stripe.")).toBeTruthy();
  });

  it("accepts custom testID", () => {
    const { getByTestId } = render(
      <StripeUnconfiguredNotice testID="custom-notice" />,
    );
    expect(getByTestId("custom-notice")).toBeTruthy();
  });
});

describe("StripeUnconfiguredBanner", () => {
  it("renders with default testID", () => {
    const { getByTestId, getByText } = render(<StripeUnconfiguredBanner />);
    expect(getByTestId("stripe-unconfigured-banner")).toBeTruthy();
    expect(
      getByText("Stripe not configured — card actions unavailable."),
    ).toBeTruthy();
  });

  it("accepts custom testID", () => {
    const { getByTestId } = render(
      <StripeUnconfiguredBanner testID="pm-tiles-stripe-banner" />,
    );
    expect(getByTestId("pm-tiles-stripe-banner")).toBeTruthy();
  });
});

/* ── useStripeConfig context shape ──────────────────── */

jest.mock("@/src/api/payments", () => ({
  getPublicConfig: jest.fn().mockResolvedValue({
    stripe_publishable_key: "",
    stripe_mode: "",
  }),
}));

describe("StripeConfigProvider context shape", () => {
  it("exports useStripeConfig and StripeConfigProvider", () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require("@/src/config/stripe");
    expect(typeof mod.useStripeConfig).toBe("function");
    expect(typeof mod.StripeConfigProvider).toBe("function");
  });
});
