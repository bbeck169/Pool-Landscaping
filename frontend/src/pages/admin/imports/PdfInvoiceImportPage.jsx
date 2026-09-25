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
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  UploadCloud,
  FileText,
  ShieldCheck,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Clock,
  X,
  ChevronDown,
  ChevronUp,
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
  PREVIEW_READY: "preview_ready",
  ERROR: "error",
};


// Backend status → terminal check.  Any of these values, once
// observed on the batch, ends the poll loop for that file.
// See recon report §A.2 for the full status enum.
export const TERMINAL_BATCH_STATUSES = new Set([
  "preview_complete",
  "failed",
  "cancelled",
  "committing",         // once commit starts, the poller yields
  "committed",
  "commit_failed",
  "rolling_back",
  "rolled_back",
  "rollback_failed",
]);


// Poll-hint clamp (Ruling E.5) — honour backend hint but never
// slower than 15s (admin UI responsiveness) or faster than 3s
// (avoid hammering the backend rate limiter).
export const POLL_HINT_MIN_SECONDS = 3;
export const POLL_HINT_MAX_SECONDS = 15;

export function clampPollHint(hint) {
  const n = Number(hint);
  if (!isFinite(n) || n <= 0) return POLL_HINT_MIN_SECONDS;
  return Math.max(POLL_HINT_MIN_SECONDS,
                  Math.min(POLL_HINT_MAX_SECONDS, Math.floor(n)));
}


export function isTerminalStatus(status) {
  return TERMINAL_BATCH_STATUSES.has(String(status || ""));
}


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


/**
 * GET the current state of a batch.  Returns the sanitised row
 * from the backend (see recon report §A.2): carries ``status``,
 * ``stage``, and a computed ``progress_pct`` (0-100 int).
 *
 * Exported so the vitest can drive the poll loop without
 * mounting the component.  Failures throw with a translated
 * user message; the caller can retry on transient errors.
 */
