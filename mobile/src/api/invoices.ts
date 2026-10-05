import { api } from "@/src/api";

export type InvoiceFull = {
  company: { name: string; address?: string; phone?: string; website?: string };
  bill_to: { name: string; address?: string };
  property_address?: string;
  header: {
    invoice_number: string;
    invoice_date: string;
    credit_available?: number;
    outstanding_balance?: number;
  };
  line_items: {
    description: string;
    cost_rate?: number;
    qty_hr?: number;
    percent?: number;
    total?: number;
    is_late_fee?: boolean;
  }[];
  totals: {
    subtotal: number;
    this_invoice: number;
    amount_paid: number;
    total_due: number;
    paid_method?: string;
  };
  notes: string;
  is_due_on_receipt?: boolean;
  payment_status?: string;
  // PDFI-PAID-D — paid-state fields. ``paid_at`` comes from the raw
  // invoice document when the backend serialises it; ``paid_method``
  // lives on ``totals`` but is also surfaced top-level for convenience.
  paid_at?: string;
  is_paid?: boolean;
  paid_method?: string;
};

export const getInvoiceFull = (iid: string): Promise<InvoiceFull> =>
  api.get(`/invoices/${iid}/full`);

export const getInvoiceMagic = (iid: string, token: string): Promise<InvoiceFull> =>
  api.get(`/invoices/${iid}/full-magic?token=${encodeURIComponent(token)}`);
