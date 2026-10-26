/**
 * TD-customer-ai-excel-csv-import · Feb-2026
 * ==========================================
 *
 * AI-powered customer importer sidepanel.  Mirrors the posture of
 * ``ImportCsvModalP41`` for the toolbar invocation but uses the
 * AI-mapped two-step upload → preview-confirm → commit workflow.
 *
 * Flow
 * ----
 * 1. Operator picks an ``.xlsx``, ``.xls``, or ``.csv`` file.
 * 2. POST ``/api/customers/import-excel/upload`` → preview payload
 *    with per-row ``mapped_fields`` + ``suggested_action`` +
 *    ``match_candidates``.
 * 3. Preview table — one row per data row; operator can override
 *    the action (``create`` / ``attach`` / ``skip``) and the
 *    attach-target customer_id via a dropdown.
 * 4. POST ``/api/customers/import-excel/commit`` with the operator-
 *    approved row list.  Backend persists / PATCHes / skips per the
 *    per-row action.
 *
 * Blank-cell semantics (operator Q3)
 * ----------------------------------
 * Only fields in ``mapped_fields`` for a row are sent to the
 * commit endpoint, and the backend PATCHes only those fields on
 * an attach — existing customer values for keys absent from
 * ``mapped_fields`` are preserved verbatim.  The modal surfaces a
 * tooltip on the "Attach" action explaining this.
 */
import React, { useCallback, useMemo, useRef, useState } from "react";


function _authHeaders() {
    const tok = localStorage.getItem("token") || "";
    return tok ? { Authorization: `Bearer ${tok}` } : {};
}

async function _uploadFile(file) {
    const BASE = process.env.REACT_APP_BACKEND_URL || "";
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(
        `${BASE}/api/customers/import-excel/upload`,
        { method: "POST", headers: _authHeaders(), body: fd },
    );
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = null; }
    if (!res.ok) {
        const detail = data?.detail;
        let msg;
        if (typeof detail === "string") msg = detail;
        else if (detail?.error === "row_limit_exceeded") {
            msg = `File exceeds ${detail.max_rows} row limit `
                     + `(${detail.found_rows} rows found).`;
        } else if (detail?.error === "empty_file") {
            msg = "The uploaded file is empty.";
        } else if (detail?.error === "unsupported_file_type") {
            msg = "Unsupported file type. Upload .xlsx, .xls, or .csv.";
        } else if (detail?.error) {
            msg = String(detail.error);
        } else {
            msg = `Upload failed (${res.status})`;
        }
        const err = new Error(msg);
        err.status = res.status;
        throw err;
    }
    return data;
}

async function _commitBatch(batchId, rows) {
    const BASE = process.env.REACT_APP_BACKEND_URL || "";
    const res = await fetch(
        `${BASE}/api/customers/import-excel/commit`,
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                ..._authHeaders(),
            },
            body: JSON.stringify({ batch_id: batchId, rows }),
        },
    );
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = null; }
    if (!res.ok) {
        const detail = data?.detail;
        let msg;
        if (typeof detail === "string") msg = detail;
        else if (detail?.error === "batch_not_found") {
            msg = "Preview batch expired or not found — re-upload "
                     + "the file to try again.";
        } else {
            msg = `Commit failed (${res.status})`;
        }
        const err = new Error(msg);
        err.status = res.status;
        throw err;
    }
    return data;
}


function _matchStatusLabel(status) {
    switch (status) {
        case "exact_email":        return "Email match";
        case "exact_phone":        return "Phone match";
        case "ladder_exact_name":  return "Name match";
        case "ladder_fuzzy_name":  return "Fuzzy name match";
        case "no_match":           return "No match";
        case "no_signal":          return "No usable fields";
        default:                   return status || "";
    }
}


