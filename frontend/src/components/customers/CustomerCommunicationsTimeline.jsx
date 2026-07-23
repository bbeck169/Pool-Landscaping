/**
 * Phase 16 · Item 4 · Feb-2026 — Customer Detail communications timeline.
 *
 * Bottom-of-page section on the Customer Detail view. Admin-only —
 * the parent guards the mount so tech / customer roles never see it.
 *
 *   Fetches `/api/communications-log?customer_id=<cid>&page_size=50`
 *   with a "Load more" cursor. Each row shows a channel icon, subject
 *   (email) or body preview (SMS), sent-at (relative + absolute
 *   tooltip), sent-by user, and colored status badges. Clicking a
 *   row opens a right-side sheet with the full delivery timeline —
 *   matching the shape used on `/admin/communications-log`.
 */
import React, { useEffect, useState } from "react";
import {
  Mail, MessageSquareText, Loader2, MessageCircle, ChevronRight,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";

const STATUS_TONES = {
  sent:      { bg: "#E5E7EB", fg: "#374151", label: "Sent" },
  delivered: { bg: "#E5E7EB", fg: "#374151", label: "Delivered" },
  opened:    { bg: "#DBEAFE", fg: "#1E3A8A", label: "Opened" },
  clicked:   { bg: "#DCFCE7", fg: "#166534", label: "Clicked" },
  bounced:   { bg: "#FEE2E2", fg: "#991B1B", label: "Bounced" },
  failed:    { bg: "#FCA5A5", fg: "#7F1D1D", label: "Failed" },
};

function relTime(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return String(iso);
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

function StatusBadge({ row }) {
  // SMS delivered surfaces as "Delivered" (gray) since carriers
  // don't expose reads — same rule the Communications Log page uses.
  let key = row.status_derived;
  if (row.channel === "sms" && key === "sent"
        && row.sms_status_final === "delivered") {
    key = "delivered";
  }
  const t = STATUS_TONES[key] || STATUS_TONES.sent;
  return (
    <span
      className="text-[10px] px-2 py-0.5 rounded-full font-semibold"
      style={{ background: t.bg, color: t.fg }}
      data-testid={`customer-comm-status-${key}`}
    >
      {t.label}
    </span>
  );
}

export default function CustomerCommunicationsTimeline({ customerId }) {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");

  const loadPage = (p) => {
    if (!customerId) return;
    setLoading(true); setError("");
    api.get(
      `/communications-log?customer_id=${encodeURIComponent(customerId)}`
      + `&page=${p}&page_size=50`
    ).then((r) => {
      setTotal(r?.total || 0);
      setRows((prev) => p === 1
        ? (r?.items || [])
        : [...prev, ...(r?.items || [])]);
    }).catch((e) => {
      setError(e?.message || "Failed to load communications");
    }).finally(() => setLoading(false));
  };

  useEffect(() => { setPage(1); loadPage(1); /* eslint-disable-next-line */ }, [customerId]);

  const hasMore = rows.length < total;
  const loadMore = () => {
    const next = page + 1;
    setPage(next);
    loadPage(next);
  };

  return (
    <section
      className="rounded-2xl p-4 md:p-5 mt-6"
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="customer-comm-timeline"
    >
      <div className="flex items-center gap-2 mb-3">
        <MessageCircle size={16} color={colors.brand} />
        <h3
          className="text-sm font-bold"
          style={{ color: colors.onSurface }}
        >
          Communications
        </h3>
        <div style={{ flex: 1 }} />
        <span className="text-[11px]" style={{ color: colors.muted }}>
          {total} total
        </span>
      </div>

      {error ? (
        <div className="text-xs px-2 py-1 rounded"
             style={{ background: "#FEE2E2", color: "#991B1B" }}>
          {error}
        </div>
      ) : loading && rows.length === 0 ? (
        <div className="p-4 text-sm text-center"
             style={{ color: colors.muted }}>
          <Loader2 className="inline animate-spin mr-2" size={14} />
          Loading…
        </div>
      ) : rows.length === 0 ? (
        <div
          className="p-6 text-sm text-center"
          style={{ color: colors.muted }}
          data-testid="customer-comm-empty"
        >
          No communications yet.
        </div>
      ) : (
        <>
          <ul className="grid gap-1"
              data-testid="customer-comm-list">
            {rows.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => setSelected(r)}
                  className="w-full flex items-start gap-2 px-2 py-2 rounded text-left hover:bg-black/[0.03] transition-colors"
                  style={{ cursor: "pointer" }}
                  data-testid={`customer-comm-row-${r.id}`}
                >
                  <span
                    className="mt-0.5 shrink-0"
                    style={{ color: colors.brand }}
                    title={r.channel}
                  >
                    {r.channel === "email"
                      ? <Mail size={14} />
                      : <MessageSquareText size={14} />}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm truncate"
                         style={{ color: colors.onSurface }}>
                      {r.subject || r.body_preview
                        || <span style={{ color: colors.muted }}>(empty)</span>}
                    </div>
                    <div className="text-[11px] flex items-center gap-2 flex-wrap"
                         style={{ color: colors.muted }}>
                      <span title={r.created_at}>{relTime(r.created_at)}</span>
                      {r.recipient_email || r.recipient_phone ? (
                        <span>· to {r.recipient_email || r.recipient_phone}</span>
                      ) : null}
                    </div>
                  </div>
                  <StatusBadge row={r} />
                  <ChevronRight size={14} style={{ color: colors.muted }} />
                </button>
              </li>
            ))}
          </ul>
          {hasMore ? (
            <div className="mt-3 flex justify-center">
              <button
                type="button"
                onClick={loadMore}
                disabled={loading}
                className="text-xs font-semibold px-3 py-1.5 rounded-md"
                style={{
                  background: colors.surfaceSecondary,
                  border: `1px solid ${colors.border}`,
                  color: colors.onSurface, cursor: "pointer",
                }}
                data-testid="customer-comm-load-more"
              >
                {loading ? "Loading…" : `Load more (${total - rows.length} remaining)`}
              </button>
            </div>
          ) : null}
        </>
      )}

      {/* Detail side sheet — mirrors the shape used on the
          Communications Log page for consistency. */}
      <Sheet open={!!selected} onOpenChange={(v) => !v && setSelected(null)}>
        <SheetContent
          className="w-full sm:max-w-lg overflow-y-auto"
          data-testid="customer-comm-detail-sheet"
        >
          {selected ? (
            <>
              <SheetHeader>
                <SheetTitle>
                  {selected.subject || (selected.channel === "sms"
                    ? "SMS message" : "Message detail")}
                </SheetTitle>
              </SheetHeader>
              <div className="mt-4 space-y-3">
                <div className="flex items-center gap-2">
                  <StatusBadge row={selected} />
                  <span className="text-xs" style={{ color: colors.muted }}>
                    {selected.channel.toUpperCase()}
                    {" · via "}{selected.provider || "unknown"}
                  </span>
                </div>
                <div className="text-xs" style={{ color: colors.muted }}>
                  To: <b style={{ color: colors.onSurface }}>
                    {selected.recipient_email || selected.recipient_phone || "—"}
                  </b>
                </div>
                <div
                  className="rounded-lg p-3"
                  style={{
                    background: colors.surfaceSecondary,
                    border: `1px solid ${colors.border}`,
                  }}
                >
                  <div className="text-[10px] font-bold uppercase mb-2"
                       style={{ color: colors.muted }}>
                    Delivery timeline
                  </div>
                  <ul className="text-xs space-y-1"
                      style={{ color: colors.onSurface }}>
                    <li>· Created — {selected.created_at || "?"}</li>
                    {selected.delivered_at ? (
                      <li>· Delivered — {selected.delivered_at}</li>
                    ) : null}
                    {selected.opened_at ? (
                      <li>· Opened — {selected.opened_at}</li>
                    ) : null}
                    {selected.clicked_at ? (
                      <li>· Clicked — {selected.clicked_at}</li>
                    ) : null}
                    {selected.bounced_at ? (
                      <li>· Bounced — {selected.bounced_at}</li>
                    ) : null}
                    {selected.sms_status_at ? (
                      <li>· SMS carrier: {selected.sms_status_final} — {selected.sms_status_at}</li>
                    ) : null}
                  </ul>
                </div>
                <div
                  className="text-sm rounded-lg p-3"
                  style={{
                    background: colors.surface,
                    border: `1px solid ${colors.border}`,
                    color: colors.onSurface,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {selected.body_preview || "(empty)"}
                </div>
              </div>
            </>
          ) : null}
        </SheetContent>
      </Sheet>
    </section>
  );
}
