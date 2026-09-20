/**
 * Phase C · Feb-2026 · Sales Pipeline Kanban.
 *
 * Route: ``/admin/pipeline``. Admin+super_admin+manager only —
 * ``<AdminOrManager>`` in App.js keeps the surface in lock-step with
 * the backend contract (403 ``insufficient_role_for_pipeline``).
 *
 * Layout
 * ------
 * - Sticky column-header row across the top (color-coded pills).
 * - 5 columns: Leads · Quoted · Scheduled · Completed · Follow-up.
 * - Full-width Risk swimlane below, horizontal scroll.
 * - Filter bar: date_from / date_to (ISO date), owner_id.
 * - 60s polling. No websocket.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  KanbanSquare, AlertTriangle, DollarSign, User, Loader2, RefreshCw,
} from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";


const _COLUMN_META = {
  leads:     { label: "Leads",     accent: "#94A3B8", empty: "No leads yet" },
  quoted:    { label: "Quoted",    accent: "#F59E0B", empty: "No open quotes" },
  scheduled: { label: "Scheduled", accent: "#0284C7", empty: "Nothing scheduled" },
  completed: { label: "Completed", accent: "#16A34A", empty: "No completed jobs this window" },
  follow_up: { label: "Follow-up", accent: "#7C3AED", empty: "No follow-ups this week" },
};
const _COLUMN_ORDER = ["leads", "quoted", "scheduled", "completed", "follow_up"];
const _SEV_DOT = {
  urgent:      "#DC2626",
  recommended: "#D97706",
  info:        "#0284C7",
};
const _POLL_MS = 60_000;


function _fmtMoney(cents, currency) {
  const n = (cents || 0) / 100;
  try {
    return n.toLocaleString(undefined, {
      style: "currency", currency: currency || "USD",
      maximumFractionDigits: 2, minimumFractionDigits: 2,
    });
  } catch {
    return `$${n.toFixed(2)}`;
  }
}


function KanbanCard({ card, onClick }) {
  const isRisk = card.source === "alert";
  const testid = isRisk
    ? `pipeline-risk-card-${card.id}`
    : `pipeline-card-${card.source}-${card.id}`;
  const dot = _SEV_DOT[card.risk_severity] || colors.muted;
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testid}
      data-source={card.source}
      data-customer-id={card.customer_id}
      className="w-full text-left rounded-xl p-3 transition-colors hover:opacity-95"
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
    >
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-sm font-semibold truncate"
                style={{ color: colors.onSurface }}>
          {card.customer_name || "—"}
        </span>
        {isRisk ? (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase rounded-full px-2 py-0.5"
                 style={{ background: colors.surfaceSecondary,
                          color: colors.muted }}
                 data-testid="pipeline-risk-severity-dot">
            <span className="inline-block h-2 w-2 rounded-full"
                   style={{ background: dot }} />
            {card.risk_category || "risk"}
          </span>
        ) : (
          <span className="text-[11px] font-mono"
                 style={{ color: colors.muted }}>
            {_fmtMoney(card.amount_cents, card.currency)}
          </span>
        )}
      </div>
      <div className="text-xs mb-1 truncate"
             style={{ color: colors.onSurfaceSecondary }}>
        {card.title || "—"}
      </div>
      <div className="flex items-center gap-2 text-[11px]"
             style={{ color: colors.muted }}>
        {card.assigned_to_display_name ? (
          <span className="inline-flex items-center gap-1">
            <User size={10} />
            {card.assigned_to_display_name}
          </span>
        ) : null}
        <span className="ml-auto capitalize">
          {card.status || ""}
        </span>
      </div>
    </button>
  );
}


function ColumnSkeleton() {
  return (
    <div className="flex flex-col gap-2" data-testid="pipeline-column-skeleton">
      {[0, 1, 2].map((k) => (
        <div key={k}
              className="rounded-xl h-20 animate-pulse"
              style={{ background: colors.surfaceSecondary }} />
      ))}
    </div>
  );
}


export default function SalesPipeline() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [data, setData]       = useState(null);

  // Filters — default: 90-day trailing window.
  const defaultFrom = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - 90);
    return d.toISOString().slice(0, 10);
  }, []);
  const defaultTo = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() + 90);
    return d.toISOString().slice(0, 10);
  }, []);
  const [dateFrom, setDateFrom] = useState(defaultFrom);
  const [dateTo,   setDateTo]   = useState(defaultTo);
  const [ownerId,  setOwnerId]  = useState("");
  const [owners,   setOwners]   = useState([]);

  const load = useCallback(async () => {
    setError("");
    const qs = new URLSearchParams();
    if (dateFrom) qs.set("date_from", `${dateFrom}T00:00:00+00:00`);
    if (dateTo)   qs.set("date_to",   `${dateTo}T23:59:59+00:00`);
    if (ownerId)  qs.set("owner_id",  ownerId);
    try {
      const r = await api.get(`/pipeline/kanban?${qs.toString()}`);
      setData(r);
    } catch (e) {
      setError((e && e.message) || "Failed to load pipeline");
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, ownerId]);

  // Populate the owner dropdown from technicians. Best-effort — a
  // failure just leaves the dropdown empty, we don't block the page.
  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/technicians");
        const rows = Array.isArray(r) ? r : (r && r.items) || [];
        setOwners(rows.filter(Boolean));
      } catch {
        // silent — dropdown just stays empty
      }
    })();
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const t = setInterval(load, _POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  const cardHref = (card) => {
    if (card.source === "lead")   return `/leads/${card.id}`;
    if (card.source === "quote")  return `/quotes/${card.id}`;
    if (card.source === "job")    return `/jobs/${card.id}`;
    if (card.source === "alert")  {
      const qs = new URLSearchParams();
      if (card.risk_category) qs.set("category", card.risk_category);
      if (card.risk_alert_id) qs.set("highlight", card.risk_alert_id);
      return `/admin/intelligence/alerts?${qs.toString()}`;
    }
    return "#";
  };
  const onCardClick = (card) => navigate(cardHref(card));

  const columns = data?.columns || _COLUMN_ORDER.map((k) => ({
    key: k, label: _COLUMN_META[k].label,
    total_amount_cents: 0, total_currency: "USD",
    count: 0, cards: [],
  }));
  const swim = data?.risk_swimlane || [];

  return (
    <div className="p-4 md:p-6" data-testid="pipeline-page">
      <div className="flex items-center gap-2 mb-4">
        <KanbanSquare size={20} style={{ color: colors.brand }} />
        <h1 className="text-2xl font-bold"
             style={{ color: colors.onSurface }}>
          Sales Pipeline
        </h1>
        <button
          type="button"
          onClick={load}
          data-testid="pipeline-refresh-btn"
          className="ml-auto inline-flex items-center gap-1 text-xs rounded-full px-3 py-1"
          style={{ background: colors.surfaceSecondary,
                    color: colors.onSurfaceSecondary }}
        >
          <RefreshCw size={12} />
          Refresh
        </button>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <label className="flex flex-col text-xs"
                style={{ color: colors.muted }}>
          <span>Date from</span>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            data-testid="pipeline-filter-date-from"
            className="mt-1 rounded-lg px-2 py-1 text-sm"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}`,
                      color: colors.onSurface }}
          />
        </label>
        <label className="flex flex-col text-xs"
                style={{ color: colors.muted }}>
          <span>Date to</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            data-testid="pipeline-filter-date-to"
            className="mt-1 rounded-lg px-2 py-1 text-sm"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}`,
                      color: colors.onSurface }}
          />
        </label>
        <label className="flex flex-col text-xs"
                style={{ color: colors.muted }}>
          <span>Owner</span>
          <select
            value={ownerId}
            onChange={(e) => setOwnerId(e.target.value)}
            data-testid="pipeline-filter-owner"
            className="mt-1 rounded-lg px-2 py-1 text-sm"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}`,
                      color: colors.onSurface }}
          >
            <option value="">All</option>
            {owners.map((o) => (
              <option key={o.id || o.technician_id || o.name}
                       value={o.technician_id || o.id}>
                {o.name || o.email || o.id}
              </option>
            ))}
          </select>
        </label>
        {loading ? (
          <span className="inline-flex items-center gap-1 text-xs"
                 style={{ color: colors.muted }}
                 data-testid="pipeline-loading-indicator">
            <Loader2 size={12} className="animate-spin" />
            Loading
          </span>
        ) : null}
        {error ? (
          <span className="text-xs" style={{ color: colors.error }}
                 data-testid="pipeline-error">
            {error}
          </span>
        ) : null}
      </div>

      {/* Column headers (sticky) */}
      <div
        className="grid gap-3 sticky top-0 z-10 pt-1 pb-2"
        style={{
          gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
          background: colors.surface,
        }}
        data-testid="pipeline-column-headers"
      >
        {_COLUMN_ORDER.map((k) => {
          const meta = _COLUMN_META[k];
          const col = columns.find((c) => c.key === k) || {
            count: 0, total_amount_cents: 0, total_currency: "USD",
          };
          return (
            <div key={k}
                  className="rounded-xl p-2 flex items-center justify-between gap-2"
                  style={{
                    background: colors.surfaceSecondary,
                    borderLeft: `4px solid ${meta.accent}`,
                  }}
                  data-testid={`pipeline-column-header-${k}`}>
              <div className="min-w-0">
                <div className="text-sm font-semibold truncate"
                       style={{ color: colors.onSurface }}>
                  {meta.label}
                  <span className="ml-2 text-xs font-normal"
                         style={{ color: colors.muted }}
                         data-testid={`pipeline-column-count-${k}`}>
                    ({col.count})
                  </span>
                </div>
                <div className="text-[11px] font-mono"
                       style={{ color: colors.onSurfaceSecondary }}
                       data-testid={`pipeline-column-total-${k}`}>
                  {_fmtMoney(col.total_amount_cents, col.total_currency)}
                </div>
              </div>
              <DollarSign size={14} style={{ color: colors.muted }} />
            </div>
          );
        })}
      </div>

      {/* Column bodies */}
      <div className="grid gap-3 mt-2"
             style={{ gridTemplateColumns: "repeat(5, minmax(0, 1fr))" }}
             data-testid="pipeline-columns-grid">
        {_COLUMN_ORDER.map((k) => {
          const meta = _COLUMN_META[k];
          const col = columns.find((c) => c.key === k) || { cards: [] };
          return (
            <div key={k} className="flex flex-col gap-2"
                  data-testid={`pipeline-column-${k}`}>
              {loading && !data ? (
                <ColumnSkeleton />
              ) : col.cards.length === 0 ? (
                <div
                  className="rounded-xl p-4 text-center text-xs"
                  style={{
                    background: colors.surface,
                    border: `1px dashed ${colors.border}`,
                    color: colors.muted,
                  }}
                  data-testid={`pipeline-column-empty-${k}`}
                >
                  {meta.empty}
                </div>
              ) : (
                col.cards.map((card) => (
                  <KanbanCard key={`${card.source}-${card.id}`}
                                card={card}
                                onClick={() => onCardClick(card)} />
                ))
              )}
            </div>
          );
        })}
      </div>

      {/* Risk swimlane */}
      {swim.length > 0 ? (
        <div className="mt-6" data-testid="pipeline-risk-swimlane">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle size={16} style={{ color: colors.warning }} />
            <span className="text-sm font-semibold"
                   style={{ color: colors.onSurface }}>
              Risk swimlane · {swim.length}
            </span>
          </div>
          <div className="flex gap-3 overflow-x-auto pb-2"
                 data-testid="pipeline-risk-swimlane-strip">
            {swim.map((card) => (
              <div key={`alert-${card.id}`}
                    className="min-w-[240px] max-w-[280px]">
                <KanbanCard card={card}
                              onClick={() => onCardClick(card)} />
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-6 text-xs"
              style={{ color: colors.muted }}
              data-testid="pipeline-risk-swimlane-empty">
          No risk alerts on active pipeline customers.
        </div>
      )}
    </div>
  );
}
