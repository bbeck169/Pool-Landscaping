// LSP-1 · Feb-2026 — Lead-Sense visitor-intent dashboard.
//
// Admin-only surface. Tenant-scoped on the server. Reads:
//   * GET /api/lead-sense/intents          (paginated rows)
//   * GET /api/lead-sense/intents/summary  (aggregate window stats)
//
// Row click expands an in-line detail panel with page_title,
// user_agent, viewport, capture_mode, and — when the session
// converted — a link back to the existing lead detail page at
// /leads/{lead_id}.
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api";
import { Card } from "@/components/ui/card";
import { colors } from "@/theme";
import { ArrowLeft, ChevronDown, ChevronRight } from "lucide-react";

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200];
const CONVERTED_OPTIONS = [
  { value: "",      label: "All sessions" },
  { value: "true",  label: "Converted only" },
  { value: "false", label: "Not yet converted" },
];
const SORT_OPTIONS = [
  { value: "created_at_desc", label: "Newest first" },
  { value: "created_at_asc",  label: "Oldest first" },
];

function _fmt(ts) {
  if (!ts) return "—";
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}
function _short(u, max = 40) {
  if (!u) return "—";
  return u.length > max ? u.slice(0, max - 1) + "…" : u;
}

export default function LeadsIntentPage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());
  const [filters, setFilters] = useState({
    session_id: "",
    converted:  "",
    since:      "",
    until:      "",
    sort:       "created_at_desc",
  });

  const buildQs = () => {
    const qs = new URLSearchParams();
    if (filters.session_id) qs.set("session_id", filters.session_id);
    if (filters.converted)  qs.set("converted",  filters.converted);
    if (filters.since)      qs.set("since",      filters.since);
    if (filters.until)      qs.set("until",      filters.until);
    qs.set("sort",      filters.sort);
    qs.set("page",      String(page));
    qs.set("page_size", String(pageSize));
    return qs.toString();
  };

  const refresh = () => {
    setLoading(true);
    setError("");
    api.get(`/lead-sense/intents?${buildQs()}`)
      .then((r) => {
        setItems(r?.items || []);
        setTotal(r?.total || 0);
        setTotalPages(r?.total_pages || 1);
      })
      .catch((e) => setError(e?.message || "Failed to load intent list"))
      .finally(() => setLoading(false));
  };

  const refreshSummary = () => {
    const qs = new URLSearchParams();
    if (filters.since) qs.set("since", filters.since);
    if (filters.until) qs.set("until", filters.until);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    api.get(`/lead-sense/intents/summary${suffix}`)
      .then((r) => setSummary(r))
      .catch(() => setSummary(null));
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [
    filters.session_id, filters.converted, filters.since, filters.until,
    filters.sort, page, pageSize,
  ]);
  useEffect(() => { refreshSummary(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [
    filters.since, filters.until,
  ]);

  const toggleExpand = (id) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const setF = (k, v) => { setFilters((f) => ({ ...f, [k]: v })); setPage(1); };

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto" data-testid="leads-intent-page">
      <div className="flex items-center gap-3 mb-4">
        <Link
          to="/leads"
          className="inline-flex items-center gap-1 text-sm hover:underline"
          data-testid="leads-intent-back"
          style={{ color: colors.muted }}
        >
          <ArrowLeft size={14} /> Leads
        </Link>
        <h1 className="text-xl font-bold" style={{ color: colors.onSurface }}>
          Lead-Sense · Visitor Intent
        </h1>
      </div>

      {/* Summary tiles */}
      <div
        className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4"
        data-testid="leads-intent-summary"
      >
        <Card className="p-3">
          <div className="text-[11px] uppercase tracking-wide" style={{ color: colors.muted }}>
            Total sessions
          </div>
          <div className="text-2xl font-bold" data-testid="summary-total-sessions">
            {summary?.total_sessions ?? "—"}
          </div>
        </Card>
        <Card className="p-3">
          <div className="text-[11px] uppercase tracking-wide" style={{ color: colors.muted }}>
            Conversion rate
          </div>
          <div className="text-2xl font-bold" data-testid="summary-conversion-rate">
            {summary?.conversion_rate_pct != null
              ? `${summary.conversion_rate_pct}%` : "—"}
          </div>
        </Card>
        <Card className="p-3">
          <div className="text-[11px] uppercase tracking-wide" style={{ color: colors.muted }}>
            Top page
          </div>
          <div className="text-sm font-semibold truncate" data-testid="summary-top-page">
            {summary?.top_pages?.[0]?.page || "—"}
          </div>
        </Card>
        <Card className="p-3">
          <div className="text-[11px] uppercase tracking-wide" style={{ color: colors.muted }}>
            Top referrer
          </div>
          <div className="text-sm font-semibold truncate" data-testid="summary-top-referrer">
            {summary?.top_referrers?.[0]?.referrer || "—"}
          </div>
        </Card>
      </div>

      {/* Filter bar */}
      <Card className="p-3 mb-3" data-testid="leads-intent-filters">
        <div className="flex flex-wrap gap-2 items-end">
          <label className="flex flex-col text-xs">
            <span className="mb-0.5" style={{ color: colors.muted }}>Session ID</span>
            <input
              type="text"
              value={filters.session_id}
              onChange={(e) => setF("session_id", e.target.value)}
              placeholder="session id"
              data-testid="intent-filter-session-id"
              className="px-2 py-1 border rounded text-sm"
              style={{ borderColor: colors.border }}
            />
          </label>
          <label className="flex flex-col text-xs">
            <span className="mb-0.5" style={{ color: colors.muted }}>Converted</span>
            <select
              value={filters.converted}
              onChange={(e) => setF("converted", e.target.value)}
              data-testid="intent-filter-converted"
              className="px-2 py-1 border rounded text-sm"
              style={{ borderColor: colors.border }}
            >
              {CONVERTED_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col text-xs">
            <span className="mb-0.5" style={{ color: colors.muted }}>Since</span>
            <input
              type="datetime-local"
              value={filters.since}
              onChange={(e) => setF("since", e.target.value)}
              data-testid="intent-filter-since"
              className="px-2 py-1 border rounded text-sm"
              style={{ borderColor: colors.border }}
            />
          </label>
          <label className="flex flex-col text-xs">
            <span className="mb-0.5" style={{ color: colors.muted }}>Until</span>
            <input
              type="datetime-local"
              value={filters.until}
              onChange={(e) => setF("until", e.target.value)}
              data-testid="intent-filter-until"
              className="px-2 py-1 border rounded text-sm"
              style={{ borderColor: colors.border }}
            />
          </label>
          <label className="flex flex-col text-xs">
            <span className="mb-0.5" style={{ color: colors.muted }}>Sort</span>
            <select
              value={filters.sort}
              onChange={(e) => setF("sort", e.target.value)}
              data-testid="intent-filter-sort"
              className="px-2 py-1 border rounded text-sm"
              style={{ borderColor: colors.border }}
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col text-xs">
            <span className="mb-0.5" style={{ color: colors.muted }}>Page size</span>
            <select
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
              data-testid="intent-filter-page-size"
              className="px-2 py-1 border rounded text-sm"
              style={{ borderColor: colors.border }}
            >
              {PAGE_SIZE_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
        </div>
      </Card>

      {/* Table */}
      <Card className="overflow-hidden" data-testid="leads-intent-table">
        <div
          className="grid grid-cols-12 gap-2 px-4 py-2 text-[10px] uppercase font-semibold"
          style={{
            borderBottom: `1px solid ${colors.border}`,
            background:   colors.surfaceSecondary,
            color:        colors.muted,
          }}
        >
          <div className="col-span-1"></div>
          <div className="col-span-2">When</div>
          <div className="col-span-2">Session</div>
          <div className="col-span-3">Page</div>
          <div className="col-span-2">Referrer</div>
          <div className="col-span-1">UTM</div>
          <div className="col-span-1">Converted</div>
        </div>
        {loading ? (
          <div className="px-4 py-6 text-sm" style={{ color: colors.muted }}
               data-testid="intent-loading">
            Loading…
          </div>
        ) : error ? (
          <div className="px-4 py-6 text-sm text-red-600" data-testid="intent-error">
            {error}
          </div>
        ) : items.length === 0 ? (
          <div className="px-4 py-6 text-sm" style={{ color: colors.muted }}
               data-testid="intent-empty">
            No visitor intent in the current window.
          </div>
        ) : (
          items.map((it) => {
            const isOpen = expanded.has(it.id);
            let utm = "";
            try {
              const url = new URL(it.current_url);
              utm = url.searchParams.get("utm_source") || "";
            } catch { /* current_url may be malformed on legacy rows */ }
            return (
              <React.Fragment key={it.id}>
                <div
                  className="grid grid-cols-12 gap-2 px-4 py-2 text-sm items-center hover:bg-slate-50 cursor-pointer"
                  style={{ borderBottom: `1px solid ${colors.border}` }}
                  onClick={() => toggleExpand(it.id)}
                  data-testid={`intent-row-${it.id}`}
                >
                  <div className="col-span-1">
                    {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </div>
                  <div className="col-span-2 text-xs">{_fmt(it.occurred_at)}</div>
                  <div className="col-span-2 text-xs truncate" title={it.session_id}>
                    {it.session_id}
                  </div>
                  <div className="col-span-3 text-xs truncate" title={it.current_url}>
                    {_short(it.current_url, 60)}
                  </div>
                  <div className="col-span-2 text-xs truncate" title={it.referrer || ""}>
                    {_short(it.referrer, 40)}
                  </div>
                  <div className="col-span-1 text-xs truncate">{utm || "—"}</div>
                  <div className="col-span-1">
                    {it.has_converted ? (
                      <span
                        className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                        style={{ background: "#DCFCE7", color: "#166534" }}
                        data-testid={`intent-converted-badge-${it.id}`}
                      >
                        Converted
                      </span>
                    ) : (
                      <span
                        className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                        style={{ background: "#F3F4F6", color: "#4B5563" }}
                      >
                        Open
                      </span>
                    )}
                  </div>
                </div>
                {isOpen && (
                  <div
                    className="px-4 py-3 text-xs"
                    style={{
                      borderBottom: `1px solid ${colors.border}`,
                      background:   colors.surfaceSecondary,
                    }}
                    data-testid={`intent-detail-${it.id}`}
                  >
                    <div className="grid gap-1">
                      <div>
                        <span className="font-semibold">Page title:</span>{" "}
                        {it.page_title || "—"}
                      </div>
                      <div className="truncate">
                        <span className="font-semibold">User agent:</span>{" "}
                        {it.user_agent || "—"}
                      </div>
                      <div>
                        <span className="font-semibold">Viewport:</span>{" "}
                        {it.viewport ? `${it.viewport.w}×${it.viewport.h}` : "—"}
                      </div>
                      <div>
                        <span className="font-semibold">Capture mode:</span>{" "}
                        {it.capture_mode || "beacon"}
                      </div>
                      <div>
                        <span className="font-semibold">Full URL:</span>{" "}
                        <span className="break-all">{it.current_url || "—"}</span>
                      </div>
                      {it.has_converted && it.converted_lead_id && (
                        <div>
                          <span className="font-semibold">Converted lead:</span>{" "}
                          <Link
                            to={`/leads/${it.converted_lead_id}`}
                            className="hover:underline"
                            style={{ color: colors.brand }}
                            data-testid={`intent-converted-link-${it.id}`}
                          >
                            {it.converted_lead_id}
                          </Link>{" "}
                          <span style={{ color: colors.muted }}>
                            at {_fmt(it.converted_at)}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </React.Fragment>
            );
          })
        )}
      </Card>

      {/* Pagination */}
      <div
        className="flex items-center justify-between mt-3 text-sm"
        data-testid="leads-intent-pagination"
      >
        <div style={{ color: colors.muted }}>{total} total</div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            data-testid="intent-page-prev"
            className="px-3 py-1 rounded border disabled:opacity-40"
            style={{ borderColor: colors.border }}
          >
            Prev
          </button>
          <span data-testid="intent-page-indicator">
            Page {page} / {totalPages}
          </span>
          <button
            type="button"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            data-testid="intent-page-next"
            className="px-3 py-1 rounded border disabled:opacity-40"
            style={{ borderColor: colors.border }}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
