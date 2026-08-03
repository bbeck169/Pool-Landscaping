import React, { useCallback, useEffect, useState } from "react";
import api from "@/api";

export default function AdminTimeOffPage() {
  const [tab, setTab] = useState("pending"); // pending | all
  const [rows, setRows] = useState([]);
  const [balances, setBalances] = useState([]);
  const [policy, setPolicy] = useState(null);
  const [reject, setReject] = useState(null); // {id} to prompt notes
  const [rejectNotes, setRejectNotes] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = tab === "pending" ? "scope=all&status=pending" : "scope=all";
      const [r, b, p] = await Promise.all([
        api.get(`/time-off/requests?${q}`),
        api.get("/time-off/balances/all"),
        api.get("/time-off/policy"),
      ]);
      setRows(r); setBalances(b); setPolicy(p);
    } finally { setLoading(false); }
  }, [tab]);

  useEffect(() => { load(); }, [load]);

  const approve = async (id) => {
    await api.post(`/time-off/requests/${id}/approve`, { decision_notes: "" });
    setRows((prev) => prev.filter((r) => r.id !== id));
    load();
  };
  const doReject = async () => {
    if (!reject) return;
    await api.post(`/time-off/requests/${reject.id}/reject`, { decision_notes: rejectNotes });
    setRows((prev) => prev.filter((r) => r.id !== reject.id));
    setReject(null); setRejectNotes("");
  };

  const savePolicy = async () => {
    const p = await api.put("/time-off/policy", policy);
    setPolicy(p);
  };

  return (
    <div className="p-6 max-w-6xl" data-testid="admin-time-off-page">
      <h1 className="text-2xl font-bold mb-4">Time Off Approvals</h1>

      <div className="flex gap-2 mb-4">
        {["pending", "all"].map((t) => (
          <button key={t}
                  className={`px-3 py-1.5 rounded ${tab === t ? "bg-teal-600 text-white" : "bg-slate-100 text-slate-700"}`}
                  onClick={() => setTab(t)}
                  data-testid={`admin-tof-tab-${t}`}>
            {t === "pending" ? "Pending Approvals" : "All Requests"}
          </button>
        ))}
      </div>

      {loading ? <div>Loading…</div> : (
        <>
          <div className="overflow-x-auto rounded border mb-6">
            <table className="w-full text-sm" data-testid="admin-tof-list">
              <thead className="bg-slate-50 text-left">
                <tr><th className="p-2">Employee</th><th>Type</th><th>Dates</th><th>Hours</th><th>Status</th><th>Reason</th><th></th></tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr><td colSpan={7} className="p-4 text-center text-slate-500">Nothing to review.</td></tr>
                ) : rows.map((r) => {
                  const emp = balances.find((b) => b.user_id === r.user_id);
                  return (
                    <tr key={r.id} className="border-t" data-testid={`admin-tof-row-${r.id}`}>
                      <td className="p-2">{emp?.user_name || r.user_id.slice(0, 8)}</td>
                      <td className="capitalize">{r.type}</td>
                      <td>{r.from_date === r.to_date ? r.from_date : `${r.from_date} → ${r.to_date}`}</td>
                      <td>{r.hours}</td>
                      <td>{r.status}</td>
                      <td className="max-w-xs truncate" title={r.reason}>{r.reason}</td>
                      <td className="whitespace-nowrap">
                        {r.status === "pending" ? (
                          <>
                            <button className="text-emerald-700 font-semibold mr-2 hover:underline"
                                    onClick={() => approve(r.id)}
                                    data-testid={`admin-tof-approve-${r.id}`}>Approve</button>
                            <button className="text-rose-700 font-semibold hover:underline"
                                    onClick={() => { setReject({ id: r.id }); setRejectNotes(""); }}
                                    data-testid={`admin-tof-reject-${r.id}`}>Reject</button>
                          </>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <h2 className="text-lg font-bold mb-2">Employee balances</h2>
          <div className="overflow-x-auto rounded border mb-6">
            <table className="w-full text-sm" data-testid="admin-tof-balances">
              <thead className="bg-slate-50 text-left">
                <tr><th className="p-2">Employee</th><th>Hire date</th><th>Worked YTD</th><th>Accrued</th><th>Used</th><th>Available</th></tr>
              </thead>
              <tbody>
                {balances.map((b) => (
                  <tr key={b.user_id} className="border-t" data-testid={`admin-tof-bal-${b.user_id}`}>
                    <td className="p-2">{b.user_name}</td>
                    <td>{b.hire_date ? String(b.hire_date).slice(0, 10) : "—"}</td>
                    <td>{b.worked_hours_ytd}</td>
                    <td>{b.accrued_hours_ytd}</td>
                    <td>{b.used_hours_ytd}</td>
                    <td className="font-semibold">{b.available_hours}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {policy ? (
            <div className="rounded border p-4 bg-slate-50" data-testid="admin-tof-policy">
              <h2 className="text-lg font-bold mb-3">Policy</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                <NumField label="Accrue" value={policy.accrual_numerator}
                          onChange={(v) => setPolicy({ ...policy, accrual_numerator: v })}
                          testid="policy-num" />
                <NumField label="per hours worked" value={policy.accrual_denominator}
                          onChange={(v) => setPolicy({ ...policy, accrual_denominator: v })}
                          testid="policy-den" />
                <NumField label="Annual cap (hrs)" value={policy.annual_cap_hours}
                          onChange={(v) => setPolicy({ ...policy, annual_cap_hours: v })}
                          testid="policy-cap" />
                <NumField label="Waiting period (days)" value={policy.waiting_period_days}
                          onChange={(v) => setPolicy({ ...policy, waiting_period_days: v })}
                          testid="policy-wait" />
              </div>
              <button className="rounded bg-teal-600 px-4 py-2 text-white font-semibold hover:bg-teal-700"
                      onClick={savePolicy} data-testid="policy-save">Save policy</button>
            </div>
          ) : null}
        </>
      )}

      {reject ? (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" data-testid="admin-tof-reject-modal">
          <div className="bg-white rounded-lg p-5 w-full max-w-md">
            <h3 className="text-lg font-bold mb-2">Reject request</h3>
            <label className="block text-xs font-semibold mb-1">Notes (optional)</label>
            <textarea value={rejectNotes} onChange={(e) => setRejectNotes(e.target.value)}
                      rows={3} className="w-full border rounded px-2 py-1 mb-3"
                      data-testid="admin-tof-reject-notes" />
            <div className="flex justify-end gap-2">
              <button className="px-3 py-1.5 rounded border" onClick={() => setReject(null)}
                      data-testid="admin-tof-reject-cancel">Cancel</button>
              <button className="px-3 py-1.5 rounded bg-rose-600 text-white font-semibold hover:bg-rose-700"
                      onClick={doReject} data-testid="admin-tof-reject-confirm">Reject</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function NumField({ label, value, onChange, testid }) {
  return (
    <label className="block text-sm">
      <span className="block text-xs font-semibold text-slate-500 mb-1">{label}</span>
      <input type="number" value={value} onChange={(e) => onChange(Number(e.target.value))}
             className="w-full border rounded px-2 py-1" data-testid={testid} />
    </label>
  );
}
