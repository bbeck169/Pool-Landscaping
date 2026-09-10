import { api } from "@/src/api";

export type EstimateLineItem = {
  description: string;
  cost_rate?: number;
  qty_hr?: number;
  quantity?: number;
  visits?: number;
  total?: number;
  calc?: string;
  m_rate?: number;
  bh?: number;
  t_bh?: number;
  t_b_cost?: number;
  margin_pct?: number;
  customer_status?: string;
  decline_reason?: string;
};

export type EstimateFull = {
  company: { name: string; address?: string; phone?: string; website?: string };
  bill_to: { name: string; address?: string };
  property_address?: string;
  header: {
    customer_number?: string;
    estimate_number: string;
    estimate_date: string;
    expiration_date?: string;
  };
  title?: string;
  status?: string;
  decision?: string;
  accepted_at?: string;
  declined_at?: string;
  sent_at?: string;
  sent_via?: string;
  as_customer?: boolean;
  line_items: EstimateLineItem[];
  totals: {
    subtotal: number;
    taxes: number;
    amount_paid: number;
    total_estimated_cost: number;
    estimated_profit?: number;
    total_b_hrs?: number;
    total_b_hrs_revenue?: number;
    has_declined_lines?: boolean;
    declined_line_count?: number;
    original_total?: number;
    adjusted_total?: number;
    original_subtotal?: number;
    adjusted_subtotal?: number;
  };
  notes?: string;
  /** Task 6 — Terms & Conditions text (from doc or tenant fallback). */
  terms_and_conditions?: string;
};

export const getEstimateFull = (eid: string): Promise<EstimateFull> =>
  api.get(`/quotes/${eid}/full`);

export const acceptEstimate = (eid: string) =>
  api.post(`/quotes/${eid}/accept`, {});

export const declineEstimate = (eid: string, reason?: string) =>
  api.post(`/quotes/${eid}/decline`, { reason: reason || "" });

export const requestEstimateChanges = (eid: string, message: string) =>
  api.post(`/quotes/${eid}/request-changes`, { message });

export const fetchMagicLinkToken = async (eid: string): Promise<string | null> => {
  try {
    const res = await api.get(`/quotes/${eid}/magic-link`);
    return res?.token || null;
  } catch {
    return null;
  }
};

export const declineLineItem = (token: string, index: number, reason?: string) =>
  api.post(`/portal/quotes/via-token/${encodeURIComponent(token)}/line-items/${index}/decline`, { reason: reason || "" });

export const undeclineLineItem = (token: string, index: number) =>
  api.post(`/portal/quotes/via-token/${encodeURIComponent(token)}/line-items/${index}/undecline`, {});

export const approveViaToken = (token: string) =>
  api.post(`/portal/quotes/via-token/${encodeURIComponent(token)}/approve`, {});

export const declineViaToken = (token: string, reason?: string) =>
  api.post(`/portal/quotes/via-token/${encodeURIComponent(token)}/decline`, { reason: reason || "" });
