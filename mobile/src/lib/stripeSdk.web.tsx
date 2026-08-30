/**
 * stripeSdk.web.tsx — Web stubs for @stripe/stripe-react-native.
 *
 * The native SDK cannot be imported on web. This file provides
 * no-op stubs so the payment-methods screen renders on web preview
 * with graceful "native build required" alerts.
 */
import React from "react";

const NoopProvider = ({ children }: { children: React.ReactNode }) => <>{children}</>;

const noopSheet = async () => ({
  error: {
    code: "UnsupportedPlatform",
    message: "PaymentSheet requires a native build (not available on web preview).",
  },
});

export const StripeProvider: React.ComponentType<any> = NoopProvider;
export const initPaymentSheet = noopSheet;
export const presentPaymentSheet = noopSheet;
