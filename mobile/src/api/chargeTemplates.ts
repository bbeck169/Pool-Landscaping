/**
 * Charge Templates API helpers — mirrors web ApplyChargeTemplateButton.jsx.
 * Phase H8 · F2 parity.
 */
import { api } from "@/src/api";

export type ChargeTemplate = {
  id: string;
  name: string;
  category?: string;
  line_items?: { id?: string; name?: string; description?: string }[];
  is_active?: boolean;
};

/** Fetch all active charge templates for the tenant. */
export const getChargeTemplates = () =>
  api.get("/charge-templates") as Promise<{ templates: ChargeTemplate[] }>;

/**
 * Apply a charge template to a job — appends template line items.
 * Returns { added_count, ... }.
 */
export const applyChargeTemplate = (templateId: string, jobId: string) =>
  api.post(`/charge-templates/${templateId}/apply-to-job/${jobId}`) as Promise<{
    added_count?: number;
  }>;
