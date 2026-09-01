/**
 * Phase I7 · Wave A · Feb-2026 — Communication Timeline (shared).
 *
 * Vertical timeline of a customer's SMS + email events sourced
 * from ``GET /api/customers/{customer_id}/communication-timeline``.
 * Wave A mounts on the admin CustomerDetail Timeline tab; Wave B
 * will drop the same component into the portal Communication tab
 * with ``variant="portal"``.
 *
 * Server-side portal field-stripping (see
 * ``backend/routers/communication_timeline.py``) means the portal
 * variant never receives ``actor_user_id`` / ``delivery_error`` —
 * the component defensively hides the delivery-status pill + error
 * banner for ``variant="portal"`` as well, so an admin who
 * accidentally passes the portal variant on the admin surface
 * still can't leak the sensitive fields.
 */
import React, { useCallback, useEffect, useState } from "react";
import { MessageSquare, Mail, Clock, AlertTriangle }
  from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";


// ═══════════════════════════════════════════════════════════════════
// Small utilities
// ═══════════════════════════════════════════════════════════════════
function _relative(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return new Date(iso).toLocaleDateString();
}


function TypePill({ kind }) {
  const isSms = kind === "sms";
  const bg = isSms ? "#FEE2E2" : "#DCFCE7";
  const fg = isSms ? "#991B1B" : "#166534";
  const Icon = isSms ? MessageSquare : Mail;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider"
      style={{ background: bg, color: fg }}
      data-testid={`timeline-pill-${kind}`}
    >
      <Icon size={10} />
      {isSms ? "Message" : "Email"}
    </span>
  );
}


function StatusPill({ status, testid }) {
  const map = {
    delivered: { bg: "#DCFCE7", fg: "#166534" },
    sent:      { bg: "#DBEAFE", fg: "#1E3A8A" },
    queued:    { bg: "#FEF3C7", fg: "#92400E" },
    reserved:  { bg: "#FEF3C7", fg: "#92400E" },
    failed:    { bg: "#FEE2E2", fg: "#991B1B" },
  };
  const s = map[status] || { bg: "#F1F5F9", fg: "#475569" };
  return (
    <span
      className="inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
      style={{ background: s.bg, color: s.fg }}
      data-testid={testid}
    >
      {status}
    </span>
  );
}


function Row({ item, isAdmin }) {
  const [expanded, setExpanded] = useState(false);
  const body = item.body_preview || "";
  const clamp = body.length > 220;
  const shown = expanded || !clamp ? body : `${body.slice(0, 220)}…`;
  const isEmail = item.type === "email";
  return (
    <li
      className="relative pl-8 pb-4"
      data-testid={`timeline-row-${item.id}`}
    >
      {/* Marker circle */}
      <span
        className="absolute left-0 top-1.5 rounded-full"
        style={{
          width: 14, height: 14,
          background: item.type === "sms" ? "#DC2626" : "#16A34A",
          border: `2px solid ${colors.surface}`,
          boxShadow: `0 0 0 2px ${item.type === "sms"
                                          ? "#DC2626" : "#16A34A"}`,
        }}
      />
      <div className="flex items-center gap-2 flex-wrap mb-1">
        <TypePill kind={item.type} />
        <span
          className="text-xs"
          style={{ color: colors.muted }}
          title={item.occurred_at}
          data-testid={`timeline-time-${item.id}`}
        >
          <Clock size={10} className="inline mr-1" />
          {_relative(item.occurred_at)}
        </span>
        <span className="text-xs" style={{ color: colors.muted }}>
          by{" "}
          <span
            className="font-bold"
            style={{ color: colors.onSurface }}
            data-testid={`timeline-actor-${item.id}`}
          >
            {item.actor_label}
          </span>
        </span>
        {isAdmin && item.delivery_status ? (
          <StatusPill status={item.delivery_status}
                          testid={`timeline-status-${item.id}`} />
        ) : null}
      </div>
      {isEmail && item.subject ? (
        <div
          className="text-sm font-bold mb-1"
          style={{ color: colors.onSurface }}
          data-testid={`timeline-subject-${item.id}`}
        >
          Subject: {item.subject}
        </div>
      ) : null}
      {body ? (
        <div
          className="text-sm"
          style={{ color: colors.onSurface, whiteSpace: "pre-wrap" }}
          data-testid={`timeline-body-${item.id}`}
        >
          {shown}
          {clamp ? (
            <button
              type="button"
              className="ml-1 text-xs font-semibold underline"
              style={{ color: colors.brand || colors.onSurface }}
              onClick={() => setExpanded((v) => !v)}
              data-testid={`timeline-expand-${item.id}`}
            >
              {expanded ? "show less" : "show more"}
            </button>
          ) : null}
        </div>
      ) : null}
      {isAdmin && item.delivery_error ? (
        <div
          className="mt-1 text-xs flex items-center gap-1"
          style={{ color: "#991B1B" }}
          data-testid={`timeline-error-${item.id}`}
        >
          <AlertTriangle size={12} /> {item.delivery_error}
        </div>
      ) : null}
      {item.recipient ? (
        <div className="mt-1 text-[11px] font-mono"
                 style={{ color: colors.muted }}
                 data-testid={`timeline-recipient-${item.id}`}>
          to {item.recipient}
        </div>
      ) : null}
    </li>
  );
}


