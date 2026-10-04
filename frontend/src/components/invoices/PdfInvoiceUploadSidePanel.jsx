/**
 * PDFI-IV · Feb-2026 — Side-panel upload flow for /invoices.
 *
 * Single-file upload → poll → preview (5 color-coded tiles) →
 * inline edit via PATCH → commit → fire ``onImportComplete(id)``
 * and close. On cancel after a successful upload, best-effort
 * rollback so the batch doesn't leak.
 *
 * State machine (``step``):
 *   idle → uploading → polling → preview_ready → editing →
 *   committing → committed
 *                              ↘ error (recoverable; "Retry")
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Upload, X, CheckCircle2, AlertCircle } from "lucide-react";
import { toast } from "sonner";

import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from "@/components/ui/sheet";
import {
  kickoffUpload, pollBatch, patchPreview, commitBatch, rollbackBatch,
} from "@/api/pdfImports";

import CustomerTile from "@/components/invoices/pdfPreviewTiles/CustomerTile";
import LineItemsTile from "@/components/invoices/pdfPreviewTiles/LineItemsTile";
import LineItemDescriptionsTile from "@/components/invoices/pdfPreviewTiles/LineItemDescriptionsTile";
import TotalTile from "@/components/invoices/pdfPreviewTiles/TotalTile";
import DateTile from "@/components/invoices/pdfPreviewTiles/DateTile";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 60000;

export default function PdfInvoiceUploadSidePanel({
  open,
  onClose,
  onImportComplete,
}) {
  const [step, setStep] = useState("idle");
  const [file, setFile] = useState(null);
  const [batchId, setBatchId] = useState(null);
  const [preview, setPreview] = useState(null);
  const [errorMsg, setErrorMsg] = useState("");
  const pollTimerRef = useRef(null);
  const pollStartRef = useRef(0);

  const _reset = useCallback(() => {
    setStep("idle");
    setFile(null);
    setBatchId(null);
    setPreview(null);
    setErrorMsg("");
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const _close = useCallback(async () => {
    // Best-effort rollback if the operator closed mid-flow without
    // committing. Fire-and-forget — the admin bulk hub can clean up
    // any orphan batch if this request fails.
    if (batchId && step !== "committed") {
      try { await rollbackBatch(batchId, { reason: "user_cancelled_sidepanel" }); }
      catch { /* swallow — not critical for client UX */ }
    }
    _reset();
    onClose?.();
  }, [batchId, step, _reset, onClose]);

  // ── File drop / pick ───────────────────────────────────────
  const _onPickFile = (f) => {
    if (!f) return;
    if (f.type !== "application/pdf" && !f.name?.toLowerCase().endsWith(".pdf")) {
      toast.error("Only PDF files are accepted.");
      return;
    }
    if (f.size > MAX_UPLOAD_BYTES) {
      toast.error(`PDF is over the 10 MB cap (${(f.size / 1024 / 1024).toFixed(1)} MB).`);
      return;
    }
    setFile(f);
    setErrorMsg("");
  };

  const _onUpload = async () => {
    if (!file) return;
    setStep("uploading");
    setErrorMsg("");
    try {
      const res = await kickoffUpload(file);
      if (!res?.batch_id) throw new Error("missing_batch_id");
      setBatchId(res.batch_id);
      setStep("polling");
      pollStartRef.current = Date.now();
    } catch (err) {
      setErrorMsg(err?.message || "Upload failed.");
      setStep("error");
      toast.error("Upload failed. Please try again.");
    }
  };

  // ── Polling loop ───────────────────────────────────────────
  useEffect(() => {
    if (step !== "polling" || !batchId) return undefined;
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      try {
        const row = await pollBatch(batchId);
        if (cancelled) return;
        if (row?.status === "preview_complete") {
          const previews = row.mapper_previews || [];
          setPreview(previews[0] || null);
          setStep("preview_ready");
          return;
        }
        if (row?.status === "failed" || row?.status === "commit_failed") {
          setErrorMsg(row?.error || "Extraction failed.");
          setStep("error");
          return;
        }
        if (Date.now() - pollStartRef.current > POLL_TIMEOUT_MS) {
          setErrorMsg("Polling timed out after 60s — try again.");
          setStep("error");
          return;
        }
        pollTimerRef.current = setTimeout(tick, POLL_INTERVAL_MS);
      } catch (err) {
        if (cancelled) return;
        setErrorMsg(err?.message || "Polling failed.");
        setStep("error");
      }
    };
    tick();
    return () => {
      cancelled = true;
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [step, batchId]);

  // ── Preview edit helpers ───────────────────────────────────
  const _applyPatch = useCallback(async (patch) => {
    if (!batchId || !preview) return;
    // Optimistic update.
    const prevSnapshot = preview;
    const nextQuoteIn = { ...(preview.quote_in || {}) };
    if (patch.line_items) {
      const curr = [...(nextQuoteIn.line_items || [])];
      for (const [idx, p] of Object.entries(patch.line_items)) {
        const i = Number(idx);
        if (p === null) {
          curr.splice(i, 1);
        } else if (i < curr.length) {
          curr[i] = { ...curr[i], ...p };
        } else {
          curr[i] = p;
        }
      }
      nextQuoteIn.line_items = curr;
    }
    for (const k of ["customer_name", "customer_address", "doc_number", "doc_date", "grand_total"]) {
      if (k in patch) nextQuoteIn[k] = patch[k];
    }
    setPreview({ ...preview, quote_in: nextQuoteIn });
    try {
      await patchPreview(batchId, { doc_idx: 0, patch });
    } catch (err) {
      setPreview(prevSnapshot);
      toast.error(err?.message || "Save failed.");
    }
  }, [batchId, preview]);

  // ── Readiness gate for the Create Invoice button ──────────
  const qi = preview?.quote_in || {};
  const _readyToCommit = (
    Boolean(qi.customer_name) &&
    Boolean(qi.doc_date) &&
    Number(qi.grand_total) > 0 &&
    Array.isArray(qi.line_items) &&
    qi.line_items.length > 0
  );

  const _onCommit = async () => {
    if (!batchId) return;
    setStep("committing");
    try {
      const res = await commitBatch(batchId, { on_duplicate: "skip" });
      const createdId = res?.quote_ids?.[0]
        || res?.commit_result?.created_quote_ids?.[0]
        || null;
      setStep("committed");
      toast.success("Invoice created from PDF.");
      onImportComplete?.(createdId);
      _reset();
      onClose?.();
    } catch (err) {
      setErrorMsg(err?.message || "Create failed.");
      setStep("error");
      toast.error("Create failed. Please try again.");
    }
  };

  // ── Render ─────────────────────────────────────────────────
  const previewCount = (preview && preview.quote_in) ? 1 : 0;
  return (
    <Sheet
      open={open}
      onOpenChange={(v) => { if (!v) _close(); }}
    >
      <SheetContent
        side="right"
        className="w-full sm:max-w-xl overflow-y-auto bg-white"
        data-testid="pdfi-upload-sidepanel"
      >
        <SheetHeader>
          <SheetTitle data-testid="pdfi-upload-sidepanel-title">
            Upload PDF Invoice
          </SheetTitle>
          <SheetDescription>
            Drop a PDF to parse it into an editable preview. Review
            and confirm to create the invoice.
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4 space-y-4">
          {step === "idle" && (
            <div
              className="rounded-xl border-2 border-dashed border-slate-300 p-6 text-center"
              data-testid="pdfi-upload-dropzone"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                _onPickFile(e.dataTransfer?.files?.[0]);
              }}
            >
              <Upload size={28} className="mx-auto mb-2 text-slate-500" />
              <div className="text-sm text-slate-600 mb-3">
                Drag a PDF here or
              </div>
              <input
                type="file"
                accept="application/pdf"
                onChange={(e) => _onPickFile(e.target.files?.[0])}
                className="hidden"
                id="pdfi-upload-file-input"
                data-testid="pdfi-upload-file-input"
              />
              <label
                htmlFor="pdfi-upload-file-input"
                className="inline-block cursor-pointer rounded-lg bg-slate-800 text-white px-3 py-1.5 text-sm font-medium hover:bg-slate-900"
                data-testid="pdfi-upload-pick-btn"
              >
                Choose file
              </label>
              {file && (
                <div className="mt-3 text-xs text-slate-700" data-testid="pdfi-upload-filename">
                  {file.name} · {(file.size / 1024).toFixed(1)} KB
                </div>
              )}
              {file && (
                <button
                  type="button"
                  onClick={_onUpload}
                  className="mt-3 w-full rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold py-2"
                  data-testid="pdfi-upload-start-btn"
                >
                  Upload & Analyze
                </button>
              )}
            </div>
          )}

          {(step === "uploading" || step === "polling") && (
            <div
              className="rounded-xl border border-slate-300 p-6 text-center"
              data-testid="pdfi-upload-progress"
            >
              <Loader2 size={28} className="mx-auto mb-2 animate-spin text-blue-600" />
              <div className="text-sm text-slate-700">
                {step === "uploading" ? "Uploading…" : "Analyzing PDF…"}
              </div>
            </div>
          )}

          {step === "preview_ready" && preview && (
            <div className="space-y-4" data-testid="pdfi-preview-ready">
              {previewCount > 0 && (
                <div className="text-xs text-slate-600 italic" data-testid="pdfi-preview-doc-count">
                  Previewing invoice 1 of 1.
                </div>
              )}
              <CustomerTile
                customerName={qi.customer_name}
                customerAddress={qi.customer_address}
                matchedCustomerId={preview.matched_customer_id}
                onEditName={(v) => _applyPatch({ customer_name: v })}
                onEditAddress={(v) => _applyPatch({ customer_address: v })}
                onPickCustomer={() => toast.info("Customer picker — select from the admin customer directory.")}
              />
              <DateTile
                docDate={qi.doc_date}
                docNumber={qi.doc_number}
                onEditDate={(v) => _applyPatch({ doc_date: v })}
                onEditNumber={(v) => _applyPatch({ doc_number: v })}
              />
              <LineItemsTile
                lineItems={qi.line_items || []}
                onEditLine={(i, p) => _applyPatch({ line_items: { [i]: p } })}
                onPickPricebook={() => toast.info("Pricebook picker — attach a catalogue item.")}
                onAddLine={() => _applyPatch({ line_items: { [(qi.line_items || []).length]: { item_name: "", quantity: 1, unit_price: 0, line_total: 0 } } })}
              />
              <LineItemDescriptionsTile
                lineItems={qi.line_items || []}
                onEditDescription={(i, v) => _applyPatch({ line_items: { [i]: { description: v } } })}
              />
              <TotalTile
                grandTotal={qi.grand_total}
                subtotal={qi.subtotal}
                amountPaid={qi.amount_paid}
                totalDue={qi.total_due}
                onEditGrandTotal={(v) => _applyPatch({ grand_total: v })}
              />
              <button
                type="button"
                onClick={_onCommit}
                disabled={!_readyToCommit}
                className="w-full rounded-lg bg-green-600 hover:bg-green-700 disabled:bg-slate-300 disabled:cursor-not-allowed text-white text-sm font-semibold py-2 flex items-center justify-center gap-2"
                data-testid="pdfi-upload-commit-btn"
              >
                <CheckCircle2 size={16} /> Create Invoice
              </button>
            </div>
          )}

          {step === "committing" && (
            <div className="text-center text-sm text-slate-600" data-testid="pdfi-upload-committing">
              <Loader2 size={20} className="mx-auto mb-2 animate-spin text-green-600" />
              Creating invoice…
            </div>
          )}

          {step === "error" && (
            <div
              className="rounded-xl border-2 border-red-400 bg-red-50 p-4 text-sm text-red-900"
              data-testid="pdfi-upload-error"
            >
              <div className="flex items-center gap-2 font-semibold mb-1">
                <AlertCircle size={16} /> Something went wrong
              </div>
              <div data-testid="pdfi-upload-error-msg">{errorMsg || "Unknown error."}</div>
              <button
                type="button"
                onClick={_reset}
                className="mt-3 rounded-md bg-red-700 hover:bg-red-800 text-white text-xs px-3 py-1"
                data-testid="pdfi-upload-retry-btn"
              >
                Try again
              </button>
            </div>
          )}

          <button
            type="button"
            onClick={_close}
            className="w-full rounded-lg border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 text-sm py-2 flex items-center justify-center gap-2"
            data-testid="pdfi-upload-cancel-btn"
          >
            <X size={14} /> {step === "committed" ? "Close" : "Cancel"}
          </button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
