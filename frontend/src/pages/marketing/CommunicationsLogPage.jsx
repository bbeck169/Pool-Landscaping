/**
 * Slice O · Feb-2026 — Communications Log page (admin only).
 *
 * Route: `/admin/communications-log`.
 *
 * Layout:
 *  1. Four KPI cards (Total Sent · Open Rate · Click Rate · Bounce Rate)
 *     — populated from `GET /api/communications-log/summary?days=30`.
 *  2. Filters row — customer typeahead, channel segmented, date range,
 *     status dropdown, refresh button, CSV export.
 *  3. Table — one row per delivery attempt with a colored status pill,
 *     channel icon, customer name, recipient, subject/body preview.
 *  4. Row click → side sheet with the full rendered body and a
 *     delivery timeline (created → sent → delivered → opened → clicked
 *     / bounced / failed).
 *
 * SMS rows never surface an "Opened" pill — carriers don't expose
 * that data. The strongest positive state for SMS is "Delivered"
 * (gray pill) via the `sms_status_final` field.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Mail, MessageSquareText, Loader2, RefreshCw, Download, ChevronRight } from "lucide-react";
import { toast as sonnerToast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";
import { Forbidden } from "@/hooks/usePermissions";
import { Button } from "@/components/ui/button";
import {
  useBulkSelect,
  BulkSelectAll,
  BulkSelectRow,
  BulkActionBar,
} from "@/components/bulk-select/BulkSelectToolkit";
import { Input } from "@/components/ui/input";
import CommunicationDetailModal
  from "@/components/communications/CommunicationDetailModal";

// ── Pill color scheme (single source of truth) ─────────────────
const STATUS_TONES = {
  sent:    { bg: "#E5E7EB", fg: "#374151", label: "Sent" },
  opened:  { bg: "#DBEAFE", fg: "#1E3A8A", label: "Opened" },
  clicked: { bg: "#DCFCE7", fg: "#166534", label: "Clicked" },
  bounced: { bg: "#FEE2E2", fg: "#991B1B", label: "Bounced" },
  failed:  { bg: "#FCA5A5", fg: "#7F1D1D", label: "Failed" },
  delivered: { bg: "#E5E7EB", fg: "#374151", label: "Delivered" },
};

function StatusPill({ status, channel, smsFinal }) {
  // SMS rows use "Delivered" instead of "Opened" for status="sent"
  // because carriers don't expose read receipts.
  let effective = status;
  if (channel === "sms" && status === "sent"
        && (smsFinal === "delivered")) {
    effective = "delivered";
  }
  const t = STATUS_TONES[effective] || STATUS_TONES.sent;
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold"
      style={{ background: t.bg, color: t.fg }}
      data-testid={`comm-log-status-pill-${effective}`}
    >
      {t.label}
    </span>
  );
}

function KpiCard({ label, value, sub, testid }) {
  return (
    <div
      className="rounded-2xl p-4"
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={testid}
    >
      <div
        className="text-[11px] font-bold uppercase tracking-wider mb-1"
        style={{ color: colors.muted }}
      >
        {label}
      </div>
      <div
        className="text-2xl font-bold"
        style={{ color: colors.onSurface }}
      >
        {value}
      </div>
      {sub ? (
        <div className="text-[11px] mt-0.5" style={{ color: colors.muted }}>
          {sub}
        </div>
      ) : null}
    </div>
  );
}

function relTime(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return String(iso);
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d`;
}

function csvEscape(v) {
  const s = v == null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function downloadCsv(rows) {
  const header = [
    "sent_at", "channel", "status", "customer", "recipient",
    "subject", "provider", "provider_response_id",
  ];
  const body = rows.map((r) => [
    r.created_at, r.channel, r.status_derived,
    r.customer_name || "", r.recipient_email || r.recipient_phone || "",
    r.subject || r.body_preview || "",
    r.provider || "", r.provider_response_id || "",
  ].map(csvEscape).join(","));
  const csv = [header.join(","), ...body].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `communications-log-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function CommunicationsLogPage() {
  const { user } = useAuth();
  const role = (user?.role || "").toLowerCase();
  const allowed = role === "admin" || role === "super_admin";

  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);

  const [customerId, setCustomerId] = useState("");
  const [channel, setChannel] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState(null);
  // Phase 34 · Task LL Phase 2 UI wrap-up · Feb 2026 — comms bulk-select.
  const visibleIds = useMemo(() => rows.map((r) => r.id), [rows]);
  const {
    selected: bulkSelected,
    selectedCount, allVisibleSelected, indeterminate,
    toggleAll, toggleOne, clear,
  } = useBulkSelect(visibleIds);
  const doBulkArchive = async () => {
    try {
      const res = await api.post("/communications/bulk-archive",
                                    { ids: Array.from(bulkSelected) });
      sonnerToast.success(`${res.archived_count || 0} archived`);
      clear(); load();
    } catch (e) { sonnerToast.error(e?.message || "Bulk archive failed"); }
  };
  const doBulkMarkRead = async () => {
    try {
      const res = await api.post("/communications/bulk-mark-read",
                                    { ids: Array.from(bulkSelected) });
      sonnerToast.success(`${res.updated_count || 0} marked read`);
      clear(); load();
    } catch (e) { sonnerToast.error(e?.message || "Mark-read failed"); }
  };

  const params = useMemo(() => {
    const p = new URLSearchParams();
    p.set("page", String(page));
    p.set("page_size", "50");
    if (customerId) p.set("customer_id", customerId);
    if (channel && channel !== "all") p.set("channel", channel);
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    if (status) p.set("status", status);
    return p.toString();
  }, [customerId, channel, dateFrom, dateTo, status, page]);

  const load = () => {
    if (!allowed) return;
    setLoading(true);
    Promise.all([
      api.get(`/communications-log?${params}`)
        .catch(() => ({ items: [], total: 0 })),
      api.get("/communications-log/summary?days=30")
        .catch(() => null),
    ]).then(([listRes, sumRes]) => {
      setRows(listRes?.items || []);
      setTotal(listRes?.total || 0);
      setSummary(sumRes);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [params, allowed]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: load intentionally omitted (mount-only / stable-ref)

  if (!allowed) return <Forbidden reason="Communications log is admin-only." />;

  return (
    <div
      className="p-4 md:p-6"
      style={{ background: colors.surfaceSecondary, minHeight: "100%" }}
      data-testid="comm-log-page"
    >
      <div className="flex items-center gap-3 mb-4">
        <div>
          <div
            className="text-xl font-bold"
            style={{ color: colors.onSurface }}
          >
            Communications Log
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Every email + SMS attempted by this tenant, with open, click,
            bounce, and delivery status.
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <Button
          type="button" variant="outline" size="sm"
          onClick={load}
          data-testid="comm-log-refresh-btn"
        >
          <RefreshCw size={14} className="mr-1" />
          Refresh
        </Button>
        <Button
          type="button" size="sm"
          onClick={() => downloadCsv(rows)}
          disabled={rows.length === 0}
          data-testid="comm-log-csv-export-btn"
        >
          <Download size={14} className="mr-1" />
          CSV Export
        </Button>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-4">
        <KpiCard
          testid="comm-log-kpi-total"
          label="Sent last 30d"
          value={summary?.total_sent ?? "—"}
          sub={`${summary?.email_sent ?? 0} email · ${summary?.sms_sent ?? 0} SMS`}
        />
        <KpiCard
          testid="comm-log-kpi-open"
          label="Open rate (email)"
          value={summary ? `${summary.open_rate_pct}%` : "—"}
          sub={`${summary?.opened ?? 0} opens`}
        />
        <KpiCard
          testid="comm-log-kpi-click"
          label="Click rate (email)"
          value={summary ? `${summary.click_rate_pct}%` : "—"}
          sub={`${summary?.clicked ?? 0} clicks`}
        />
        <KpiCard
          testid="comm-log-kpi-bounce"
          label="Bounce rate"
          value={summary ? `${summary.bounce_rate_pct}%` : "—"}
          sub={`${summary?.bounced ?? 0} bounces · ${summary?.failed ?? 0} failed`}
        />
      </div>

      {/* Filters row */}
      <div
        className="rounded-lg p-3 mb-3 flex flex-wrap gap-3 items-end"
        style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid="comm-log-filters"
      >
        <div className="flex-1 min-w-[180px]">
          <label
            className="text-[11px] font-bold uppercase block mb-1"
            style={{ color: colors.muted }}
          >
            Customer ID
          </label>
          <Input
            value={customerId}
            onChange={(e) => { setPage(1); setCustomerId(e.target.value); }}
            placeholder="Paste a customer id"
            data-testid="comm-log-filter-customer-id"
          />
        </div>
        <div>
          <label
            className="text-[11px] font-bold uppercase block mb-1"
            style={{ color: colors.muted }}
          >
            Channel
          </label>
          <div
            className="inline-flex rounded-md overflow-hidden"
            style={{ border: `1px solid ${colors.border}` }}
            data-testid="comm-log-filter-channel"
          >
            {[
              { k: "all",   l: "All" },
              { k: "email", l: "Email" },
              { k: "sms",   l: "SMS" },
            ].map(({ k, l }) => (
              <button
                key={k}
                type="button"
                onClick={() => { setPage(1); setChannel(k); }}
                className="px-3 py-1.5 text-xs font-semibold"
                style={{
                  background: channel === k ? colors.brand : colors.surface,
                  color: channel === k ? "#fff" : colors.onSurface,
                  cursor: "pointer",
                }}
                data-testid={`comm-log-filter-channel-${k}`}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label
            className="text-[11px] font-bold uppercase block mb-1"
            style={{ color: colors.muted }}
          >
            From
          </label>
          <Input
            type="date" value={dateFrom}
            onChange={(e) => { setPage(1); setDateFrom(e.target.value); }}
            data-testid="comm-log-filter-date-from"
          />
        </div>
        <div>
          <label
            className="text-[11px] font-bold uppercase block mb-1"
            style={{ color: colors.muted }}
          >
            To
          </label>
          <Input
            type="date" value={dateTo}
            onChange={(e) => { setPage(1); setDateTo(e.target.value); }}
            data-testid="comm-log-filter-date-to"
          />
        </div>
        <div>
          <label
            className="text-[11px] font-bold uppercase block mb-1"
            style={{ color: colors.muted }}
          >
            Status
          </label>
          <select
            value={status}
            onChange={(e) => { setPage(1); setStatus(e.target.value); }}
            className="px-3 py-2 rounded-md text-sm"
            style={{
              background: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            data-testid="comm-log-filter-status"
          >
            <option value="">Any</option>
            <option value="sent">Sent</option>
            <option value="opened">Opened</option>
            <option value="clicked">Clicked</option>
            <option value="bounced">Bounced</option>
            <option value="failed">Failed</option>
          </select>
        </div>
      </div>

      {/* Table */}
      <div
        className="rounded-lg overflow-hidden"
        style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid="comm-log-table"
      >
        <div
          className="grid grid-cols-[36px_110px_36px_1fr_1fr_100px_36px] gap-2 px-3 py-2 text-[11px] font-bold uppercase"
          style={{
            background: colors.surfaceSecondary,
            color: colors.muted,
            borderBottom: `1px solid ${colors.border}`,
          }}
        >
          <div>
            <BulkSelectAll checked={allVisibleSelected}
                             indeterminate={indeterminate}
                             onChange={toggleAll} />
          </div>
          <div>Sent</div>
          <div>Ch</div>
          <div>Customer</div>
          <div>Subject / preview</div>
          <div>Status</div>
          <div />
        </div>

        {loading && rows.length === 0 ? (
          <div className="p-6 text-sm text-center" style={{ color: colors.muted }}>
            <Loader2 className="inline animate-spin mr-2" size={14} />
            Loading…
          </div>
        ) : rows.length === 0 ? (
          <div
            className="p-8 text-sm text-center"
            style={{ color: colors.muted }}
            data-testid="comm-log-empty-state"
          >
            No communications match your filters.
          </div>
        ) : (
          rows.map((r) => (
            <div
              key={r.id}
              className="w-full grid grid-cols-[36px_110px_36px_1fr_1fr_100px_36px] gap-2 px-3 py-2 text-left text-sm hover:bg-black/[0.02] transition-colors"
              style={{
                borderBottom: `1px solid ${colors.border}`,
                background: colors.surface,
              }}
              data-testid={`comm-log-row-${r.id}`}
            >
              <div onClick={(e) => e.stopPropagation()} className="flex items-center">
                <BulkSelectRow id={r.id} checked={bulkSelected.has(r.id)}
                                  onChange={() => toggleOne(r.id)} />
              </div>
              <button type="button" onClick={() => setSelected(r)}
                      className="text-xs text-left" style={{ color: colors.muted, cursor: "pointer" }}
                      title={r.created_at}>
                {relTime(r.created_at)} ago
              </button>
              <button type="button" onClick={() => setSelected(r)}
                      className="flex items-center text-left"
                      style={{ color: colors.brand, cursor: "pointer" }}>
                {r.channel === "email" ? <Mail size={14} /> : <MessageSquareText size={14} />}
              </button>
              <button type="button" onClick={() => setSelected(r)}
                      className="truncate text-left"
                      style={{ color: colors.onSurface, cursor: "pointer" }}>
                {r.customer_name || <span style={{ color: colors.muted }}>—</span>}
                <div className="text-[11px]" style={{ color: colors.muted }}>
                  {r.recipient_email || r.recipient_phone || ""}
                </div>
              </button>
              <button type="button" onClick={() => setSelected(r)}
                      className="truncate text-left" style={{ cursor: "pointer" }}>
                {r.subject ? (
                  <div style={{ color: colors.onSurface }}>{r.subject}</div>
                ) : null}
                <div className="text-[11px] truncate"
                     style={{ color: colors.muted }}>
                  {r.body_preview}
                </div>
              </button>
              <button type="button" onClick={() => setSelected(r)}
                      className="text-left" style={{ cursor: "pointer" }}>
                <StatusPill
                  status={r.status_derived}
                  channel={r.channel}
                  smsFinal={r.sms_status_final}
                />
              </button>
              <button type="button" onClick={() => setSelected(r)}
                      className="flex items-center justify-end"
                      style={{ color: colors.muted, cursor: "pointer" }}>
                <ChevronRight size={14} />
              </button>
            </div>
          ))
        )}

        {/* Pagination */}
        {total > 50 ? (
          <div className="flex items-center justify-between px-3 py-2 text-xs"
               style={{ color: colors.muted, borderTop: `1px solid ${colors.border}` }}>
            <span>Page {page} of {Math.ceil(total / 50)} · {total} total</span>
            <div className="flex gap-2">
              <Button
                type="button" variant="outline" size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                data-testid="comm-log-prev-page"
              >
                Prev
              </Button>
              <Button
                type="button" variant="outline" size="sm"
                disabled={page * 50 >= total}
                onClick={() => setPage((p) => p + 1)}
                data-testid="comm-log-next-page"
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </div>

      {/* P2 #5 · Feb-2026 — row click opens the shared Dialog modal
          via GET /communications-detail/{id}.  Replaces the previous
          right-side Sheet which only showed body_preview (100 chars). */}
      <CommunicationDetailModal
        open={!!selected}
        rowId={selected?.id || null}
        onClose={() => setSelected(null)}
      />

      {/* Phase 34 · Task LL Phase 2 UI wrap-up · Feb 2026 — comms bulk-action bar.
          No delete (per spec) — archive + mark-read only. */}
      <BulkActionBar
        selectedCount={selectedCount}
        onClear={clear}
        actions={[
          { key: "mark-read", label: "Mark read", onClick: doBulkMarkRead },
          { key: "archive", label: "Archive selected", tone: "danger",
            onClick: doBulkArchive },
        ]}
      />
    </div>
  );
}
