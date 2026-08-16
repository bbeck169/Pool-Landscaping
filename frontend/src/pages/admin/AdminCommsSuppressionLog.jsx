/**
 * Queue Item 4 · Feb-2026 — Suppression Log viewer.
 *
 * Route: /admin/comms/suppression-log (super_admin only, gated at
 * the App.js route level as well).
 *
 * Reads GET /api/comms/suppression-log with:
 *   • Pagination (limit/skip)
 *   • Filters: comm_type ("email" | "sms"), provider, recipient_type
 * Renders a compact table of blocked outbound-comm attempts with
 * timestamp, recipient anonymized (domain only), action that would
 * have sent it, and the block reason.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ShieldAlert, RefreshCw, ChevronLeft, ChevronRight } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import CommsWhitelistBanner from "@/components/comms/CommsWhitelistBanner";

const PAGE_SIZE = 50;

const COMM_TYPES = [
  { value: "", label: "All types" },
  { value: "email", label: "Email" },
  { value: "sms", label: "SMS" },
];

const RECIPIENT_TYPES = [
  { value: "", label: "All recipients" },
  { value: "user", label: "User" },
  { value: "customer", label: "Customer" },
  { value: "external", label: "External" },
];

const PROVIDERS = [
  { value: "", label: "All providers" },
  { value: "resend", label: "Resend" },
  { value: "ringcentral", label: "RingCentral" },
];

function formatTimestamp(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  } catch {
    return String(iso);
  }
}

export default function AdminCommsSuppressionLog() {
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [busy, setBusy] = useState(false);
  const [commType, setCommType] = useState("");
  const [recipientType, setRecipientType] = useState("");
  const [provider, setProvider] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      params.set("skip", String(skip));
      if (commType) params.set("comm_type", commType);
      if (recipientType) params.set("recipient_type", recipientType);
      if (provider) params.set("provider", provider);
      const r = await api.get(`/comms/suppression-log?${params.toString()}`);
      setRows(Array.isArray(r?.rows) ? r.rows : []);
      setTotal(Number(r?.total || 0));
    } catch {
      setRows([]);
      setTotal(0);
    } finally { setBusy(false); }
  }, [skip, commType, recipientType, provider]);

  useEffect(() => { load(); }, [load]);

  // Reset paging whenever a filter changes so the user isn't stuck
  // on a page that no longer has data.
  useEffect(() => { setSkip(0); }, [commType, recipientType, provider]);

  const currentPage = Math.floor(skip / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const canPrev = skip > 0;
  const canNext = skip + PAGE_SIZE < total;

  const rangeLabel = useMemo(() => {
    if (!total) return "0 of 0";
    const start = skip + 1;
    const end = Math.min(skip + PAGE_SIZE, total);
    return `${start}–${end} of ${total}`;
  }, [skip, total]);

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="admin-suppression-log-page">
      <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            <ShieldAlert size={20} className="inline mr-2" /> Suppression Log
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Outbound comms blocked by the whitelist gate (super_admin only).
          </p>
        </div>
        <button
          onClick={load}
          disabled={busy}
          className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5 disabled:opacity-60"
          style={{
            backgroundColor: colors.surfaceSecondary,
            color: colors.onSurfaceSecondary,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="admin-suppression-log-refresh-btn"
        >
          <RefreshCw size={12} /> {busy ? "Loading…" : "Refresh"}
        </button>
      </div>

      <CommsWhitelistBanner />

      {/* Filter row */}
      <div
        className="rounded-2xl p-3 mb-3 flex flex-wrap items-center gap-2"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <FilterSelect
          label="Type"
          value={commType}
          options={COMM_TYPES}
          onChange={setCommType}
          testid="admin-suppression-log-filter-type"
        />
        <FilterSelect
          label="Recipient"
          value={recipientType}
          options={RECIPIENT_TYPES}
          onChange={setRecipientType}
          testid="admin-suppression-log-filter-recipient"
        />
        <FilterSelect
          label="Provider"
          value={provider}
          options={PROVIDERS}
          onChange={setProvider}
          testid="admin-suppression-log-filter-provider"
        />
      </div>

      {/* Table */}
      <div
        className="rounded-2xl overflow-hidden"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <table className="w-full text-sm" data-testid="admin-suppression-log-table">
          <thead>
            <tr style={{ backgroundColor: colors.surfaceSecondary }}>
              <Th>Time</Th>
              <Th>Type</Th>
              <Th>Provider</Th>
              <Th>Recipient</Th>
              <Th>Trigger</Th>
              <Th>Reason</Th>
            </tr>
          </thead>
          <tbody>
            {rows === null ? (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-sm" style={{ color: colors.muted }}>
                  Loading…
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-sm"
                     style={{ color: colors.muted }}
                     data-testid="admin-suppression-log-empty">
                  No suppression events match this filter.
                </td>
              </tr>
            ) : rows.map((r, idx) => (
              <tr
                key={r.id || `${r.created_at}-${idx}`}
                style={{ borderTop: `1px solid ${colors.divider}` }}
                data-testid={`admin-suppression-log-row-${idx}`}
              >
                <td className="px-3 py-2 text-xs" style={{ color: colors.onSurfaceSecondary }}>
                  {formatTimestamp(r.created_at)}
                </td>
                <td className="px-3 py-2 text-xs">
                  <Pill value={r.comm_type} />
                </td>
                <td className="px-3 py-2 text-xs" style={{ color: colors.muted }}>
                  {r.provider || "—"}
                </td>
                <td className="px-3 py-2 text-xs" style={{ color: colors.onSurfaceSecondary }}>
                  <span className="inline-block">
                    {r.recipient_type ? (
                      <b style={{ color: colors.onSurface }}>{r.recipient_type}</b>
                    ) : "—"}
                    {r.recipient_email_domain ? (
                      <span className="ml-1" style={{ color: colors.muted }}>
                        @{r.recipient_email_domain}
                      </span>
                    ) : null}
                    {r.recipient_phone_masked ? (
                      <span className="ml-1" style={{ color: colors.muted }}>
                        {r.recipient_phone_masked}
                      </span>
                    ) : null}
                  </span>
                </td>
                <td className="px-3 py-2 text-xs" style={{ color: colors.onSurfaceSecondary }}>
                  {r.trigger_action || "—"}
                </td>
                <td className="px-3 py-2 text-xs" style={{ color: colors.muted }}>
                  {r.reason || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between mt-3 text-xs"
             style={{ color: colors.muted }}>
        <span data-testid="admin-suppression-log-range">{rangeLabel}</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setSkip((s) => Math.max(0, s - PAGE_SIZE))}
            disabled={!canPrev || busy}
            className="px-2 py-1.5 rounded-lg inline-flex items-center gap-1 disabled:opacity-40"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            data-testid="admin-suppression-log-prev"
          >
            <ChevronLeft size={12} /> Prev
          </button>
          <span data-testid="admin-suppression-log-page-num">
            Page {currentPage} of {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setSkip((s) => s + PAGE_SIZE)}
            disabled={!canNext || busy}
            className="px-2 py-1.5 rounded-lg inline-flex items-center gap-1 disabled:opacity-40"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            data-testid="admin-suppression-log-next"
          >
            Next <ChevronRight size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}

function Th({ children }) {
  return (
    <th
      className="text-left px-3 py-2 font-semibold"
      style={{ color: colors.onSurfaceSecondary }}
    >
      {children}
    </th>
  );
}

function Pill({ value }) {
  if (!value) return <span style={{ color: colors.muted }}>—</span>;
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full font-bold uppercase tracking-wider text-[10px]"
      style={{
        backgroundColor: colors.surfaceSecondary,
        color: colors.onSurfaceSecondary,
        border: `1px solid ${colors.border}`,
      }}
    >
      {value}
    </span>
  );
}

function FilterSelect({ label, value, options, onChange, testid }) {
  return (
    <>
      <label className="text-xs font-semibold" style={{ color: colors.muted }}>
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="text-xs font-semibold px-3 py-2 rounded-lg"
        style={{
          backgroundColor: colors.surfaceSecondary,
          color: colors.onSurfaceSecondary,
          border: `1px solid ${colors.border}`,
        }}
        data-testid={testid}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </>
  );
}