export default function ImportExcelCsvAIModal({
    open, onClose, onDone, setToast,
}) {
    const fileRef = useRef(null);
    const [busy, setBusy] = useState(false);
    const [uploadResult, setUploadResult] = useState(null);
    const [rowActions, setRowActions] = useState({});
    const [commitResult, setCommitResult] = useState(null);

    const handleUpload = useCallback(async () => {
        const file = fileRef.current?.files?.[0];
        if (!file) {
            setToast?.({
                kind: "error",
                message: "Pick an .xlsx, .xls, or .csv file first.",
            });
            return;
        }
        setBusy(true);
        try {
            const result = await _uploadFile(file);
            setUploadResult(result);
            // Seed per-row action overrides with the backend's
            // suggested defaults so the operator sees the picks
            // pre-selected.
            const seeded = {};
            for (const row of (result.preview || [])) {
                seeded[row.row_num] = {
                    action: row.suggested_action,
                    attach_to_customer_id: (
                        row.match_candidates?.[0]?.customer_id || ""
                    ),
                };
            }
            setRowActions(seeded);
        } catch (err) {
            setToast?.({
                kind: "error",
                message: err.message || "Upload failed.",
            });
        } finally {
            setBusy(false);
        }
    }, [setToast]);

    const handleCommit = useCallback(async () => {
        if (!uploadResult?.batch_id) return;
        setBusy(true);
        try {
            const rows = (uploadResult.preview || []).map((p) => {
                const override = rowActions[p.row_num] || {};
                return {
                    row_num: p.row_num,
                    action: override.action || p.suggested_action,
                    mapped_fields: p.mapped_fields || {},
                    attach_to_customer_id:
                        override.attach_to_customer_id || null,
                };
            });
            const result = await _commitBatch(
                uploadResult.batch_id, rows,
            );
            setCommitResult(result);
            onDone?.(result);
        } catch (err) {
            setToast?.({
                kind: "error",
                message: err.message || "Commit failed.",
            });
        } finally {
            setBusy(false);
        }
    }, [uploadResult, rowActions, onDone, setToast]);

    const stats = useMemo(() => {
        if (!uploadResult) return null;
        const create = Object.values(rowActions)
            .filter((r) => r.action === "create").length;
        const attach = Object.values(rowActions)
            .filter((r) => r.action === "attach").length;
        const skip = Object.values(rowActions)
            .filter((r) => r.action === "skip").length;
        return { create, attach, skip };
    }, [uploadResult, rowActions]);

    if (!open) return null;

    return (
        <div
            data-testid="import-excel-ai-modal"
            className="fixed inset-0 flex items-center justify-center"
            style={{ background: "rgba(15, 23, 42, 0.55)", zIndex: 50 }}
        >
            <div
                className="bg-white rounded-lg p-6 shadow-lg"
                style={{
                    maxHeight: "90vh", overflowY: "auto",
                    width: "min(90vw, 1024px)",
                }}
            >
                {!uploadResult && !commitResult ? (
                    <UploadPrompt
                        fileRef={fileRef}
                        busy={busy}
                        onUpload={handleUpload}
                        onClose={onClose}
                    />
                ) : commitResult ? (
                    <CommitResultView
                        result={commitResult}
                        onClose={onClose}
                    />
                ) : (
                    <PreviewTable
                        upload={uploadResult}
                        rowActions={rowActions}
                        setRowActions={setRowActions}
                        stats={stats}
                        busy={busy}
                        onCommit={handleCommit}
                        onCancel={() => {
                            setUploadResult(null);
                            setRowActions({});
                        }}
                    />
                )}
            </div>
        </div>
    );
}


function UploadPrompt({ fileRef, busy, onUpload, onClose }) {
    return (
        <>
            <h2
                className="text-lg font-bold mb-2"
                style={{ color: "#0F172A" }}
            >
                Import Customers from Excel / CSV (AI)
            </h2>
            <p
                className="text-xs mb-4"
                style={{ color: "#64748B" }}
            >
                Upload a ``.xlsx``, ``.xls``, or ``.csv`` file with any column
                layout.  Our AI will map your columns to the right
                customer fields, flag duplicates, and let you review
                every row before any customers are created or updated.
            </p>
            <input
                ref={fileRef}
                type="file"
                accept=".xlsx,.xls,.csv,application/vnd.ms-excel,text/csv"
                data-testid="import-excel-ai-file-input"
                className="mb-4 block w-full text-sm"
            />
            <div className="flex justify-end gap-2 mt-4">
                <button
                    type="button"
                    onClick={onClose}
                    disabled={busy}
                    data-testid="import-excel-ai-cancel"
                    className="px-4 py-2 rounded border text-sm"
                >
                    Cancel
                </button>
                <button
                    type="button"
                    onClick={onUpload}
                    disabled={busy}
                    data-testid="import-excel-ai-upload-submit"
                    className="px-4 py-2 rounded text-sm text-white"
                    style={{
                        background: busy ? "#94A3B8" : "#2563EB",
                    }}
                >
                    {busy ? "Uploading…" : "Upload & Preview"}
                </button>
            </div>
        </>
    );
}


