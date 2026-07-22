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
  };
  notes: string;
  is_due_on_receipt?: boolean;
  payment_status?: string;
};

export const getInvoiceFull = (iid: string): Promise<InvoiceFull> =>
  api.get(`/invoices/${iid}/full`);

export const getInvoiceMagic = (iid: string, token: string): Promise<InvoiceFull> =>
  api.get(`/invoices/${iid}/full-magic?token=${encodeURIComponent(token)}`);
