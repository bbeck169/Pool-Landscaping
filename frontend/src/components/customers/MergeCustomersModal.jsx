/**
 * Feb 2026 · Customer Merge · Phase 2 UI · Merge modal.
 *
 * Manual merge flow — opens from the Customers list bulk-action bar
 * when ≥2 customers are checked. Contract:
 *
 *   • Detection banner — fires
 *     ``POST /api/customers/detect-duplicates`` scoped to the
 *     currently-selected ``customer_ids`` on mount so the operator
 *     immediately sees whether the engine agrees this is a duplicate
 *     cluster.
 *   • Side-by-side cards — one per selected customer, with a
 *     ``<input type="radio">`` at the top to designate the primary.
 *   • Dry-run preview — every primary change (debounced 500ms) hits
 *     ``POST /api/customers/merge`` with ``dry_run: true`` and
 *     renders the returned reconciliation + rewire counts.
 *   • Type MERGE to confirm + confirm button — the button uses the
 *     rose-500 accent since this is destructive-ish.
 *
 * On success: fires ``onDone(result)`` so the parent can toast +
 * reload. On error: keeps the modal open, surfaces the error in an
 * inline banner (also fires ``onError`` for the parent's toast).
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Modal, Button } from "@/components/ui-kit";


// Feb 2026 · CONFIRM_TOKEN retired — the "Type MERGE" input was
// removed as part of the app-wide type-to-confirm friction sweep.
// Kept commented for future spelunkers so ``git log`` on this
// file surfaces the intent without a full history walk.
// const CONFIRM_TOKEN = "MERGE";


function _shortDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleDateString(undefined, {
      year: "numeric", month: "short", day: "numeric",
    });
  } catch {
    return "—";
  }
}


function CustomerCard({ customer, isPrimary, onSelectPrimary }) {
  const tags = Array.isArray(customer.tags) ? customer.tags : [];
  return (
    <div
      className="rounded-xl p-3 flex flex-col gap-1.5"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${isPrimary ? colors.brand : colors.border}`,
        boxShadow: isPrimary
          ? `inset 3px 0 0 0 ${colors.brand}`
          : "none",
      }}
      data-testid={`merge-card-${customer.id}`}
    >
      <label
        className="flex items-center gap-2 cursor-pointer"
        data-testid={`merge-card-${customer.id}-primary-label`}
      >
        <input
          type="radio"
          name="merge-primary"
          checked={isPrimary}
          onChange={() => onSelectPrimary(customer.id)}
          data-testid={`merge-card-${customer.id}-primary-radio`}
          aria-label={`Set ${customer.name} as primary`}
        />
        <span
          className="text-[11px] font-bold uppercase tracking-wider"
          style={{ color: isPrimary ? colors.brand : colors.muted }}
        >
          {isPrimary ? "Primary" : "Set as primary"}
        </span>
      </label>
      <div className="font-semibold truncate"
             style={{ color: colors.onSurface }}
             data-testid={`merge-card-${customer.id}-name`}>
        {customer.name || "—"}
      </div>
      <div className="text-xs truncate" style={{ color: colors.muted }}>
        {customer.email || "no email"}
      </div>
      <div className="text-xs truncate" style={{ color: colors.muted }}>
        {customer.phone || "no phone"}
      </div>
      <div className="text-xs" style={{ color: colors.muted }}>
        {customer.address || customer.address_line1 || "no address"}
      </div>
      {customer.service_line ? (
        <div className="text-[11px]" style={{ color: colors.muted }}>
          service line: {customer.service_line}
        </div>
      ) : null}
      {tags.length ? (
        <div className="flex flex-wrap gap-1 mt-1">
          {tags.slice(0, 4).map((t, i) => (
            <span key={i}
                   className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                   style={{
                     backgroundColor: colors.accent.sky[100],
                     color: colors.accent.sky[700],
                   }}>
              {t}
            </span>
          ))}
        </div>
      ) : null}
      <div className="text-[10px] mt-1" style={{ color: colors.muted }}>
        Updated {_shortDate(customer.updated_at || customer.created_at)}
      </div>
    </div>
  );
}


function DetectionBanner({ scanning, groups, selectedIds }) {
  if (scanning) {
    return (
      <div className="rounded-xl px-3 py-2 flex items-center gap-2 text-xs"
             style={{
               backgroundColor: colors.surfaceSecondary,
               color: colors.muted,
             }}
             data-testid="merge-detection-scanning">
        <Loader2 size={12} className="animate-spin" />
        Scanning for auto-detected match…
      </div>
    );
  }
  const sel = new Set(selectedIds);
  const matched = (groups || []).find((g) => {
    const ids = new Set(g.customer_ids || []);
    // A group applies if AT LEAST 2 of the selected ids are in it —
    // stronger than "any one overlaps", weaker than "exact set" so a
    // 3-way select still surfaces a 2-way flagged pair.
    let hits = 0;
    ids.forEach((x) => { if (sel.has(x)) hits += 1; });
    return hits >= 2;
  });
  if (matched) {
    return (
      <div
        className="rounded-xl px-3 py-2 flex items-center gap-2 text-xs font-semibold"
        style={{
          backgroundColor: colors.accent.emerald[50],
          color: colors.accent.emerald[700],
          border: `1px solid ${colors.accent.emerald[100]}`,
        }}
        data-testid="merge-detection-matched"
      >
        <CheckCircle2 size={14} />
        Auto-detected match:{" "}
        <span className="font-normal">{matched.match_type}</span>{" "}
        <span
          className="ml-1 px-1.5 py-0.5 rounded"
          style={{
            backgroundColor: matched.confidence === "high"
              ? colors.accent.emerald[100]
              : colors.accent.amber[100],
            color: matched.confidence === "high"
              ? colors.accent.emerald[700]
              : colors.accent.amber[700],
          }}
        >
          {matched.confidence}
        </span>
      </div>
    );
  }
  return (
    <div
      className="rounded-xl px-3 py-2 flex items-center gap-2 text-xs"
      style={{
        backgroundColor: colors.accent.amber[50],
        color: colors.accent.amber[700],
        border: `1px solid ${colors.accent.amber[100]}`,
      }}
      data-testid="merge-detection-manual"
    >
      <AlertTriangle size={14} />
      Manual merge — these customers were not auto-detected as
      duplicates. Proceed with care.
    </div>
  );
}


function PreviewSection({ preview, loading, primaryName }) {
  if (!primaryName) {
    return (
      <div className="rounded-xl p-3 text-xs"
             style={{
               backgroundColor: colors.surfaceSecondary,
               color: colors.muted,
             }}
             data-testid="merge-preview-empty">
        Select a primary customer to see the merge preview.
      </div>
    );
  }
  if (loading) {
    return (
      <div className="rounded-xl p-3 flex items-center gap-2 text-xs"
             style={{
               backgroundColor: colors.surfaceSecondary,
               color: colors.muted,
             }}
             data-testid="merge-preview-loading">
        <Loader2 size={12} className="animate-spin" /> Computing merge preview…
      </div>
    );
  }
  if (!preview) return null;
  const reconciled = preview.fields_reconciled || {};
  const filled = preview.empty_fields_filled || {};
  const rewired = preview.related_records_rewired || {};
  const totalRewired = Object.values(rewired).reduce(
    (a, b) => a + (Number(b) || 0), 0,
  );
  const reconciledEntries = Object.entries(reconciled);
  const filledEntries = Object.entries(filled);
  return (
    <div className="rounded-xl p-3 space-y-2"
           style={{
             backgroundColor: colors.surfaceSecondary,
             border: `1px solid ${colors.border}`,
           }}
           data-testid="merge-preview">
      <div className="text-[11px] font-bold uppercase tracking-wider"
             style={{ color: colors.muted }}>
        Primary: <span style={{ color: colors.onSurface }}>{primaryName}</span>
      </div>
      {reconciledEntries.length ? (
        <div className="text-xs" data-testid="merge-preview-reconciled">
          <div className="font-semibold mb-0.5"
                 style={{ color: colors.onSurface }}>
            Fields overwritten on primary (newest wins):
          </div>
          <ul className="pl-4 list-disc space-y-0.5"
                style={{ color: colors.onSurfaceSecondary }}>
            {reconciledEntries.map(([k, v]) => (
              <li key={k}>
                <b>{k}</b> → {String(v).slice(0, 80) || "(empty)"}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {filledEntries.length ? (
        <div className="text-xs" data-testid="merge-preview-filled">
          <div className="font-semibold mb-0.5"
                 style={{ color: colors.onSurface }}>
            Empty fields on primary now filled:
          </div>
          <ul className="pl-4 list-disc space-y-0.5"
                style={{ color: colors.onSurfaceSecondary }}>
            {filledEntries.map(([k, v]) => (
              <li key={k}>
                <b>{k}</b> ← {String(v).slice(0, 80) || "(empty)"}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {!reconciledEntries.length && !filledEntries.length ? (
        <div className="text-xs" style={{ color: colors.muted }}>
          No field-level changes on the primary — every field already
          matches or the secondaries were empty.
        </div>
      ) : null}
      <div className="text-xs" data-testid="merge-preview-rewire">
        <div className="font-semibold mb-0.5"
               style={{ color: colors.onSurface }}>
          Related records reassigned to primary:
        </div>
        <div className="flex flex-wrap gap-1.5">
          {[
            ["jobs", rewired.jobs],
            ["invoices", rewired.invoices],
            ["payments", rewired.payments],
            ["service_reports", rewired.service_reports],
            ["estimates", rewired.estimates],
            ["leads", rewired.leads],
          ].map(([k, v]) => (
            <span key={k}
                   className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
                   style={{
                     backgroundColor: (Number(v) || 0) > 0
                       ? colors.accent.sky[100]
                       : colors.surface,
                     color: (Number(v) || 0) > 0
                       ? colors.accent.sky[700]
                       : colors.muted,
                     border: `1px solid ${colors.border}`,
                   }}
                   data-testid={`merge-preview-count-${k}`}>
              {Number(v) || 0} {k}
            </span>
          ))}
        </div>
        <div className="text-[11px] mt-1"
               style={{ color: colors.muted }}>
          {totalRewired.toLocaleString()} related record{totalRewired === 1 ? "" : "s"} total.
        </div>
      </div>
    </div>
  );
}


export default function MergeCustomersModal({
  open,
  onClose,
  customers,   // Full customer row objects for the selected ids.
  onDone,      // (result) => void — parent toasts + reloads.
  onError,     // (message) => void — optional; parent toasts on error.
}) {
  const [primaryId, setPrimaryId] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [detectGroups, setDetectGroups] = useState([]);
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  // Feb 2026 · Type-to-confirm input retired — ``confirmText`` state
  // is no longer referenced. Kept out of the render path entirely.
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const debounceRef = useRef(null);
  const previewCounterRef = useRef(0);

  const selectedIds = useMemo(
    () => (customers || []).map((c) => c.id).filter(Boolean),
    [customers],
  );

  // Detection scan on open.
  useEffect(() => {
    if (!open || !selectedIds.length) return undefined;
    let cancelled = false;
    (async () => {
      setScanning(true);
      try {
        const res = await api.post(
          "/customers/detect-duplicates",
          { filters: { customer_ids: selectedIds } },
        );
        if (cancelled) return;
        setDetectGroups(res?.duplicate_groups || []);
      } catch {
        if (!cancelled) setDetectGroups([]);
      } finally {
        if (!cancelled) setScanning(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open, selectedIds.join(",")]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Reset internal state whenever the modal reopens with a new set.
  useEffect(() => {
    if (!open) return;
    setPrimaryId(null);
    setPreview(null);
    setErrorMsg("");
    setSubmitting(false);
  }, [open, selectedIds.join(",")]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Dry-run preview on primary change (debounced).
  useEffect(() => {
    if (!open) return undefined;
    if (!primaryId) { setPreview(null); return undefined; }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const secs = selectedIds.filter((x) => x !== primaryId);
    if (!secs.length) return undefined;
    const runId = ++previewCounterRef.current;
    debounceRef.current = setTimeout(async () => {
      setPreviewLoading(true);
      try {
        const res = await api.post("/customers/merge", {
          primary_id: primaryId,
          secondary_ids: secs,
          dry_run: true,
        });
        if (previewCounterRef.current === runId) setPreview(res);
      } catch (e) {
        if (previewCounterRef.current === runId) {
          setPreview(null);
          setErrorMsg(e?.message || "Preview failed");
        }
      } finally {
        if (previewCounterRef.current === runId) setPreviewLoading(false);
      }
    }, 500);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [primaryId, open, selectedIds.join(",")]);   // eslint-disable-line react-hooks/exhaustive-deps

  const primaryName = useMemo(() => {
    const p = (customers || []).find((c) => c.id === primaryId);
    return p ? (p.name || "(unnamed)") : null;
  }, [customers, primaryId]);

  const canMerge =
    !!primaryId
    && !!preview
    && !submitting;

  const doMerge = async () => {
    if (!canMerge) return;
    setSubmitting(true);
    setErrorMsg("");
    try {
      const secs = selectedIds.filter((x) => x !== primaryId);
      const res = await api.post("/customers/merge", {
        primary_id: primaryId,
        secondary_ids: secs,
        dry_run: false,
      });
      // Success — hand off to parent.
      onDone?.({
        ...res,
        primary_name: primaryName,
        merged_count: secs.length,
      });
    } catch (e) {
      const msg = e?.message || "Merge failed. Please retry.";
      setErrorMsg(msg);
      onError?.(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const footer = (
    <>
      <Button variant="ghost" onClick={onClose} disabled={submitting}
               testid="merge-modal-cancel">
        Cancel
      </Button>
      <button
        type="button"
        onClick={doMerge}
        disabled={!canMerge}
        className="px-4 py-2 rounded-lg text-sm font-semibold inline-flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
        style={{
          backgroundColor: colors.accent.rose[500],
          color: "#fff",
        }}
        data-testid="merge-modal-confirm"
      >
        {submitting ? (
          <><Loader2 size={14} className="animate-spin" /> Merging…</>
        ) : (
          <>Merge into {primaryName || "…"}</>
        )}
      </button>
    </>
  );

  return (
    <Modal
      open={open}
      onClose={submitting ? () => {} : onClose}
      title={`Merge ${(customers || []).length} customer${(customers || []).length === 1 ? "" : "s"}`}
      testid="merge-customers-modal"
      wide
      footer={footer}
    >
      <div className="space-y-3">
        <DetectionBanner
          scanning={scanning}
          groups={detectGroups}
          selectedIds={selectedIds}
        />

        <div>
          <div className="text-[11px] font-bold uppercase tracking-wider mb-1.5"
                 style={{ color: colors.muted }}>
            Choose the primary
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2"
                 data-testid="merge-cards-grid">
            {(customers || []).map((c) => (
              <CustomerCard
                key={c.id}
                customer={c}
                isPrimary={primaryId === c.id}
                onSelectPrimary={setPrimaryId}
              />
            ))}
          </div>
        </div>

        <div>
          <div className="text-[11px] font-bold uppercase tracking-wider mb-1.5"
                 style={{ color: colors.muted }}>
            Preview
          </div>
          <PreviewSection
            preview={preview}
            loading={previewLoading}
            primaryName={primaryName}
          />
        </div>

        {/* Feb 2026 · Type-to-confirm removed — the "Type MERGE"
            input previously required to enable the Merge button
            has been retired. The two-click safety flow (open modal
            → click Merge) is preserved via the Cancel button and
            the disabled state while dry-run preview is pending. */}

        {errorMsg ? (
          <div className="rounded-xl px-3 py-2 text-xs"
                 style={{
                   backgroundColor: colors.accent.rose[50],
                   color: colors.accent.rose[700],
                   border: `1px solid ${colors.accent.rose[100]}`,
                 }}
                 data-testid="merge-modal-error">
            {errorMsg}
          </div>
        ) : null}
      </div>
    </Modal>
  );
}
