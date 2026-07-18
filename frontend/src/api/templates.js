/**
 * Phase 2 · Templates Library — web API client.
 *
 * Thin wrappers over the backend routes shipped in Phase 1
 * (`/app/backend/routers/templates_library.py`). Reuses the shared
 * `api` fetch wrapper for auth + tenant header handling. PDF export
 * bypasses `api` because the response body is a binary blob.
 */
import { api, api_base, TOKEN_KEY } from "@/api";

export const TEMPLATE_CATEGORIES = [
  { key: "all", label: "All" },
  { key: "pricing_money", label: "Pricing & Money" },
  { key: "operations_checklists", label: "Operations & Checklists" },
  { key: "chemicals_chemistry", label: "Chemicals & Chemistry" },
  { key: "documents", label: "Documents" },
];

export const CATEGORY_LABEL = TEMPLATE_CATEGORIES.reduce((acc, c) => {
  acc[c.key] = c.label;
  return acc;
}, {});

/** List all template definitions visible to this user (optionally category). */
export function listDefinitions(category) {
  const qs = category && category !== "all" ? `?category=${encodeURIComponent(category)}` : "";
  return api.get(`/templates/definitions${qs}`);
}

/** Fetch a single template definition by code. */
export function getDefinition(code) {
  return api.get(`/templates/definitions/${encodeURIComponent(code)}`);
}

/** List instances (drafts + finalized) for this tenant. */
export function listInstances({ mine = false, status = null, template_code = null } = {}) {
  const p = new URLSearchParams();
  if (mine) p.set("mine", "true");
  if (status) p.set("status", status);
  if (template_code) p.set("template_code", template_code);
  const qs = p.toString();
  return api.get(`/templates/instances${qs ? `?${qs}` : ""}`);
}

export function getInstance(iid) {
  return api.get(`/templates/instances/${iid}`);
}

export function createInstance({ template_code, title, values }) {
  return api.post("/templates/instances", { template_code, title, values: values || {} });
}

export function updateInstance(iid, patch) {
  return api.patch(`/templates/instances/${iid}`, patch);
}

export function finalizeInstance(iid) {
  return api.post(`/templates/instances/${iid}/finalize`);
}

export function duplicateInstance(iid) {
  return api.post(`/templates/instances/${iid}/duplicate`);
}

export function deleteInstance(iid) {
  return api.del(`/templates/instances/${iid}`);
}

/**
 * Generate + download a PDF of the finalized (or draft) instance.
 * `filename` will be sanitized to a safe download name.
 */
export async function generatePdf(iid, filename = "template.pdf") {
  const token = localStorage.getItem(TOKEN_KEY) || "";
  const tenantSlug = localStorage.getItem("tenant_slug") || "";
  const res = await fetch(`${api_base()}/templates/instances/${iid}/pdf`, {
    method: "POST",
    headers: {
      Authorization: token ? `Bearer ${token}` : "",
      ...(tenantSlug ? { "X-Tenant-Slug": tenantSlug } : {}),
    },
  });
  if (!res.ok) {
    let msg = "";
    try { msg = (await res.json())?.detail || ""; } catch { /* noop */ }
    throw new Error(msg || `PDF request failed (${res.status})`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = sanitizeFilename(filename);
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function sanitizeFilename(name) {
  const cleaned = String(name || "template").replace(/[^\w\-. ]+/g, "_").trim();
  return cleaned.toLowerCase().endsWith(".pdf") ? cleaned : `${cleaned}.pdf`;
}
