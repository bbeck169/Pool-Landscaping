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
  UserPlus,
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
  // Phase 33 Step C.1 · Feb-2026 — renamed error code for the
  // residual manual-review bucket after the Step B auto-create
  // pre-pass. ``unresolved_customers`` is kept above for one
  // release as a legacy alias (backend emits both the new code
  // and the legacy ``unresolved`` detail field).
  if (code === "manual_review_required") {
    return "Some invoices need manual customer review — the "
      + "auto-create helper could not resolve them from the PDF "
      + "(no name, address, or phone captured). Open the review "
      + "panel and fill in a customer before committing.";
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
export async function postPdfInvoice(file, opts = {}) {
  const { baseUrl, token } = opts;
  const BASE = baseUrl || process.env.REACT_APP_BACKEND_URL || "";
  const TOKEN = token || (
    typeof localStorage !== "undefined"
      ? (localStorage.getItem("token") || "")
      : ""
  );
  const fd = new FormData();
  fd.append("file", file);
  // PDF-HUB · Feb-2026 — optional Document Type hint from the
  // upload-area dropdown. When the value is "" (Auto-Detect) we
  // OMIT the field entirely so the router's normaliser branches
  // straight to auto-detect (None). Any explicit selection is
  // forwarded verbatim; the router boundary maps ``payment`` →
  // ``payment_receipt`` before it reaches the extractor.
  const hint = (opts && opts.hintDocKind) || "";
  if (hint) {
    fd.append("hint_doc_kind", hint);
  }
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
  customerMatchOverrides = null,
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
  // Feb-2026 · match-ladder expansion — per-pending-id override
  // map (``{<pending_customer_id>: "reject_fuzzy"}``) wired
  // through to ``routers/imports._CommitOptions``. Omit the key
  // entirely when the operator didn't reject anything so the
  // commit payload stays minimal.
  if (customerMatchOverrides
      && typeof customerMatchOverrides === "object"
      && Object.keys(customerMatchOverrides).length > 0) {
    body.customer_match_overrides = customerMatchOverrides;
  }
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


// PDF-HUB · Feb-2026 — Type-column pill component.
// Renders a color-coded badge for the AI-classified doc_kind:
//   * ``invoice``         → Blue
//   * ``estimate``        → Green (emerald)
//   * ``payment_receipt`` → Purple (violet)
//   * anything else       → Neutral slate (fallback so the column
//                           never renders blank)
// The internal literal for payments is ``payment_receipt`` — the
// user-facing label collapses that to "Payment" so the column
// header + copy stay concise. Exported so the vitest suite can
// mount + assert on it without spinning up the whole PreviewRow.
//
// Feb-2026 · PDF Import Hub Bug 1 fix — accepts an optional
// ``autoDetectedDocKind`` so the pill can render an "AI said: X"
// secondary chip when the operator's explicit Document Type
// selection overrode the classifier output. Backend stamps
// ``quote_in.auto_detected_doc_type`` + ``quote_in.doc_type_user
// _override`` via ``services/imports/pdf_preview_post.py``.
const _DOC_KIND_LABEL = {
  invoice: "Invoice",
  estimate: "Estimate",
  quote: "Estimate",
  payment_receipt: "Payment",
  payment: "Payment",
};
function _docKindToLabel(k) {
  return _DOC_KIND_LABEL[k] || (k ? String(k) : "Unknown");
}
export function DocKindPill({ docKind, testid, autoDetectedDocKind }) {
  const spec = (() => {
    switch (docKind) {
      case "invoice":
        return { label: "Invoice", cls: "bg-blue-100 text-blue-800" };
      case "estimate":
      case "quote":
        return { label: "Estimate", cls: "bg-emerald-100 text-emerald-800" };
      case "payment_receipt":
      case "payment":
        return { label: "Payment", cls: "bg-violet-100 text-violet-800" };
      default:
        return { label: "Unknown", cls: "bg-slate-100 text-slate-700" };
    }
  })();
  const autoLabel = autoDetectedDocKind
    ? _docKindToLabel(autoDetectedDocKind)
    : null;
  const showAutoBadge =
    autoLabel && autoLabel !== spec.label;
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${spec.cls}`}
        data-testid={testid}
        data-doc-kind={docKind || "unknown"}
      >
        {spec.label}
      </span>
      {showAutoBadge ? (
        <span
          className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-slate-100 text-slate-600"
          data-testid={testid ? `${testid}-ai-said` : undefined}
          title={`Classifier auto-detected ${autoLabel}; overridden by your Document Type selection.`}
        >
          AI said: {autoLabel}
        </span>
      ) : null}
    </span>
  );
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
  // PDF-HUB · Feb-2026 — Document Type hint. Empty string =
  // Auto-Detect (backend receives no field). Explicit selection
  // forwards through the multipart form as ``hint_doc_kind``.
  const [hintDocKind, setHintDocKind] = useState("");
  const hintDocKindRef = useRef("");
  useEffect(() => { hintDocKindRef.current = hintDocKind; }, [hintDocKind]);
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
      // PDF-HUB · Feb-2026 — forward the page-level hint via the
      // ref so a hint selected AFTER queueing still reaches the
      // POST body without a stale-closure bug.
      postPdfInvoice(next.file, { hintDocKind: hintDocKindRef.current })
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
        title="PDF Import Hub"
        subtitle={
          "Upload PDFs for automatic extraction and commit — "
          + "supports Invoices, Estimates, and Payment History. "
          + "Preview extracted rows, review duplicates, then "
          + "commit — or roll back within the same batch. "
          + "Admin-only."
        }
      />

      {/* PDF-HUB · Feb-2026 — Document Type dropdown. Sits above
          the drop zone so the operator picks the doc kind BEFORE
          selecting files. Empty value = Auto-Detect (no hint
          forwarded); explicit selections plumb straight through
          the multipart form as ``hint_doc_kind``. */}
      <div
        data-testid="pdf-hub-doc-type-container"
        className="mt-6 flex flex-col gap-1"
      >
        <label
          htmlFor="pdf-hub-doc-type-select"
          className="text-sm font-medium"
          style={{ color: colors.onSurface }}
        >
          Document Type
        </label>
        <select
          id="pdf-hub-doc-type-select"
          data-testid="pdf-hub-doc-type-select"
          value={hintDocKind}
          onChange={(e) => setHintDocKind(e.target.value)}
          className="w-full max-w-sm rounded-md border px-3 py-2 text-sm"
          style={{
            borderColor: colors.border,
            backgroundColor: colors.surface,
            color: colors.onSurface,
          }}
        >
          <option value="" data-testid="pdf-hub-doc-type-option-auto">
            Auto-Detect
          </option>
          <option value="invoice" data-testid="pdf-hub-doc-type-option-invoice">
            Invoice
          </option>
          <option value="estimate" data-testid="pdf-hub-doc-type-option-estimate">
            Estimate
          </option>
          <option value="payment" data-testid="pdf-hub-doc-type-option-payment">
            Payment History
          </option>
        </select>
        <span
          className="text-xs"
          style={{ color: colors.muted }}
          data-testid="pdf-hub-doc-type-hint"
        >
          Auto-detect uses AI classification.
        </span>
      </div>

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

  // Feb-2026 · auto-create UX ticket — number of DISTINCT new
  // customer rows the backend commit path would mint. Backed
  // by ``classification.summary.will_auto_create_count`` which
  // the Step C.1 ``classify_pending_for_preview`` now computes
  // as ``len(distinct dedup_group_ids)``. Falls back to the
  // raw array length for pre-upgrade response payloads.
  const _classification = batch.pending_customer_classification;
  const willAutoCreateCount = (() => {
    const s = _classification?.summary;
    if (s && typeof s.will_auto_create_count === "number") {
      return s.will_auto_create_count;
    }
    return Array.isArray(_classification?.will_auto_create)
      ? _classification.will_auto_create.length : 0;
  })();

  // PDF-MIRROR · Feb-2026 — needs_review derivation.  A preview
  // is flagged when the extractor produced no grand_total AND
  // the line-item recompute also came up $0.00 (see
  // ``pdf_commit._apply_totals`` — ``total_source ==
  // 'zero_total_unrecoverable'``). Backend refuses to commit
  // these; FE surfaces a banner + disables the commit button
  // until admin explicitly acknowledges via the override
  // checkbox.
  const _isNeedsReview = (p) => {
    const qi = p?.quote_in || {};
    // The extractor's grand_total AND total_due are both empty,
    // AND the mapper's line-items sum to zero → preview will be
    // marked ``zero_total_unrecoverable`` by the backend on
    // commit. Compute FE-side so the badge renders pre-commit.
    const gt = qi.grand_total;
    const td = qi.total_due;
    if ((gt !== null && gt !== undefined && Number(gt) !== 0)
        || (td !== null && td !== undefined && Number(td) !== 0)) {
      return false;
    }
    const items = Array.isArray(qi.line_items) ? qi.line_items : [];
    let sum = 0;
    for (const li of items) {
      const lt = li?.line_total;
      if (lt !== null && lt !== undefined) {
        sum += Number(lt) || 0;
      } else {
        sum += (Number(li?.quantity) || 0) * (Number(li?.unit_price) || 0);
      }
    }
    return sum === 0;
  };
  const needsReviewPreviews = invoicePreviews.filter(_isNeedsReview);
  const needsReviewCount = needsReviewPreviews.length;

  const [needsReviewAcked, setNeedsReviewAcked] = useState(false);

  // Feb-2026 · match-ladder expansion — operator can click
  // "Reject match" next to a fuzzy chip to opt out of the
  // dry-run's fuzzy attachment.  Map keyed by
  // ``pending_customer_id`` → ``"reject_fuzzy"``; threaded into
  // the commit payload as ``customer_match_overrides``.
  const [customerMatchOverrides, setCustomerMatchOverrides] =
    useState({});
  const toggleRejectFuzzy = useCallback((pendingCustomerId) => {
    if (!pendingCustomerId) return;
    setCustomerMatchOverrides((prev) => {
      const next = { ...(prev || {}) };
      if (next[pendingCustomerId] === "reject_fuzzy") {
        delete next[pendingCustomerId];
      } else {
        next[pendingCustomerId] = "reject_fuzzy";
      }
      return next;
    });
  }, []);

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
        customerMatchOverrides,
      });
      setCommitOutcome(envelope);
      onCommitSuccess?.(fileId, envelope);
    } catch (err) {
      setCommitError(err?.message || "Commit failed.");
      setCommitErrorStatus(err?.status || null);
      onCommitFailure?.(fileId, err);
    }
  }, [batch, fileId, onDuplicate, customerMatchOverrides,
      onCommitStart, onCommitSuccess, onCommitFailure]);

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
          {/* ─────────────────────────────────────────────────
              Phase 33 Step C.2 · Feb-2026 — Will-Auto-Create
              preview badge. Renders when the batch is in
              ``preview_complete`` and the GET poll response
              carries ``pending_customer_classification``
              (populated by the Step C.1 router helper
              ``classify_pending_for_preview``). Gives the
              operator advance notice of how many new customers
              commit will auto-mint — so clicking Commit stops
              feeling like a surprise. ───────────────────── */}
          <WillAutoCreateCustomersBanner
            fileId={fileId}
            classification={batch.pending_customer_classification}
            customerMatchOverrides={customerMatchOverrides}
            onToggleRejectFuzzy={toggleRejectFuzzy}
          />

          {/* PDF-MIRROR · Feb-2026 — Needs Review banner. Renders
              when ≥1 preview row's grand_total AND line-item sum
              are both $0 — the backend will refuse to commit these
              (``zero_total_unrecoverable``). Admin must
              acknowledge before the commit button re-enables. */}
          {needsReviewCount > 0 ? (
            <div
              className="mb-3 rounded-md border p-3 flex items-start gap-3"
              style={{
                borderColor: "#F59E0B",
                backgroundColor: "#FFFBEB",
              }}
              data-testid={`pdf-import-needs-review-banner-${fileId}`}
            >
              <AlertCircle size={16} className="mt-0.5 shrink-0"
                            style={{ color: "#B45309" }} />
              <div className="flex-1 text-sm" style={{ color: "#78350F" }}>
                <div className="font-semibold">
                  {needsReviewCount} invoice{needsReviewCount === 1 ? "" : "s"} need review
                </div>
                <div className="mt-1 text-xs" style={{ color: "#92400E" }}>
                  Extractor produced no grand total AND line items
                  sum to $0 — these will NOT be committed unless
                  you acknowledge below. Fix the source PDF or
                  edit the extracted values before proceeding.
                </div>
                <label
                  className="mt-2 inline-flex items-center gap-2 cursor-pointer"
                  data-testid={`pdf-import-needs-review-ack-label-${fileId}`}
                >
                  <input
                    type="checkbox"
                    checked={needsReviewAcked}
                    onChange={(e) => setNeedsReviewAcked(e.target.checked)}
                    data-testid={`pdf-import-needs-review-ack-${fileId}`}
                  />
                  <span className="text-xs font-medium">
                    I understand — commit the rest anyway (the {needsReviewCount} zero-total row{needsReviewCount === 1 ? "" : "s"} will be skipped server-side)
                  </span>
                </label>
              </div>
            </div>
          ) : null}
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
                  <th
                    className="px-3 py-2 text-left font-medium"
                    data-testid={`pdf-import-preview-th-type-${fileId}`}
                  >
                    Type
                  </th>
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
                      disabled={isCommitting
                        || (needsReviewCount > 0 && !needsReviewAcked)}
                      testid={`pdf-import-commit-btn-${fileId}`}
                    >
                      {isCommitting ? (
                        <span className="inline-flex items-center gap-1.5">
                          <Loader2 size={14} className="animate-spin" />
                          Committing…
                        </span>
                      ) : willAutoCreateCount > 0 ? (
                        // Feb-2026 · auto-create UX ticket — surface
                        // the auto-create fan-out so Commit never
                        // feels like a surprise mint. Count comes
                        // from the summary block the Step C.1
                        // classifier populates (distinct dedup
                        // groups, not raw pending-row count).
                        `Commit ${totalCount} invoice${totalCount === 1 ? "" : "s"} `
                        + `and auto-create ${willAutoCreateCount} customer`
                        + `${willAutoCreateCount === 1 ? "" : "s"}`
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
          onClick={() => renderableItems.length > 0 && onToggle(sourceIdx)}
          disabled={renderableItems.length === 0}
          className="mr-2 inline-flex h-5 w-5 items-center justify-center rounded hover:bg-black/5 disabled:opacity-40 disabled:cursor-not-allowed"
          aria-label={
            renderableItems.length === 0
              ? "No line items extracted"
              : (expanded ? "Collapse line items" : "Expand line items")
          }
          aria-expanded={expanded ? "true" : "false"}
          aria-disabled={renderableItems.length === 0 ? "true" : "false"}
          title={
            renderableItems.length === 0
              ? "No line items extracted"
              : undefined
          }
          data-testid={`pdf-import-line-items-toggle-${fileId}-${sourceIdx}`}
          data-no-line-items={renderableItems.length === 0 ? "true" : "false"}
        >
          {expanded ? (
            <ChevronUp size={14} style={{ color: colors.muted }} />
          ) : (
            <ChevronDown size={14} style={{ color: colors.muted }} />
          )}
        </button>
        {q.doc_number || "—"}
      </td>
      {/* PDF-HUB · Feb-2026 — Type column. Color-coded pill from
          the AI-classified ``doc_kind`` field on the preview
          MapperReport. Blue = Invoice, Green = Estimate, Purple
          = Payment (payment_receipt). Unknown falls back to
          neutral slate so the column never renders blank.
          Feb-2026 · Bug 1 fix — when the operator's explicit
          Document Type selection overrode the classifier, prefer
          ``quote_in.doc_type`` for the pill + pass the auto-
          detected value through so the "AI said: X" secondary
          chip renders. */}
      <td
        className="px-3 py-2"
        data-testid={`pdf-import-preview-row-${fileId}-${sourceIdx}-type-cell`}
      >
        <DocKindPill
          docKind={q.doc_type || preview.doc_kind}
          autoDetectedDocKind={
            q.doc_type_user_override
              ? q.auto_detected_doc_type
              : undefined
          }
          testid={`pdf-import-preview-row-${fileId}-${sourceIdx}-type-pill`}
        />
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
        {/* PDF-MIRROR · Feb-2026 — total_source badge. Rendered
            below the amount so the operator can distinguish
            verbatim / reconstructed / needs-review origins at a
            glance. Priority: needs-review > reconstructed >
            verbatim (default when we can't tell). */}
        {(() => {
          // Compute badge state client-side. Backend adds a
          // ``total_source`` field on the persisted doc; before
          // commit we approximate from the preview's quote_in.
          const gt = q.grand_total;
          const td = q.total_due;
          const hasVerbatim =
            (gt !== null && gt !== undefined && Number(gt) !== 0)
            || (td !== null && td !== undefined && Number(td) !== 0);
          let badge = "Verbatim";
          let bg = "bg-emerald-50 text-emerald-800";
          if (!hasVerbatim) {
            const items = Array.isArray(q.line_items) ? q.line_items : [];
            let sum = 0;
            for (const li of items) {
              const lt = li?.line_total;
              if (lt !== null && lt !== undefined) {
                sum += Number(lt) || 0;
              } else {
                sum += (Number(li?.quantity) || 0) * (Number(li?.unit_price) || 0);
              }
            }
            if (sum === 0) {
              badge = "Needs Review";
              bg = "bg-amber-100 text-amber-900";
            } else {
              badge = "Reconstructed";
              bg = "bg-sky-50 text-sky-800";
            }
          }
          return (
            <div
              className={`mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${bg}`}
              data-testid={`pdf-import-preview-row-${fileId}-${preview.source_doc_index}-total-source-badge`}
            >
              {badge}
            </div>
          );
        })()}
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
        <td colSpan={6} className="px-3 py-3" style={{ backgroundColor: colors.surfaceSecondary }}>
          {/* Feb-2026 · PDF Import Hub Bug 2 defensive — amber
              banner inside the expand panel when
              ``Σ line_item.line_total`` disagrees with the stated
              ``subtotal`` by more than $0.01. Backend post-
              processor at ``services/imports/pdf_preview_post.py``
              stamps the signed delta on
              ``quote_in.line_total_subtotal_mismatch_cents``. */}
          {Math.abs(Number(q.line_total_subtotal_mismatch_cents) || 0) > 1 ? (
            <div
              className="mb-2 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-900"
              data-testid={`pdf-import-line-items-subtotal-mismatch-${fileId}-${sourceIdx}`}
            >
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              <span>
                Line-item total does not match the stated
                subtotal by{" "}
                <strong>
                  {formatCurrency(
                    Math.abs(Number(q.line_total_subtotal_mismatch_cents) || 0) / 100,
                  )}
                </strong>
                . Review before commit.
              </span>
            </div>
          ) : null}
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
                        className="px-2 py-1 whitespace-pre-wrap"
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
  // Feb-2026 · PDF Import Hub Bug 3 fix — low-confidence
  // customer-name extraction (backend post-processor nulled a
  // suspect value that looked like a doc number) shows a warning
  // triangle so the operator reviews before commit.
  const lowConfidence = q.customer_extraction_confidence === "low";
  const warningBadge = lowConfidence ? (
    <span
      className="ml-1.5 inline-flex items-center text-amber-700"
      title={
        "Customer could not be confidently extracted — review "
        + "before commit."
        + (q.customer_name_suspect_value
            ? ` (Extractor returned "${q.customer_name_suspect_value}", `
              + "which looks like a document number.)"
            : "")
      }
      data-testid={
        `pdf-import-preview-row-${preview.source_doc_index}-`
        + `customer-low-confidence`
      }
    >
      <AlertTriangle size={12} />
    </span>
  ) : null;
  if (resolution === "matched") {
    return (
      <span className="text-sm" style={{ color: colors.onSurface }}>
        {name}
        {warningBadge}
      </span>
    );
  }
  if (resolution === "pending") {
    return (
      <span className="text-sm text-slate-600">
        {name}
        {warningBadge}
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
      {warningBadge}
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
      {/* Phase 33 Step C.2 · Feb-2026 — Auto-created customers
          success banner. Renders when the commit response
          carries non-empty ``auto_created_customers`` so the
          operator sees a clear "N new customers added from this
          batch" confirmation and can click through to review
          them. Legacy response shapes (pre-Phase-33) read
          ``outcome.auto_created_customers`` as ``undefined`` →
          component short-circuits to ``null``. */}
      <AutoCreatedCustomersBanner
        fileId={fileId}
        autoCreated={outcome?.auto_created_customers}
      />
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
 * Phase 33 Step C.2 · Feb-2026 — Will-Auto-Create preview badge.
 *
 * Renders in the PreviewSurface above the ``needs-review`` banner
 * when the GET poll response includes
 * ``pending_customer_classification`` (populated by the Step C.1
 * router helper ``classify_pending_for_preview``). Shows the
 * operator how many brand-new customer rows Commit will mint
 * from PENDING sentinels — plus a smaller sub-count for rows
 * that still need manual review (zero identifying info on the
 * extracted customer).
 *
 * Short-circuits to ``null`` on:
 *   * missing classification key (pre-Phase-33 batches, or
 *     batches without PENDING sentinels)
 *   * both buckets empty (nothing to communicate)
 */
export function WillAutoCreateCustomersBanner({
  fileId, classification,
  customerMatchOverrides = null,
  onToggleRejectFuzzy = null,
}) {
  const willAuto = Array.isArray(classification?.will_auto_create)
    ? classification.will_auto_create : [];
  const manual = Array.isArray(classification?.will_require_manual_review)
    ? classification.will_require_manual_review : [];
  // Feb-2026 · match-ladder expansion — rows that will attach
  // to an existing customer at commit time (any tier).  Shape
  // per entry: ``{source_doc_index, pending_customer_id,
  // extracted_name, match_status, matched_customer_id,
  // matched_customer_name, matched_customer_status, match_method,
  // match_confidence, fuzzy_distance}``.
  const willMatchExisting = Array.isArray(
    classification?.will_match_existing,
  ) ? classification.will_match_existing : [];
  // Feb-2026 · auto-create UX ticket — the backend summary block
  // computes the DISTINCT-dedup-group count the commit path will
  // actually produce.  Falls back to the raw array length for
  // pre-upgrade response payloads.
  const _summaryCount = classification?.summary?.will_auto_create_count;
  const autoCreateCount = (typeof _summaryCount === "number")
    ? _summaryCount
    : willAuto.length;
  const _matchExistingCount =
    classification?.summary?.will_match_existing_count;
  const matchExistingCount = (typeof _matchExistingCount === "number")
    ? _matchExistingCount
    : willMatchExisting.length;
  // Feb-2026 · match-ladder expansion — operator rejections
  // locally flip a fuzzy row into the manual-review visual state
  // without blocking the Commit button; the backend honours the
  // override by routing the row through auto-create instead of
  // the fuzzy match.  The resulting ``match_status`` is still
  // ``fuzzy_match`` server-side; the FE just renders it with a
  // rejected-match treatment.
  const overrides = (customerMatchOverrides
                      && typeof customerMatchOverrides === "object")
    ? customerMatchOverrides : {};
  const lowConfRows = manual.filter(
    (r) => r?.reason === "customer_extraction_confidence_low",
  );
  if (willAuto.length === 0 && manual.length === 0
      && willMatchExisting.length === 0) return null;

  // Scroll-into-view affordance that reuses the existing per-row
  // customer picker (``pdf-import-preview-row-${idx}-customer-low-confidence``
  // or the row-level ``CustomerCell``).  Keeps the picker single-
  // sourced -- no duplicate state in the banner.
  const _onResolveLowConfidence = (sourceDocIndex) => {
    try {
      const sel = `[data-testid="pdf-import-preview-row-`
        + `${sourceDocIndex}-customer-low-confidence"]`;
      const el = document.querySelector(sel);
      if (el && typeof el.scrollIntoView === "function") {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        // Flash the row so the operator notices the jump.
        el.classList.add("ring-2", "ring-amber-500");
        setTimeout(() => {
          el.classList.remove("ring-2", "ring-amber-500");
        }, 1500);
      }
    } catch { /* non-fatal UX helper */ }
  };

  return (
    <div
      className="mb-3 rounded-md border p-3 flex items-start gap-3"
      style={{ borderColor: "#60A5FA", backgroundColor: "#EFF6FF" }}
      data-testid={`pdf-import-will-auto-create-banner-${fileId}`}
    >
      <UserPlus size={16} className="mt-0.5 shrink-0" style={{ color: "#1D4ED8" }} />
      <div className="flex-1 text-sm" style={{ color: "#1E3A8A" }}>
        <div
          className="font-semibold"
          data-testid={`pdf-import-will-auto-create-count-${fileId}`}
        >
          {autoCreateCount > 0 ? (
            <>
              Will auto-create {autoCreateCount} customer
              {autoCreateCount === 1 ? "" : "s"} on commit
            </>
          ) : (
            <>No customers to auto-create</>
          )}
          {matchExistingCount > 0 ? (
            <span
              className="ml-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold"
              style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
              data-testid={`pdf-import-will-match-existing-count-${fileId}`}
            >
              {matchExistingCount} matched to existing
            </span>
          ) : null}
          {manual.length > 0 ? (
            <span
              className="ml-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold"
              style={{ backgroundColor: "#FEF3C7", color: "#78350F" }}
              data-testid={`pdf-import-manual-review-count-${fileId}`}
            >
              <AlertTriangle size={10} />
              {manual.length} need manual review
            </span>
          ) : null}
        </div>
        {willMatchExisting.length > 0 ? (
          <MatchExistingChips
            fileId={fileId}
            rows={willMatchExisting}
            overrides={overrides}
            onToggleRejectFuzzy={onToggleRejectFuzzy}
          />
        ) : null}
        {willAuto.length > 0 ? (
          <details className="mt-1 group">
            <summary
              className="cursor-pointer list-none text-xs font-medium underline underline-offset-2 group-open:mb-2"
              data-testid={`pdf-import-will-auto-create-toggle-${fileId}`}
            >
              <span className="group-open:hidden">Show details</span>
              <span className="hidden group-open:inline">Hide details</span>
            </summary>
            <AutoCreateCandidatesTable fileId={fileId} rows={willAuto} />
          </details>
        ) : null}
        {lowConfRows.length > 0 ? (
          <div
            className="mt-2 rounded-md border p-2 flex flex-col gap-1.5"
            style={{
              borderColor: "#F59E0B", backgroundColor: "#FFFBEB",
            }}
            data-testid={`pdf-import-low-confidence-section-${fileId}`}
          >
            <div
              className="text-xs font-semibold flex items-center gap-1"
              style={{ color: "#78350F" }}
            >
              <AlertTriangle size={12} />
              {lowConfRows.length} row
              {lowConfRows.length === 1 ? "" : "s"} with low-confidence
              customer extraction
            </div>
            <ul className="flex flex-col gap-1 text-xs">
              {lowConfRows.map((row, idx) => (
                <li
                  key={row.pending_customer_id || idx}
                  className="flex items-center justify-between gap-2"
                  data-testid={`pdf-import-low-confidence-row-${fileId}-${row.source_doc_index}`}
                >
                  <span className="truncate" style={{ color: "#78350F" }}>
                    <span className="font-mono text-[11px] opacity-70">
                      #{row.source_doc_index}
                    </span>
                    {" "}
                    {row.extracted_name
                      ? (
                        <span className="italic">
                          “{row.extracted_name}” looks like a doc number
                        </span>
                      )
                      : <span>Customer not confidently extracted</span>}
                  </span>
                  <button
                    type="button"
                    onClick={() => _onResolveLowConfidence(
                      row.source_doc_index,
                    )}
                    className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium hover:brightness-105"
                    style={{
                      borderColor: "#D97706", color: "#78350F",
                      backgroundColor: "#FEF3C7",
                    }}
                    data-testid={`pdf-import-low-confidence-resolve-btn-${fileId}-${row.source_doc_index}`}
                  >
                    Resolve customer
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}


/**
 * Feb-2026 · match-ladder expansion — per-row chip list for the
 * ``will_match_existing`` bucket surfaced by the Phase 33 Step C.1
 * classifier.  One chip per pending row, color-coded by the
 * matched customer's bucket (``active`` / ``inactive`` / ``muted``)
 * or by the match method (``fuzzy``):
 *
 *   * ``active``        → green chip "Matched: <name> (Active)"
 *   * ``inactive``      → amber chip "Matched: <name> (Inactive — will
 *                                      attach to this customer)"
 *   * ``muted``         → amber chip "Matched: <name> (Muted — will
 *                                      attach to this customer)"
 *   * ``fuzzy_match``   → amber chip "Matched: <name> (Fuzzy, distance N)"
 *                        + "Reject match" link that calls
 *                        ``onToggleRejectFuzzy(pending_customer_id)``
 *                        → payload grows ``customer_match_overrides``
 *                        so the backend routes this row through
 *                        auto-create instead of the fuzzy match.
 *
 * Rows the operator rejected locally render with a strike-through
 * + an "Undo reject" link so the override is reversible.
 */
function MatchExistingChips({
  fileId, rows, overrides, onToggleRejectFuzzy,
}) {
  return (
    <div
      className="mt-2 flex flex-col gap-1.5"
      data-testid={`pdf-import-match-existing-chips-${fileId}`}
    >
      {rows.map((row) => {
        const pid = row?.pending_customer_id;
        const rejected = pid && overrides?.[pid] === "reject_fuzzy";
        const status = row?.match_status;
        // Status → chip palette.  Active uses green; inactive /
        // muted / fuzzy all use amber (operator should look twice).
        const bg = status === "active" ? "#DCFCE7" : "#FEF3C7";
        const fg = status === "active" ? "#166534" : "#78350F";
        const border = status === "active" ? "#86EFAC" : "#FBBF24";
        const matchedName = row?.matched_customer_name
          || row?.extracted_name || "(unnamed)";
        let suffix;
        if (status === "active") {
          suffix = "(Active)";
        } else if (status === "inactive") {
          suffix = "(Inactive — will attach to this customer)";
        } else if (status === "muted") {
          suffix = "(Muted — will attach to this customer)";
        } else if (status === "fuzzy_match") {
          const d = row?.fuzzy_distance;
          suffix = d != null
            ? `(Fuzzy, distance ${d})`
            : "(Fuzzy match)";
        } else {
          suffix = "";
        }
        return (
          <div
            key={pid || row.source_doc_index}
            className="flex items-center gap-2 text-xs"
            data-testid={
              `pdf-import-match-existing-row-${fileId}-${row.source_doc_index}`
            }
          >
            <span className="font-mono text-[11px] opacity-60"
                   style={{ color: "#1E3A8A" }}>
              #{row.source_doc_index}
            </span>
            <span
              className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium"
              style={{
                backgroundColor: bg,
                color: fg,
                borderColor: border,
                textDecoration: rejected ? "line-through" : "none",
                opacity: rejected ? 0.6 : 1,
              }}
              title={status === "fuzzy_match"
                ? "Levenshtein distance from extracted name"
                : undefined}
              data-testid={
                `pdf-import-match-chip-${fileId}-${row.source_doc_index}`
              }
              data-match-status={status || ""}
            >
              Matched: {matchedName} {suffix}
            </span>
            {status === "fuzzy_match" && onToggleRejectFuzzy ? (
              <button
                type="button"
                onClick={() => onToggleRejectFuzzy(pid)}
                className="underline underline-offset-2 text-[11px] hover:brightness-110"
                style={{ color: "#B45309" }}
                data-testid={
                  `pdf-import-reject-fuzzy-btn-${fileId}-${row.source_doc_index}`
                }
              >
                {rejected ? "Undo reject" : "Reject match"}
              </button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}


/**
 * Feb-2026 · auto-create UX ticket — per-dedup-group candidate
 * table. Replaces the pre-ticket raw list ``<ul>`` with columns
 * for Name / Email / Phone / Address and a trailing fields chip
 * ("3 of 4 extracted").  Missing fields render as "—" with a
 * tooltip "Not extracted from PDF" so the operator can tell
 * ahead of commit that TD-30 harder extraction would be needed.
 */
function AutoCreateCandidatesTable({ fileId, rows }) {
  // Collapse rows by dedup_group_id so one new customer renders
  // once even when 2 PDFs in the batch resolve to the same
  // candidate. First-wins source_doc_index + merged fields.
  const grouped = (() => {
    const by = new Map();
    for (const row of rows || []) {
      const key = row.dedup_group_id
        || row.pending_customer_id || row.source_doc_index;
      if (!by.has(key)) {
        by.set(key, row);
      }
    }
    return Array.from(by.values());
  })();
  const _notExtracted = (
    <span
      className="opacity-60"
      title="Not extracted from PDF"
    >
      —
    </span>
  );
  const _addressString = (addr) => {
    if (!addr) return null;
    if (typeof addr === "string") return addr;
    const parts = [addr.street, addr.city, addr.state, addr.zip]
      .filter(Boolean);
    return parts.join(", ") || null;
  };
  return (
    <div
      className="overflow-x-auto"
      data-testid={`pdf-import-auto-create-table-${fileId}`}
    >
      <table className="min-w-full text-left text-xs">
        <thead>
          <tr style={{ color: "#1E3A8A" }}>
            <th className="pr-3 py-1 font-semibold">Row</th>
            <th className="pr-3 py-1 font-semibold">Name</th>
            <th className="pr-3 py-1 font-semibold">Email</th>
            <th className="pr-3 py-1 font-semibold">Phone</th>
            <th className="pr-3 py-1 font-semibold">Address</th>
            <th className="pr-3 py-1 font-semibold">Fields</th>
          </tr>
        </thead>
        <tbody>
          {grouped.map((row, idx) => {
            const cand = row.auto_create_candidate || {};
            const addr = _addressString(cand.mailing_address);
            const extracted = Array.isArray(row.fields_extracted)
              ? row.fields_extracted : [];
            const missing = Array.isArray(row.fields_missing)
              ? row.fields_missing : [];
            const total = extracted.length + missing.length;
            return (
              <tr
                key={row.dedup_group_id || row.pending_customer_id || idx}
                className="border-t"
                style={{ borderColor: "#BFDBFE" }}
                data-testid={`pdf-import-will-auto-create-item-${fileId}`}
              >
                <td className="pr-3 py-1 font-mono text-[11px] opacity-70">
                  #{row.source_doc_index}
                </td>
                <td className="pr-3 py-1">
                  {cand.name || row.extracted_name || _notExtracted}
                </td>
                <td className="pr-3 py-1">
                  {cand.email || _notExtracted}
                </td>
                <td className="pr-3 py-1">
                  {cand.phone || row.extracted_phone || _notExtracted}
                </td>
                <td className="pr-3 py-1">
                  {addr || row.extracted_address || _notExtracted}
                </td>
                <td className="pr-3 py-1">
                  {total > 0 ? (
                    <span
                      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold"
                      style={missing.length === 0 ? {
                        backgroundColor: "#DCFCE7", color: "#166534",
                      } : {
                        backgroundColor: "#FEF3C7", color: "#78350F",
                      }}
                      title={missing.length === 0
                        ? "All candidate fields extracted"
                        : `Missing: ${missing.join(", ")}`}
                      data-testid={`pdf-import-will-auto-create-fields-chip-${fileId}-${row.source_doc_index}`}
                    >
                      {extracted.length} of {total} extracted
                    </span>
                  ) : _notExtracted}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}


/**
 * Phase 33 Step C.2 · Feb-2026 — Auto-created customers success
 * banner.
 *
 * Renders inside ``CommittedSummary`` right after the warnings
 * banner when the commit response includes a non-empty
 * ``auto_created_customers`` array (new Step C.1 top-level
 * bucket). Legacy response shapes read ``autoCreated`` as
 * ``undefined`` → component short-circuits to ``null``.
 *
 * Groups the entries by action (``created`` / ``deduped_db`` /
 * ``deduped_batch``) so the operator sees the breakdown without
 * expanding a details panel. The expanded list links each row
 * to the pre-existing customer-detail page via a native anchor
 * — same pattern as ``CountCard`` for cross-page affordance
 * without pulling in Router context.
 */
export function AutoCreatedCustomersBanner({ fileId, autoCreated }) {
  const list = Array.isArray(autoCreated) ? autoCreated : [];
  if (list.length === 0) return null;
  const createdCount = list.filter((c) => c.action === "created").length;
  const dedupedDb = list.filter((c) => c.action === "deduped_db").length;
  const dedupedBatch = list.filter((c) => c.action === "deduped_batch").length;
  return (
    <Alert
      data-testid={`pdf-import-auto-created-banner-${fileId}`}
      className="border-emerald-300 bg-emerald-50 text-emerald-900"
    >
      <UserPlus className="h-4 w-4 text-emerald-700" />
      <AlertTitle
        className="text-emerald-900"
        data-testid={`pdf-import-auto-created-title-${fileId}`}
      >
        {`${list.length} customer${list.length === 1 ? "" : "s"} resolved from this PDF`}
      </AlertTitle>
      <AlertDescription>
        <div className="mt-1 text-xs text-emerald-800">
          {createdCount > 0 ? (
            <span data-testid={`pdf-import-auto-created-new-${fileId}`}>
              {createdCount} new
            </span>
          ) : null}
          {createdCount > 0 && (dedupedDb + dedupedBatch) > 0
            ? " · " : null}
          {dedupedDb > 0 ? (
            <span data-testid={`pdf-import-auto-created-deduped-db-${fileId}`}>
              {dedupedDb} matched existing
            </span>
          ) : null}
          {dedupedDb > 0 && dedupedBatch > 0 ? " · " : null}
          {dedupedBatch > 0 ? (
            <span data-testid={`pdf-import-auto-created-deduped-batch-${fileId}`}>
              {dedupedBatch} deduped in-batch
            </span>
          ) : null}
        </div>
        <details className="mt-2 group">
          <summary
            className="cursor-pointer list-none text-xs font-medium underline underline-offset-2 group-open:mb-2"
            data-testid={`pdf-import-auto-created-toggle-${fileId}`}
          >
            <span className="group-open:hidden">Show all</span>
            <span className="hidden group-open:inline">Hide details</span>
          </summary>
          <ul className="flex flex-col gap-1 text-xs">
            {list.map((row, idx) => (
              <li
                key={row.pending_customer_id || idx}
                className="flex gap-2 items-start"
                data-testid={`pdf-import-auto-created-item-${fileId}`}
              >
                <span className="font-mono text-[11px] opacity-70">
                  #{row.source_doc_index}
                </span>
                <a
                  href={`/customers/${encodeURIComponent(row.resolved_customer_id)}`}
                  className="underline underline-offset-2 hover:brightness-110"
                  data-testid={`pdf-import-auto-created-link-${fileId}-${row.resolved_customer_id}`}
                >
                  {row.extracted_name || row.resolved_customer_id}
                </a>
                <span className="opacity-70">
                  · {row.action.replace(/_/g, " ")}
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
