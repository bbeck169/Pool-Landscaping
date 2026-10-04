/**
 * PDFI-VB · Feb-2026 — Thin client wrapper over the customers
 * router. Only exports what the PDF-import new-customer modal
 * needs so the surface stays small; richer CRM flows continue
 * to call ``api.post("/customers", …)`` directly from
 * ``CustomerForm.jsx``.
 */
import { api } from "@/api";

export async function createCustomer(payload) {
  return api.post("/customers", payload);
}

export default { createCustomer };
