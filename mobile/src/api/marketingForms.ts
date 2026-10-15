/**
 * Marketing Forms (Form Builder) — READ-ONLY mobile client.
 * Mirrors the web GETs; no create / patch / delete / revert from mobile
 * (edit-on-mobile deferred — TD-48). Backend gate: `require_admin`.
 */
import { api } from "@/src/api";

export type MarketingForm = {
  id: string; name: string; slug?: string; active?: boolean; fields?: any[];
  submission_count?: number; version?: number; created_at?: string; updated_at?: string;
  submit_button_label?: string; success_message?: string; notify_admin_bell?: boolean;
  submit_config?: Record<string, any>; theme?: Record<string, any>; hero?: Record<string, any>;
};
export type FormVersion = { id: string; version: number; action?: string; at?: string; actor_id?: string; name?: string; fields?: any[] };
export type FormSubmission = {
  id: string; form_id: string; form_name?: string; form_slug?: string; created_at?: string;
  answers?: Record<string, any>; data?: Record<string, any>; ip?: string; user_agent?: string;
  page_url?: string; submission_kind?: string; lead_id?: string; customer_id?: string;
  file_uploads?: any[]; delivery_id?: string;
};

export const listForms = async (): Promise<MarketingForm[]> => {
  const r: any = await api.get("/admin/forms");
  return Array.isArray(r) ? r : [];
};
export const getForm = async (fid: string): Promise<MarketingForm> =>
  (await api.get(`/admin/forms/${encodeURIComponent(fid)}`)) as MarketingForm;
export const listFormVersions = async (fid: string): Promise<FormVersion[]> => {
  const r: any = await api.get(`/admin/forms/${encodeURIComponent(fid)}/versions`);
  const rows: FormVersion[] = Array.isArray(r?.versions) ? r.versions : [];
  return [...rows].sort((a, b) => (b.version || 0) - (a.version || 0));
};
export const listFormSubmissions = async (fid: string, limit = 100): Promise<FormSubmission[]> => {
  const r: any = await api.get(`/admin/forms/${encodeURIComponent(fid)}/submissions?limit=${limit}`);
  return Array.isArray(r) ? r : [];
};