export async function pollBatch(batchId, { baseUrl, token } = {}) {
  const BASE = baseUrl || process.env.REACT_APP_BACKEND_URL || "";
  const TOKEN = token || (
    typeof localStorage !== "undefined"
      ? (localStorage.getItem("token") || "")
      : ""
  );
  const res = await fetch(
    `${BASE}/api/imports/pdf-invoice/${encodeURIComponent(batchId)}`,
    {
      method: "GET",
      headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {},
    },
  );
  if (!res.ok) {
    let body = null;
    try { body = await res.json(); } catch { /* body empty */ }
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


/**
 * GET the pre-flight duplicates snapshot for a batch.  Returns
 * ``{ batch_id, duplicate_count, duplicates: [...] }`` per recon
 * report §A.3.  Each duplicate entry carries ``source_doc_index``
 * + ``existing_quote_id`` + ``doc_number`` + ``customer_id``.
 *
 * Exported so the vitest can drive the pre-flight surface
 * without mounting the component.
 */
export async function fetchDuplicates(batchId, { baseUrl, token } = {}) {
  const BASE = baseUrl || process.env.REACT_APP_BACKEND_URL || "";
  const TOKEN = token || (
    typeof localStorage !== "undefined"
      ? (localStorage.getItem("token") || "")
      : ""
  );
  const res = await fetch(
    `${BASE}/api/imports/pdf-invoice/${encodeURIComponent(batchId)}/duplicates`,
    {
      method: "GET",
      headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {},
    },
  );
  if (!res.ok) {
    let body = null;
    try { body = await res.json(); } catch { /* body empty */ }
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


/**
 * Format a decimal amount as US currency ``$1,234.56``.  Falls
 * back to ``—`` for null / undefined / non-numeric.
 */
export function formatCurrency(amount) {
  if (amount === null || amount === undefined) return "—";
  const n = Number(amount);
  if (!isFinite(n)) return "—";
  return n.toLocaleString("en-US", {
    style: "currency", currency: "USD",
  });
}


/**
 * Format an ISO date-ish string as ``Mar 14, 2026``.  Falls
 * back to ``—`` for null / undefined / invalid.
 */
export function formatIsoDate(dateStr) {
  if (!dateStr || typeof dateStr !== "string") return "—";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });
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
  // Track which PREVIEW_READY rows have their preview surface
  // expanded.  Set<fileId>.
  const [expandedIds, setExpandedIds] = useState(() => new Set());
  // Pool-slot counter kept in a ref so the pump can read/write it
  // synchronously without a re-render round-trip.
  const inFlightRef = useRef(0);
  // Fresh ref to the latest files snapshot so the poll loop can
  // read without stale-closure bugs.
  const filesRef = useRef(files);
  filesRef.current = files;
  // Poll-timer registry keyed by file id — used to cancel timers
  // on unmount or when a row leaves PROCESSING.
  const pollTimersRef = useRef(new Map());


  const toggleExpanded = useCallback((id) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);


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
    // Also cancel any pending poll timer for this row.
    const t = pollTimersRef.current.get(id);
    if (t) {
      clearTimeout(t);
      pollTimersRef.current.delete(id);
    }
  }, []);


  /**
   * Poll one file's batch until its backend status reaches a
   * terminal value (preview_complete / failed / cancelled /
   * commit_failed / rollback_failed / committed / rolled_back).
   *
   * Uses a self-scheduling setTimeout chain rather than a raw
   * setInterval so the next tick honours the FRESH
   * ``poll_hint_seconds`` value returned by the last response
   * (clamped 3-15s per Ruling E.5).  Transient errors are
   * absorbed with a scheduled retry — the loop only stops on
   * a terminal backend status or an explicit unmount.
   */
  const pollOne = useCallback(async (fileId) => {
    const current = filesRef.current.find((f) => f.id === fileId);
    if (!current || current.status !== FILE_STATUS.PROCESSING) {
      // Row was dismissed or already terminal — bail.
      return;
    }
    let scheduleNext = true;
    let hintSeconds = clampPollHint(current.poll_hint_seconds || 5);
    try {
      const batch = await pollBatch(current.batch_id);
      const nextHint = clampPollHint(batch.poll_hint_seconds || hintSeconds);
      hintSeconds = nextHint;
      if (isTerminalStatus(batch.status)) {
        scheduleNext = false;
        setFiles((prev) => prev.map((f) => {
          if (f.id !== fileId) return f;
          if (batch.status === "preview_complete") {
            return {
              ...f,
              status: FILE_STATUS.PREVIEW_READY,
              progress_pct: 100,
              stage: batch.stage || null,
              batch,
              poll_hint_seconds: nextHint,
            };
          }
          // Any other terminal state → ERROR with a
          // descriptive label so the operator can retry or
          // roll back.
          return {
            ...f,
            status: FILE_STATUS.ERROR,
            progress_pct: batch.progress_pct ?? null,
            stage: batch.stage || null,
            error: batch.error
              || batch.message
              || `Batch ended in ${batch.status}.`,
            batch,
            poll_hint_seconds: nextHint,
          };
        }));
      } else {
        // Still processing — merge the live progress values so
        // the row's progress bar + stage label move.
        setFiles((prev) => prev.map((f) => (
          f.id === fileId
            ? {
              ...f,
              progress_pct: batch.progress_pct ?? f.progress_pct ?? 0,
              stage: batch.stage || f.stage || null,
              poll_hint_seconds: nextHint,
            }
            : f
        )));
      }
    } catch {
      // Transient failure — do NOT flip to ERROR (network
      // hiccups happen).  Keep polling at the last known hint.
    }
    if (scheduleNext) {
      const timerId = setTimeout(() => pollOne(fileId),
                                  hintSeconds * 1000);
      pollTimersRef.current.set(fileId, timerId);
    } else {
      pollTimersRef.current.delete(fileId);
    }
  }, []);


  /**
   * Kick a poll loop whenever a file enters PROCESSING, and
   * cancel any orphaned timer when a file leaves PROCESSING
   * (either dismissed or flipped to a terminal state by the
   * loop itself).  Runs on every ``files`` change so the
   * managed set of active timers reflects the latest state.
   */
  useEffect(() => {
    const activeIds = new Set(
      files
        .filter((f) => f.status === FILE_STATUS.PROCESSING && f.batch_id)
        .map((f) => f.id),
    );
    // Start pollers for rows that just entered PROCESSING.
    for (const id of activeIds) {
      if (!pollTimersRef.current.has(id)) {
        // Sentinel value so a rapid re-render doesn't schedule
        // twice — the sentinel is replaced by the real timer id
        // when pollOne schedules the next tick.
        pollTimersRef.current.set(id, "pending");
        pollOne(id);
      }
    }
    // Cancel pollers for rows that left PROCESSING.
    for (const [id, timer] of pollTimersRef.current.entries()) {
      if (!activeIds.has(id) && timer !== "pending") {
        clearTimeout(timer);
        pollTimersRef.current.delete(id);
      }
    }
  }, [files, pollOne]);


  // Cancel every poller on unmount so a route change doesn't
  // leak timers.
  useEffect(() => {
    const timers = pollTimersRef.current;
    return () => {
      for (const t of timers.values()) {
        if (t && t !== "pending") clearTimeout(t);
      }
      timers.clear();
    };
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
          file.  Rendered as a lean rows-only list; each
          PREVIEW_READY row can expand a preview surface with a
          duplicate-highlighted table + summary chip. */}
      {hasFiles ? (
        <div
          data-testid="pdf-import-files-list"
          className="mt-6 space-y-2"
        >
          {files.map((f) => (
            <React.Fragment key={f.id}>
              <FileRow
                f={f}
                onRemove={removeFile}
                onToggleExpand={toggleExpanded}
                expanded={expandedIds.has(f.id)}
              />
              {f.status === FILE_STATUS.PREVIEW_READY
                && expandedIds.has(f.id)
                && f.batch ? (
                <PreviewSurface
                  fileId={f.id}
                  batch={f.batch}
                />
              ) : null}
            </React.Fragment>
          ))}
        </div>
      ) : null}
    </div>
  );
}


