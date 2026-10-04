/**
 * PDFI-IV · Feb-2026 — Thin client wrapper over the five
 * ``/api/imports/pdf-invoice/*`` endpoints. Named-exports keep
 * callers terse. The upload path uses raw ``fetch`` because the
 * ``api`` wrapper serializes ``body`` as JSON — multipart needs
 * the browser-set ``Content-Type: multipart/form-data; boundary=…``
 * header which only happens when ``body`` is a ``FormData``.
 */
import { api, api_base, TOKEN_KEY } from "@/api";

const _bearer = () => {
  try {
    const t = typeof localStorage !== "undefined"
      ? localStorage.getItem(TOKEN_KEY) : null;
    return t ? { Authorization: `Bearer ${t}` } : {};
  } catch {
    return {};
  }
};

export async function kickoffUpload(file, opts = {}) {
  const fd = new FormData();
  fd.append("file", file);
  if (opts.hintDocKind) fd.append("hint_doc_kind", opts.hintDocKind);
  const res = await fetch(`${api_base()}/imports/pdf-invoice`, {
    method: "POST",
    headers: _bearer(),
    body: fd,
  });
  if (!res.ok) {
    let body = null;
    try { body = await res.json(); } catch { /* body empty */ }
    const detail = (body && typeof body === "object" && body.detail !== undefined)
      ? body.detail : body;
    const err = new Error(
      (detail && (detail.message || detail.error)) || `upload_failed_${res.status}`,
    );
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return res.json();
}

export const pollBatch = (batchId) =>
  api.get(`/imports/pdf-invoice/${encodeURIComponent(batchId)}`);

export const patchPreview = (batchId, body) =>
  api.patch(
    `/imports/pdf-invoice/${encodeURIComponent(batchId)}/preview`,
    body,
  );

export const commitBatch = (batchId, body = {}) =>
  api.post(
    `/imports/pdf-invoice/${encodeURIComponent(batchId)}/commit`,
    body,
  );

export const rollbackBatch = (batchId, body = {}) =>
  api.post(
    `/imports/pdf-invoice/${encodeURIComponent(batchId)}/rollback`,
    body,
  );
