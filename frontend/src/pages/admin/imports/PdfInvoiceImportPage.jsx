/**
 * Task B · Feb-2026 — PDF Invoice Importer admin page.
 *
 * Route: ``/admin/imports/pdf-invoice`` (admin+ only via
 * ``<AdminOnly>`` in App.js).
 *
 * Backend endpoints (see recon halt report, §A):
 *
 *   POST /api/imports/pdf-invoice                       — kickoff
 *   GET  /api/imports/pdf-invoice/{batch_id}            — poll
 *   GET  /api/imports/pdf-invoice/{batch_id}/duplicates — pre-flight
 *   POST /api/imports/pdf-invoice/{batch_id}/commit     — commit
 *   POST /api/imports/pdf-invoice/{batch_id}/rollback   — rollback
 *
 * Backend caps (frozen in Phase 2 ruling E.1 / E.2):
 *
 *   * 10 MB per PDF (415 pdf_only / 413 pdf_too_large)
 *   * 3 concurrent in-flight per tenant (429 rate limit)
 *
 * Client-side caps (frozen in Phase 2 ruling E.1 / E.2):
 *
 *   * 20 PDFs max per selection (toast.error above cap).
 *   * Soft-warn at 10 PDFs (toast.warning).
 *   * 10 MB client-side reject before POST (belt-and-suspenders).
 *   * Concurrency pool of 2 uploads (leave 1 slot for co-admins).
 *
 * This module ships in phased commits:
 *
 *   * Commit 1  — scaffold (idle state, route, sidebar).  [LANDED]
 *   * Commit 2  — this commit — upload flow: validation
 *     (count / size), per-file state machine
 *     (queued → uploading → processing / error), POST fan-out
 *     with a 2-slot concurrency pool.
 *   * Commit 3  — async polling + progress bar per batch.
 *   * Commit 4  — dry-run preview table + duplicate highlighting.
 *   * Commit 5  — commit + rollback actions.
 *   * Commit 6  — integration test + PRD update.
 */
import React, { useCallback, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  UploadCloud,
  FileText,
  ShieldCheck,
  Loader2,
  AlertCircle,
  Clock,
  X,
} from "lucide-react";
import { PageHeader, Button } from "@/components/ui-kit";
import { colors } from "@/theme";


// Frozen client-side caps — see module doc for rulings.
export const MAX_FILES_PER_BATCH = 20;
export const MAX_BYTES_PER_FILE = 10 * 1024 * 1024;   // 10 MB
export const SOFT_WARN_FILES = 10;
export const CONCURRENCY_POOL = 2;


// Per-file state machine (see Ruling E.1).
export const FILE_STATUS = {
  QUEUED: "queued",
  UPLOADING: "uploading",
  PROCESSING: "processing",
  ERROR: "error",
};


/**
 * Pure validation over a File[] selection.  Splits the input into
 * ``accepted`` (pass both count + size caps), ``oversized`` (per-
 * file 10 MB cap violation), and ``rejectedForCount`` (batch >
 * 20 files — whole selection rejected).
 *
 * Exported so the vitest can drive validation edge cases without
 * mounting the component.
 */
export function validateSelection(fileList) {
  const files = Array.from(fileList || []);
  if (files.length > MAX_FILES_PER_BATCH) {
    return {
      accepted: [],
      oversized: [],
      rejectedForCount: files,
      shouldSoftWarn: false,
    };
  }
  const accepted = [];
  const oversized = [];
  for (const f of files) {
    if (f && typeof f.size === "number" && f.size > MAX_BYTES_PER_FILE) {
      oversized.push(f);
    } else if (f) {
      accepted.push(f);
    }
  }
  return {
    accepted,
    oversized,
    rejectedForCount: [],
    shouldSoftWarn: accepted.length >= SOFT_WARN_FILES,
  };
}


/**
 * Format a byte count for the size-cap toast copy.  ``12582912``
 * → ``"12.0 MB"``.
 */
export function formatBytes(bytes) {
  if (typeof bytes !== "number" || !isFinite(bytes)) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}


