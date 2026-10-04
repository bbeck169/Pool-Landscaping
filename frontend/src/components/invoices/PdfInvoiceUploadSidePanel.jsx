/**
 * PDFI-V · Feb-2026 — Side-panel upload flow for /invoices.
 *
 * State machine (``step``):
 *   idle → uploading → polling → preview_ready → committing →
 *   committed
 *                              ↘ error (recoverable; "Retry")
 *                              ↘ timeout (recoverable; "Retry" +
 *                                 "Open bulk hub")
 *
 * Multi-doc PDF support: when the batch's ``mapper_previews``
 * array has length > 1, a doc selector dropdown lets the
 * operator switch between invoices in the file. Commit only
 * creates the currently-selected doc.
 *
 * Picker wiring:
 *   * No-match customer → inline CustomerCombobox mounts;
 *     parent dispatches ``patchPreview`` with
 *     ``matched_customer_id + customer_name + customer_address``.
 *   * Line without ``pricebook_item_id`` → inline
 *     PricebookItemPicker mounts per row; parent dispatches
 *     ``patchPreview`` with the ``line_items`` partial.
 *
 * ``pollTimeoutMs`` prop (default 60000) is parametrized so
 * unit tests can inject a short deadline — makes the timeout
 * path deterministically reachable under real timers.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Upload, X, CheckCircle2, AlertCircle, Clock } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api";
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
const DEFAULT_POLL_INTERVAL_MS = 2000;
const DEFAULT_POLL_TIMEOUT_MS = 60000;
const BULK_HUB_URL = "/admin/imports/pdf-invoice";

export default function PdfInvoiceUploadSidePanel({
  open,
  onClose,
  onImportComplete,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  pollTimeoutMs = DEFAULT_POLL_TIMEOUT_MS,
}) {
  const [step, setStep] = useState("idle");
  const [file, setFile] = useState(null);
  const [batchId, setBatchId] = useState(null);
  const [batchPreviews, setBatchPreviews] = useState([]);
  const [activeDocIdx, setActiveDocIdx] = useState(0);
  const [errorMsg, setErrorMsg] = useState("");
  const [customers, setCustomers] = useState([]);
  // PDFI-VB · Feb-2026 — recovery chip book-keeping, keyed by
  // ``activeDocIdx`` so each doc in a multi-doc batch can carry
  // its own post-create link-failure state.
  const [createRecoveryByDoc, setCreateRecoveryByDoc] = useState({});
  const pollTimerRef = useRef(null);
  const pollStartRef = useRef(0);

  const _reset = useCallback(() => {
    setStep("idle");
    setFile(null);
    setBatchId(null);
    setBatchPreviews([]);
    setActiveDocIdx(0);
    setErrorMsg("");
    setCreateRecoveryByDoc({});
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const _close = useCallback(async () => {
    if (batchId && step !== "committed") {
      try {
        await rollbackBatch(batchId, { reason: "user_cancelled_sidepanel" });
        toast.success("Upload cancelled.");
      } catch {
        // Non-critical — admin hub can clean up any orphan.
      }
    }
    _reset();
    onClose?.();
  }, [batchId, step, _reset, onClose]);

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
          setBatchPreviews(previews);
          setActiveDocIdx(0);
          setStep("preview_ready");
          return;
        }
        if (row?.status === "failed" || row?.status === "commit_failed") {
          setErrorMsg(row?.error || "Extraction failed.");
          setStep("error");
          toast.error("Extraction failed.");
          return;
        }
        if (Date.now() - pollStartRef.current > pollTimeoutMs) {
          setStep("timeout");
          return;
        }
        pollTimerRef.current = setTimeout(tick, pollIntervalMs);
      } catch (err) {
        if (cancelled) return;
        setErrorMsg(err?.message || "Polling failed.");
        setStep("error");
        toast.error("Polling failed.");
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
  }, [step, batchId, pollIntervalMs, pollTimeoutMs]);

  useEffect(() => {
    if (step !== "preview_ready" || customers.length > 0) return;
    (async () => {
      try {
        const rows = await api.get("/customers?active=true");
        setCustomers(Array.isArray(rows) ? rows : []);
      } catch {
        setCustomers([]);
      }
    })();
  }, [step, customers.length]);

  const preview = batchPreviews[activeDocIdx] || null;
  const qi = preview?.quote_in || {};

  const _applyPatch = useCallback(async (patch) => {
    if (!batchId || !preview) return;
    const prevSnapshot = batchPreviews;
    const nextPreview = { ...preview };
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
    for (const k of [
      "customer_name", "customer_address",
      "doc_number", "doc_date", "grand_total",
      "matched_customer_id",
    ]) {
      if (k in patch) {
        if (k === "matched_customer_id") {
          nextPreview.matched_customer_id = patch[k];
        } else {
          nextQuoteIn[k] = patch[k];
        }
      }
    }
    nextPreview.quote_in = nextQuoteIn;
    const nextPreviews = [...batchPreviews];
    nextPreviews[activeDocIdx] = nextPreview;
    setBatchPreviews(nextPreviews);
    try {
      await patchPreview(batchId, { doc_idx: activeDocIdx, patch });
    } catch (err) {
      setBatchPreviews(prevSnapshot);
      toast.error(err?.message || "Save failed.");
    }
  }, [batchId, preview, batchPreviews, activeDocIdx]);

  const _onPickCustomer = (customer) => {
    _applyPatch({
      matched_customer_id: customer.id,
      customer_name: customer.name || "",
      customer_address: customer.address || "",
    });
  };

  // PDFI-VB · Feb-2026 — new-customer create-and-link.  The tile's
  // modal has already fired ``createCustomer`` and the row exists on
  // the server before this handler runs; our job is to fire the
  // follow-up ``patchPreview`` link to attach the fresh id/name/
  // address to the preview.  On link failure we DO NOT re-throw —
  // the modal closes anyway (user already paid the create cost)
  // and the amber "Customer created, retry link" chip takes over so
  // the operator can re-fire the link without creating a duplicate.
  const _onCreateCustomer = async (created) => {
    if (!batchId) return;
    const linkPatch = {
      matched_customer_id: created.id,
      customer_name: created.name || "",
      customer_address: created.billing_address || created.address || "",
    };
    const prevSnapshot = batchPreviews;
    const currPreview = batchPreviews[activeDocIdx] || {};
    const nextPreview = { ...currPreview };
    const nextQuoteIn = { ...(currPreview.quote_in || {}) };
    nextPreview.matched_customer_id = linkPatch.matched_customer_id;
    nextQuoteIn.customer_name = linkPatch.customer_name;
    nextQuoteIn.customer_address = linkPatch.customer_address;
    nextPreview.quote_in = nextQuoteIn;
    const nextPreviews = [...batchPreviews];
    nextPreviews[activeDocIdx] = nextPreview;
    setBatchPreviews(nextPreviews);
    try {
      await patchPreview(batchId, { doc_idx: activeDocIdx, patch: linkPatch });
      toast.success(`Customer "${linkPatch.customer_name}" created and linked`);
      setCreateRecoveryByDoc((prev) => {
        if (!(activeDocIdx in prev)) return prev;
        const next = { ...prev };
        delete next[activeDocIdx];
        return next;
      });
    } catch (err) {
      setBatchPreviews(prevSnapshot);
      toast.error(`Failed to link new customer: ${err?.message || "retry"}`);
      setCreateRecoveryByDoc((prev) => ({ ...prev, [activeDocIdx]: created }));
      // Intentionally do NOT re-throw — the modal must close so the
      // recovery chip is the single affordance surfaced to the user.
    }
  };

  const _onRetryCreateLink = async (created) => {
    if (!batchId) return;
    const linkPatch = {
      matched_customer_id: created.id,
      customer_name: created.name || "",
      customer_address: created.billing_address || created.address || "",
    };
    try {
      await patchPreview(batchId, { doc_idx: activeDocIdx, patch: linkPatch });
      const currPreview = batchPreviews[activeDocIdx] || {};
      const nextPreview = { ...currPreview };
      const nextQuoteIn = { ...(currPreview.quote_in || {}) };
      nextPreview.matched_customer_id = linkPatch.matched_customer_id;
      nextQuoteIn.customer_name = linkPatch.customer_name;
      nextQuoteIn.customer_address = linkPatch.customer_address;
      nextPreview.quote_in = nextQuoteIn;
      const nextPreviews = [...batchPreviews];
      nextPreviews[activeDocIdx] = nextPreview;
      setBatchPreviews(nextPreviews);
      toast.success(`Customer "${linkPatch.customer_name}" linked`);
      setCreateRecoveryByDoc((prev) => {
        const next = { ...prev };
        delete next[activeDocIdx];
        return next;
      });
    } catch (err) {
      toast.error(`Retry failed: ${err?.message || "try again"}`);
    }
  };

  const _onPickPricebook = (lineIdx, item) => {
    _applyPatch({
      line_items: {
        [lineIdx]: {
          pricebook_item_id: item.id,
          item_name: item.name || "",
          unit_price: Number(item.unit_price) || 0,
        },
      },
    });
  };

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
      const invNum = qi.doc_number || createdId || "";
      toast.success(invNum ? `Invoice created · #${invNum}` : "Invoice created.");
      onImportComplete?.(createdId);
      _reset();
      onClose?.();
    } catch (err) {
      setErrorMsg(err?.message || "Create failed.");
      setStep("error");
      toast.error("Create failed. Please try again.");
    }
  };

  const _onTimeoutRetry = () => {
    if (!batchId) return;
    setStep("polling");
    pollStartRef.current = Date.now();
  };

  const _onOpenBulkHub = () => {
    if (typeof window !== "undefined" && window.location) {
      window.location.assign(BULK_HUB_URL);
    }
  };

  const docCount = batchPreviews.length;
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
                <div
                  className="mt-3 text-xs text-slate-700"
                  data-testid="pdfi-upload-filename"
                >
                  {file.name} · {(file.size / 1024 / 1024).toFixed(2)} MB · ready to upload
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

          {step === "timeout" && (
            <div
              className="rounded-xl border-2 border-amber-400 bg-amber-50 p-4"
              data-testid="pdfi-upload-timeout"
            >
              <div className="flex items-center gap-2 font-semibold text-amber-900 mb-1">
                <Clock size={16} /> Taking longer than usual
              </div>
              <div className="text-xs text-amber-900 mb-3">
                Your PDF is still being processed. Retry to resume
                polling or open the bulk hub to track it there.
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={_onTimeoutRetry}
                  className="flex-1 rounded-md bg-amber-700 hover:bg-amber-800 text-white text-xs px-3 py-1"
                  data-testid="pdfi-upload-timeout-retry-btn"
                >
                  Retry
                </button>
                <button
                  type="button"
                  onClick={_onOpenBulkHub}
                  className="flex-1 rounded-md border border-amber-700 text-amber-900 hover:bg-amber-100 text-xs px-3 py-1"
                  data-testid="pdfi-upload-timeout-bulk-btn"
                >
                  Open bulk hub
                </button>
              </div>
            </div>
          )}

          {step === "preview_ready" && preview && (
            <div className="space-y-4" data-testid="pdfi-preview-ready">
              {docCount > 1 && (
                <div
                  className="rounded-md bg-slate-100 border border-slate-300 p-3"
                  data-testid="pdfi-preview-doc-selector"
                >
                  <label className="block text-xs text-slate-700 mb-1">
                    Document ({activeDocIdx + 1} of {docCount})
                  </label>
                  <select
                    value={activeDocIdx}
                    onChange={(e) => setActiveDocIdx(Number(e.target.value))}
                    className="w-full px-2 py-1 rounded border border-slate-400 bg-white text-sm"
                    data-testid="pdfi-preview-doc-selector-input"
                  >
                    {batchPreviews.map((p, i) => (
                      <option key={i} value={i}>
                        Document {i + 1}
                        {p?.quote_in?.doc_number ? ` · #${p.quote_in.doc_number}` : ""}
                      </option>
                    ))}
                  </select>
                  <div
                    className="mt-2 text-[11px] text-slate-600"
                    data-testid="pdfi-preview-doc-selector-hint"
                  >
                    {docCount - 1} additional invoice{docCount > 2 ? "s" : ""} in this file —
                    <a
                      href={BULK_HUB_URL}
                      className="underline ml-1"
                      data-testid="pdfi-preview-doc-selector-bulk-link"
                    >
                      use the bulk import hub
                    </a>
                    {" "}to process all at once.
                  </div>
                </div>
              )}
              <CustomerTile
                customerName={qi.customer_name}
                customerAddress={qi.customer_address}
                matchedCustomerId={preview.matched_customer_id}
                customers={customers}
                onEditName={(v) => _applyPatch({ customer_name: v })}
                onEditAddress={(v) => _applyPatch({ customer_address: v })}
                onPickCustomer={_onPickCustomer}
                onCreateCustomer={_onCreateCustomer}
                createRecoveryCustomer={createRecoveryByDoc[activeDocIdx] || null}
                onRetryCreateLink={_onRetryCreateLink}
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
                onPickPricebook={_onPickPricebook}
                onAddLine={() => _applyPatch({
                  line_items: {
                    [(qi.line_items || []).length]: {
                      item_name: "", quantity: 1, unit_price: 0, line_total: 0,
                    },
                  },
                })}
              />
              <LineItemDescriptionsTile
                lineItems={qi.line_items || []}
                onEditDescription={(i, v) => _applyPatch({
                  line_items: { [i]: { description: v } },
                })}
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
            <div
              className="text-center text-sm text-slate-600"
              data-testid="pdfi-upload-committing"
            >
              <Loader2 size={20} className="mx-auto mb-2 animate-spin text-green-600" />
              Creating…
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
