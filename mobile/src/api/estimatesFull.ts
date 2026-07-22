import { api } from "@/src/api";

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
  line_items: {
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
  }[];
  totals: {
    subtotal: number;
    taxes: number;
    amount_paid: number;
    total_estimated_cost: number;
    estimated_profit?: number;
    total_b_hrs?: number;
    total_b_hrs_revenue?: number;
  };
  notes?: string;
};

export const getEstimateFull = (eid: string): Promise<EstimateFull> =>
  api.get(`/estimates/${eid}/full`);

export const acceptEstimate = (eid: string) =>
  api.post(`/estimates/${eid}/accept`, {});

export const declineEstimate = (eid: string, reason?: string) =>
  api.post(`/estimates/${eid}/decline`, { reason: reason || "" });

export const requestEstimateChanges = (eid: string, message: string) =>
  api.post(`/estimates/${eid}/request-changes`, { message });
