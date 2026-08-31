/**
 * Line-Items API helpers — mirrors web LineItemsSection.jsx endpoints.
 * K2 + F7 endpoints for job line-item CRUD + pricebook items + categories.
 */
import { api } from "@/src/api";

/* ═══════════ Types ═══════════ */

export type LineItem = {
  id: string;
  name?: string;
  description?: string;
  quantity: number;
  unit_price?: number;
  subtotal?: number;
  category?: string;
  pricebook_item_id?: string;
  pricebook_writeback_flag?: boolean;
  custom_price_override_flag?: boolean;
  notes?: string;
};

export type JobTotals = {
  subtotal?: number;
  tax?: number;
  total?: number;
};

export type PricebookItem = {
  id: string;
  name: string;
  description?: string;
  unit_price?: number;
  category?: string;
  unit?: string;
};

/* ═══════════ Line Item CRUD ═══════════ */

export const getLineItems = (jobId: string) =>
  api.get(`/jobs/${jobId}/line-items`) as Promise<{
    line_items: LineItem[];
    job_totals: JobTotals | null;
  }>;

export const addLineItem = (
  jobId: string,
  body: {
    pricebook_item_id?: string;
    description?: string;
    quantity?: number;
    unit_price?: number;
    category?: string;
    pricebook_writeback?: boolean;
  },
) => api.post(`/jobs/${jobId}/line-items`, body);

export const updateLineItem = (
  jobId: string,
  liId: string,
  body: {
    quantity?: number;
    unit_price?: number;
    category?: string;
    pricebook_writeback?: boolean;
  },
) => api.patch(`/jobs/${jobId}/line-items/${liId}`, body);

export const deleteLineItem = (jobId: string, liId: string) =>
  api.del(`/jobs/${jobId}/line-items/${liId}`);

/* ═══════════ Pricebook ═══════════ */

export const getPricebookItems = (q?: string) =>
  api.get(
    `/pricebook-items${q ? `?q=${encodeURIComponent(q)}` : ""}`,
  ) as Promise<{ items: PricebookItem[] }>;

export const getCategories = async (): Promise<{ id: string; name: string }[]> => {
  try {
    const res: any = await api.get("/pricebook/categories?active=true");
    return Array.isArray(res) ? res : res?.categories || res?.items || [];
  } catch {
    return [];
  }
};

/* ═══════════ Error parser ═══════════ */

export function parseLineItemError(e: any): {
  error_code?: string;
  attempted_category?: string;
  available_categories?: string[];
  line_index?: number;
} | null {
  const raw = e?.body || e?.detail || e?.message || "";
  if (typeof raw === "object" && raw.error_code) return raw;
  if (typeof raw === "string") {
    try {
      const j = JSON.parse(raw);
      if (j?.detail?.error_code) return j.detail;
      if (j?.error_code) return j;
    } catch {
      /* not JSON */
    }
  }
  return null;
}
