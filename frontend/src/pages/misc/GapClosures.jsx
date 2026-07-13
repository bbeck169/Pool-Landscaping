import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api";
import { colors } from "@/theme";

/* Phase 13 parity-gap closures — two thin admin list pages that
   mirror the Expo mobile equivalents. */

function Card({ children, testid }) {
  return (
    <div className="rounded-2xl bg-white p-5" style={{ border: `1px solid ${colors.border}` }} data-testid={testid}>
      {children}
    </div>
  );
}

/* ─── /leads ─── */
export function LeadsList() {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/leads").then((r) => setRows(Array.isArray(r) ? r : [])); }, []);
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-4" data-testid="leads-list-page">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Leads</h1>
        <Link to="/leads/new" className="px-4 py-2 rounded-xl text-sm font-semibold text-white" style={{ backgroundColor: colors.brand }} data-testid="leads-new">+ New lead</Link>
      </div>
      <Card>
        {rows === null && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
        {rows && rows.length === 0 && <div className="text-sm text-center py-8" style={{ color: colors.onSurfaceSecondary }}>No leads yet — capture one from D2D or a public form.</div>}
        <table className="w-full text-sm">
          <tbody>
            {rows && rows.map((l) => (
              <tr key={l.id} className="border-b last:border-0" style={{ borderColor: colors.border }} data-testid={`lead-row-${l.id}`}>
                <td className="py-2 font-semibold">{l.name || "Unknown"}</td>
                <td className="py-2">{l.phone || l.email || "—"}</td>
                <td className="py-2 text-xs" style={{ color: colors.onSurfaceSecondary }}>{l.source}</td>
                <td className="py-2 text-xs" style={{ color: colors.onSurfaceSecondary }}>{l.status || "new"}</td>
                <td className="py-2 text-xs" style={{ color: colors.onSurfaceSecondary }}>{(l.created_at || "").slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

/* ─── /checkins ─── */
export function CheckinsList() {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    api.get("/attendance/checkins").catch(() => api.get("/checkins"))
      .then((r) => setRows(Array.isArray(r) ? r : []))
      .catch(() => setRows([]));
  }, []);
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-4" data-testid="checkins-page">
      <h1 className="text-3xl font-bold">Job check-ins</h1>
      <Card>
        {rows === null && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
        {rows && rows.length === 0 && <div className="text-sm text-center py-8" style={{ color: colors.onSurfaceSecondary }}>No check-ins recorded yet.</div>}
        {rows && rows.map((c) => (
          <div key={c.id} className="py-2 border-b last:border-0 flex items-center justify-between" style={{ borderColor: colors.border }} data-testid={`checkin-${c.id}`}>
            <div>
              <div className="font-semibold text-sm">{c.technician_name || c.tech_name}</div>
              <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{c.address || c.job_id} · {(c.created_at || "").slice(0, 16).replace("T", " ")}</div>
            </div>
            {c.event && <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: colors.surfaceSecondary }}>{c.event}</span>}
          </div>
        ))}
      </Card>
    </div>
  );
}
