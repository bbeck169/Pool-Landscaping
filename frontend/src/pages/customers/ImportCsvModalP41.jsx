/**
 * Feb-2026 · P41 — CSV Import (fill-in-blanks merge) modal.
 *
 * Web-only admin/manager surface. Distinct from the legacy
 * ``ImportModal`` (which lives in ``CustomersList.jsx`` and uses the
 * older ``/api/import/customers`` endpoint) — P41's endpoint is
 * ``POST /api/customers/import-csv`` with a fixed 12-column schema
 * and merge-on-duplicate semantics.
 *
 * The response envelope this modal renders:
 *   {
 *     created: number,
 *     updated: number,
 *     skipped_no_new_data: number,
 *     errored: number,
 *     row_errors: [{ row, reason, detail? }, ...]
 *   }
 */
import React, { useCallback, useMemo, useRef, useState } from "react";

const _HEADERS = [
  "First Name", "Last Name", "Service Address", "Service City",
  "Service State", "Service Zip Code", "Billing Address",
  "Billing City", "Billing State", "Billing Zip Code",
  "Email", "Phone Number",
];

// Kept small on purpose — the built-in blob URL fires the browser
// download without a network round-trip.
function _buildTemplateBlob() {
  const csv = _HEADERS.join(",") + "\n"
                + _HEADERS.map(() => "").join(",") + "\n";
  return new Blob([csv], { type: "text/csv" });
}

