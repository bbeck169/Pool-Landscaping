/**
 * Communications API client — Phase 4 · Mobile Parity.
 *
 * Thin wrapper over the FastAPI /api/comms/* endpoints. Uses the shared
 * `api` helper so bearer-token injection stays uniform.
 */
import { api } from "@/src/api";

// ─── Email templates ──────────────────────────────────────────────────
export const listEmailTemplates = () => api.get("/comms/email-templates");
export const getEmailTemplate = (code: string) =>
  api.get(`/comms/email-templates/${encodeURIComponent(code)}`);
export const previewEmailTemplate = (code: string, customerId?: string) =>
  api.post(
    `/comms/email-templates/${encodeURIComponent(code)}/preview`,
    customerId ? { customer_id: customerId } : {}
  );

// ─── SMS templates ────────────────────────────────────────────────────
export const listSmsTemplates = () => api.get("/comms/sms-templates");
export const getSmsTemplate = (code: string) =>
  api.get(`/comms/sms-templates/${encodeURIComponent(code)}`);
export const previewSmsTemplate = (code: string, customerId?: string) =>
  api.post(
    `/comms/sms-templates/${encodeURIComponent(code)}/preview`,
    customerId ? { customer_id: customerId } : {}
  );

// ─── Automations ──────────────────────────────────────────────────────
export const listAutomations = () => api.get("/comms/automations");
export const getAutomation = (code: string) =>
  api.get(`/comms/automations/${encodeURIComponent(code)}`);
export const toggleAutomation = (code: string, active: boolean) =>
  api.patch(`/comms/automations/${encodeURIComponent(code)}`, { active });
export const testFireAutomation = (code: string, recipientId: string) =>
  api.post(`/comms/automations/${encodeURIComponent(code)}/test-fire`, {
    recipient_id: recipientId,
  });

// ─── Sends & tokens ──────────────────────────────────────────────────
export const sendNow = (body: {
  channel: string;
  template_code: string;
  recipient_id: string;
}) => api.post("/comms/send-now", body);

export const listSends = (params: Record<string, string | undefined> = {}) => {
  const qs = new URLSearchParams(
    Object.entries(params).filter(
      ([, v]) => v !== undefined && v !== "" && v !== null
    ) as [string, string][]
  ).toString();
  return api.get(`/comms/sends${qs ? `?${qs}` : ""}`);
};

export const getSend = (id: string) =>
  api.get(`/comms/sends/${encodeURIComponent(id)}`);

// ─── Automation-engine journal (Phase 3 endpoint) ────────────────────
export const listAutomationEvents = (
  params: Record<string, string | undefined> = {}
) => {
  const qs = new URLSearchParams(
    Object.entries(params).filter(
      ([, v]) => v !== undefined && v !== "" && v !== null
    ) as [string, string][]
  ).toString();
  return api.get(`/comms/automation-events${qs ? `?${qs}` : ""}`);
};

// ─── Token catalog (mirrors backend) ─────────────────────────────────
export const getTokensCatalog = () => api.get("/comms/tokens");

// ─── Trigger event catalog (mirrors backend) ─────────────────────────
export const TRIGGER_EVENTS = [
  "job.scheduled",
  "job.completed",
  "job.cancelled",
  "invoice.created",
  "invoice.paid",
  "invoice.overdue",
  "customer.created",
  "customer.deactivated",
  "estimate.sent",
  "estimate.accepted",
  "review.requested",
  "review.received",
  "manual.send",
];
