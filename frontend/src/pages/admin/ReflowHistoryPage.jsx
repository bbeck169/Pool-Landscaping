/**
 * Task Reflow-History · Feb 2026 — dispatcher-facing view of every
 * mass reschedule action. Aggregates audit_log rows into one row per
 * (actor, at, shift_days) tuple. Read-only.
 */
import React, { useEffect, useState } from "react";
import { History, RefreshCw } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function formatDetails(item) {
  if (item.shift_days !== undefined && item.shift_days !== null) {
    const s = item.shift_days;
    const anchor = item.anchored_count
      ? ` · ${item.anchored_count} anchored from today`
      : "";
    return `${s > 0 ? "+" : ""}${s} day${Math.abs(s) === 1 ? "" : "s"}${anchor}`;
  }
  return "—";
}

export default function ReflowHistoryPage() {
  const [items, setItems] = useState(null);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [actorEmail, setActorEmail] = useState("");
  const [nextCursor, setNextCursor] = useState(null);
  const [error, setError] = useState(null);

  const load = () => {
    setError(null);
    const params = new URLSearchParams();
    if (since) params.set("since", since);
    if (until) params.set("until", until);
    params.set("limit", "50");
    api.get(`/admin/reflow-history?${params.toString()}`)
      .then((r) => {
        let list = r?.items || [];
        if (actorEmail) {
          const q = actorEmail.toLowerCase();
          list = list.filter((it) => (it.actor_email || "").toLowerCase().includes(q));
        }
        setItems(list);
        setNextCursor(r?.cursor || null);
      })
      .catch((e) => { setItems([]); setError(e?.message || "Failed to load"); });
  };
  useEffect(load, []); // eslint-disable-line
  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
         data-testid="reflow-history-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            <History size={20} className="inline mr-2" /> Reflow History
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Audit log of every bulk-reschedule and bulk-shift action.
          </p>
        </div>
        <button onClick={load}
                className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurfaceSecondary,
                          border: `1px solid ${colors.border}` }}
                data-testid="reflow-history-refresh-btn">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      <form onSubmit={(e) => { e.preventDefault(); load(); }}
             className="rounded-2xl p-3 mb-3 flex flex-wrap items-end gap-2"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="reflow-history-filter-form">
        <div className="flex flex-col">
          <label className="text-[10px] font-bold uppercase tracking-wider mb-1"
                   style={{ color: colors.muted }}>Since</label>
          <input type="date" value={since} onChange={(e) => setSince(e.target.value)}
                   className="text-xs font-semibold px-3 py-2 rounded-lg"
                   style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurfaceSecondary,
                              border: `1px solid ${colors.border}` }}
                   data-testid="reflow-history-since" />
        </div>
        <div className="flex flex-col">
          <label className="text-[10px] font-bold uppercase tracking-wider mb-1"
                   style={{ color: colors.muted }}>Until</label>
          <input type="date" value={until} onChange={(e) => setUntil(e.target.value)}
                   className="text-xs font-semibold px-3 py-2 rounded-lg"
                   style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurfaceSecondary,
                              border: `1px solid ${colors.border}` }}
                   data-testid="reflow-history-until" />
        </div>
        <div className="flex flex-col">
          <label className="text-[10px] font-bold uppercase tracking-wider mb-1"
                   style={{ color: colors.muted }}>Actor email</label>
          <input type="text" value={actorEmail} placeholder="email…"
                   onChange={(e) => setActorEmail(e.target.value)}
                   className="text-xs font-semibold px-3 py-2 rounded-lg"
                   style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurfaceSecondary,
                              border: `1px solid ${colors.border}` }}
                   data-testid="reflow-history-actor" />
        </div>
        <button type="submit"
                  className="text-xs font-bold uppercase tracking-wider px-4 py-2 rounded-lg text-white"
                  style={{ backgroundColor: "#1D4ED8" }}
                  data-testid="reflow-history-apply">
          Apply
        </button>
      </form>

      {error ? (
        <div className="rounded-xl p-4 text-sm"
              style={{ background: "#FEF2F2", color: "#991B1B",
                        border: "1px solid #FECACA" }}
              data-testid="reflow-history-error">
          {error}
        </div>
      ) : (
      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <table className="w-full text-sm" data-testid="reflow-history-table">
          <thead>
            <tr style={{ backgroundColor: colors.surfaceSecondary }}>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>When</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Who</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Action</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Count</th>
              <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Details</th>
            </tr>
          </thead>
          <tbody>
            {items === null ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-sm"
                       style={{ color: colors.muted }}>
                Loading…
              </td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-sm"
                       style={{ color: colors.muted }}
                       data-testid="reflow-history-empty">
                No reflow actions in this window yet.
              </td></tr>
            ) : items.map((it, i) => (
              <tr key={`${it.at}-${it.actor_user_id}-${i}`}
                  style={{ borderTop: `1px solid ${colors.divider}` }}
                  data-testid={`reflow-history-row-${i}`}>
                <td className="px-3 py-3 text-xs" style={{ color: colors.muted }}>
                  {(it.at || "").replace("T", " ").slice(0, 19)}
                </td>
                <td className="px-3 py-3 text-xs" style={{ color: colors.onSurface }}>
                  {it.actor_email || it.actor_user_id?.slice(0, 8) || "—"}
                </td>
                <td className="px-3 py-3 text-xs font-mono"
                    style={{ color: colors.onSurface }}>
                  {it.action}
                </td>
                <td className="px-3 py-3 font-semibold"
                    style={{ color: colors.onSurface }}>
                  {it.count}
                </td>
                <td className="px-3 py-3 text-xs" style={{ color: colors.muted }}>
                  {formatDetails(it)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
      {nextCursor ? (
        <div className="mt-3 text-center">
          <button onClick={() => {
                     const params = new URLSearchParams();
                     if (since) params.set("since", since);
                     if (until) params.set("until", until);
                     params.set("cursor", nextCursor);
                     params.set("limit", "50");
                     api.get(`/admin/reflow-history?${params.toString()}`).then((r) => {
                       setItems((prev) => [...(prev || []), ...(r?.items || [])]);
                       setNextCursor(r?.cursor || null);
                     });
                   }}
                   className="text-xs font-semibold px-4 py-2 rounded-lg"
                   style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurfaceSecondary,
                              border: `1px solid ${colors.border}` }}
                   data-testid="reflow-history-load-more">
            Load more
          </button>
        </div>
      ) : null}
    </div>
  );
}