function _downloadTemplate() {
  const blob = _buildTemplateBlob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "customer-import-template.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

async function _uploadCsv(file, targetStatus) {
  const BASE = process.env.REACT_APP_BACKEND_URL || "";
  const tok = localStorage.getItem("token") || "";
  const fd = new FormData();
  fd.append("file", file);
  fd.append("target_status", targetStatus);
  const res = await fetch(`${BASE}/api/customers/import-csv`, {
    method: "POST",
    headers: tok ? { Authorization: `Bearer ${tok}` } : {},
    body: fd,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!res.ok) {
    const detail = data?.detail;
    let msg;
    if (typeof detail === "string") msg = detail;
    else if (detail?.error === "missing_headers") {
      msg = `Missing required header(s): `
              + `${(detail.missing_headers || []).join(", ")}`;
    } else if (detail?.error === "too_many_rows") {
      msg = `CSV exceeds ${detail.max_rows} row limit.`;
    } else if (detail?.error) msg = String(detail.error);
    else msg = `Import failed (${res.status})`;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return data;
}


export default function ImportCsvModalP41({ open, onClose, onDone,
                                                setToast }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [target, setTarget] = useState("active");
  const [errorsExpanded, setErrorsExpanded] = useState(false);
  const [fileName, setFileName] = useState("");
  const fileRef = useRef(null);

  const reset = useCallback(() => {
    setResult(null);
    setBusy(false);
    setErrorsExpanded(false);
    setFileName("");
    if (fileRef.current) fileRef.current.value = "";
  }, []);

  const handleClose = useCallback(() => {
    if (result) {
      // Post-import close: refresh the customer list.
      onDone && onDone();
    }
    reset();
    onClose && onClose();
  }, [result, onDone, onClose, reset]);

  const handleSubmit = useCallback(async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setToast && setToast({
        tone: "error", message: "Choose a CSV file to import." });
      return;
    }
    setBusy(true);
    try {
      const res = await _uploadCsv(file, target);
      setResult(res);
      const summary = [
        res?.created ? `${res.created} created` : null,
        res?.updated ? `${res.updated} updated` : null,
        res?.errored ? `${res.errored} errored` : null,
      ].filter(Boolean).join(" · ") || "No changes";
      setToast && setToast({
        tone: (res?.errored || 0) > 0 ? "warning" : "success",
        message: summary,
      });
    } catch (e) {
      setToast && setToast({ tone: "error", message: e.message });
    } finally {
      setBusy(false);
    }
  }, [target, setToast]);

  const displayedErrors = useMemo(() => {
    if (!result?.row_errors) return [];
    const cap = errorsExpanded ? 100 : 10;
    return result.row_errors.slice(0, cap);
  }, [result, errorsExpanded]);

  if (!open) return null;

  return (
    <div
      data-testid="import-csv-modal"
      className="fixed inset-0 flex items-center justify-center"
      style={{ background: "rgba(15, 23, 42, 0.55)", zIndex: 50 }}
    >
      <div
        className="bg-white rounded-lg p-6 max-w-lg w-full shadow-lg"
        style={{ maxHeight: "90vh", overflowY: "auto" }}
      >
        {!result ? (
          <>
            <h2 className="text-lg font-bold mb-2"
                style={{ color: "#0F172A" }}>
              Import Customers (CSV)
            </h2>
            <p className="text-xs mb-4" style={{ color: "#64748B" }}>
              Rows will import into the&nbsp;
              <b>{target === "active" ? "Active" : "Inactive"}</b>&nbsp;
              customer list. Rows matching an existing customer by email
              or phone will fill in only the blank fields on the
              existing customer — no field is ever overwritten.
            </p>

            <div className="mb-3">
              <label className="block text-xs font-semibold mb-1"
                       style={{ color: "#334155" }}>
                Target list
              </label>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="p41-target"
                    value="active"
                    checked={target === "active"}
                    onChange={() => setTarget("active")}
                    data-testid="import-csv-target-active"
                  />
                  <span className="text-sm">Active</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="p41-target"
                    value="inactive"
                    checked={target === "inactive"}
                    onChange={() => setTarget("inactive")}
                    data-testid="import-csv-target-inactive"
                  />
                  <span className="text-sm">Inactive</span>
                </label>
              </div>
            </div>

            <div className="mb-3">
              <label className="block text-xs font-semibold mb-1"
                       style={{ color: "#334155" }}>
                CSV file
              </label>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => setFileName(
                  e.target.files?.[0]?.name || "")}
                data-testid="import-csv-file-input"
                className="text-sm"
              />
              {fileName ? (
                <div className="text-xs mt-1"
                       style={{ color: "#64748B" }}>{fileName}</div>
              ) : null}
            </div>

            <div className="mb-4">
              <button
                type="button"
                onClick={_downloadTemplate}
                data-testid="import-csv-template-link"
                className="text-xs font-semibold underline"
                style={{ color: "#0EA5E9" }}
              >
                Download template (.csv)
              </button>
            </div>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={handleClose}
                className="px-3 py-2 text-sm rounded border"
                style={{ borderColor: "#E5E7EB" }}
              >Cancel</button>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={busy}
                data-testid="import-csv-submit"
                className="px-3 py-2 text-sm font-semibold rounded"
                style={{ background: "#0EA5E9", color: "#fff",
                            opacity: busy ? 0.6 : 1 }}
              >{busy ? "Uploading…" : "Import"}</button>
            </div>
          </>
        ) : (
          <div data-testid="import-csv-result-modal">
            <h2 className="text-lg font-bold mb-3"
                style={{ color: "#0F172A" }}>
              Import complete
            </h2>
            <div className="grid grid-cols-4 gap-2 mb-4">
              <div className="rounded p-2 text-center"
                     style={{ background: "#F0FDF4" }}>
                <div className="text-2xl font-bold"
                       style={{ color: "#166534" }}
                       data-testid="import-csv-result-created">
                  {result.created || 0}
                </div>
                <div className="text-xs" style={{ color: "#166534" }}>
                  Created
                </div>
              </div>
              <div className="rounded p-2 text-center"
                     style={{ background: "#EFF6FF" }}>
                <div className="text-2xl font-bold"
                       style={{ color: "#1E40AF" }}
                       data-testid="import-csv-result-updated">
                  {result.updated || 0}
                </div>
                <div className="text-xs" style={{ color: "#1E40AF" }}>
                  Updated
                </div>
              </div>
              <div className="rounded p-2 text-center"
                     style={{ background: "#F1F5F9" }}>
                <div className="text-2xl font-bold"
                       style={{ color: "#475569" }}
                       data-testid="import-csv-result-skipped">
                  {result.skipped_no_new_data || 0}
                </div>
                <div className="text-xs" style={{ color: "#475569" }}>
                  Skipped
                </div>
              </div>
              <div className="rounded p-2 text-center"
                     style={{ background: "#FEF2F2" }}>
                <div className="text-2xl font-bold"
                       style={{ color: "#7F1D1D" }}
                       data-testid="import-csv-result-errored">
                  {result.errored || 0}
                </div>
                <div className="text-xs" style={{ color: "#7F1D1D" }}>
                  Errored
                </div>
              </div>
            </div>

            {result.row_errors && result.row_errors.length > 0 ? (
              <div className="mb-4">
                <div className="flex items-center justify-between mb-1">
                  <h3 className="text-sm font-semibold"
                        style={{ color: "#7F1D1D" }}>
                    Row errors ({result.row_errors.length})
                  </h3>
                  {result.row_errors.length > 10 && !errorsExpanded ? (
                    <button
                      type="button"
                      onClick={() => setErrorsExpanded(true)}
                      data-testid="import-csv-errors-expand"
                      className="text-xs font-semibold underline"
                      style={{ color: "#0EA5E9" }}
                    >Show all (up to 100)</button>
                  ) : null}
                </div>
                <ul className="text-xs border rounded max-h-64
                                     overflow-y-auto p-2 bg-white"
                    style={{ borderColor: "#FCA5A5" }}>
                  {displayedErrors.map((e, i) => {
                    const isInfo = e.reason === "matched_in_other_status";
                    return (
                      <li key={`${e.row}-${i}`}
                            data-testid={`import-csv-result-error-row-${i}`}
                            data-reason={e.reason}
                            className="py-0.5"
                            style={{
                              color: isInfo ? "#1E3A8A" : "#7F1D1D",
                              background: isInfo
                                  ? "rgba(59,130,246,0.06)"
                                  : "transparent",
                              borderLeft: isInfo
                                  ? "2px solid #3B82F6"
                                  : "2px solid transparent",
                              paddingLeft: 6,
                            }}>
                        <span className="font-mono font-semibold">
                          Row {e.row}
                        </span>
                        &nbsp;·&nbsp;
                        <span>
                          {isInfo ? "info: " : ""}{e.reason}
                        </span>
                        {e.detail ? (
                          <span style={{
                              color: isInfo ? "#1E40AF" : "#64748B" }}>
                            &nbsp;— {e.detail}
                          </span>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
                {result.row_errors.length > 100 ? (
                  <div className="text-xs mt-1"
                         style={{ color: "#64748B" }}>
                    Showing 100 of {result.row_errors.length}. Full detail
                    in the audit log.
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="flex justify-end">
              <button
                type="button"
                onClick={handleClose}
                data-testid="import-csv-result-close"
                className="px-3 py-2 text-sm font-semibold rounded"
                style={{ background: "#0EA5E9", color: "#fff" }}
              >Close</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
