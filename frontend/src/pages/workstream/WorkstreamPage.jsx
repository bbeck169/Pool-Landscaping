/**
 * Phase 31 · Step 2b — Workstream admin page (/workstream).
 *
 * Reverse-chronological event feed powered by GET /api/workstream/events
 * (Step 1 spine). Admin/super_admin only — customers/techs never see
 * this page. Filter by event `type` via a text input (exact match on
 * the backend query param). Payload summary and relative timestamp
 * render inline; no drill-in yet (deferred).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Workflow, RefreshCw, Loader2, Filter } from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { Forbidden } from "@/hooks/usePermissions";

const c = {
  brand: "#0EA5E9",
  border: "#E2E8F0",
  muted: "#64748B",
  surface: "#FFFFFF",
  surfaceAlt: "#F8FAFC",
  onSurface: "#0F172A",
};

function relTime(iso) {
  if (!iso) return "";
  const now = Date.now();
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const s = Math.max(0, Math.floor((now - then) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

function payloadSummary(ev) {
  const p = ev.payload || {};
  const bits = [];
  if (p.customer_name) bits.push(p.customer_name);
  if (p.service_type) bits.push(p.service_type);
  if (p.template) bits.push(`tpl:${p.template}`);
  if (p.tech_name) bits.push(`by ${p.tech_name}`);
  if (typeof p.photos_count === "number") bits.push(`${p.photos_count} photos`);
  if (typeof p.chemicals_added_count === "number") bits.push(`${p.chemicals_added_count} chem`);
  return bits.join(" · ");
}

export default function WorkstreamPage() {
  const { user } = useAuth();
  const role = user?.role || "";
  const allowed = role === "admin" || role === "super_admin";

  const [events, setEvents] = useState([]);
  const [typeFilter, setTypeFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    if (!allowed) return;
    setLoading(true); setErr("");
    try {
      const qs = new URLSearchParams({ limit: "100" });
      if (typeFilter.trim()) qs.set("type", typeFilter.trim());
      const rows = await api.get(`/workstream/events?${qs.toString()}`);
      setEvents(Array.isArray(rows) ? rows : []);
    } catch (e) {
      setErr(e?.message || "Failed to load workstream events.");
    } finally {
      setLoading(false);
    }
  }, [allowed, typeFilter]);

  useEffect(() => { load(); }, [load]);

  const uniqueTypes = useMemo(() => {
    const s = new Set();
    for (const e of events) if (e?.type) s.add(e.type);
    return Array.from(s).sort();
  }, [events]);

  if (!allowed) {
    return <Forbidden reason="Workstream is admin-only." />;
  }

  return (
    <div className="p-4 md:p-6" style={{ background: c.surfaceAlt, minHeight: "100%" }}>
      <div className="flex items-center gap-3 mb-4">
        <Workflow size={22} color={c.brand} />
        <div>
          <div className="text-xl font-bold" style={{ color: c.onSurface }} data-testid="workstream-title">
            Workstream
          </div>
          <div className="text-xs" style={{ color: c.muted }}>
            Tap-job telemetry · every checklist moment, in reverse order.
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-sm font-semibold"
          style={{ background: c.surface, border: `1px solid ${c.border}`, color: c.onSurface, cursor: "pointer" }}
          data-testid="workstream-refresh"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Refresh
        </button>
      </div>

      <div className="flex items-center gap-2 mb-4">
        <Filter size={14} color={c.muted} />
        <input
          type="text"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") load(); }}
          placeholder="Filter by type (e.g. job.completed)"
          className="px-3 py-1.5 rounded-md text-sm"
          style={{
            border: `1px solid ${c.border}`, background: c.surface,
            color: c.onSurface, minWidth: 260,
          }}
          list="workstream-type-suggestions"
          data-testid="workstream-type-filter"
        />
        {uniqueTypes.length > 0 && (
          <datalist id="workstream-type-suggestions">
            {uniqueTypes.map((t) => (<option key={t} value={t} />))}
          </datalist>
        )}
        {typeFilter && (
          <button
            type="button"
            onClick={() => { setTypeFilter(""); }}
            className="text-xs font-semibold"
            style={{ background: "transparent", border: 0, color: c.brand, cursor: "pointer" }}
            data-testid="workstream-type-clear"
          >
            Clear
          </button>
        )}
      </div>

      {err ? (
        <div className="rounded-md p-3 text-sm mb-4"
             style={{ background: "#FEE2E2", color: "#991B1B", border: "1px solid #FCA5A5" }}
             data-testid="workstream-error">
          {err}
        </div>
      ) : null}

      <div className="rounded-lg" style={{ background: c.surface, border: `1px solid ${c.border}` }}
           data-testid="workstream-list">
        {loading && events.length === 0 ? (
          <div className="p-8 flex items-center justify-center" data-testid="workstream-loading">
            <Loader2 size={20} className="animate-spin" color={c.brand} />
          </div>
        ) : events.length === 0 ? (
          <div className="p-8 text-sm text-center" style={{ color: c.muted }}
               data-testid="workstream-empty">
            No workstream events yet. Close a job on the schedule and it will
            appear here in real time.
          </div>
        ) : (
          events.map((ev) => (
            <div
              key={ev.id}
              className="flex items-start gap-3 px-4 py-3"
              style={{ borderBottom: `1px solid ${c.border}` }}
              data-testid="workstream-item"
            >
              <div
                className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase whitespace-nowrap"
                style={{ background: "#E0F2FE", color: "#075985" }}
                data-testid={`workstream-item-type-${ev.id}`}
              >
                {ev.type}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="text-sm" style={{ color: c.onSurface }}>
                  {payloadSummary(ev) || <span style={{ color: c.muted }}>—</span>}
                </div>
                <div className="text-[11px] mt-0.5" style={{ color: c.muted }}>
                  {ev.actor_role || "?"}
                  {ev.related_ref?.id ? ` · ref:${ev.related_ref.type || "?"}/${String(ev.related_ref.id).slice(0, 8)}` : ""}
                </div>
              </div>
              <div className="text-[11px] whitespace-nowrap" style={{ color: c.muted }}
                   title={ev.created_at}>
                {relTime(ev.created_at)}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
