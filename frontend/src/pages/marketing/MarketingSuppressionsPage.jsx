/**
 * Feb-2026 · Marketing Slice F — Admin Suppression list.
 *
 * Tenant-wide view of every active suppression + a Manual add form +
 * per-row soft-delete (revoke).  Read-only aside from those two
 * admin-only actions.
 */
import React, { useEffect, useState } from "react";
import { Plus, Trash2, MailX, Ban, RefreshCw } from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";


export default function MarketingSuppressionsPage() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [channel, setChannel] = useState("");
  const [reason, setReason] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ channel: "email", address: "",
                                       reason: "manual_admin", category: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () => {
    const q = new URLSearchParams();
    if (channel) q.set("channel", channel);
    if (reason) q.set("reason", reason);
    q.set("limit", "200");
    api.get(`/marketing/suppressions?${q.toString()}`)
      .then((r) => { setRows(r.suppressions || []); setTotal(r.total || 0); })
      .catch(() => { setRows([]); setTotal(0); });
  };
  useEffect(load, [channel, reason]);

  const add = async () => {
    setBusy(true); setError("");
    try {
      const payload = { ...form,
                         category: form.category || null };
      await api.post("/marketing/suppressions", payload);
      setShowAdd(false);
      setForm({ channel: "email", address: "",
                 reason: "manual_admin", category: "" });
      load();
    } catch (e) { setError(e?.message || "Failed to add suppression"); }
    finally { setBusy(false); }
  };

  const del = async (id) => {
    if (!window.confirm("Revoke this suppression? The recipient will start receiving messages again.")) return;
    try { await api.del(`/marketing/suppressions/${id}`); load(); }
    catch (e) { alert(e?.message || "Delete failed"); }
  };

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
         data-testid="admin-suppressions-page">
      <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
            Suppression list
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            {total} active suppression{total === 1 ? "" : "s"}. Every marketing/review-request/sequence send checks this list before delivery.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select value={channel} onChange={(e) => setChannel(e.target.value)}
                  className="px-2 py-1.5 rounded-lg text-sm outline-none"
                  style={inputStyle}
                  data-testid="suppressions-channel-filter">
            <option value="">All channels</option>
            <option value="email">Email</option>
            <option value="sms">SMS</option>
          </select>
          <select value={reason} onChange={(e) => setReason(e.target.value)}
                  className="px-2 py-1.5 rounded-lg text-sm outline-none"
                  style={inputStyle}
                  data-testid="suppressions-reason-filter">
            <option value="">All reasons</option>
            <option value="user_unsubscribe">User unsubscribe</option>
            <option value="manual_admin">Manual (admin)</option>
            <option value="bounce">Bounce</option>
            <option value="complaint">Complaint</option>
          </select>
          <button onClick={load}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: colors.surfaceSecondary,
                           color: colors.onSurface,
                           border: `1px solid ${colors.border}` }}>
            <RefreshCw size={13} /> Refresh
          </button>
          <button onClick={() => setShowAdd(true)}
                  className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white"
                  style={{ background: brandGradientCss }}
                  data-testid="admin-add-suppression-btn">
            <Plus size={14} /> Add
          </button>
        </div>
      </div>

      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        {rows.length === 0 ? (
          <div className="p-10 text-center">
            <MailX size={22} className="mx-auto mb-3" style={{ color: colors.muted }} />
            <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
              No suppressions yet
            </div>
            <div className="text-xs mt-1" style={{ color: colors.muted }}>
              Suppressions are auto-created when a customer opts out — or add one manually above.
            </div>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.divider}` }}>
                {["Address", "Channel", "Reason", "Category", "Added", ""].map((h) => (
                  <th key={h}
                      className="text-left py-2 px-3 text-xs font-bold uppercase tracking-wide"
                      style={{ color: colors.muted }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}
                    style={{ borderBottom: `1px solid ${colors.divider}` }}
                    data-testid={`suppression-row-${r.id}`}>
                  <td className="py-2 px-3 font-mono text-xs"
                      style={{ color: colors.onSurface }}>{r.address}</td>
                  <td className="py-2 px-3" style={{ color: colors.onSurface }}>{r.channel}</td>
                  <td className="py-2 px-3" style={{ color: colors.muted }}>{r.reason}</td>
                  <td className="py-2 px-3" style={{ color: colors.muted }}>{r.category || "all"}</td>
                  <td className="py-2 px-3" style={{ color: colors.muted }}>
                    {String(r.created_at || "").slice(0, 10)}
                  </td>
                  <td className="py-2 px-3 text-right">
                    <button onClick={() => del(r.id)}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold"
                            style={{ backgroundColor: colors.surfaceSecondary,
                                     color: colors.error }}
                            data-testid={`suppression-delete-btn-${r.id}`}>
                      <Trash2 size={11} /> Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showAdd ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ background: "rgba(15,23,42,0.55)" }}
             onMouseDown={(e) => { if (e.target === e.currentTarget) setShowAdd(false); }}>
          <div className="w-full max-w-sm rounded-2xl shadow-2xl overflow-hidden"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}>
            <div className="p-4" style={{ borderBottom: `1px solid ${colors.divider}` }}>
              <h3 className="text-base font-bold" style={{ color: colors.onSurface }}>
                Add suppression
              </h3>
            </div>
            <div className="p-4 space-y-3">
              <Field label="Channel">
                <select value={form.channel}
                        onChange={(e) => setForm({ ...form, channel: e.target.value })}
                        className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                        style={inputStyle}>
                  <option value="email">Email</option>
                  <option value="sms">SMS</option>
                </select>
              </Field>
              <Field label={form.channel === "email" ? "Email address" : "Phone number"}>
                <input type="text" value={form.address}
                       onChange={(e) => setForm({ ...form, address: e.target.value })}
                       className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                       style={inputStyle} />
              </Field>
              <Field label="Category">
                <select value={form.category}
                        onChange={(e) => setForm({ ...form, category: e.target.value })}
                        className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                        style={inputStyle}>
                  <option value="">All (channel-level opt-out)</option>
                  <option value="review_requests">Review requests</option>
                  <option value="sequences">Sequences</option>
                  <option value="campaigns">Campaigns</option>
                </select>
              </Field>
              {error ? (
                <div className="text-xs" style={{ color: colors.error }}>{error}</div>
              ) : null}
            </div>
            <div className="p-4 flex items-center justify-end gap-2"
                 style={{ borderTop: `1px solid ${colors.divider}` }}>
              <button onClick={() => setShowAdd(false)}
                      className="px-4 py-2 rounded-xl text-sm font-semibold"
                      style={{ backgroundColor: colors.surfaceSecondary,
                               color: colors.onSurface }}>
                Cancel
              </button>
              <button onClick={add} disabled={busy || !form.address}
                      className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
                      style={{ background: brandGradientCss }}>
                <Ban size={14} /> Add suppression
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}


const inputStyle = {
  backgroundColor: colors.surface,
  color: colors.onSurface,
  border: `1px solid ${colors.border}`,
};


function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] font-bold uppercase tracking-wider"
            style={{ color: colors.muted }}>{label}</span>
      {children}
    </label>
  );
}
