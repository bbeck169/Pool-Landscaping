/**
 * QuoteIQ Q1-UI · Mobile API — AI Credits + Deals.
 *
 * Thin wrappers around the same FastAPI endpoints the web app talks to.
 * Uses the shared ``api`` helper so bearer-token injection is uniform.
 */
import { api } from "@/src/api";

// ─── AI Credits ───────────────────────────────────────────────────────
export const getCreditsBalance = () => api.get("/ai-credits/balance");
export const listCreditTransactions = (opts: {
  limit?: number;
  cursor?: string;
  feature?: string;
} = {}) => {
  const qs = new URLSearchParams();
  qs.set("limit", String(opts.limit ?? 20));
  if (opts.cursor) qs.set("cursor", opts.cursor);
  if (opts.feature) qs.set("feature", opts.feature);
  return api.get(`/ai-credits/transactions?${qs.toString()}`);
};

// ─── Deals + pipelines ────────────────────────────────────────────────
export const listPipelines = () => api.get("/deal-pipelines");
export const listDeals = (opts: {
  pipeline_id?: string;
  stage_id?: string;
  owner_user_id?: string;
  customer_id?: string;
  status?: string;
  q?: string;
  limit?: number;
} = {}) => {
  const qs = new URLSearchParams();
  Object.entries(opts).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  });
  return api.get(`/deals?${qs.toString()}`);
};
export const getDeal = (id: string) => api.get(`/deals/${id}`);
export const getDealEvents = (id: string) => api.get(`/deals/${id}/events`);
export const createDeal = (body: any) => api.post("/deals", body);
export const patchDeal = (id: string, body: any) =>
  api.patch(`/deals/${id}`, body);
export const moveDeal = (id: string, stage_id: string, note?: string) =>
  api.post(`/deals/${id}/move`, { stage_id, note: note || "" });
export const wonDeal = (id: string) => api.post(`/deals/${id}/won`);
export const lostDeal = (id: string, lost_reason?: string) =>
  api.post(`/deals/${id}/lost`, { lost_reason: lost_reason || "" });
export const convertDeal = (id: string) =>
  api.post(`/deals/${id}/convert-to-job`);

// ─── Chemical Products (read-only for techs) ──────────────────────────
export const listChemicalProducts = (activeOnly = true) => {
  const qs = new URLSearchParams();
  if (activeOnly) qs.set("active", "true");
  return api.get(`/chemical-products?${qs.toString()}`);
};
