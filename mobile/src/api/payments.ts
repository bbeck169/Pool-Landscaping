import { api } from "@/src/api";

export type PublicConfig = {
  stripe_publishable_key: string;
  stripe_mode: string;
  app_public_url?: string;
};

export type PaymentIntentResult = {
  client_secret: string;
  amount_cents: number;
  currency: string;
};

export const getPublicConfig = (): Promise<PublicConfig> =>
  api.get("/config/public");

export const createPaymentIntent = (
  invoiceId: string,
  source: "authenticated" | "portal",
  magicToken?: string,
  promoCodeId?: string,
): Promise<PaymentIntentResult> =>
  api.post("/payments/create-payment-intent", {
    invoice_id: invoiceId,
    source,
    ...(magicToken ? { magic_token: magicToken } : {}),
    ...(promoCodeId ? { promo_code_id: promoCodeId } : {}),
  });

export const getPaymentStatus = (paymentIntentId: string) =>
  api.get(`/payments/${paymentIntentId}`);
