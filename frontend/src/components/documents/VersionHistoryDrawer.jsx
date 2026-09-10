/**
 * Feb-2026 · Editable Sent Docs · Phase 2 —
 * Right-side slide-in drawer that lists the version history of an
 * invoice / estimate / quote. Read-only in Phase 2: "View snapshot"
 * shows a modal with the raw doc snapshot as JSON; "Restore this
 * version" is present but disabled with a tooltip explaining that
 * restore ships in Phase 3.
 *
 * Data source:
 *   * ``GET /api/invoices/{id}/versions``  → docType = "invoice"
 *   * ``GET /api/quotes/{qid}/versions``   → docType = "quote"
 * Both return the shared shape defined in
 * ``backend/routers/document_versions.py`` — items ordered newest
 * first, ``document_snapshot`` inline so the preview modal never
 * needs a follow-up round-trip.
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import { api } from "@/api";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from "@/components/ui/tooltip";
import { Clock, Eye, RotateCcw, User } from "lucide-react";


function _relative(ts) {
  if (!ts) return "";
  const then = new Date(ts).getTime();
  if (!Number.isFinite(then)) return String(ts);
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (secs < 45) return "just now";
  if (secs < 90) return "1 minute ago";
  const mins = Math.floor(secs / 60);
  if (mins < 45) return `${mins} minutes ago`;
  if (mins < 90) return "1 hour ago";
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} hours ago`;
  const days = Math.floor(hrs / 24);
  if (days < 2) return "1 day ago";
  if (days < 30) return `${days} days ago`;
  const months = Math.floor(days / 30);
  if (months < 2) return "1 month ago";
  if (months < 12) return `${months} months ago`;
  return `${Math.floor(months / 12)} years ago`;
}

function _absolute(ts) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return String(ts);
  }
}


function SnapshotModal({ version, onClose }) {
  if (!version) return null;
  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-6"
      data-testid={`doc-version-snapshot-modal-${version.version_id}`}
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg max-w-3xl w-full max-h-[80vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b flex items-center justify-between">
          <div>
            <div className="font-semibold">
              Version {version.version} snapshot
            </div>
            <div className="text-xs text-slate-500">
              {_absolute(version.created_at)} · {version.created_by?.email || "system"}
            </div>
          </div>
          <button
            className="text-slate-500 hover:text-slate-700"
            onClick={onClose}
            data-testid="doc-version-snapshot-close"
          >
            Close
          </button>
        </div>
        <pre
          className="flex-1 overflow-auto p-4 text-xs bg-slate-50 whitespace-pre-wrap break-words"
          data-testid="doc-version-snapshot-body"
        >
          {JSON.stringify(version.document_snapshot, null, 2)}
        </pre>
      </div>
    </div>
  );
}


function VersionRow({ version, onView }) {
  const isBaseline = !!version.is_baseline;
  const summary = version.change_summary;
  const displayName = version.created_by?.name
                       || version.created_by?.email
                       || "system";
  return (
    <li
      className="border-b py-3 px-4"
      data-testid={`doc-version-row-${version.version_id}`}
      data-is-baseline={isBaseline ? "true" : "false"}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Clock size={14} className="text-slate-400" />
            <span
              title={_absolute(version.created_at)}
              data-testid={`doc-version-timestamp-${version.version_id}`}
            >
              {_relative(version.created_at)}
            </span>
            {isBaseline ? (
              <span
                className="ml-1 px-1.5 py-0.5 text-[10px] uppercase tracking-wide bg-slate-100 rounded"
                data-testid={`doc-version-baseline-badge-${version.version_id}`}
              >
                original
              </span>
            ) : null}
          </div>
          <div className="mt-1 text-xs text-slate-600 flex items-center gap-1">
            <User size={12} className="text-slate-400" />
            <span>{displayName}</span>
          </div>
          <div
            className="mt-1 text-sm text-slate-800"
            data-testid={`doc-version-summary-${version.version_id}`}
          >
            {isBaseline
              ? "Original sent version"
              : (summary || "No content changes captured")}
          </div>
        </div>
        <div className="flex-shrink-0 flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => onView(version)}
            data-testid={`doc-version-view-${version.version_id}`}
          >
            <Eye size={14} className="mr-1" /> View
          </Button>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  data-testid={`doc-version-restore-wrap-${version.version_id}`}
                >
                  <Button
                    size="sm"
                    variant="outline"
                    disabled
                    data-testid={`doc-version-restore-${version.version_id}`}
                  >
                    <RotateCcw size={14} className="mr-1" />
                    Restore
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent
                data-testid={`doc-version-restore-tooltip-${version.version_id}`}
              >
                Restore ships in Phase 3.
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>
    </li>
  );
}


export default function VersionHistoryDrawer({
  open,
  onOpenChange,
  docType,   // "invoice" | "quote"
  docId,
}) {
  const endpoint = useMemo(() => {
    if (docType === "invoice") return `/invoices/${docId}/versions`;
    return `/quotes/${docId}/versions`;
  }, [docType, docId]);

  const [state, setState] = useState({ loading: false, error: null, items: [] });
  const [preview, setPreview] = useState(null);

  const load = useCallback(async () => {
    setState({ loading: true, error: null, items: [] });
    try {
      const data = await api.get(endpoint);
      const items = Array.isArray(data?.items) ? data.items : [];
      setState({ loading: false, error: null, items });
    } catch (e) {
      setState({
        loading: false,
        error: e?.message || "Failed to load version history.",
        items: [],
      });
    }
  }, [endpoint]);

  useEffect(() => {
    if (open && docId) load();
    // Reset the preview modal every time the drawer re-opens so a
    // stale snapshot from a previous doc never leaks across.
    if (!open) setPreview(null);
  }, [open, docId, load]);

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent
          side="right"
          className="w-full sm:max-w-md p-0 flex flex-col"
          data-testid="doc-version-history-drawer"
        >
          <SheetHeader className="p-4 border-b">
            <SheetTitle>Version history</SheetTitle>
            <SheetDescription>
              Every edit to this document is captured. Newest first.
            </SheetDescription>
          </SheetHeader>

          <div className="flex-1 overflow-auto" data-testid="doc-version-history-body">
            {state.loading ? (
              <div
                className="p-6 text-sm text-slate-500"
                data-testid="doc-version-history-loading"
              >
                Loading version history…
              </div>
            ) : state.error ? (
              <div
                className="p-6 text-sm text-red-600"
                data-testid="doc-version-history-error"
              >
                {state.error}
              </div>
            ) : state.items.length === 0 ? (
              <div
                className="p-6 text-sm text-slate-500"
                data-testid="doc-version-history-empty"
              >
                No edits have been made to this document.
              </div>
            ) : (
              <ul data-testid="doc-version-history-list">
                {state.items.map((v) => (
                  <VersionRow
                    key={v.version_id}
                    version={v}
                    onView={setPreview}
                  />
                ))}
              </ul>
            )}
          </div>
        </SheetContent>
      </Sheet>
      <SnapshotModal version={preview} onClose={() => setPreview(null)} />
    </>
  );
}