function PreviewTable({
    upload, rowActions, setRowActions, stats, busy,
    onCommit, onCancel,
}) {
    const preview = upload.preview || [];
    return (
        <>
            <div className="flex items-start justify-between mb-3">
                <div>
                    <h2
                        className="text-lg font-bold"
                        style={{ color: "#0F172A" }}
                    >
                        Confirm Import — {preview.length} row
                        {preview.length === 1 ? "" : "s"}
                    </h2>
                    <p
                        className="text-xs mt-1"
                        style={{ color: "#64748B" }}
                    >
                        AI provider:&nbsp;
                        {Object.keys(upload.ai_providers || {})
                            .join(", ") || "unknown"}.
                        Review every row — attaching will PATCH only
                        the fields present in your file; blank cells
                        never overwrite existing customer data.
                    </p>
                </div>
                {stats && (
                    <div
                        className="text-xs"
                        style={{ color: "#334155" }}
                        data-testid="import-excel-ai-stats"
                    >
                        <div>Create: <b>{stats.create}</b></div>
                        <div>Attach: <b>{stats.attach}</b></div>
                        <div>Skip: <b>{stats.skip}</b></div>
                    </div>
                )}
            </div>
            <div
                className="border rounded"
                style={{
                    maxHeight: "55vh", overflowY: "auto",
                    borderColor: "#E2E8F0",
                }}
            >
                <table
                    className="w-full text-xs"
                    data-testid="import-excel-ai-preview-table"
                >
                    <thead
                        className="bg-slate-50 sticky top-0"
                        style={{ color: "#334155" }}
                    >
                        <tr>
                            <th className="p-2 text-left">Row</th>
                            <th className="p-2 text-left">
                                Mapped fields
                            </th>
                            <th className="p-2 text-left">
                                Match
                            </th>
                            <th className="p-2 text-left">
                                Action
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {preview.map((row) => (
                            <PreviewRow
                                key={row.row_num}
                                row={row}
                                override={rowActions[row.row_num]}
                                onChangeAction={(action) =>
                                    setRowActions((s) => ({
                                        ...s,
                                        [row.row_num]: {
                                            ...s[row.row_num],
                                            action,
                                        },
                                    }))}
                                onChangeAttachId={(cid) =>
                                    setRowActions((s) => ({
                                        ...s,
                                        [row.row_num]: {
                                            ...s[row.row_num],
                                            attach_to_customer_id: cid,
                                        },
                                    }))}
                            />
                        ))}
                    </tbody>
                </table>
            </div>
            <div className="flex justify-end gap-2 mt-4">
                <button
                    type="button"
                    onClick={onCancel}
                    disabled={busy}
                    data-testid="import-excel-ai-cancel-preview"
                    className="px-4 py-2 rounded border text-sm"
                >
                    Back
                </button>
                <button
                    type="button"
                    onClick={onCommit}
                    disabled={busy}
                    data-testid="import-excel-ai-commit-submit"
                    className="px-4 py-2 rounded text-sm text-white"
                    style={{
                        background: busy ? "#94A3B8" : "#16A34A",
                    }}
                >
                    {busy ? "Committing…" : "Confirm & Import"}
                </button>
            </div>
        </>
    );
}