function FileRow({ f, onRemove, onToggleExpand, expanded }) {
  const canDismiss = f.status === FILE_STATUS.QUEUED
    || f.status === FILE_STATUS.ERROR
    || f.status === FILE_STATUS.PREVIEW_READY;
  const canExpand = f.status === FILE_STATUS.PREVIEW_READY
    && f.batch;
  const tone = STATUS_TONE[f.status] || STATUS_TONE.queued;
  const Icon = tone.Icon;
  const showProgress = f.status === FILE_STATUS.PROCESSING
    || f.status === FILE_STATUS.PREVIEW_READY;
  const progress = Math.max(0, Math.min(100,
    Number(f.progress_pct) || 0));
  return (
    <div
      data-testid={`pdf-import-file-row-${f.id}`}
      data-status={f.status}
      className="flex items-start gap-3 rounded-md border px-3 py-2"
      style={{
        borderColor: colors.border,
        backgroundColor: colors.surface,
      }}
    >
      <FileText size={16} style={{ color: colors.muted }} className="mt-1" />
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
          {f.status === FILE_STATUS.PROCESSING && f.stage
            ? ` · ${prettyStage(f.stage)}`
            : null}
        </div>
        {showProgress ? (
          <div
            className="mt-1.5 h-1.5 w-full rounded bg-slate-100 overflow-hidden"
            role="progressbar"
            aria-valuenow={progress}
            aria-valuemin="0"
            aria-valuemax="100"
            data-testid={`pdf-import-file-progress-${f.id}`}
          >
            <div
              className="h-full transition-[width] duration-300 ease-out"
              style={{
                width: `${progress}%`,
                backgroundColor: colors.brand,
              }}
            />
          </div>
        ) : null}
      </div>
      <span
        className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${tone.className}`}
        data-testid={`pdf-import-file-status-${f.id}`}
      >
        <Icon size={12} className={tone.spin ? "animate-spin" : ""} />
        {tone.label}
      </span>
      {canExpand ? (
        <button
          type="button"
          onClick={() => onToggleExpand(f.id)}
          className="ml-1 rounded p-1 hover:bg-black/5"
          data-testid={`pdf-import-file-expand-${f.id}`}
          aria-label={
            expanded ? `Collapse ${f.name} preview`
                     : `Expand ${f.name} preview`
          }
          aria-expanded={expanded ? "true" : "false"}
        >
          {expanded ? (
            <ChevronUp size={16} style={{ color: colors.muted }} />
          ) : (
            <ChevronDown size={16} style={{ color: colors.muted }} />
          )}
        </button>
      ) : null}
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


/**
 * Renders the dry-run preview table for one PREVIEW_READY batch.
 * On mount runs the pre-flight ``GET /duplicates`` fetch and
 * highlights matching rows in amber with a ``Duplicate`` pill
 * linking to the existing invoice.
 *
 * MVP scope (Ruling E.6): single-scroll table, no pagination /
 * virtualization.  ``max-h-[70vh] overflow-auto`` caps the
 * table height so the future commit/rollback footer stays on-
 * screen for large batches (typical is ~10 rows; scanned
 * batches hit 50+).
 */
function PreviewSurface({ fileId, batch }) {
  const [duplicates, setDuplicates] = useState(null); // null=loading, [] once resolved
  const [dupError, setDupError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchDuplicates(batch.id || batch.batch_id)
      .then((envelope) => {
        if (cancelled) return;
        setDuplicates(envelope?.duplicates || []);
      })
      .catch((err) => {
        if (cancelled) return;
        setDupError(err?.message
          || "Could not check for duplicates.");
        setDuplicates([]);
      });
    return () => { cancelled = true; };
  }, [batch]);

  const previews = Array.isArray(batch.mapper_previews)
    ? batch.mapper_previews : [];
  // Only ``quote_in``-mapped previews participate in dedup;
  // payment receipts (mapped_target=deferred_to_h4) render as
  // an info row.
  const invoicePreviews = previews.filter(
    (p) => p.mapped_target === "quote_in",
  );

  const dupIndex = useMemo(() => {
    const m = new Map();
    for (const d of (duplicates || [])) {
      m.set(d.source_doc_index, d);
    }
    return m;
  }, [duplicates]);

  const totalCount = invoicePreviews.length;
  const dupCount = dupIndex.size;

  return (
    <div
      data-testid={`pdf-import-preview-${fileId}`}
      className="rounded-md border px-4 py-3"
      style={{
        borderColor: colors.border,
        backgroundColor: colors.surfaceSecondary,
      }}
    >
      {/* Summary chip strip — "N duplicates / M total". */}
      <div
        data-testid={`pdf-import-preview-summary-${fileId}`}
        className="mb-3 flex flex-wrap items-center gap-3 text-xs"
      >
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-medium bg-slate-100 text-slate-700"
        >
          <FileText size={12} />
          {totalCount} row{totalCount === 1 ? "" : "s"}
        </span>
        <span
          className={
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-medium "
            + (dupCount > 0
              ? "bg-amber-100 text-amber-900"
              : "bg-slate-100 text-slate-500")
          }
          data-testid={`pdf-import-preview-dupchip-${fileId}`}
        >
          <AlertCircle size={12} />
          {dupCount} duplicate{dupCount === 1 ? "" : "s"}
        </span>
        {duplicates === null ? (
          <span
            className="inline-flex items-center gap-1.5 text-slate-500"
            data-testid={`pdf-import-preview-dup-loading-${fileId}`}
          >
            <Loader2 size={12} className="animate-spin" />
            Checking for duplicates…
          </span>
        ) : null}
        {dupError ? (
          <span
            className="inline-flex items-center gap-1.5 text-red-600"
            data-testid={`pdf-import-preview-dup-error-${fileId}`}
          >
            <AlertCircle size={12} />
            {dupError}
          </span>
        ) : null}
      </div>

      {totalCount === 0 ? (
        <div className="text-sm" style={{ color: colors.muted }}>
          No invoice rows extracted from this PDF (may be a
          payment receipt — Phase H.4 handles those separately).
        </div>
      ) : (
        <div
          className="max-h-[70vh] overflow-auto rounded"
          style={{ backgroundColor: colors.surface }}
        >
          <table
            data-testid={`pdf-import-preview-table-${fileId}`}
            className="w-full text-sm"
          >
            <thead
              style={{
                backgroundColor: colors.surfaceSecondary,
                color: colors.onSurfaceSecondary,
              }}
            >
              <tr>
                <th className="px-3 py-2 text-left font-medium">Invoice #</th>
                <th className="px-3 py-2 text-left font-medium">Date</th>
                <th className="px-3 py-2 text-right font-medium">Total</th>
                <th className="px-3 py-2 text-left font-medium">Customer</th>
                <th className="px-3 py-2 text-left font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {invoicePreviews.map((p) => (
                <PreviewRow
                  key={p.source_doc_index}
                  preview={p}
                  duplicate={dupIndex.get(p.source_doc_index)}
                  fileId={fileId}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


function PreviewRow({ preview, duplicate, fileId }) {
  const isDup = Boolean(duplicate);
  const q = preview.quote_in || {};
  return (
    <tr
      data-testid={`pdf-import-preview-row-${fileId}-${preview.source_doc_index}`}
      data-source-index={preview.source_doc_index}
      data-duplicate={isDup ? "true" : "false"}
      className={
        isDup ? "bg-amber-50 text-amber-900"
              : "hover:bg-black/2"
      }
      style={{ borderTop: `1px solid ${colors.border}` }}
    >
      <td className="px-3 py-2 font-mono">
        {q.doc_number || "—"}
      </td>
      <td className="px-3 py-2">
        {formatIsoDate(q.doc_date)}
      </td>
      <td className="px-3 py-2 text-right">
        {formatCurrency(q.total_due ?? q.amount_paid)}
      </td>
      <td className="px-3 py-2">
        <CustomerCell preview={preview} />
      </td>
      <td className="px-3 py-2">
        {isDup ? (
          <a
            href={`/invoices/${duplicate.existing_quote_id}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-900 hover:bg-amber-200"
            data-testid={`pdf-import-preview-dup-link-${fileId}-${preview.source_doc_index}`}
          >
            <AlertCircle size={12} />
            Duplicate
          </a>
        ) : (
          <span
            className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium bg-emerald-50 text-emerald-800"
          >
            <CheckCircle2 size={12} />
            New
          </span>
        )}
      </td>
    </tr>
  );
}


