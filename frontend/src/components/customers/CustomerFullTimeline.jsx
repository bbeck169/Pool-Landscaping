/**
 * Feb-2026 · Customer Communication Timeline — full history view.
 *
 * Sources merged server-side from ``marketing_deliveries`` (email +
 * SMS), ``invoices`` and ``estimates`` (both live in the ``quotes``
 * collection under distinct ``doc_type`` values). Consumes:
 *
 *   * admin:  ``GET /api/customers/{id}/timeline``
 *   * portal: ``GET /api/customers/me/timeline``
 *
 * Both accept ``page``, ``page_size``, ``kind`` (CSV filter of
 * ``email,sms,invoice,estimate``), ``from``, ``to``. Response
 * shape: ``{ items, page, page_size, total, total_pages }``.
 *
 * Pagination row is ALWAYS mounted (mirrors the portal service-
 * reports post-tester fix) so mobile tests + Vitest can locate the
 * testids regardless of ``total_pages``.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Mail, MessageSquare, FileText, Receipt, Clock, ExternalLink }
  from "lucide-react";
import { Link } from "react-router-dom";

import { api } from "@/api";
import { colors } from "@/theme";


// ═══════════════════════════════════════════════════════════════════
// Utilities
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

const _KIND_META = {
  email:    { label: "Email",    icon: Mail,          bg: "#DCFCE7", fg: "#166534" },
  sms:      { label: "SMS",      icon: MessageSquare, bg: "#FEE2E2", fg: "#991B1B" },
  invoice:  { label: "Invoice",  icon: Receipt,       bg: "#DBEAFE", fg: "#1E3A8A" },
  estimate: { label: "Estimate", icon: FileText,      bg: "#FEF3C7", fg: "#92400E" },
};


function KindPill({ kind }) {
  const meta = _KIND_META[kind] || { label: kind, icon: Mail, bg: "#F1F5F9", fg: "#475569" };
  const Icon = meta.icon;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider"
      style={{ background: meta.bg, color: meta.fg }}
      data-testid={`timeline-pill-${kind}`}
    >
      <Icon size={10} />
      {meta.label}
    </span>
  );
}


function Row({ item, index }) {
  const meta = _KIND_META[item.kind] || _KIND_META.email;
  const hasUrl = !!item.url;
  const money = typeof item.total === "number" && item.total > 0
    ? `$${item.total.toFixed(2)}`
    : "";
  return (
    <li
      className="flex items-start gap-3 py-3"
      style={{ borderBottom: `1px solid ${colors.border}` }}
      data-testid={`timeline-row-${index}`}
    >
      <span
        className="mt-1 rounded-full shrink-0"
        style={{ width: 10, height: 10, background: meta.fg }}
        aria-hidden="true"
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <KindPill kind={item.kind} />
          <span
            className="text-xs"
            style={{ color: colors.muted }}
            title={item.created_at}
          >
            <Clock size={10} className="inline mr-1" />
            {_relative(item.created_at)}
          </span>
          {money ? (
            <span className="text-xs font-semibold"
                  style={{ color: colors.onSurface }}>
              {money}
            </span>
          ) : null}
          {item.delivery_status ? (
            <span
              className="text-[10px] font-semibold uppercase tracking-wide rounded-full px-2 py-0.5"
              style={{ background: colors.surfaceSecondary,
                        color: colors.muted }}
            >
              {item.delivery_status}
            </span>
          ) : null}
        </div>
        <div
          className="text-sm mt-1 font-medium truncate"
          style={{ color: colors.onSurface }}
          data-testid={`timeline-subject-${index}`}
        >
          {hasUrl ? (
            <Link
              to={item.url}
              className="inline-flex items-center gap-1"
              style={{ color: meta.fg }}
              data-testid={`timeline-link-${index}`}
            >
              {item.subject} <ExternalLink size={12} />
            </Link>
          ) : item.subject}
        </div>
        {item.recipient ? (
          <div className="text-[11px] font-mono mt-0.5"
                style={{ color: colors.muted }}>
            to {item.recipient}
          </div>
        ) : null}
      </div>
    </li>
  );
}


const _KIND_CHIPS = ["all", "email", "sms", "invoice", "estimate"];


export default function CustomerFullTimeline({ scope = "admin", customerId }) {
  const isAdmin = scope === "admin";
  const basePath = isAdmin
    ? `/customers/${customerId}/timeline`
    : `/customers/me/timeline`;
  const [items, setItems]           = useState([]);
  const [page, setPage]             = useState(1);
  const [pageSize]                  = useState(20);
  const [total, setTotal]           = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [activeKind, setActiveKind] = useState("all");
  const [loading, setLoading]       = useState(true);
  const [err, setErr]               = useState("");

  const kindCsv = useMemo(
    () => (activeKind === "all" ? "" : activeKind),
    [activeKind],
  );

  const fetchPage = useCallback(async () => {
    if (isAdmin && !customerId) return;
    setLoading(true);
    setErr("");
    try {
      const qs = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (kindCsv) qs.set("kind", kindCsv);
      const r = await api.get(`${basePath}?${qs}`);
      setItems(r?.items || []);
      setTotal(r?.total || 0);
      setTotalPages(r?.total_pages || 0);
    } catch (e) {
      setErr(e?.message || "Couldn't load timeline");
    } finally {
      setLoading(false);
    }
  }, [basePath, page, pageSize, kindCsv, isAdmin, customerId]);
  useEffect(() => { fetchPage(); }, [fetchPage]);

  // Reset page → 1 on any filter change.
  useEffect(() => { setPage(1); }, [activeKind]);

  return (
    <div data-testid={`full-timeline-${scope}`}>
      {/* Filter chips ───────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2 mb-3"
            data-testid="timeline-filters">
        {_KIND_CHIPS.map((k) => {
          const on = activeKind === k;
          return (
            <button
              key={k}
              type="button"
              onClick={() => setActiveKind(k)}
              className="text-xs font-semibold rounded-full px-3 py-1 transition-colors"
              style={{
                background: on
                  ? (_KIND_META[k]?.fg || colors.brand || colors.onSurface)
                  : colors.surface,
                color: on ? colors.onBrand || "#FFFFFF" : colors.onSurface,
                border: `1px solid ${on
                  ? "transparent"
                  : colors.border}`,
              }}
              data-testid={`timeline-filter-${k}`}
            >
              {k === "all" ? "All" : (_KIND_META[k]?.label || k)}
            </button>
          );
        })}
      </div>

      {/* List ───────────────────────────────────────────────────── */}
      {loading ? (
        <div className="text-sm rounded-lg p-3"
              style={{ background: colors.surfaceSecondary,
                        color: colors.muted }}
              data-testid="timeline-loading">
          Loading timeline…
        </div>
      ) : err ? (
        <div className="text-sm rounded-lg p-3"
              style={{ background: "#FEE2E2", color: "#991B1B" }}
              data-testid="timeline-error">
          {err}
        </div>
      ) : items.length === 0 ? (
        <div className="text-sm rounded-lg p-6 text-center"
              style={{ background: colors.surfaceSecondary,
                        color: colors.muted,
                        border: `1px solid ${colors.border}` }}
              data-testid="timeline-empty">
          No timeline entries for this filter.
        </div>
      ) : (
        <ul className="list-none" data-testid="timeline-list">
          {items.map((it, i) => (
            <Row key={`${it.ref_type}-${it.ref_id}-${i}`} item={it} index={i} />
          ))}
        </ul>
      )}

      {/* Pagination — always mounted ────────────────────────────── */}
      <div className="mt-4 flex items-center justify-between gap-2"
            data-testid="timeline-pagination">
        <button
          type="button"
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page <= 1}
          className="rounded-lg px-3 py-2 text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ border: `1px solid ${colors.border}`,
                    background: colors.surface, minHeight: 40 }}
          data-testid="timeline-pagination-prev"
        >
          ← Prev
        </button>
        <div className="text-sm" style={{ color: colors.muted }}
              data-testid="timeline-page-indicator">
          Page {page} of {Math.max(totalPages, 1)} ({total} total)
        </div>
        <button
          type="button"
          onClick={() => setPage((p) => Math.min(Math.max(totalPages, 1), p + 1))}
          disabled={page >= Math.max(totalPages, 1)}
          className="rounded-lg px-3 py-2 text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ border: `1px solid ${colors.border}`,
                    background: colors.surface, minHeight: 40 }}
          data-testid="timeline-pagination-next"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
