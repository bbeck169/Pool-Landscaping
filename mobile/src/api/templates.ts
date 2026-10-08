/**
 * Templates Library — Phase 3 (Mobile) · API client.
 *
 * Mirrors `frontend/src/api/templates.js` 1:1 (same endpoints, same
 * payloads). Reuses the shared mobile `api` fetch wrapper for auth.
 * PDF export bypasses `api` because the response is a binary stream.
 */
import { Platform } from "react-native";
import * as Sharing from "expo-sharing";
import { File, Paths } from "expo-file-system";
import { fetch as expoFetch } from "expo/fetch";
import { api, api_base, getAuthToken } from "@/src/api";

export const TEMPLATE_CATEGORIES = [
  { key: "all", label: "All" },
  { key: "pricing_money", label: "Pricing & Money" },
  { key: "operations_checklists", label: "Operations & Checklists" },
  { key: "chemicals_chemistry", label: "Chemicals & Chemistry" },
  { key: "documents", label: "Documents" },
];

export const CATEGORY_LABEL: Record<string, string> = TEMPLATE_CATEGORIES.reduce(
  (acc, c) => ({ ...acc, [c.key]: c.label }),
  {} as Record<string, string>,
);

export function listDefinitions(category?: string) {
  const qs = category && category !== "all" ? `?category=${encodeURIComponent(category)}` : "";
  return api.get(`/templates/definitions${qs}`);
}

export function getDefinition(code: string) {
  return api.get(`/templates/definitions/${encodeURIComponent(code)}`);
}

export function listInstances(opts: { mine?: boolean; status?: string; template_code?: string } = {}) {
  const p: string[] = [];
  if (opts.mine) p.push("mine=true");
  if (opts.status) p.push(`status=${encodeURIComponent(opts.status)}`);
  if (opts.template_code) p.push(`template_code=${encodeURIComponent(opts.template_code)}`);
  return api.get(`/templates/instances${p.length ? `?${p.join("&")}` : ""}`);
}

export function getInstance(iid: string) {
  return api.get(`/templates/instances/${iid}`);
}

export function createInstance(body: { template_code: string; title?: string; values?: Record<string, any> }) {
  return api.post("/templates/instances", {
    template_code: body.template_code,
    title: body.title,
    values: body.values || {},
  });
}

export function updateInstance(iid: string, patch: { title?: string; values?: Record<string, any> }) {
  return api.patch(`/templates/instances/${iid}`, patch);
}

export function finalizeInstance(iid: string) {
  return api.post(`/templates/instances/${iid}/finalize`);
}

export function duplicateInstance(iid: string) {
  return api.post(`/templates/instances/${iid}/duplicate`);
}

export function deleteInstance(iid: string) {
  return api.del(`/templates/instances/${iid}`);
}

export function sanitizeFilename(name: string) {
  const cleaned = String(name || "template").replace(/[^\w\-. ]+/g, "_").trim() || "template";
  return cleaned.toLowerCase().endsWith(".pdf") ? cleaned : `${cleaned}.pdf`;
}

async function readError(res: { status: number; json: () => Promise<any> }) {
  let msg = "";
  try { msg = (await res.json())?.detail || ""; } catch { /* binary / empty */ }
  return new Error(msg || `PDF request failed (${res.status})`);
}

/**
 * POST /templates/instances/{id}/pdf → save to app cache → open share sheet.
 * Same File(Paths.cache) + Sharing.shareAsync pattern as `utils/exportCsv.ts`.
 * Returns the local file URI (or the object URL on web).
 */
export async function downloadPdf(iid: string, filename = "template.pdf"): Promise<string> {
  const token = await getAuthToken();
  const url = `${api_base()}/templates/instances/${iid}/pdf`;
  const headers = { Authorization: token ? `Bearer ${token}` : "" };
  const name = sanitizeFilename(filename);

  if (Platform.OS === "web") {
    const res = await fetch(url, { method: "POST", headers });
    if (!res.ok) throw await readError(res);
    const blobUrl = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = blobUrl;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(blobUrl), 2000);
    return blobUrl;
  }

  const res = await expoFetch(url, { method: "POST", headers });
  if (!res.ok) throw await readError(res);
  const bytes = new Uint8Array(await res.arrayBuffer());
  const file = new File(Paths.cache, name);
  try { file.create({ overwrite: true }); } catch { /* exists */ }
  file.write(bytes);
  if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(file.uri, { mimeType: "application/pdf", dialogTitle: name, UTI: "com.adobe.pdf" });
  }
  return file.uri;
}
