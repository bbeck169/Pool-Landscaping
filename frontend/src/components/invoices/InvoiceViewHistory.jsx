/**
 * InvoiceViewHistory — Phase K47 · Feb 2026 · Admin view-history card.
 *
 * Renders the aggregated view stats for a single invoice on the admin
 * detail page. Fetches ``GET /api/invoices/{id}/views`` once on mount
 * and shows:
 *
 *   • Summary line: "Viewed N times · first {relative} · last {relative}"
 *     — empty-state text when the invoice has never been viewed.
 *   • Expandable event log: each row shows a source badge
 *     (email / sms / portal / link), timestamp, and (when present)
 *     a truncated user-agent string.
 *
 * The component is self-contained: no props beyond ``invoiceId``. It's
 * safe to mount on any admin/office role — the endpoint enforces its
 * own RBAC (403 for technician/customer).
 */
import React, { useEffect, useState } from "react";
import { Eye, ChevronDown, ChevronUp } from "lucide-react";
import { api } from "@/api";

// Mirrors backend/services/invoice_view_tracker.py::_VALID_SOURCES.
const SOURCE_LABELS = {
  email: { label: "Email",  bg: "#DBEAFE", fg: "#1E40AF" },
  sms:   { label: "SMS",    bg: "#D1FAE5", fg: "#065F46" },
  portal:{ label: "Portal", bg: "#F3E8FF", fg: "#6B21A8" },
  link:  { label: "Link",   bg: "#F3F4F6", fg: "#374151" },
};

function _relativeFromIso(iso) {
  if (!iso) return "";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "";
  const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (diffSec < 60)   return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60)   return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24)     return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  if (diffD < 30)     return `${diffD}d ago`;
  const diffMo = Math.floor(diffD / 30);
  return `${diffMo}mo ago`;
}

function _fmtLocal(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export default function InvoiceViewHistory({ invoiceId }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!invoiceId) return;
    api.get(`/invoices/${invoiceId}/views`)
      .then((r) => { if (!cancelled) setData(r); })
      .catch((e) => { if (!cancelled) setErr(e?.message || "Failed to load view history"); });
    return () => { cancelled = true; };
  }, [invoiceId]);

  if (err) {
    return (
      <div
        style={{
          padding: 12, borderRadius: 8, background: "#FEF2F2",
          border: "1px solid #FCA5A5", color: "#991B1B", fontSize: 13,
        }}
        data-testid="invoice-view-history-error"
      >
        Couldn't load view history — {err}
      </div>
    );
  }
  if (!data) {
    return (
      <div
        style={{ padding: 12, color: "#6B7280", fontSize: 13 }}
        data-testid="invoice-view-history-loading"
      >
        Loading view history…
      </div>
    );
  }

  const {
    first_viewed_at: firstAt,
    last_viewed_at: lastAt,
    view_count: viewCount = 0,
    events = [],
  } = data;

  return (
    <div
      style={{
        background: "#fff", borderRadius: 8, border: "1px solid #E5E7EB",
        padding: 16, marginTop: 12,
      }}
      data-testid="invoice-view-history-card"
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Eye size={18} />
          <span style={{ fontWeight: 600, fontSize: 15 }}>View History</span>
        </div>
        {events.length > 0 && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              fontSize: 12, color: "#4B5563",
              background: "transparent", border: "1px solid #E5E7EB",
              padding: "4px 8px", borderRadius: 6, cursor: "pointer",
            }}
            data-testid="invoice-view-history-toggle"
          >
            {open ? "Collapse" : `Expand (${events.length})`}
            {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        )}
      </div>

      {viewCount === 0 ? (
        <div
          style={{ marginTop: 12, fontSize: 13, color: "#6B7280" }}
          data-testid="invoice-view-history-empty"
        >
          This invoice hasn't been opened yet.
        </div>
      ) : (
        <div style={{ marginTop: 12, fontSize: 13, color: "#374151" }} data-testid="invoice-view-history-summary">
          Viewed <strong data-testid="invoice-view-count">{viewCount}</strong>{" "}
          {viewCount === 1 ? "time" : "times"}
          {firstAt && (
            <>
              {" · first "}
              <span title={_fmtLocal(firstAt)} data-testid="invoice-view-first-at">{_relativeFromIso(firstAt)}</span>
            </>
          )}
          {lastAt && (
            <>
              {" · last "}
              <span title={_fmtLocal(lastAt)} data-testid="invoice-view-last-at">{_relativeFromIso(lastAt)}</span>
            </>
          )}
        </div>
      )}

      {open && events.length > 0 && (
        <div
          style={{
            marginTop: 12, borderTop: "1px solid #F3F4F6", paddingTop: 8,
            maxHeight: 240, overflowY: "auto",
          }}
          data-testid="invoice-view-history-events"
        >
          {events.map((ev, idx) => {
            const meta = SOURCE_LABELS[ev.source] || SOURCE_LABELS.link;
            return (
              <div
                key={`${ev.viewed_at}-${idx}`}
                style={{
                  display: "grid", gridTemplateColumns: "auto 1fr auto",
                  alignItems: "center", gap: 8, padding: "6px 0",
                  borderBottom: idx === events.length - 1 ? "none" : "1px solid #F9FAFB",
                }}
                data-testid={`invoice-view-history-event-${idx}`}
              >
                <span
                  style={{
                    background: meta.bg, color: meta.fg, borderRadius: 999,
                    fontSize: 11, fontWeight: 600, padding: "2px 8px",
                  }}
                  data-testid={`invoice-view-history-event-source-${idx}`}
                >
                  {meta.label}
                </span>
                <span style={{ fontSize: 12, color: "#6B7280", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {ev.user_agent || ev.ip || "—"}
                </span>
                <span
                  style={{ fontSize: 12, color: "#374151" }}
                  title={_fmtLocal(ev.viewed_at)}
                >
                  {_relativeFromIso(ev.viewed_at)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