function CustomerCell({ preview }) {
  const q = preview.quote_in || {};
  const name = q.customer_name || "—";
  const resolution = preview.customer_resolution;
  if (resolution === "matched") {
    return (
      <span className="text-sm" style={{ color: colors.onSurface }}>
        {name}
      </span>
    );
  }
  if (resolution === "pending") {
    return (
      <span className="text-sm text-slate-600">
        {name}
        <span
          className="ml-1.5 inline-flex items-center rounded-full bg-slate-100 px-1.5 py-0 text-[10px] font-medium text-slate-700"
        >
          Pending
        </span>
      </span>
    );
  }
  return (
    <span className="text-sm text-red-700">
      {name}
      <span
        className="ml-1.5 inline-flex items-center rounded-full bg-red-100 px-1.5 py-0 text-[10px] font-medium text-red-800"
      >
        Unresolved
      </span>
    </span>
  );
}


/**
 * Pretty-print the backend ``stage`` string.  Values arrive as
 * ``segmentation`` / ``extraction N/M`` / ``mapping N/M`` /
 * ``persisting`` (see recon report §A.2) — capitalise + retain
 * the N/M suffix so operators see 'Extraction 3/7' etc.
 */
export function prettyStage(stage) {
  if (typeof stage !== "string" || !stage) return "";
  const m = stage.match(/^([a-z_]+)(?:\s+(\d+\/\d+))?$/i);
  if (!m) return stage;
  const [, verb, suffix] = m;
  const label = verb.replace(/_/g, " ")
                    .replace(/\b\w/g, (c) => c.toUpperCase());
  return suffix ? `${label} ${suffix}` : label;
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
  [FILE_STATUS.PREVIEW_READY]: {
    label: "Preview ready",
    Icon: CheckCircle2,
    className: "bg-emerald-100 text-emerald-800",
  },
  [FILE_STATUS.ERROR]: {
    label: "Error",
    Icon: AlertCircle,
    className: "bg-red-100 text-red-800",
  },
};