function PreviewRow({
    row, override, onChangeAction, onChangeAttachId,
}) {
    const action = override?.action || row.suggested_action;
    const attachId = override?.attach_to_customer_id
        || (row.match_candidates?.[0]?.customer_id || "");
    const mapped = row.mapped_fields || {};
    const mappedPairs = Object.entries(mapped)
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .slice(0, 4);
    return (
        <tr
            data-testid={`import-excel-ai-row-${row.row_num}`}
            className="border-t"
            style={{ borderColor: "#F1F5F9" }}
        >
            <td className="p-2 align-top" style={{ color: "#334155" }}>
                {row.row_num}
            </td>
            <td className="p-2 align-top">
                {row.error ? (
                    <span className="text-rose-600">
                        AI error: {row.error}
                    </span>
                ) : mappedPairs.length === 0 ? (
                    <span style={{ color: "#94A3B8" }}>
                        (no fields mapped)
                    </span>
                ) : (
                    <ul className="space-y-0.5">
                        {mappedPairs.map(([k, v]) => (
                            <li key={k}>
                                <b style={{ color: "#334155" }}>{k}</b>:{" "}
                                <span style={{ color: "#475569" }}>
                                    {Array.isArray(v) ? v.join(", ") : String(v)}
                                </span>
                            </li>
                        ))}
                    </ul>
                )}
            </td>
            <td className="p-2 align-top">
                <div
                    style={{ color: "#334155" }}
                    data-testid={`import-excel-ai-match-${row.row_num}`}
                >
                    {_matchStatusLabel(row.match_status)}
                </div>
                {(row.match_candidates || []).length > 1 && (
                    <select
                        value={attachId}
                        onChange={(e) => onChangeAttachId(e.target.value)}
                        data-testid={`import-excel-ai-attach-${row.row_num}`}
                        className="mt-1 text-xs border rounded px-1 py-0.5"
                    >
                        {row.match_candidates.map((c) => (
                            <option key={c.customer_id} value={c.customer_id}>
                                {c.name} ({c.match_reason})
                            </option>
                        ))}
                    </select>
                )}
            </td>
            <td className="p-2 align-top">
                <select
                    value={action}
                    onChange={(e) => onChangeAction(e.target.value)}
                    data-testid={`import-excel-ai-action-${row.row_num}`}
                    className="text-xs border rounded px-1 py-0.5"
                >
                    <option value="create">Create new</option>
                    <option
                        value="attach"
                        disabled={!(row.match_candidates || []).length}
                    >
                        Attach to match
                    </option>
                    <option value="skip">Skip</option>
                </select>
            </td>
        </tr>
    );
}


function CommitResultView({ result, onClose }) {
    return (
        <div data-testid="import-excel-ai-result-view">
            <h2
                className="text-lg font-bold mb-3"
                style={{ color: "#0F172A" }}
            >
                Import complete
            </h2>
            <div
                className="grid grid-cols-2 gap-2 text-sm mb-4"
                style={{ color: "#334155" }}
            >
                <div>
                    Created:{" "}
                    <b data-testid="import-excel-ai-result-created">
                        {result.created || 0}
                    </b>
                </div>
                <div>
                    Attached:{" "}
                    <b data-testid="import-excel-ai-result-attached">
                        {result.attached || 0}
                    </b>
                </div>
                <div>
                    Skipped:{" "}
                    <b data-testid="import-excel-ai-result-skipped">
                        {result.skipped || 0}
                    </b>
                </div>
                <div>
                    Errored:{" "}
                    <b
                        data-testid="import-excel-ai-result-errored"
                        style={{
                            color: (result.errored || 0) > 0
                                ? "#DC2626" : "#334155",
                        }}
                    >
                        {result.errored || 0}
                    </b>
                </div>
            </div>
            {(result.row_errors || []).length > 0 && (
                <details className="mb-3">
                    <summary
                        className="cursor-pointer text-xs mb-1"
                        style={{ color: "#DC2626" }}
                    >
                        {result.row_errors.length} row error
                        {result.row_errors.length === 1 ? "" : "s"} —
                        tap to inspect
                    </summary>
                    <ul
                        className="text-xs ml-4 mt-2"
                        style={{ color: "#475569" }}
                    >
                        {result.row_errors.slice(0, 20).map(
                            (e, idx) => (
                                <li key={`${e.row_num}-${idx}`}>
                                    row {e.row_num}: {e.reason}
                                </li>
                            ),
                        )}
                    </ul>
                </details>
            )}
            <div className="flex justify-end">
                <button
                    type="button"
                    onClick={onClose}
                    data-testid="import-excel-ai-result-close"
                    className="px-4 py-2 rounded text-sm text-white"
                    style={{ background: "#2563EB" }}
                >
                    Done
                </button>
            </div>
        </div>
    );
}
