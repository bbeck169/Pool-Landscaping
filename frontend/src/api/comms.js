/**
 * Communications API client — Phase 2 (Feb 2026).
 *
 * Thin wrapper over the FastAPI /api/comms/* endpoints that shipped in
 * Phase 1. Uses the shared ``api`` helper from ``@/api`` so bearer-token
 * injection and REACT_APP_BACKEND_URL routing stay uniform with the
 * rest of the admin surface.
 */
import { api } from "@/api";

// ─── Email templates ──────────────────────────────────────────────────
export const listEmailTemplates = () => api.get("/comms/email-templates");
export const getEmailTemplate = (code) => api.get(`/comms/email-templates/${encodeURIComponent(code)}`);
export const createEmailTemplate = (body) => api.post("/comms/email-templates", body);
export const updateEmailTemplate = (code, body) => api.patch(`/comms/email-templates/${encodeURIComponent(code)}`, body);
export const deleteEmailTemplate = (code) => api.del(`/comms/email-templates/${encodeURIComponent(code)}`);
export const duplicateEmailTemplate = (code) => api.post(`/comms/email-templates/${encodeURIComponent(code)}/duplicate`, {});
export const previewEmailTemplate = (code, customer_id) =>
  api.post(`/comms/email-templates/${encodeURIComponent(code)}/preview`, customer_id ? { customer_id } : {});
export const testSendEmailTemplate = (code, to) =>
  api.post(`/comms/email-templates/${encodeURIComponent(code)}/test-send`,
            to ? { to } : {});

// ─── SMS templates ────────────────────────────────────────────────────
export const listSmsTemplates = () => api.get("/comms/sms-templates");
export const getSmsTemplate = (code) => api.get(`/comms/sms-templates/${encodeURIComponent(code)}`);
export const createSmsTemplate = (body) => api.post("/comms/sms-templates", body);
export const updateSmsTemplate = (code, body) => api.patch(`/comms/sms-templates/${encodeURIComponent(code)}`, body);
export const deleteSmsTemplate = (code) => api.del(`/comms/sms-templates/${encodeURIComponent(code)}`);
export const duplicateSmsTemplate = (code) => api.post(`/comms/sms-templates/${encodeURIComponent(code)}/duplicate`, {});
export const previewSmsTemplate = (code, customer_id) =>
  api.post(`/comms/sms-templates/${encodeURIComponent(code)}/preview`, customer_id ? { customer_id } : {});

// ─── Automations ──────────────────────────────────────────────────────
export const listAutomations = () => api.get("/comms/automations");
export const getAutomation = (code) => api.get(`/comms/automations/${encodeURIComponent(code)}`);
export const createAutomation = (body) => api.post("/comms/automations", body);
export const updateAutomation = (code, body) => api.patch(`/comms/automations/${encodeURIComponent(code)}`, body);
export const deleteAutomation = (code) => api.del(`/comms/automations/${encodeURIComponent(code)}`);
export const testFireAutomation = (code, recipient_id) =>
  api.post(`/comms/automations/${encodeURIComponent(code)}/test-fire`, { recipient_id });

// ─── Sends & tokens ───────────────────────────────────────────────────
export const sendNow = (body) => api.post("/comms/send-now", body);
export const listSends = (params = {}) => {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== "" && v !== null),
  ).toString();
  return api.get(`/comms/sends${qs ? `?${qs}` : ""}`);
};
export const getSend = (id) => api.get(`/comms/sends/${encodeURIComponent(id)}`);
export const getTokensCatalog = () => api.get("/comms/tokens");
export const listOptOuts = () => api.get("/comms/opt-outs");
export const addOptOut = (body) => api.post("/comms/opt-out", body);

// ─── Trigger events (client-side enum mirror of the backend catalog) ─
export const TRIGGER_EVENTS = [
  "job.scheduled", "job.completed", "job.cancelled",
  "invoice.created", "invoice.paid", "invoice.overdue",
  "customer.created", "customer.deactivated",
  "estimate.sent", "estimate.accepted",
  "review.requested", "review.received",
  "manual.send",
];

// SMS segment maths mirrors ``services/comms_sms_adapter.py`` — GSM-7
// caps at 160 for a single segment (then 153 per multi-segment chunk),
// UCS-2 caps at 70 for a single segment (then 67 per multi-segment).
const _GSM7_RE = /^[\u0020-\u007E\r\n\t\u00A3\u00A5\u00E8\u00E9\u00F9\u00EC\u00F2\u00C7\u00D8\u00F8\u00C5\u00E5\u00C4\u00D6\u00D1\u00DC\u00A7\u00BF\u00E4\u00F6\u00F1\u00FC\u00E0]*$/;
export function smsMetrics(body) {
  const text = body || "";
  const chars = text.length;
  const gsm = _GSM7_RE.test(text);
  let segs;
  if (chars === 0) segs = 0;
  else if (gsm) segs = chars <= 160 ? 1 : Math.ceil(chars / 153);
  else segs = chars <= 70 ? 1 : Math.ceil(chars / 67);
  return { chars, encoding: gsm ? "GSM-7" : "UCS-2", segments: segs };
}
