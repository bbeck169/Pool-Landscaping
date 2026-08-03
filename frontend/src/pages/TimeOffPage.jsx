import React, { useCallback, useEffect, useMemo, useState } from "react";
import api from "@/lib/api";

const TYPES = ["sick", "vacation", "personal", "unpaid"];
const STATUS_COLORS = {
  pending:   "bg-amber-100 text-amber-800",
  approved:  "bg-emerald-100 text-emerald-800",
  rejected:  "bg-rose-100 text-rose-800",
  cancelled: "bg-slate-100 text-slate-600",
};

function StatusPill({ status }) {
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_COLORS[status] || ""}`}
          data-testid={`tof-status-${status}`}>
      {status}
    </span>
  );
}

export default function TimeOffPage() {
  const [balance, setBalance] = useState(null);
  const [rows, setRows] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [b, r] = await Promise.all([
        api.get("/time-off/balance/me"),
        api.get("/time-off/requests?scope=me"),
      ]);
      setBalance(b); setRows(r);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onCancel = async (id) => {
    try { await api.post(`/time-off/requests/${id}/cancel`, {}); await load(); }
    catch (e) { setError(e?.response?.data?.detail?.code || "cancel_failed"); }
  };

  return (
    <div className="p-6 max-w-5xl" data-testid="time-off-page">
      <h1 className="text-2xl font-bold mb-4">Time Off</h1>
      {loading || !balance ? <div>Loading…</div> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6" data-testid="tof-balance-card">
            <Stat label="Available" value={`${balance.available_hours} hrs`} testid="tof-stat-available" />
            <Stat label="Accrued YTD" value={`${balance.accrued_hours_ytd} hrs`} testid="tof-stat-accrued" />
            <Stat label="Used YTD" value={`${balance.used_hours_ytd} hrs`} testid="tof-stat-used" />
            {balance.waiting_period_remaining_days > 0 ? (
              <Stat label="Waiting period"
                    value={`${balance.waiting_period_remaining_days} days`}
                    tint="amber"
                    testid="tof-stat-waiting" />
            ) : (
              <Stat label="Annual cap" value={`${balance.annual_cap_hours} hrs`} testid="tof-stat-cap" />
            )}
          </div>

          <div className="flex justify-end mb-3">
            <button
              className="rounded bg-teal-600 px-4 py-2 text-white font-semibold hover:bg-teal-700"
              onClick={() => { setError(""); setShowModal(true); }}
              data-testid="tof-open-request">Request Time Off</button>
          </div>

          <div className="overflow-x-auto rounded border">
            <table className="w-full text-sm" data-testid="tof-requests-table">
              <thead className="bg-slate-50 text-left">
                <tr><th className="p-2">Type</th><th>From</th><th>To</th><th>Hours</th><th>Status</th><th>Reason</th><th></th></tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr><td colSpan={7} className="p-4 text-center text-slate-500">No requests yet.</td></tr>
                ) : rows.map((r) => (
                  <tr key={r.id} className="border-t" data-testid={`tof-row-${r.id}`}>
                    <td className="p-2 capitalize">{r.type}</td>
                    <td>{r.from_date}</td>
                    <td>{r.to_date}</td>
                    <td>{r.hours}</td>
                    <td><StatusPill status={r.status} /></td>
                    <td className="max-w-xs truncate" title={r.reason}>{r.reason}</td>
                    <td>{r.status === "pending" ? (
                      <button className="text-rose-600 hover:underline" onClick={() => onCancel(r.id)}
                              data-testid={`tof-cancel-${r.id}`}>Cancel</button>
                    ) : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {showModal ? (
        <RequestModal
          onClose={() => setShowModal(false)}
          onSubmitted={() => { setShowModal(false); load(); }}
          onError={setError}
        />
      ) : null}
    </div>
  );
}

function Stat({ label, value, tint, testid }) {
  return (
    <div className={`rounded border p-3 ${tint === "amber" ? "bg-amber-50 border-amber-200" : "bg-white"}`}
         data-testid={testid}>
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="text-2xl font-bold text-slate-800 mt-1">{value}</div>
    </div>
  );
}

function RequestModal({ onClose, onSubmitted, onError }) {
  const today = new Date().toISOString().slice(0, 10);
  const [type, setType] = useState("sick");
  const [fromDate, setFromDate] = useState(today);
  const [toDate, setToDate] = useState(today);
  const [hours, setHours] = useState(8);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [modalError, setModalError] = useState("");

  useEffect(() => {
    const f = new Date(fromDate); const t = new Date(toDate);
    if (isNaN(f) || isNaN(t) || t < f) return;
    const days = Math.round((t - f) / 86400000) + 1;
    setHours(days * 8);
  }, [fromDate, toDate]);

  const submit = async () => {
    setSubmitting(true); setModalError("");
    try {
      await api.post("/time-off/requests", { type, from_date: fromDate, to_date: toDate, hours, reason });
      onSubmitted();
    } catch (e) {
      const code = e?.response?.data?.detail?.code;
      if (code === "waiting_period") {
        setModalError(`You're inside your 90-day waiting period (${e.response.data.detail.remaining_days} days remaining).`);
      } else if (code === "insufficient_balance") {
        setModalError(`Not enough balance — you have ${e.response.data.detail.available} hrs available.`);
      } else {
        setModalError(String(code || e?.message || "Submit failed"));
      }
      onError?.(code || "");
    } finally { setSubmitting(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" data-testid="tof-modal">
      <div className="bg-white rounded-lg p-6 w-full max-w-md">
        <h2 className="text-lg font-bold mb-3">Request Time Off</h2>
        <label className="block text-xs font-semibold mb-1">Type</label>
        <select value={type} onChange={(e) => setType(e.target.value)}
                className="w-full border rounded px-2 py-1 mb-3" data-testid="tof-type">
          {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <label className="block text-xs font-semibold mb-1">From</label>
            <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)}
                   className="w-full border rounded px-2 py-1" data-testid="tof-from" />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">To</label>
            <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)}
                   className="w-full border rounded px-2 py-1" data-testid="tof-to" />
          </div>
        </div>
        <label className="block text-xs font-semibold mb-1">Hours</label>
        <input type="number" min="0.25" step="0.25" value={hours}
               onChange={(e) => setHours(Number(e.target.value))}
               className="w-full border rounded px-2 py-1 mb-3" data-testid="tof-hours" />
        <label className="block text-xs font-semibold mb-1">Reason</label>
        <textarea value={reason} onChange={(e) => setReason(e.target.value)}
                  className="w-full border rounded px-2 py-1 mb-3" rows={3} data-testid="tof-reason" />
        {modalError ? (
          <div className="bg-rose-50 border border-rose-200 text-rose-800 rounded p-2 mb-3 text-sm"
               data-testid="tof-error-banner">{modalError}</div>
        ) : null}
        <div className="flex justify-end gap-2">
          <button className="px-3 py-1.5 rounded border" onClick={onClose} data-testid="tof-cancel">Cancel</button>
          <button className="px-3 py-1.5 rounded bg-teal-600 text-white font-semibold hover:bg-teal-700"
                  onClick={submit} disabled={submitting} data-testid="tof-submit">
            {submitting ? "Submitting…" : "Submit"}
          </button>
        </div>
      </div>
    </div>
  );
}
