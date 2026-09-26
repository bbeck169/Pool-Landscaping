/**
 * QuoteViewHistory — QV-ui · Feb 2026 · Admin view-history card.
 *
 * Renders the aggregated view stats for a single quote on the admin
 * detail page. Fetches ``GET /api/quotes/{id}/views`` once on mount
 * and shows:
 *
 *   • Summary line: "Viewed N times · first {relative} · last {relative}"
 *     — empty-state text when the quote has never been viewed.
 *   • Expandable event log: each row shows a source badge
 *     (email / sms / portal / link), UA class, timestamp.
 *
 * Divergence vs sibling ``InvoiceViewHistory``:
 *   • Renders ``ua_class`` in the middle column (invoice sibling
 *     renders raw ``user_agent`` — quote events carry a friendlier
 *     ``ua_class`` string per the QV-service backend contract).
 *   • Empty-state wording ("This quote has never been viewed.")
 *     matches QV-service dispatch. Byte-identical relative-time
 *     wording via the shared ``formatRelativeFromIso`` helper.
 *
 * The component is self-contained: no props beyond ``quoteId``. It's
 * safe to mount on any admin/super_admin role — the endpoint
 * enforces its own RBAC (403 for technician/customer).
 */
import React, { useEffect, useState } from "react";
import { Eye, ChevronDown, ChevronUp } from "lucide-react";
import { api } from "@/api";
import {
  formatRelativeFromIso,
  formatLocalFromIso,
} from "@/lib/relativeTime";

// Mirrors ``backend/services/quote_view_tracker._VALID_SOURCES``.
const SOURCE_LABELS = {
  email: { label: "Email",  bg: "#DBEAFE", fg: "#1E40AF" },
  sms:   { label: "SMS",    bg: "#D1FAE5", fg: "#065F46" },
  portal:{ label: "Portal", bg: "#F3E8FF", fg: "#6B21A8" },
  link:  { label: "Link",   bg: "#F3F4F6", fg: "#374151" },
};


export default function QuoteViewHistory({ quoteId }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    if (!quoteId) return;
    setErr("");
    api.get(`/quotes/${quoteId}/views`)
      .then((r) => { if (!cancelled) setData(r); })
      .catch((e) => {
        if (!cancelled) setErr(
          e?.message || "Failed to load view history",
        );
      });
    return () => { cancelled = true; };
  }, [quoteId, reloadKey]);

  if (err) {
    return (
      <div
        style={{
          padding: 12, borderRadius: 8, background: "#FEF2F2",
          border: "1px solid #FCA5A5", color: "#991B1B",
          fontSize: 13,
          display: "flex", alignItems: "center",
          justifyContent: "space-between", gap: 12,
        }}
        data-testid="quote-view-history-error"
      >
        <span>Couldn't load view history — {err}</span>
        <button
          type="button"
          onClick={() => setReloadKey((n) => n + 1)}
          style={{
            fontSize: 12, color: "#991B1B",
            background: "#fff", border: "1px solid #FCA5A5",
            padding: "4px 8px", borderRadius: 6, cursor: "pointer",
          }}
          data-testid="quote-view-history-retry"
        >
          Retry
        </button>
      </div>
    );
  }
  if (!data) {
    return (
      <div
        style={{ padding: 12, color: "#6B7280", fontSize: 13 }}
        data-testid="quote-view-history-loading"
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
        background: "#fff", borderRadius: 8,
        border: "1px solid #E5E7EB",
        padding: 16, marginTop: 12,
      }}
      data-testid="quote-view-history-card"
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Eye size={18} />
          <span style={{ fontWeight: 600, fontSize: 15 }}>
            View History
          </span>
        </div>
        {events.length > 0 && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              fontSize: 12, color: "#4B5563",
              background: "transparent",
              border: "1px solid #E5E7EB",
              padding: "4px 8px", borderRadius: 6, cursor: "pointer",
            }}
            data-testid="quote-view-history-toggle"
          >
            {open ? "Collapse" : `Expand (${events.length})`}
            {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        )}
      </div>

      {viewCount === 0 ? (
        <div
          style={{ marginTop: 12, fontSize: 13, color: "#6B7280" }}
          data-testid="quote-view-history-empty"
        >
          This quote has never been viewed.
        </div>
      ) : (
        <div
          style={{ marginTop: 12, fontSize: 13, color: "#374151" }}
          data-testid="quote-view-history-summary"
        >
          Viewed{" "}
          <strong data-testid="quote-view-count">{viewCount}</strong>{" "}
          {viewCount === 1 ? "time" : "times"}
          {firstAt && (
            <>
              {" · first "}
              <span
                title={formatLocalFromIso(firstAt)}
                data-testid="quote-view-first-at"
              >
                {formatRelativeFromIso(firstAt)}
              </span>
            </>
          )}
          {lastAt && (
            <>
              {" · last "}
              <span
                title={formatLocalFromIso(lastAt)}
                data-testid="quote-view-last-at"
              >
                {formatRelativeFromIso(lastAt)}
              </span>
            </>
          )}
        </div>
      )}

      {open && events.length > 0 && (
        <div
          style={{
            marginTop: 12, borderTop: "1px solid #F3F4F6",
            paddingTop: 8, maxHeight: 240, overflowY: "auto",
          }}
          data-testid="quote-view-history-events"
        >
          {events.map((ev, idx) => {
            const meta = SOURCE_LABELS[ev.source] || SOURCE_LABELS.link;
            return (
              <div
                key={`${ev.viewed_at}-${idx}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "auto 1fr auto",
                  alignItems: "center", gap: 8, padding: "6px 0",
                  borderBottom: idx === events.length - 1
                    ? "none" : "1px solid #F9FAFB",
                }}
                data-testid={`quote-view-history-event-${idx}`}
              >
                <span
                  style={{
                    background: meta.bg, color: meta.fg,
                    borderRadius: 999,
                    fontSize: 11, fontWeight: 600,
                    padding: "2px 8px",
                  }}
                  data-testid={`quote-view-history-event-source-${idx}`}
                >
                  {meta.label}
                </span>
                <span
                  style={{
                    fontSize: 12, color: "#6B7280",
                    overflow: "hidden", textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={ev.user_agent || ""}
                  data-testid={`quote-view-history-event-ua-${idx}`}
                >
                  {ev.ua_class || "—"}
                </span>
                <span
                  style={{ fontSize: 12, color: "#374151" }}
                  title={formatLocalFromIso(ev.viewed_at)}
                >
                  {formatRelativeFromIso(ev.viewed_at)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