// ═══════════════════════════════════════════════════════════════════
// Component
// ═══════════════════════════════════════════════════════════════════
export default function CommunicationTimeline({
  customerId,
  variant = "admin",
  limit = 50,
}) {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [items, setItems] = useState([]);
  const [nextBefore, setNextBefore] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const isAdmin = variant === "admin";

  const fetchPage = useCallback(async (before = null) => {
    if (!customerId) return;
    if (!before) setLoading(true);
    else setLoadingMore(true);
    try {
      const qs = new URLSearchParams({ limit: String(limit) });
      if (before) qs.set("before", before);
      const r = await api.get(
        `/customers/${customerId}/communication-timeline?${qs}`,
      );
      const next = r?.items || [];
      setItems((prev) => before ? [...prev, ...next] : next);
      setHasMore(Boolean(r?.has_more));
      setNextBefore(r?.next_before || null);
      setErr("");
    } catch (e) {
      setErr(e?.message || "Couldn't load timeline");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [customerId, limit]);
  useEffect(() => { fetchPage(null); }, [fetchPage]);

  if (loading) {
    return (
      <div className="space-y-3"
               data-testid="communication-timeline-loading">
        {[0, 1, 2].map((i) => (
          <div key={i}
                    className="rounded-lg h-12"
                    style={{ background: colors.surfaceSecondary }} />
        ))}
      </div>
    );
  }

  if (err) {
    return (
      <div className="text-sm rounded-lg px-3 py-2"
                style={{ background: "#FEE2E2", color: "#991B1B" }}
                data-testid="communication-timeline-error">
        {err}
      </div>
    );
  }

  if (!items.length) {
    return (
      <div className="rounded-2xl p-6 text-center text-sm"
                style={{ background: colors.surfaceSecondary,
                            color: colors.muted,
                            border: `1px solid ${colors.border}` }}
                data-testid="communication-timeline-empty">
        No email or SMS communications yet.
      </div>
    );
  }

  return (
    <div data-testid={`communication-timeline-${variant}`}>
      <ol
        className="relative"
        style={{
          borderLeft: `2px dashed ${colors.borderStrong || "#D1D5DB"}`,
          marginLeft: 6,
        }}
        data-testid="communication-timeline-list"
      >
        {items.map((it) => (
          <Row key={it.id} item={it} isAdmin={isAdmin} />
        ))}
      </ol>
      {hasMore ? (
        <button
          type="button"
          className="mt-2 text-sm font-semibold px-3 py-1.5 rounded-lg"
          style={{
            background: colors.surfaceSecondary,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
            opacity: loadingMore ? 0.6 : 1,
            cursor: loadingMore ? "not-allowed" : "pointer",
          }}
          onClick={() => fetchPage(nextBefore)}
          disabled={loadingMore}
          data-testid="communication-timeline-load-more"
        >
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      ) : null}
    </div>
  );
}
