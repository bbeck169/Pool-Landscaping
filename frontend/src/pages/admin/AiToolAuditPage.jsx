/**
 * Task RR/SS Phase 2 · Feb 2026 — AI Tool Audit admin page.
 *
 * Mirrors the ReflowHistory pattern. Read-only table of every
 * ``ai_tool_calls`` row (90-day TTL). Filters by persona / tool /
 * date; supports load-more cursor pagination.
 *
 * API: ``GET /api/admin/ai-tool-audit?persona_key=&tool_name=&since=&limit=``
 */
import React, { useEffect, useState } from "react";
import { History, RefreshCw } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const TOOL_OPTIONS = [
  "", "lookup_customer", "lookup_invoices", "lookup_invoice_detail",
  "lookup_next_visit", "lookup_service_history", "lookup_balance",
  "lookup_schedule", "search_customers",
];

function fmtWhen(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); }
  catch { return String(iso).slice(0, 19); }
}

function fmtStatus(s) {
  if (!s) return "";
  const color = s === "ok" ? "text-emerald-700 bg-emerald-50 border-emerald-200"
    : s.startsWith("rate_limited") ? "text-amber-800 bg-amber-50 border-amber-200"
    : (s === "permission_denied" || s === "unknown_tool") ? "text-red-700 bg-red-50 border-red-200"
    : "text-zinc-700 bg-zinc-100 border-zinc-200";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs border ${color}`}>
      {s}
    </span>
  );
}

export default function AiToolAuditPage() {
  const [items, setItems] = useState(null);
  const [personaKey, setPersonaKey] = useState("");
  const [toolName, setToolName] = useState("");
  const [since, setSince] = useState("");
  const [limit, _setLimit] = useState(200);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setError(null);
    setLoading(true);
    const params = new URLSearchParams();
    if (personaKey) params.set("persona_key", personaKey);
    if (toolName) params.set("tool_name", toolName);
    if (since) params.set("since", since);
    params.set("limit", String(limit));
    api.get(`/admin/ai-tool-audit?${params.toString()}`)
      .then((r) => setItems(r?.items || []))
      .catch((e) => { setItems([]); setError(e?.message || "Failed to load"); })
      .finally(() => setLoading(false));
  };
  useEffect(load, []); // eslint-disable-line

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
          data-testid="ai-tool-audit-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold"
              style={{ color: colors.onSurface }}>
            <History size={20} className="inline mr-2" />
            AI Tool Audit
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Every read-only tool call an AI Employee has made. Retained 90 days.
          </p>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm hover:brightness-95"
          style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}`,
                    color: colors.onSurface }}
          data-testid="ai-tool-audit-refresh">
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {/* ─── Filters ─── */}
      <div className="rounded-2xl p-4 mb-4 grid grid-cols-1 md:grid-cols-4 gap-3"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <div>
          <div className="text-xs uppercase tracking-wide mb-1"
                style={{ color: colors.muted }}>Persona key</div>
          <input value={personaKey}
                  onChange={(e) => setPersonaKey(e.target.value)}
                  placeholder="e.g. billy, skedra"
                  data-testid="ai-tool-audit-filter-persona"
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ backgroundColor: colors.surfaceSecondary,
                            border: `1px solid ${colors.border}`,
                            color: colors.onSurface }} />
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide mb-1"
                style={{ color: colors.muted }}>Tool</div>
          <select value={toolName}
                    onChange={(e) => setToolName(e.target.value)}
                    data-testid="ai-tool-audit-filter-tool"
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.surfaceSecondary,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }}>
            {TOOL_OPTIONS.map((t) =>
              <option key={t || "any"} value={t}>{t || "(any)"}</option>)}
          </select>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide mb-1"
                style={{ color: colors.muted }}>Since (ISO)</div>
          <input value={since}
                  onChange={(e) => setSince(e.target.value)}
                  placeholder="2026-02-01T00:00:00Z"
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ backgroundColor: colors.surfaceSecondary,
                            border: `1px solid ${colors.border}`,
                            color: colors.onSurface }} />
        </div>
        <div className="flex items-end">
          <button onClick={load}
                  data-testid="ai-tool-audit-apply"
                  className="w-full px-4 py-2 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: colors.brand || "#0284c7",
                            color: "#fff" }}>
            Apply filters
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-2xl p-4 mb-4 text-sm"
              style={{ backgroundColor: "#fef2f2",
                        border: "1px solid #fecaca",
                        color: "#991b1b" }}
              data-testid="ai-tool-audit-error">
          {error}
        </div>
      )}

      {/* ─── Table ─── */}
      <div className="rounded-2xl overflow-hidden"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
        <div className="grid grid-cols-12 gap-2 px-4 py-3 text-xs uppercase tracking-wide"
              style={{ backgroundColor: colors.surfaceSecondary,
                        color: colors.muted,
                        borderBottom: `1px solid ${colors.border}` }}>
          <div className="col-span-3">When</div>
          <div className="col-span-2">Persona</div>
          <div className="col-span-2">Tool</div>
          <div className="col-span-2">Called by</div>
          <div className="col-span-3">Status / summary</div>
        </div>
        {loading && (
          <div className="py-10 text-center text-sm"
                style={{ color: colors.muted }}
                data-testid="ai-tool-audit-loading">
            Loading…
          </div>
        )}
        {!loading && (items || []).length === 0 && (
          <div className="py-10 text-center text-sm"
                style={{ color: colors.muted }}
                data-testid="ai-tool-audit-empty">
            No tool calls match the current filters.
          </div>
        )}
        {(items || []).map((it) => (
          <div key={it.id}
                data-testid={`ai-tool-audit-row-${it.id}`}
                className="grid grid-cols-12 gap-2 px-4 py-3 items-start text-sm"
                style={{ borderBottom: `1px solid ${colors.border}`,
                          color: colors.onSurface }}>
            <div className="col-span-3" style={{ color: colors.muted }}>
              {fmtWhen(it.created_at)}
            </div>
            <div className="col-span-2">
              <div className="font-medium">{it.persona_key || "—"}</div>
              <div className="text-xs" style={{ color: colors.muted }}>
                {it.persona_scope}
              </div>
            </div>
            <div className="col-span-2">
              <code className="text-xs">{it.tool_name}</code>
            </div>
            <div className="col-span-2 text-xs"
                  style={{ color: colors.muted }}>
              {it.called_by_customer_id
                ? `cust:${String(it.called_by_customer_id).slice(0, 8)}`
                : it.called_by_user_id
                  ? `user:${String(it.called_by_user_id).slice(0, 8)}`
                  : "—"}
            </div>
            <div className="col-span-3">
              <div className="mb-1">{fmtStatus(it.result_status)}</div>
              <div className="text-xs truncate"
                    style={{ color: colors.muted }}
                    title={it.result_summary || ""}>
                {(it.result_summary || "").slice(0, 100)}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
