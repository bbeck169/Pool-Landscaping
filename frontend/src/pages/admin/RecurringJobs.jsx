/**
 * Phase 51.I — Recurring Jobs admin.
 * Endpoints:
 *   GET    /api/recurring-jobs
 *   POST   /api/recurring-jobs
 *   PATCH  /api/recurring-jobs/{id}
 *   DELETE /api/recurring-jobs/{id}
 *   POST   /api/recurring-jobs/{id}/generate?through=YYYY-MM-DD
 */
import React, { useEffect, useState } from "react";
import { CalendarClock, Plus, Pause, Play, Trash2, RefreshCw, X } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const FREQ_OPTIONS = [
  { value: "weekly", label: "Weekly" },
  { value: "biweekly", label: "Bi-weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "custom", label: "Custom (every N days)" },
];
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function fmtMoney(cents) { return `$${(Number(cents || 0) / 100).toFixed(2)}`; }
function todayIso() { return new Date().toISOString().slice(0, 10); }
function addDaysIso(iso, days) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export default function RecurringJobs() {
  const [items, setItems] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [techs, setTechs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [tpls, custs, techs] = await Promise.all([
        api.get("/recurring-jobs"),
        api.get("/customers?limit=500").catch(() => ({ items: [] })),
        api.get("/technicians").catch(() => []),
      ]);
      setItems(tpls?.items || []);
      setCustomers(Array.isArray(custs) ? custs : (custs?.items || []));
      setTechs(Array.isArray(techs) ? techs : (techs?.items || []));
    } catch (e) {
      setError(e?.message || "Failed to load");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => { setEditing({ frequency: "weekly", day_of_week: 0, start_date: todayIso(), price_cents: 12000, active: true, notes: "" }); setModalOpen(true); };
  const openEdit = (row) => { setEditing({ ...row }); setModalOpen(true); };

  const save = async () => {
    setError(null);
    try {
      const payload = { ...editing };
      if (editing.id) {
        await api.patch(`/recurring-jobs/${editing.id}`, payload);
      } else {
        await api.post("/recurring-jobs", payload);
      }
      setModalOpen(false); setEditing(null);
      await load();
    } catch (e) {
      setError(e?.message || "Save failed");
    }
  };

  const togglePause = async (row) => {
    setBusy(row.id);
    try { await api.patch(`/recurring-jobs/${row.id}`, { active: !row.active }); await load(); }
    finally { setBusy(null); }
  };

  const softDelete = async (row) => {
    setBusy(row.id);
    try { await api.delete(`/recurring-jobs/${row.id}`); await load(); }
    finally { setBusy(null); }
  };

  const generateNow = async (row) => {
    setBusy(row.id);
    try {
      const through = addDaysIso(todayIso(), 14);
      const res = await api.post(`/recurring-jobs/${row.id}/generate?through=${through}`, {});
      alertOk(`Generated ${res?.inserted || 0} jobs (skipped ${res?.skipped || 0}).`);
      await load();
    } catch (e) { setError(e?.message || "Generate failed"); }
    finally { setBusy(null); }
  };

  const alertOk = (msg) => { setError(null); setBusy(null); window.setTimeout(() => setError(null), 100); /* mini-toast substitute */ setError(msg); setTimeout(() => setError(null), 2500); };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="recurring-jobs-page">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center"
               style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
            <CalendarClock size={20} />
          </div>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>Recurring Jobs</h1>
            <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
              Auto-generates a rolling 2-week horizon of jobs. Nightly cron @ 02:00 UTC.
            </p>
          </div>
        </div>
        <button type="button" onClick={openCreate}
                className="inline-flex items-center gap-1 text-sm font-bold px-3 py-2 rounded-md"
                style={{ background: colors.brand, color: "#fff", border: 0 }}
                data-testid="recurring-jobs-create">
          <Plus size={14} /> New recurring job
        </button>
      </div>

      {error ? (
        <div className="rounded-2xl p-3 mb-4 text-sm"
             style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
             data-testid="recurring-jobs-error">{error}</div>
      ) : null}

      {loading ? (
        <div className="rounded-2xl p-8 text-center text-sm"
             style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}>
          Loading…
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm" data-testid="recurring-jobs-table">
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Customer</th>
                <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Service</th>
                <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Frequency</th>
                <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Next</th>
                <th className="text-right px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Price</th>
                <th className="text-left px-3 py-2.5 uppercase text-[11px] font-semibold" style={{ color: colors.muted }}>Status</th>
                <th className="px-3 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-sm"
                       style={{ color: colors.muted }} data-testid="recurring-jobs-empty">
                  No recurring jobs yet — click "New recurring job" to add your first.
                </td></tr>
              ) : items.map((r) => (
                <tr key={r.id} data-testid={`recurring-job-row-${r.id}`}
                    style={{ borderBottom: `1px solid ${colors.border}` }}>
                  <td className="px-3 py-2.5" style={{ color: colors.onSurface }}>{r.customer_name}</td>
                  <td className="px-3 py-2.5 text-xs" style={{ color: colors.muted }}>{r.service_type}</td>
                  <td className="px-3 py-2.5 text-xs" style={{ color: colors.muted }}>
                    {r.frequency}{r.frequency === "weekly" || r.frequency === "biweekly" ? ` (${DOW[r.day_of_week] || "?"})` : ""}
                    {r.frequency === "monthly" ? ` (day ${r.day_of_month})` : ""}
                    {r.frequency === "custom" ? ` (${r.interval_days}d)` : ""}
                  </td>
                  <td className="px-3 py-2.5 text-xs" style={{ color: colors.muted }}>
                    {(r.upcoming || []).slice(0, 1).join(", ") || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right font-semibold" style={{ color: colors.onSurface }}>
                    {fmtMoney(r.price_cents)}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase"
                          style={r.active
                            ? { background: "#DCFCE7", color: "#166534" }
                            : { background: "#FEE2E2", color: "#991B1B" }}>
                      {r.active ? "Active" : "Paused"}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right whitespace-nowrap">
                    <button type="button" onClick={() => generateNow(r)} disabled={busy === r.id || !r.active}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold mr-1"
                            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                            data-testid={`recurring-job-generate-${r.id}`}>
                      <RefreshCw size={11} /> Gen 14d
                    </button>
                    <button type="button" onClick={() => openEdit(r)}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold mr-1"
                            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                            data-testid={`recurring-job-edit-${r.id}`}>
                      Edit
                    </button>
                    <button type="button" onClick={() => togglePause(r)}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold mr-1"
                            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                            data-testid={`recurring-job-toggle-${r.id}`}>
                      {r.active ? <Pause size={11} /> : <Play size={11} />}{r.active ? "Pause" : "Resume"}
                    </button>
                    <button type="button" onClick={() => softDelete(r)}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold"
                            style={{ border: `1px solid #FECACA`, background: colors.surface, color: "#B91C1C" }}
                            data-testid={`recurring-job-delete-${r.id}`}>
                      <Trash2 size={11} /> Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalOpen && editing ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(15,23,42,0.55)" }}>
          <div className="w-full max-w-lg rounded-2xl" style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
            <div className="flex items-center justify-between px-5 py-3" style={{ borderBottom: `1px solid ${colors.border}` }}>
              <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
                {editing.id ? "Edit Recurring Job" : "New Recurring Job"}
              </h2>
              <button type="button" onClick={() => { setModalOpen(false); setEditing(null); }}
                      data-testid="recurring-jobs-modal-close">
                <X size={18} />
              </button>
            </div>
            <div className="p-5 space-y-3">
              <label className="text-xs font-semibold" style={{ color: colors.muted }}>Customer
                <select value={editing.customer_id || ""} onChange={(e) => setEditing((x) => ({ ...x, customer_id: e.target.value }))}
                        className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                        style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                        data-testid="recurring-jobs-customer">
                  <option value="">Select customer…</option>
                  {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </label>
              <label className="text-xs font-semibold" style={{ color: colors.muted }}>Service type
                <input type="text" value={editing.service_type || ""} onChange={(e) => setEditing((x) => ({ ...x, service_type: e.target.value }))}
                       className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                       style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                       data-testid="recurring-jobs-service" placeholder="Weekly Pool Service" />
              </label>
              <label className="text-xs font-semibold" style={{ color: colors.muted }}>Frequency
                <select value={editing.frequency || "weekly"} onChange={(e) => setEditing((x) => ({ ...x, frequency: e.target.value }))}
                        className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                        style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                        data-testid="recurring-jobs-frequency">
                  {FREQ_OPTIONS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                </select>
              </label>
              {(editing.frequency === "weekly" || editing.frequency === "biweekly") ? (
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>Day of week
                  <select value={editing.day_of_week ?? 0} onChange={(e) => setEditing((x) => ({ ...x, day_of_week: Number(e.target.value) }))}
                          className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                          style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                          data-testid="recurring-jobs-dow">
                    {DOW.map((d, i) => <option key={d} value={i}>{d}</option>)}
                  </select>
                </label>
              ) : null}
              {editing.frequency === "monthly" ? (
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>Day of month
                  <input type="number" min="1" max="31" value={editing.day_of_month ?? 1}
                         onChange={(e) => setEditing((x) => ({ ...x, day_of_month: Number(e.target.value) }))}
                         className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                         style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                         data-testid="recurring-jobs-dom" />
                </label>
              ) : null}
              {editing.frequency === "custom" ? (
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>Interval days
                  <input type="number" min="1" max="365" value={editing.interval_days ?? 7}
                         onChange={(e) => setEditing((x) => ({ ...x, interval_days: Number(e.target.value) }))}
                         className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                         style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                         data-testid="recurring-jobs-interval" />
                </label>
              ) : null}
              <div className="grid grid-cols-2 gap-3">
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>Start date
                  <input type="date" value={editing.start_date || todayIso()}
                         onChange={(e) => setEditing((x) => ({ ...x, start_date: e.target.value }))}
                         className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                         style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                         data-testid="recurring-jobs-start" />
                </label>
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>End date (optional)
                  <input type="date" value={editing.end_date || ""}
                         onChange={(e) => setEditing((x) => ({ ...x, end_date: e.target.value || null }))}
                         className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                         style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                         data-testid="recurring-jobs-end" />
                </label>
              </div>
              <label className="text-xs font-semibold" style={{ color: colors.muted }}>Assigned tech
                <select value={editing.assigned_tech_id || ""} onChange={(e) => setEditing((x) => ({ ...x, assigned_tech_id: e.target.value || null }))}
                        className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                        style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                        data-testid="recurring-jobs-tech">
                  <option value="">Auto-assign</option>
                  {techs.map((t) => <option key={t.id} value={t.id}>{t.name || t.email}</option>)}
                </select>
              </label>
              <label className="text-xs font-semibold" style={{ color: colors.muted }}>Price ($)
                <input type="number" min="0" step="0.01" value={((editing.price_cents || 0) / 100).toFixed(2)}
                       onChange={(e) => setEditing((x) => ({ ...x, price_cents: Math.round(Number(e.target.value) * 100) }))}
                       className="w-full mt-1 px-2 py-1.5 rounded text-sm"
                       style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                       data-testid="recurring-jobs-price" />
              </label>
              <label className="flex items-center gap-2 text-xs font-semibold" style={{ color: colors.muted }}>
                <input type="checkbox" checked={!!editing.allow_sunday}
                       onChange={(e) => setEditing((x) => ({ ...x, allow_sunday: e.target.checked }))}
                       data-testid="recurring-jobs-sunday" />
                Allow Sunday
              </label>
            </div>
            <div className="px-5 py-3 flex items-center justify-end gap-2" style={{ borderTop: `1px solid ${colors.border}` }}>
              <button type="button" onClick={() => { setModalOpen(false); setEditing(null); }}
                      className="text-sm font-semibold px-3 py-1.5 rounded"
                      style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                      data-testid="recurring-jobs-cancel">Cancel</button>
              <button type="button" onClick={save} disabled={!editing.customer_id || !editing.service_type}
                      className="text-sm font-bold px-4 py-1.5 rounded"
                      style={{ background: colors.brand, color: "#fff", border: 0, opacity: (!editing.customer_id || !editing.service_type) ? 0.5 : 1 }}
                      data-testid="recurring-jobs-save">
                {editing.id ? "Save changes" : "Create"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