/**
 * Translate a fetch-response error body into user-friendly copy.
 * Mirrors the typed-error surface documented in the recon report
 * §A.1 (415 pdf_only / 413 pdf_too_large / 400 pdf_parse_failed /
 * 429 rate-limited).  Falls back to a generic message on unknown
 * codes.
 */
export function messageForUploadError(status, detail) {
  const code = typeof detail === "object" && detail
    ? (detail.error || detail.code || detail.detail || "")
    : (detail || "");
  if (status === 415 || code === "pdf_only") {
    return "Only PDF files are accepted.";
  }
  if (status === 413 || code === "pdf_too_large") {
    return "PDF exceeds the 10 MB size cap.";
  }
  if (status === 400 && code === "pdf_parse_failed") {
    return "This PDF could not be parsed — try re-saving as a "
      + "flat PDF and re-uploading.";
  }
  if (status === 429) {
    return "Too many uploads in flight — wait a few seconds and "
      + "retry.";
  }
  if (status === 401) {
    return "Session expired — refresh and sign in again.";
  }
  if (status === 403) {
    return "You do not have permission to import PDF invoices.";
  }
  return `Upload failed (${status || "network"}).`;
}


/**
 * POST a single File to the kickoff endpoint.  Returns the parsed
 * 202 response envelope on success or throws an Error carrying
 * the translated user message on failure.
 *
 * Exported so the vitest can drive success + typed-error paths
 * without mounting the page.
 */
