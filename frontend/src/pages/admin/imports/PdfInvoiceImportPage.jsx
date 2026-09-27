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
  AlertTriangle,
  CheckCircle2,
  Clock,
  History,
  X,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Layers,
  RefreshCw,
} from "lucide-react";
import { PageHeader, Button } from "@/components/ui-kit";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
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
  COMMITTING: "committing",
  COMMITTED: "committed",
  ROLLING_BACK: "rolling_back",
  ROLLED_BACK: "rolled_back",
  ERROR: "error",
};


// Valid ``on_duplicate`` modes for the commit endpoint
// (see recon report §A.4).  Default is ``skip`` per Ruling
// E.6 — the safe choice for an admin who wants dedup to
// Just Work.
export const ON_DUPLICATE_MODES = ["skip", "insert_anyway", "fail"];
export const DEFAULT_ON_DUPLICATE = "skip";


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
  // Commit-endpoint typed errors — Ruling from recon report §A.4.
  if (code === "invalid_on_duplicate") {
    return "Unexpected duplicate-handling mode.  Refresh and retry.";
  }
  if (code === "batch_wrong_status") {
    return "Batch is no longer in preview — refresh to see its "
      + "current state.";
  }
  if (code === "unresolved_customers") {
    return "Some invoices still have unresolved customer matches. "
      + "Resolve them before committing.";
  }
  if (code === "duplicates_detected") {
    return "Duplicates detected — change the on-duplicate mode "
      + "to Skip or Insert Anyway and retry.";
  }
  if (code === "batch_not_committed") {
    return "This batch is not in a committed state — rollback "
      + "is only available for committed batches.";
  }
  if (code === "batch_not_found") {
    return "Batch not found.  It may have been rolled back or "
      + "deleted.";
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
 * POST the commit endpoint for one batch.  Payload carries the
 * ``on_duplicate`` mode (recon report §A.4).  Returns the
 * success envelope (\`\`quotes_created\`\`, ``quotes_skipped_*``,
 * ``quote_ids``, ``audit_id``) or throws with the translated
 * typed-error message.
 *
 * A 409 ``duplicates_detected`` (only fires when
 * ``on_duplicate === "fail"`` and duplicates exist) attaches the
 * duplicates array to the thrown Error's ``.detail.duplicates``
 * so the caller can render them inline.
 */
export async function commitBatch(batchId, {
  onDuplicate = DEFAULT_ON_DUPLICATE,
  notes = null,
  baseUrl,
  token,
} = {}) {
  const BASE = baseUrl || process.env.REACT_APP_BACKEND_URL || "";
  const TOKEN = token || (
    typeof localStorage !== "undefined"
      ? (localStorage.getItem("token") || "")
      : ""
  );
  const body = { on_duplicate: onDuplicate };
  if (notes) body.notes = notes;
  const res = await fetch(
    `${BASE}/api/imports/pdf-invoice/${encodeURIComponent(batchId)}/commit`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
      },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    let respBody = null;
    try { respBody = await res.json(); } catch { /* body empty */ }
    const inner = (respBody && typeof respBody === "object"
        && respBody.detail !== undefined)
      ? respBody.detail
      : respBody;
    const err = new Error(messageForUploadError(res.status, inner));
    err.status = res.status;
    err.detail = inner;
    throw err;
  }
  return await res.json();
}


/**
 * POST the rollback endpoint for one committed batch.  Returns
 * ``{ batch_id, status, quotes_deleted, collision_count,
 * audit_id }`` on success (recon §A.5).  No time-window guard
 * — rollback is available indefinitely so long as the batch is
 * in ``committed`` (Ruling E.3).
 */
export async function rollbackBatch(batchId, { baseUrl, token } = {}) {
  const BASE = baseUrl || process.env.REACT_APP_BACKEND_URL || "";
  const TOKEN = token || (
    typeof localStorage !== "undefined"
      ? (localStorage.getItem("token") || "")
      : ""
  );
  const res = await fetch(
    `${BASE}/api/imports/pdf-invoice/${encodeURIComponent(batchId)}/rollback`,
    {
      method: "POST",
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
 * Compute whether a committed batch is inside the
 * "safer to rollback" 24-hour window (Ruling E.3).  Returns:
 *
 *   * ``true`` — committed less than 24 h ago (safe zone)
 *   * ``false`` — either not committed OR more than 24 h old
 *
 * The rollback button stays enabled regardless — this only
 * gates the tooltip copy.
 */
export function isWithin24hRollbackWindow(committedAt, now = Date.now()) {
  if (!committedAt || typeof committedAt !== "string") return false;
  const t = new Date(committedAt).getTime();
  if (!isFinite(t)) return false;
  const nowT = now instanceof Date ? now.getTime() : now;
  return (nowT - t) < (24 * 60 * 60 * 1000);
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


  const handleCommitStart = useCallback((id) => {
    setFiles((prev) => prev.map(
      (f) => (f.id === id ? { ...f, status: FILE_STATUS.COMMITTING } : f),
    ));
  }, []);

  const handleCommitSuccess = useCallback((id, envelope) => {
    setFiles((prev) => prev.map(
      (f) => (f.id === id
        ? {
          ...f,
          status: FILE_STATUS.COMMITTED,
          commit_outcome: envelope,
          committed_at: new Date().toISOString(),
        }
        : f),
    ));
  }, []);

  const handleCommitFailure = useCallback((id) => {
    // Revert row to PREVIEW_READY so the operator can adjust
    // the on-duplicate mode and retry.  The PreviewSurface
    // keeps the inline error copy.
    setFiles((prev) => prev.map(
      (f) => (f.id === id ? { ...f, status: FILE_STATUS.PREVIEW_READY } : f),
    ));
  }, []);

  const handleRollbackStart = useCallback((id) => {
    setFiles((prev) => prev.map(
      (f) => (f.id === id ? { ...f, status: FILE_STATUS.ROLLING_BACK } : f),
    ));
  }, []);

  const handleRollbackSuccess = useCallback((id, envelope) => {
    setFiles((prev) => prev.map(
      (f) => (f.id === id
        ? {
          ...f,
          status: FILE_STATUS.ROLLED_BACK,
          rollback_outcome: envelope,
        }
        : f),
    ));
  }, []);

  const handleRollbackFailure = useCallback((id) => {
    // Revert to COMMITTED so the operator can retry.  The
    // PreviewSurface itself doesn't render a rollback-error
    // pill — the row-level ERROR trail would double it up.
    // A future commit can surface the copy inline.
    setFiles((prev) => prev.map(
      (f) => (f.id === id ? { ...f, status: FILE_STATUS.COMMITTED } : f),
    ));
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
          {files.map((f) => {
            const surfaceVisible = [
              FILE_STATUS.PREVIEW_READY,
              FILE_STATUS.COMMITTING,
              FILE_STATUS.COMMITTED,
              FILE_STATUS.ROLLING_BACK,
              FILE_STATUS.ROLLED_BACK,
            ].includes(f.status);
            return (
              <React.Fragment key={f.id}>
                <FileRow
                  f={f}
                  onRemove={removeFile}
                  onToggleExpand={toggleExpanded}
                  expanded={expandedIds.has(f.id)}
                />
                {surfaceVisible && expandedIds.has(f.id) && f.batch ? (
                  <PreviewSurface
                    fileId={f.id}
                    batch={f.batch}
                    fileStatus={f.status}
                    fileMeta={f}
                    onCommitStart={handleCommitStart}
                    onCommitSuccess={handleCommitSuccess}
                    onCommitFailure={handleCommitFailure}
                    onRollbackStart={handleRollbackStart}
                    onRollbackSuccess={handleRollbackSuccess}
                    onRollbackFailure={handleRollbackFailure}
                  />
                ) : null}
              </React.Fragment>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}


function FileRow({ f, onRemove, onToggleExpand, expanded }) {
  const canDismiss = f.status === FILE_STATUS.QUEUED
    || f.status === FILE_STATUS.ERROR
    || f.status === FILE_STATUS.PREVIEW_READY
    || f.status === FILE_STATUS.ROLLED_BACK;
  const canExpand = [
    FILE_STATUS.PREVIEW_READY,
    FILE_STATUS.COMMITTING,
    FILE_STATUS.COMMITTED,
    FILE_STATUS.ROLLING_BACK,
    FILE_STATUS.ROLLED_BACK,
  ].includes(f.status) && f.batch;
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
function PreviewSurface({ fileId, batch, onCommitStart, onCommitSuccess, onCommitFailure, onRollbackStart, onRollbackSuccess, onRollbackFailure, fileStatus, fileMeta }) {
  const [duplicates, setDuplicates] = useState(null); // null=loading, [] once resolved
  const [dupError, setDupError] = useState(null);
  const [onDuplicate, setOnDuplicate] = useState(DEFAULT_ON_DUPLICATE);
  const [commitError, setCommitError] = useState(null);
  const [commitErrorStatus, setCommitErrorStatus] = useState(null);
  const [commitOutcome, setCommitOutcome] = useState(null);
  // PDF-FIX-B · Feb-2026 — per-source-doc-index expansion state
  // for the line-items detail row. Matches the top-level file-
  // row pattern (``expandedIds``, line ~511) so the two toggles
  // read consistently.
  const [expandedPreviewIds, setExpandedPreviewIds] = useState(
    () => new Set(),
  );
  const togglePreviewExpanded = useCallback((sourceIdx) => {
    setExpandedPreviewIds((prev) => {
      const next = new Set(prev);
      if (next.has(sourceIdx)) next.delete(sourceIdx);
      else next.add(sourceIdx);
      return next;
    });
  }, []);

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

  const isCommitting = fileStatus === FILE_STATUS.COMMITTING;
  const isCommitted  = fileStatus === FILE_STATUS.COMMITTED;
  const isRollingBack = fileStatus === FILE_STATUS.ROLLING_BACK;
  const isRolledBack  = fileStatus === FILE_STATUS.ROLLED_BACK;
  const isTerminal    = isCommitted || isRolledBack;

  const handleCommit = useCallback(async () => {
    setCommitError(null);
    setCommitErrorStatus(null);
    onCommitStart?.(fileId);
    try {
      const envelope = await commitBatch(batch.id || batch.batch_id, {
        onDuplicate,
      });
      setCommitOutcome(envelope);
      onCommitSuccess?.(fileId, envelope);
    } catch (err) {
      setCommitError(err?.message || "Commit failed.");
      setCommitErrorStatus(err?.status || null);
      onCommitFailure?.(fileId, err);
    }
  }, [batch, fileId, onDuplicate, onCommitStart,
      onCommitSuccess, onCommitFailure]);

  const handleRollback = useCallback(async () => {
    onRollbackStart?.(fileId);
    try {
      const envelope = await rollbackBatch(batch.id || batch.batch_id);
      onRollbackSuccess?.(fileId, envelope);
    } catch (err) {
      onRollbackFailure?.(fileId, err);
    }
  }, [batch, fileId, onRollbackStart,
      onRollbackSuccess, onRollbackFailure]);

  // Rollback safe-window tooltip copy (Ruling E.3).  The button
  // stays enabled regardless; the tooltip flips its copy once
  // more than 24 h has passed since ``committed_at``.
  const committedAt = fileMeta?.committed_at || null;
  const withinWindow = isWithin24hRollbackWindow(committedAt);
  const rollbackTitle = committedAt && !withinWindow
    ? ("Rollback is available indefinitely, but is safer within "
      + "24h of commit — later rollbacks may collide with edits.")
    : "Roll back this batch — deletes every invoice created "
      + "by this import.";

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
        <>
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
                    expanded={expandedPreviewIds.has(p.source_doc_index)}
                    onToggle={togglePreviewExpanded}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* Commit / Rollback footer. */}
          <div
            className="mt-3 flex flex-col gap-3 text-sm"
            data-testid={`pdf-import-preview-actions-${fileId}`}
          >
            {isTerminal ? (
              <>
                {/* Unified committed summary (PDF-E). Renders when
                    the commit response carries the ``committed``
                    per-doc-type block. Falls back to the legacy
                    single-pill for pre-PDF-C response shapes so
                    older tests + audit-log replays stay green. */}
                {isCommitted && commitOutcome?.committed ? (
                  <CommittedSummary
                    fileId={fileId}
                    outcome={commitOutcome}
                    batchId={batch.id || batch.batch_id}
                    tileSummary={batch.tile_summary}
                  />
                ) : null}
                {/* Legacy committed pill — always rendered on
                    ``isCommitted`` so the integration test at
                    ``pdf-invoice-import-integration.test.jsx``
                    (which uses a legacy response shape) keeps
                    matching the ``preview-committed-badge`` test-
                    id + " · N created" copy. */}
                <div className="flex flex-wrap items-center gap-3">
                  {isCommitted ? (
                    <span
                      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium bg-emerald-100 text-emerald-800"
                      data-testid={`pdf-import-preview-committed-badge-${fileId}`}
                    >
                      <CheckCircle2 size={12} />
                      Committed
                      {commitOutcome?.quotes_created !== undefined
                        ? ` · ${commitOutcome.quotes_created} created`
                        : null}
                      {commitOutcome?.quotes_skipped_duplicates
                        ? ` · ${commitOutcome.quotes_skipped_duplicates} skipped`
                        : null}
                    </span>
                  ) : null}
                  {isRolledBack ? (
                    <span
                      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium bg-slate-200 text-slate-800"
                      data-testid={`pdf-import-preview-rolledback-badge-${fileId}`}
                    >
                      <History size={12} />
                      Rolled back
                    </span>
                  ) : null}
                  {isCommitted ? (
                    <Button
                      variant="secondary"
                      onClick={handleRollback}
                      disabled={isRollingBack}
                      testid={`pdf-import-rollback-btn-${fileId}`}
                      title={rollbackTitle}
                    >
                      {isRollingBack ? (
                        <span className="inline-flex items-center gap-1.5">
                          <Loader2 size={14} className="animate-spin" />
                          Rolling back…
                        </span>
                      ) : "Rollback"}
                    </Button>
                  ) : null}
                </div>
              </>
            ) : (
              <>
                {/* PDF-E · Whole-commit failure banner (5xx). Shown
                    above the retry-friendly on-duplicate strip so
                    the operator sees a clear "server failed, retry?"
                    call-to-action separate from the inline typed-
                    error pill used for 4xx validation failures. */}
                {commitError && commitErrorStatus && commitErrorStatus >= 500 ? (
                  <CommitErrorBanner
                    fileId={fileId}
                    error={commitError}
                    uploadedFilename={fileMeta?.name}
                    onRetry={handleCommit}
                    disabled={isCommitting}
                  />
                ) : null}
                <div className="flex flex-wrap items-center gap-3">
                  {/* On-duplicate radio group. */}
                  <div
                    className="flex flex-wrap items-center gap-3 text-xs"
                    data-testid={`pdf-import-preview-on-dup-${fileId}`}
                  >
                    <span
                      className="font-medium"
                      style={{ color: colors.muted }}
                    >
                      On duplicate:
                    </span>
                    {ON_DUPLICATE_MODES.map((mode) => (
                      <label
                        key={mode}
                        className="inline-flex items-center gap-1.5 cursor-pointer"
                        data-testid={`pdf-import-on-dup-${mode}-${fileId}`}
                      >
                        <input
                          type="radio"
                          name={`on-dup-${fileId}`}
                          value={mode}
                          checked={onDuplicate === mode}
                          onChange={() => setOnDuplicate(mode)}
                          disabled={isCommitting}
                          className="cursor-pointer"
                        />
                        <span
                          className={onDuplicate === mode
                            ? "font-semibold" : ""}
                          style={{ color: colors.onSurface }}
                        >
                          {ON_DUPLICATE_LABELS[mode]}
                        </span>
                      </label>
                    ))}
                  </div>
                  {commitError && (!commitErrorStatus || commitErrorStatus < 500) ? (
                    <span
                      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium bg-red-100 text-red-800"
                      data-testid={`pdf-import-preview-commit-error-${fileId}`}
                    >
                      <AlertCircle size={12} />
                      {commitError}
                    </span>
                  ) : null}
                  <div className="ml-auto">
                    <Button
                      variant="primary"
                      onClick={handleCommit}
                      disabled={isCommitting}
                      testid={`pdf-import-commit-btn-${fileId}`}
                    >
                      {isCommitting ? (
                        <span className="inline-flex items-center gap-1.5">
                          <Loader2 size={14} className="animate-spin" />
                          Committing…
                        </span>
                      ) : (
                        `Commit ${totalCount} invoice${totalCount === 1 ? "" : "s"}`
                      )}
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}


// Human copy for the on-duplicate radio group.
const ON_DUPLICATE_LABELS = {
  skip: "Skip",
  insert_anyway: "Insert anyway",
  fail: "Fail (halt commit)",
};


export function PreviewRow({
  preview, duplicate, fileId,
  expanded = false, onToggle = () => {},
}) {
  const isDup = Boolean(duplicate);
  const q = preview.quote_in || {};
  const sourceIdx = preview.source_doc_index;
  const lineItems = Array.isArray(q.line_items) ? q.line_items : [];
  // PDF-FIX-B · Feb-2026 — drop line items that carry neither
  // ``item_name`` NOR a non-empty ``description``.  Per rulings
  // §2 (Neither → line item drops from view — silently, no
  // banner). Prevents "empty rows" from cluttering the preview.
  const renderableItems = lineItems.filter((li) => {
    const hasName = Boolean(li && li.item_name);
    const hasDesc = Boolean(li && (li.description || "").trim());
    return hasName || hasDesc;
  });
  return (
    <React.Fragment>
    <tr
      data-testid={`pdf-import-preview-row-${fileId}-${sourceIdx}`}
      data-source-index={sourceIdx}
      data-duplicate={isDup ? "true" : "false"}
      className={
        isDup ? "bg-amber-50 text-amber-900"
              : "hover:bg-black/2"
      }
      style={{ borderTop: `1px solid ${colors.border}` }}
    >
      <td className="px-3 py-2 font-mono">
        {/* PDF-FIX-B · Feb-2026 — chevron toggle for the line-items
            detail row.  Icon SWAP (not CSS rotate) to match the
            ``FileRow`` precedent at ~L995. ``aria-expanded`` keeps
            the button screenreader-labelled per the same pattern. */}
        <button
          type="button"
          onClick={() => onToggle(sourceIdx)}
          className="mr-2 inline-flex h-5 w-5 items-center justify-center rounded hover:bg-black/5"
          aria-label={expanded ? "Collapse line items" : "Expand line items"}
          aria-expanded={expanded ? "true" : "false"}
          data-testid={`pdf-import-line-items-toggle-${fileId}-${sourceIdx}`}
        >
          {expanded ? (
            <ChevronUp size={14} style={{ color: colors.muted }} />
          ) : (
            <ChevronDown size={14} style={{ color: colors.muted }} />
          )}
        </button>
        {q.doc_number || "—"}
      </td>
      <td className="px-3 py-2">
        {formatIsoDate(q.doc_date)}
      </td>
      <td className="px-3 py-2 text-right" data-testid={`pdf-import-preview-row-${fileId}-${preview.source_doc_index}-total`}>
        {/* PDF-FIX-A · Feb-2026 — Total column prioritises the
            extractor's ``grand_total`` (the "Total" / "Total Due"
            line on the source PDF) over the legacy ``total_due``,
            which is $0.00 on fully-paid invoices. Falls back to
            ``total_due`` → ``amount_paid`` (Sub-phase B legacy path
            for fully-paid receipts) → 0. ``??`` treats 0 as valid,
            so a legitimately-waived invoice (grand_total = 0)
            still renders as "$0.00" verbatim per PDF-FIX §1. */}
        {formatCurrency(q.grand_total ?? q.total_due ?? q.amount_paid ?? 0)}
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
    {expanded ? (
      <tr
        data-testid={`pdf-import-line-items-expanded-${fileId}-${sourceIdx}`}
        style={{ borderTop: `1px solid ${colors.border}` }}
      >
        <td colSpan={5} className="px-3 py-3" style={{ backgroundColor: colors.surfaceSecondary }}>
          {renderableItems.length === 0 ? (
            <div
              className="text-sm italic"
              style={{ color: colors.muted }}
              data-testid={`pdf-import-line-items-empty-${fileId}-${sourceIdx}`}
            >
              No line items extracted
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr style={{ color: colors.muted }}>
                  <th className="px-2 py-1 text-left font-medium">Item Name</th>
                  <th className="px-2 py-1 text-left font-medium">Description</th>
                  <th className="px-2 py-1 text-right font-medium">Qty</th>
                  <th className="px-2 py-1 text-right font-medium">Unit</th>
                  <th className="px-2 py-1 text-right font-medium">Line $</th>
                </tr>
              </thead>
              <tbody>
                {renderableItems.map((li, idx) => {
                  // Rulings §2: both name+desc → both render.
                  //             name-only → "—" in desc col.
                  //             desc-only → desc renders in name col
                  //               (fallback), "—" in desc col.
                  const hasName = Boolean(li.item_name);
                  const nameCell = hasName ? li.item_name : li.description;
                  const descCell = hasName ? (li.description || "—") : "—";
                  const qty = Number(li.quantity ?? 0);
                  const unit = Number(li.unit_price ?? 0);
                  // PDF-FIX-D · Feb-2026 — prefer the extractor's
                  // verbatim ``line_total`` (may reflect PDF
                  // discounts / rounding invisible to a naive
                  // ``qty × unit`` computation) over the FE fallback
                  // math.  ``??`` treats ``0`` as valid — a
                  // legitimately-zero line still renders "$0.00".
                  const lineTotal = li.line_total ?? qty * unit;
                  return (
                    <tr key={idx}>
                      <td
                        className="px-2 py-1"
                        data-testid={`pdf-import-line-item-${fileId}-${sourceIdx}-${idx}-name`}
                      >
                        {nameCell}
                      </td>
                      <td
                        className="px-2 py-1"
                        data-testid={`pdf-import-line-item-${fileId}-${sourceIdx}-${idx}-description`}
                      >
                        {descCell}
                      </td>
                      <td
                        className="px-2 py-1 text-right font-mono"
                        data-testid={`pdf-import-line-item-${fileId}-${sourceIdx}-${idx}-qty`}
                      >
                        {qty}
                      </td>
                      <td
                        className="px-2 py-1 text-right font-mono"
                        data-testid={`pdf-import-line-item-${fileId}-${sourceIdx}-${idx}-price`}
                      >
                        {formatCurrency(unit)}
                      </td>
                      <td
                        className="px-2 py-1 text-right font-mono"
                        data-testid={`pdf-import-line-item-${fileId}-${sourceIdx}-${idx}-line-total`}
                      >
                        {formatCurrency(lineTotal)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </td>
      </tr>
    ) : null}
    </React.Fragment>
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

// ═════════════════════════════════════════════════════════════
// PDF Importer Sub-phase E · Feb-2026 — Unified commit-result UI
// ─────────────────────────────────────────────────────────────
// The four sub-components below render the post-commit dashboard
// that replaces the pre-E single-pill summary. Every component
// is a pure render of props (no local fetching) so the parent
// ``PreviewSurface`` owns the data lifecycle and these can be
// mounted directly in vitest for tight per-component assertions.
//
// Rendering rules:
//
//   * ``CommittedSummary``      — always shown once the commit
//     response carries a ``committed`` block (PDF-C shape).
//   * ``WarningsBanner``        — shown iff ``warnings.length > 0``.
//   * ``TileSummarySection``    — shown iff a non-null
//     ``tile_summary`` was persisted onto the batch row (PDF-D,
//     only for PDFs > 36 pages).
//   * ``ErrorsPerTypeSection``  — shown iff either
//     ``insert_errors[]`` or ``committed.payments.errors[]`` is
//     non-empty.
//   * ``CommitErrorBanner``     — shown iff a whole-commit 5xx
//     failure surfaced. Preserves the uploaded file in row state
//     via the parent's existing revert-to-PREVIEW_READY logic so
//     the retry is one click.
// ═════════════════════════════════════════════════════════════


/**
 * PDF-E — Three count cards + per-type deep-links.
 *
 * Renders side-by-side stat cards for invoices / estimates /
 * payments with click-to-navigate behaviour (each card links to
 * the corresponding admin list page filtered by
 * ``import_batch_id``). Payments card carries a secondary
 * ``unlinked`` count (payments that landed without a matching
 * invoice — needs operator review before dispatch).
 *
 * Backward-compat: this component is only rendered when
 * ``outcome.committed`` is present. Pre-PDF-C responses fall
 * through to the legacy single-pill in ``PreviewSurface``.
 */
export function CommittedSummary({ fileId, outcome, batchId, tileSummary }) {
  const committed = outcome?.committed || {};
  const invoices = committed.invoices || {};
  const estimates = committed.estimates || {};
  const payments = committed.payments || {};
  const warnings = Array.isArray(outcome?.warnings)
    ? outcome.warnings : [];
  const insertErrors = Array.isArray(outcome?.insert_errors)
    ? outcome.insert_errors : [];
  const paymentErrors = Array.isArray(payments.errors)
    ? payments.errors : [];

  const hrefFor = (target) => (batchId
    ? `/${target}?import_batch_id=${encodeURIComponent(batchId)}`
    : null);

  return (
    <div
      data-testid={`pdf-import-committed-${fileId}`}
      className="flex flex-col gap-3"
    >
      <div
        className="grid grid-cols-1 gap-3 md:grid-cols-3"
        data-testid={`pdf-import-committed-cards-${fileId}`}
      >
        <CountCard
          fileId={fileId}
          testidSuffix="invoices"
          label="Invoices"
          created={Number(invoices.created || 0)}
          updated={0}
          errors={insertErrors.length}
          href={hrefFor("invoices")}
        />
        <CountCard
          fileId={fileId}
          testidSuffix="estimates"
          label="Estimates"
          created={Number(estimates.created || 0)}
          updated={0}
          errors={0}
          href={hrefFor("estimates")}
        />
        <CountCard
          fileId={fileId}
          testidSuffix="payments"
          label="Payments"
          created={Number(payments.created || 0)}
          updated={Number(payments.updated || 0)}
          errors={paymentErrors.length}
          unlinked={Number(payments.unlinked || 0)}
          href={hrefFor("payments")}
        />
      </div>
      {warnings.length > 0 ? (
        <WarningsBanner fileId={fileId} warnings={warnings} />
      ) : null}
      {tileSummary ? (
        <TileSummarySection fileId={fileId} tileSummary={tileSummary} />
      ) : null}
      {(insertErrors.length > 0 || paymentErrors.length > 0) ? (
        <ErrorsPerTypeSection
          fileId={fileId}
          insertErrors={insertErrors}
          paymentErrors={paymentErrors}
        />
      ) : null}
    </div>
  );
}


/**
 * PDF-E — One count card (invoices / estimates / payments).
 * Rendered as a semantic ``<a>`` when ``href`` is present so
 * click-through works without a Router context (deep-link
 * navigates via native browser). Renders as a non-clickable
 * ``<div>`` when ``href`` is null — keeps 0-count cards
 * visible without misleading affordance.
 */
function CountCard({ fileId, testidSuffix, label, created, updated, errors, unlinked, href }) {
  const isClickable = Boolean(href);
  const commonClass = "group flex items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left transition";
  const clickableClass = isClickable
    ? " hover:brightness-110 cursor-pointer"
    : " cursor-default";
  const style = {
    borderColor: colors.border,
    backgroundColor: colors.brand || "#1B1F5C",
    color: "#F8FAFF",
  };
  const inner = (
    <>
      <div className="flex flex-col gap-0.5">
        <span className="text-xs font-medium uppercase tracking-wider opacity-75">
          {label}
        </span>
        <span className="text-2xl font-semibold leading-none">
          {created}
        </span>
        <span className="text-[11px] leading-tight opacity-80">
          {`created${updated ? ` · ${updated} updated` : ""}${errors ? ` · ${errors} errors` : ""}`}
        </span>
        {unlinked !== undefined && unlinked > 0 ? (
          <span
            className="mt-1 inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold"
            style={{
              backgroundColor: "#FEF3C7",
              color: "#78350F",
            }}
            data-testid={`pdf-import-payments-unlinked-${fileId}`}
          >
            <AlertTriangle size={10} />
            {unlinked} unlinked
          </span>
        ) : null}
      </div>
      {isClickable ? (
        <ExternalLink
          size={14}
          className="opacity-60 transition group-hover:opacity-100"
        />
      ) : null}
    </>
  );
  if (isClickable) {
    return (
      <a
        href={href}
        data-testid={`pdf-import-count-${testidSuffix}-${fileId}`}
        className={commonClass + clickableClass}
        style={style}
      >
        {inner}
      </a>
    );
  }
  return (
    <div
      data-testid={`pdf-import-count-${testidSuffix}-${fileId}`}
      className={commonClass + clickableClass}
      style={style}
    >
      {inner}
    </div>
  );
}


/**
 * PDF-E — Amber warnings banner. Wraps the shadcn ``Alert``
 * primitive with amber styling + a browser-native ``<details>``
 * collapse so the banner starts collapsed on batches with lots
 * of warnings (a common scanner-batch scenario) and opens on
 * click without extra state juggling.
 */
export function WarningsBanner({ fileId, warnings }) {
  const list = Array.isArray(warnings) ? warnings : [];
  if (list.length === 0) return null;
  return (
    <Alert
      data-testid={`pdf-import-warnings-banner-${fileId}`}
      className="border-amber-300 bg-amber-50 text-amber-900"
    >
      <AlertTriangle className="h-4 w-4 text-amber-700" />
      <AlertTitle className="text-amber-900">
        {`${list.length} warning${list.length === 1 ? "" : "s"} — review before dispatch`}
      </AlertTitle>
      <AlertDescription>
        <details className="mt-1 group">
          <summary
            className="cursor-pointer list-none text-xs font-medium underline underline-offset-2 group-open:mb-2"
            data-testid={`pdf-import-warnings-toggle-${fileId}`}
          >
            <span className="group-open:hidden">Show all</span>
            <span className="hidden group-open:inline">Hide details</span>
          </summary>
          <ul className="flex flex-col gap-1 text-xs">
            {list.map((w, idx) => (
              <li
                key={idx}
                data-testid={`pdf-import-warning-item-${fileId}`}
                className="flex gap-2"
              >
                <span className="font-mono text-amber-800">
                  {typeof w === "string" ? "" : (w?.code ? `${w.code}:` : "")}
                </span>
                <span>
                  {typeof w === "string"
                    ? w
                    : (w?.message || w?.code || JSON.stringify(w))}
                </span>
              </li>
            ))}
          </ul>
        </details>
      </AlertDescription>
    </Alert>
  );
}


/**
 * PDF-E — Tile summary section. Renders the per-tile
 * segmentation stats persisted by ``pdf_tiled_extractor`` for
 * PDFs whose page count exceeded ``TILE_PAGE_THRESHOLD``
 * (currently 36). Small-PDF batches see nothing (this
 * component returns null when ``tileSummary`` is falsy).
 */
export function TileSummarySection({ fileId, tileSummary }) {
  if (!tileSummary || typeof tileSummary !== "object") return null;
  const tileWarnings = Array.isArray(tileSummary.warnings)
    ? tileSummary.warnings : [];
  return (
    <div
      data-testid={`pdf-import-tile-summary-${fileId}`}
      className="rounded-xl border p-4"
      style={{
        borderColor: colors.border,
        backgroundColor: colors.surface,
      }}
    >
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold"
           style={{ color: colors.onSurface }}>
        <Layers size={16} className="text-blue-600" />
        Large PDF processed with tiled extraction
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs md:grid-cols-4">
        <TileStat
          label="Total pages"
          value={tileSummary.total_pages}
          testid={`pdf-import-tile-pages-${fileId}`}
        />
        <TileStat
          label="Tiles used"
          value={tileSummary.tiles_used}
          testid={`pdf-import-tile-count-${fileId}`}
        />
        <TileStat
          label="Documents"
          value={`${tileSummary.docs_pre_merge ?? 0} → ${tileSummary.docs_post_merge ?? 0}`}
          testid={`pdf-import-tile-docs-${fileId}`}
        />
        <TileStat
          label="Cross-tile merges"
          value={tileSummary.cross_tile_merges}
          testid={`pdf-import-tile-merges-${fileId}`}
        />
      </dl>
      {tileWarnings.length > 0 ? (
        <ul className="mt-3 flex flex-col gap-1 border-t pt-2 text-xs"
            style={{ borderColor: colors.border }}>
          {tileWarnings.map((w, idx) => (
            <li
              key={idx}
              data-testid={`pdf-import-tile-warning-${fileId}`}
              className="flex gap-2 text-amber-800"
            >
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              <span>
                <span className="font-mono mr-1">
                  {w?.code || "warning"}:
                </span>
                {w?.message || w?.tile_index || ""}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}


function TileStat({ label, value, testid }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[10px] font-medium uppercase tracking-wider"
          style={{ color: colors.muted }}>
        {label}
      </dt>
      <dd
        className="text-sm font-semibold"
        style={{ color: colors.onSurface }}
        data-testid={testid}
      >
        {value ?? "—"}
      </dd>
    </div>
  );
}


/**
 * PDF-E — Errors-per-type expandable section. First 10 error
 * entries per doc-type render inline; if more exist, a
 * ``Show all N`` toggle expands to the full list. Non-blocking
 * — the offending row still lands in the audit trail; this
 * just surfaces them so the operator can chase down anomalies
 * without paging through the audit log.
 */
export function ErrorsPerTypeSection({ fileId, insertErrors, paymentErrors }) {
  const invErr = Array.isArray(insertErrors) ? insertErrors : [];
  const payErr = Array.isArray(paymentErrors) ? paymentErrors : [];
  if (invErr.length === 0 && payErr.length === 0) return null;
  return (
    <div
      data-testid={`pdf-import-errors-section-${fileId}`}
      className="flex flex-col gap-2"
    >
      {invErr.length > 0 ? (
        <ErrorList
          fileId={fileId}
          label="Invoice errors"
          items={invErr}
          testidPrefix="invoice"
        />
      ) : null}
      {payErr.length > 0 ? (
        <ErrorList
          fileId={fileId}
          label="Payment errors"
          items={payErr}
          testidPrefix="payment"
        />
      ) : null}
    </div>
  );
}


function ErrorList({ fileId, label, items, testidPrefix }) {
  const [expanded, setExpanded] = useState(false);
  const HEAD_CAP = 10;
  const hiddenCount = Math.max(0, items.length - HEAD_CAP);
  const shown = expanded ? items : items.slice(0, HEAD_CAP);
  return (
    <div
      className="rounded-lg border px-3 py-2"
      style={{
        borderColor: "#FCA5A5",
        backgroundColor: "#FEF2F2",
      }}
    >
      <div className="mb-1 flex items-center justify-between text-xs font-semibold text-red-900">
        <span className="inline-flex items-center gap-1.5">
          <AlertCircle size={12} />
          {label} · {items.length}
        </span>
        {hiddenCount > 0 ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            data-testid={`pdf-import-errors-expand-${testidPrefix}-${fileId}`}
            className="underline underline-offset-2 hover:opacity-80"
          >
            {expanded
              ? "Show fewer"
              : `Show all ${items.length} errors`}
          </button>
        ) : null}
      </div>
      <ul className="flex flex-col gap-1 text-[11px] text-red-900">
        {shown.map((e, idx) => (
          <li
            key={idx}
            data-testid={`pdf-import-error-item-${fileId}`}
            className="flex gap-2"
          >
            <span className="font-mono">
              {e?.code || e?.error || "error"}:
            </span>
            <span>
              {e?.message
                || (typeof e === "string" ? e : JSON.stringify(e))}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}


/**
 * PDF-E — Whole-commit failure banner + retry. Shown when a
 * commit request returns HTTP >= 500 (server-side / unexpected
 * failure). Preserves the uploaded file's row state in
 * PREVIEW_READY so the retry click is a single tap.
 *
 * 4xx typed errors continue to render via the compact inline
 * pill in the actions strip (existing UX) — this banner is
 * specifically for server failures where a retry is the right
 * next action.
 */
export function CommitErrorBanner({ fileId, error, uploadedFilename, onRetry, disabled }) {
  return (
    <Alert
      data-testid={`pdf-import-commit-error-banner-${fileId}`}
      className="border-red-300 bg-red-50 text-red-900"
    >
      <AlertCircle className="h-4 w-4 text-red-700" />
      <AlertTitle className="text-red-900">Commit failed</AlertTitle>
      <AlertDescription>
        <div className="flex flex-col gap-2">
          <p className="text-xs">
            {error || "The server returned an unexpected error."}
            {uploadedFilename ? (
              <>
                {" "}
                <span className="opacity-80">
                  (Your upload of{" "}
                  <span className="font-mono">{uploadedFilename}</span>
                  {" "}is preserved — no need to re-select the file.)
                </span>
              </>
            ) : null}
          </p>
          <div>
            <Button
              variant="primary"
              onClick={onRetry}
              disabled={disabled}
              testid={`pdf-import-retry-${fileId}`}
            >
              <span className="inline-flex items-center gap-1.5">
                <RefreshCw size={14} />
                Retry commit
              </span>
            </Button>
          </div>
        </div>
      </AlertDescription>
    </Alert>
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
  [FILE_STATUS.PREVIEW_READY]: {
    label: "Preview ready",
    Icon: CheckCircle2,
    className: "bg-emerald-100 text-emerald-800",
  },
  [FILE_STATUS.COMMITTING]: {
    label: "Committing",
    Icon: Loader2,
    className: "bg-indigo-100 text-indigo-800",
    spin: true,
  },
  [FILE_STATUS.COMMITTED]: {
    label: "Committed",
    Icon: CheckCircle2,
    className: "bg-emerald-200 text-emerald-900",
  },
  [FILE_STATUS.ROLLING_BACK]: {
    label: "Rolling back",
    Icon: Loader2,
    className: "bg-amber-100 text-amber-900",
    spin: true,
  },
  [FILE_STATUS.ROLLED_BACK]: {
    label: "Rolled back",
    Icon: History,
    className: "bg-slate-200 text-slate-800",
  },
  [FILE_STATUS.ERROR]: {
    label: "Error",
    Icon: AlertCircle,
    className: "bg-red-100 text-red-800",
  },
};
