/**
 * Subscription API helpers — wrappers for /api/subscriptions/*.
 */
import { api } from "@/src/api";

export type SubRow = {
  stripe_subscription_id: string;
  price_id: string;
  formatted_plan_label?: string;
  status: string;
  quantity: number;
  current_period_end?: string;
  cancel_at_period_end?: boolean;
};

export type SubPrice = {
  id: string;
  nickname?: string;
  product_name?: string;
  unit_amount?: number;
  currency?: string;
  recurring?: { interval?: string };
  formatted_plan_label?: string;
};

export const listSubscriptions = (customerId: string): Promise<any> =>
  api.get(`/subscriptions?customer_id=${customerId}`);

export const listPrices = (): Promise<any> =>
  api.get("/subscriptions/prices");

export const createSubscription = (body: {
  customer_id: string;
  price_id: string;
  quantity?: number;
  payment_method_id?: string | null;
  trial_days?: number;
}): Promise<any> => api.post("/subscriptions", body);

export const updateSubscription = (
  subId: string,
  body: { quantity?: number; cancel_at_period_end?: boolean },
): Promise<any> => api.patch(`/subscriptions/${subId}`, body);

export const cancelSubscription = (
  subId: string,
  mode: "at_period_end" | "immediate",
): Promise<any> => api.delete(`/subscriptions/${subId}?mode=${mode}`);