export async function postPdfInvoice(file, { baseUrl, token } = {}) {
  const BASE = baseUrl || process.env.REACT_APP_BACKEND_URL || "";
  const TOKEN = token || (
    typeof localStorage !== "undefined"
      ? (localStorage.getItem("token") || "")
      : ""
  );
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${BASE}/api/imports/pdf-invoice`, {
    method: "POST",
    // NOTE: no Content-Type header — the browser sets the
    // multipart boundary automatically.  If we override to
    // application/json here FastAPI reads the body as JSON
    // and 422s.
    headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {},
    body: fd,
  });
  if (!res.ok) {
    let body = null;
    try { body = await res.json(); } catch { /* body empty */ }
    // FastAPI wraps HTTPException.detail inside a top-level
    // ``detail`` field on the response body — unwrap before
    // passing to the typed-error mapper.  Falls back gracefully
    // when the response is a plain string / null / different
    // shape.
    const inner = (body && typeof body === "object" && body.detail !== undefined)
      ? body.detail
      : body;
    const err = new Error(messageForUploadError(res.status, inner));
    err.status = res.status;
    err.detail = inner;
    throw err;
  }
  return await res.json();
}


// Local counter so React reconciliation doesn't confuse pending
// rows when the operator quickly re-selects.  A monotonic counter
// scoped to the module works because a single PdfInvoiceImportPage
// mount is the only consumer.
let _localFileIdCounter = 0;
function _nextLocalId() {
  _localFileIdCounter += 1;
  return `pdf-file-${Date.now()}-${_localFileIdCounter}`;
}


export default function PdfInvoiceImportPage() {
  const fileInputRef = useRef(null);
  // The files array is the whole state machine — each entry
  // carries a status + optional batch_id / error message.
  const [files, setFiles] = useState([]);
  // Pool-slot counter kept in a ref so the pump can read/write it
  // synchronously without a re-render round-trip.
  const inFlightRef = useRef(0);


  /**
   * Grab the next queued row (in FIFO source order) and fire off
   * a POST for it, respecting the CONCURRENCY_POOL slot cap.  Runs
   * repeatedly until either the pool is full or there are no more
   * queued rows.
   */
  const pumpPool = useCallback((currentFiles) => {
    // Fill open slots until either the pool is full or the queue
    // is empty.
    while (inFlightRef.current < CONCURRENCY_POOL) {
      const next = currentFiles.find(
        (f) => f.status === FILE_STATUS.QUEUED,
      );
      if (!next) return;
      inFlightRef.current += 1;
      // Flip status to uploading BEFORE the async POST fires so
      // the next pump iteration doesn't re-queue the same row.
      const fileId = next.id;
      setFiles((prev) => prev.map(
        (f) => (f.id === fileId
          ? { ...f, status: FILE_STATUS.UPLOADING }
          : f),
      ));
      // Mutate the local snapshot too so the while-loop below
      // doesn't hand out the same row twice on a burst.
      const idx = currentFiles.findIndex((f) => f.id === fileId);
      if (idx >= 0) {
        currentFiles[idx] = {
          ...currentFiles[idx],
          status: FILE_STATUS.UPLOADING,
        };
      }
      // Fire the POST — resolve or fail branches BOTH release
      // the slot and re-pump.
      postPdfInvoice(next.file)
        .then((envelope) => {
          setFiles((prev) => prev.map(
            (f) => (f.id === fileId
              ? {
                ...f,
                status: FILE_STATUS.PROCESSING,
                batch_id: envelope?.batch_id || null,
                poll_hint_seconds:
                  envelope?.poll_hint_seconds || null,
              }
              : f),
          ));
        })
        .catch((err) => {
          setFiles((prev) => prev.map(
            (f) => (f.id === fileId
              ? {
                ...f,
                status: FILE_STATUS.ERROR,
                error: err?.message || "Upload failed.",
              }
              : f),
          ));
        })
        .finally(() => {
          inFlightRef.current = Math.max(0, inFlightRef.current - 1);
          // Re-pump using the LATEST files state.  ``prev`` is
          // passed to setFiles so the pump reads a fresh snapshot.
          setFiles((prev) => {
            // Fire pump on the next tick to avoid a stale-render
            // loop inside a setState reducer.
            queueMicrotask(() => pumpPool(prev));
            return prev;
          });
        });
    }
  }, []);


  /**
   * Handles a new file selection from the hidden ``<input>``.
   * Runs the validation split, surfaces caps toasts, adds accepted
   * files to state, kicks the pool.
   */
  const onFilesSelected = useCallback((event) => {
    const {
      accepted,
      oversized,
      rejectedForCount,
      shouldSoftWarn,
    } = validateSelection(event.target.files);
    // Rejects come first so an operator seeing multiple toasts
    // sees the hard-cap message before individual size errors.
    if (rejectedForCount.length > 0) {
      toast.error(
        `Max ${MAX_FILES_PER_BATCH} PDFs per batch — split larger `
        + `batches into multiple runs.`,
      );
    }
    for (const f of oversized) {
      toast.error(
        `${f.name} is ${formatBytes(f.size)} — max 10 MB per PDF.`,
      );
    }
    if (shouldSoftWarn) {
      toast.warning(
        `Uploading ${accepted.length} files — this may take a `
        + `few minutes.`,
      );
    }
    // Reset the native input so re-selecting the same file
    // re-fires onChange.
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    if (accepted.length === 0) return;
    // Add accepted files to state as QUEUED, then kick the pool.
    const newRows = accepted.map((f) => ({
      id: _nextLocalId(),
      name: f.name,
      size: f.size,
      status: FILE_STATUS.QUEUED,
      file: f,
    }));
    setFiles((prev) => {
      const next = [...prev, ...newRows];
      // Kick the pool on a microtask so the setState reducer
      // returns first.
      queueMicrotask(() => pumpPool(next));
      return next;
    });
  }, [pumpPool]);


  const removeFile = useCallback((id) => {
    // Operators can dismiss rows in QUEUED or ERROR states — but
    // NOT UPLOADING (that's mid-POST) or PROCESSING (that would
    // orphan a real backend batch).  The dismiss surface hides
    // the button on those two states via ``canDismiss`` below.
    setFiles((prev) => prev.filter((f) => f.id !== id));
  }, []);


  const openFileDialog = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };


  const hasFiles = files.length > 0;


  return (
    <div
      data-testid="pdf-invoice-import-page"
      className="mx-auto max-w-5xl px-4 py-6"
    >
      <PageHeader
        title="PDF Invoice Import"
        subtitle={
          "Upload one or more supplier PDFs and turn them into "
          + "draft invoices.  Preview the extracted rows, review "
          + "duplicates, then commit — or roll back within the same "
          + "batch.  Admin-only."
        }
      />

      {/* Idle upload zone — always visible.  Commit 4 will add
          the preview surface below this block. */}
      <div
        data-testid="pdf-import-idle-zone"
        className="mt-6 rounded-lg border-2 border-dashed p-10 text-center"
        style={{
          borderColor: colors.border,
          backgroundColor: colors.surfaceSecondary,
        }}
      >
        <UploadCloud
          size={48}
          className="mx-auto mb-3"
          style={{ color: colors.muted }}
        />
        <div
          className="text-sm mb-4"
          style={{ color: colors.onSurfaceSecondary }}
        >
          Drag PDFs here, or choose them from your computer.
        </div>
        <Button
          variant="primary"
          onClick={openFileDialog}
          testid="pdf-import-choose-files-btn"
        >
          Choose PDF(s)
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="application/pdf"
          hidden
          onChange={onFilesSelected}
          data-testid="pdf-import-file-input"
        />
      </div>

      {/* Cap-summary strip. */}
      <div
        data-testid="pdf-import-caps-strip"
        className="mt-4 flex flex-wrap items-center gap-4 text-xs"
        style={{ color: colors.muted }}
      >
        <span className="inline-flex items-center gap-1.5">
          <FileText size={14} />
          Max {MAX_FILES_PER_BATCH} PDFs per batch
        </span>
        <span className="inline-flex items-center gap-1.5">
          <UploadCloud size={14} />
          Max 10 MB per PDF
        </span>
        <span className="inline-flex items-center gap-1.5">
          <ShieldCheck size={14} />
          Admin-only
        </span>
      </div>

      {/* Files list — hidden until an operator adds their first
          file.  Rendered as a lean rows-only list; Commit 3 wires
          the per-batch progress bar into each PROCESSING row. */}
      {hasFiles ? (
        <div
          data-testid="pdf-import-files-list"
          className="mt-6 space-y-2"
        >
          {files.map((f) => (
            <FileRow key={f.id} f={f} onRemove={removeFile} />
          ))}
        </div>
      ) : null}
    </div>
  );
}


function FileRow({ f, onRemove }) {
  const canDismiss = f.status === FILE_STATUS.QUEUED
    || f.status === FILE_STATUS.ERROR;
  const tone = STATUS_TONE[f.status] || STATUS_TONE.queued;
  const Icon = tone.Icon;
  return (
    <div
      data-testid={`pdf-import-file-row-${f.id}`}
      data-status={f.status}
      className="flex items-center gap-3 rounded-md border px-3 py-2"
      style={{
        borderColor: colors.border,
        backgroundColor: colors.surface,
      }}
    >
      <FileText size={16} style={{ color: colors.muted }} />
      <div className="flex-1 min-w-0">
        <div
          className="text-sm truncate"
          style={{ color: colors.onSurface }}
        >
          {f.name}
        </div>
        <div className="text-xs" style={{ color: colors.muted }}>
          {formatBytes(f.size)}
          {f.error ? ` · ${f.error}` : null}
        </div>
      </div>
      <span
        className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${tone.className}`}
        data-testid={`pdf-import-file-status-${f.id}`}
      >
        <Icon size={12} className={tone.spin ? "animate-spin" : ""} />
        {tone.label}
      </span>
      {canDismiss ? (
        <button
          type="button"
          onClick={() => onRemove(f.id)}
          className="ml-1 rounded p-1 hover:bg-black/5"
          data-testid={`pdf-import-file-dismiss-${f.id}`}
          aria-label={`Remove ${f.name}`}
        >
          <X size={14} style={{ color: colors.muted }} />
        </button>
      ) : null}
    </div>
  );
}


const STATUS_TONE = {
  [FILE_STATUS.QUEUED]: {
    label: "Queued",
    Icon: Clock,
    className: "bg-slate-100 text-slate-700",
  },
  [FILE_STATUS.UPLOADING]: {
    label: "Uploading",
    Icon: Loader2,
    className: "bg-blue-100 text-blue-800",
    spin: true,
  },
  [FILE_STATUS.PROCESSING]: {
    label: "Processing",
    Icon: Loader2,
    className: "bg-amber-100 text-amber-800",
    spin: true,
  },
  [FILE_STATUS.ERROR]: {
    label: "Error",
    Icon: AlertCircle,
    className: "bg-red-100 text-red-800",
  },
};
