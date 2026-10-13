/**
 * P2 #5 · Feb-2026 · CommunicationDetailModal
 *
 * Shared Dialog modal that renders the full detail of a single
 * communication-timeline row.  Powers the row-click modal across
 * every admin timeline surface:
 *
 *   1. CustomerCommunicationsTimeline (replaces the previous Sheet)
 *   2. CommunicationsLogPage (standalone admin page)
 *   3. CommunicationTimeline (I7 Wave A, admin customer-detail tab)
 *   4. CommTimelineItem on LeadDetail
 *
 * Fetches `GET /api/communications-detail/{rowId}` on open.  Admin+
 * manager only — the backend 403s role=customer / role=technician.
 *
 * Email bodies render inside a sandboxed <iframe srcDoc> (no
 * allow-scripts) matching the BusinessSettings email-preview
 * pattern — prevents script execution against the admin app even
 * if a tenant-authored template contains <script>.
 *
 * SMS / plaintext bodies render inside <pre class="whitespace-pre-wrap">.
 *
 * Rows with body_available=false (e.g. notification_dispatch_log
 * events, metadata-only communications_log rows) render the
 * operator-friendly fallback copy approved during P2 #5 scoping.
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";

const BODY_NOT_STORED_COPY = (
  "Message body was not stored on this record. This may be a "
  + "metadata-only dispatch log entry or predates body persistence."
);


function _fmtTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch (_e) {
    return iso;
  }
}


function _StatusRow({ detail }) {
  const items = [
    ["Sent", detail.sent_at],
    ["Delivered", detail.delivered_at],
    ["Opened", detail.opened_at],
    ["Clicked", detail.clicked_at],
    ["Bounced", detail.bounced_at],
  ].filter(([, v]) => !!v);
  if (!items.length) return null;
  return (
    <ul
      className="text-xs space-y-1 rounded-lg p-3 bg-slate-50 border border-slate-200"
      data-testid="comm-detail-timeline"
    >
      {items.map(([label, iso]) => (
        <li key={label}>
          <span className="font-semibold">{label}:</span>{" "}
          <span data-testid={`comm-detail-ts-${label.toLowerCase()}`}>
            {_fmtTime(iso)}
          </span>
        </li>
      ))}
    </ul>
  );
}


export default function CommunicationDetailModal({ open, rowId, onClose }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    if (!open || !rowId) return;
    setLoading(true);
    setError("");
    setDetail(null);
    api.get(`/communications-detail/${encodeURIComponent(rowId)}`)
      .then((d) => { setDetail(d); })
      .catch((e) => {
        const msg = e?.status === 404
          ? "This record is no longer available."
          : (e?.message || "Failed to load detail");
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, [open, rowId]);

  const title = detail?.subject
    || (detail?.channel === "sms" ? "SMS message" : "Email message");

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => { if (!v) onClose?.(); }}
    >
      <DialogContent
        className="max-w-2xl max-h-[85vh] overflow-y-auto"
        data-testid="comm-detail-modal"
      >
        <DialogHeader>
          <DialogTitle data-testid="comm-detail-title">{title}</DialogTitle>
          <DialogDescription data-testid="comm-detail-meta">
            {detail
              ? [
                  (detail.channel || "").toUpperCase(),
                  detail.direction || null,
                  detail.provider ? `via ${detail.provider}` : null,
                ].filter(Boolean).join(" · ")
              : "Loading communication detail"}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="py-6 text-sm text-center text-slate-500"
                data-testid="comm-detail-loading">
            Loading…
          </div>
        ) : error ? (
          <div className="py-4 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded p-3"
                data-testid="comm-detail-error">
            {error}
          </div>
        ) : detail ? (
          <div className="mt-2 space-y-3">
            <div className="text-xs text-slate-600 grid grid-cols-1 gap-1">
              {detail.from ? (
                <div data-testid="comm-detail-from">
                  <span className="font-semibold">From:</span> {detail.from}
                </div>
              ) : null}
              {detail.to ? (
                <div data-testid="comm-detail-to">
                  <span className="font-semibold">To:</span> {detail.to}
                </div>
              ) : null}
              {(detail.cc || []).length ? (
                <div data-testid="comm-detail-cc">
                  <span className="font-semibold">Cc:</span>{" "}
                  {(detail.cc || []).join(", ")}
                </div>
              ) : null}
              {(detail.bcc || []).length ? (
                <div data-testid="comm-detail-bcc">
                  <span className="font-semibold">Bcc:</span>{" "}
                  {(detail.bcc || []).join(", ")}
                </div>
              ) : null}
              {detail.delivery_status ? (
                <div data-testid="comm-detail-status">
                  <span className="font-semibold">Status:</span>{" "}
                  {detail.delivery_status}
                </div>
              ) : null}
              {detail.provider_response_id ? (
                <div className="font-mono text-[11px] text-slate-500"
                      data-testid="comm-detail-provider-id">
                  provider_response_id · {detail.provider_response_id}
                </div>
              ) : null}
            </div>

            <_StatusRow detail={detail} />

            {detail.body_available ? (
              detail.body_format === "html" ? (
                <iframe
                  title="Email body"
                  data-testid="comm-detail-body-iframe"
                  sandbox=""
                  srcDoc={detail.body}
                  style={{
                    width: "100%", minHeight: 320,
                    border: "1px solid #e2e8f0", borderRadius: 6,
                    background: "white",
                  }}
                />
              ) : (
                <pre
                  className="text-sm rounded-lg p-3 bg-white border border-slate-200 whitespace-pre-wrap break-words"
                  data-testid="comm-detail-body-text"
                >
                  {detail.body}
                </pre>
              )
            ) : (
              <div
                className="text-sm italic rounded-lg p-3 bg-amber-50 border border-amber-200 text-amber-900"
                data-testid="comm-detail-body-missing"
              >
                {BODY_NOT_STORED_COPY}
              </div>
            )}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

export { BODY_NOT_STORED_COPY };
