/**
 * Stripe API helpers — thin wrappers over the backend's
 * `/api/payments/stripe/*` surface.
 */
import { api } from "@/src/api";

/* ── Types ──────────────────────────────────────────── */

export type StripeConfig = {
  publishable_key: string;
  mode: "test" | "live";
};

export type SetupIntentResult = {
  client_secret: string;
  setup_intent_id: string;
};

export type PaymentMethodRow = {
  id: string;
  provider_payment_method_id: string;
  type: "card" | "us_bank_account";
  brand?: string;
  bank_name?: string;
  last4: string;
  exp_month?: number;
  exp_year?: number;
  verification_status?: string;
  is_default: boolean;
};

/* ── Endpoints ──────────────────────────────────────── */

export const getStripeConfig = (): Promise<StripeConfig> =>
  api.get("/payments/stripe/config");

export const createSetupIntent = (
  customerId: string,
  paymentMethodTypes?: string[],
): Promise<SetupIntentResult> =>
  api.post("/payments/stripe/setup-intent", {
    customer_id: customerId,
    ...(paymentMethodTypes ? { payment_method_types: paymentMethodTypes } : {}),
  });

export const attachPaymentMethod = (
  customerId: string,
  paymentMethodId: string,
  setDefault?: boolean,
): Promise<any> =>
  api.post("/payments/stripe/attach", {
    customer_id: customerId,
    payment_method_id: paymentMethodId,
    ...(setDefault !== undefined ? { set_default: setDefault } : {}),
  });

export const listPaymentMethods = (
  customerId: string,
): Promise<PaymentMethodRow[]> =>
  api.get(`/payments/stripe/payment-methods/${customerId}`);

export const removePaymentMethod = (
  paymentMethodId: string,
): Promise<any> =>
  api.delete(`/payments/stripe/payment-methods/${paymentMethodId}`);
