/** Phase 28.1 · Warranty Portal admin pages (compact). */
import React, { useCallback, useEffect, useState } from "react";
import { mustAlert } from "@/components/ui/confirm-dialog";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Shield, FileText, AlertCircle, Plus } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const STATUS_C = {
  active: "#059669", claim_pending: "#F59E0B", expired: "#6B7280",
  cancelled: "#DC2626", renewed: "#0EA5E9",
  submitted: "#F59E0B", reviewing: "#0EA5E9", approved: "#059669",
  resolved: "#059669", rejected: "#DC2626",
};
const pill = (s) => (
  <span className="inline-block px-2 py-0.5 rounded-full text-[10px] font-bold"
        style={{ backgroundColor: `${STATUS_C[s] || "#6B7280"}15`,
                 color: STATUS_C[s] || "#6B7280" }}>{s}</span>
);

export default function WarrantyPlans() {
  const nav = useNavigate();
  const [plans, setPlans] = useState([]);
  const load = useCallback(async () => {
    const r = await api.get("/warranties/plans");
    setPlans(r.items || []);
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="warranty-plans">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/")} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <h1 className="flex-1 text-2xl font-bold flex items-center gap-2"
            style={{ color: colors.onSurface }}>
          <Shield size={22} style={{ color: colors.brand }} />
          Warranty plans
        </h1>
        <button onClick={() => nav("/admin/warranties/contracts")}
                className="px-3 py-2 text-sm font-bold rounded-xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="warranty-contracts-link">Contracts</button>
        <button onClick={() => nav("/admin/warranties/claims")}
                className="px-3 py-2 text-sm font-bold rounded-xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="warranty-claims-link">Claims</button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {plans.map((p) => (
          <div key={p.id} className="rounded-2xl p-4"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid={`warranty-plan-${p.id}`}>
            <div className="flex justify-between items-start mb-2">
              <div>
                <div className="font-bold text-lg"
                     style={{ color: colors.onSurface }}>{p.name}</div>
                <div className="text-xs" style={{ color: colors.muted }}>
                  {p.kind} · {p.duration_months} months
                </div>
              </div>
              <div className="text-lg font-bold"
                   style={{ color: colors.brand }}>
                ${p.price || 0}
              </div>
            </div>
            <div className="text-sm" style={{ color: colors.onSurface }}>
              {p.coverage_summary}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function WarrantyContracts() {
  const nav = useNavigate();
  const [contracts, setContracts] = useState([]);
  const [plans, setPlans] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const [f, setF] = useState({ plan_id: "", customer_id: "",
                                     start_date: new Date().toISOString().slice(0,10) });
  const load = async () => {
    const r = await api.get("/warranties/contracts");
    setContracts(r.items || []);
    const p = await api.get("/warranties/plans"); setPlans(p.items || []);
    const c = await api.get("/customers?limit=500");
    setCustomers(Array.isArray(c) ? c : (c.items || []));
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    await api.post("/warranties/contracts", f);
    setShowNew(false); await load();
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="warranty-contracts">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin/warranties/plans")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <h1 className="flex-1 text-2xl font-bold flex items-center gap-2"
            style={{ color: colors.onSurface }}>
          <FileText size={22} style={{ color: colors.brand }} />
          Warranty contracts
        </h1>
        <button onClick={() => setShowNew(true)}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="warranty-new-contract">
          <Plus size={12} /> New contract
        </button>
      </div>
      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <table className="w-full text-sm">
          <thead style={{ backgroundColor: "#F1F5F9" }}>
            <tr>
              <th className="p-2 text-left">Plan</th>
              <th className="p-2 text-left">Customer</th>
              <th className="p-2 text-left">Start</th>
              <th className="p-2 text-left">End</th>
              <th className="p-2 text-left">Status</th>
            </tr>
          </thead>
          <tbody>
            {contracts.map((c) => (
              <tr key={c.id}
                  style={{ borderTop: `1px solid ${colors.border}` }}
                  data-testid={`warranty-contract-${c.id}`}>
                <td className="p-2 font-bold"
                    style={{ color: colors.onSurface }}>
                  {c.plan_name_snapshot}
                </td>
                <td className="p-2 text-xs" style={{ color: colors.muted }}>
                  {c.customer_name_snapshot}
                </td>
                <td className="p-2 text-xs">{c.start_date}</td>
                <td className="p-2 text-xs font-bold"
                    style={{ color: colors.onSurface }}>{c.end_date}</td>
                <td className="p-2">{pill(c.status)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showNew ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
             data-testid="warranty-new-modal">
          <div className="rounded-2xl w-full max-w-md p-5"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}>
            <h2 className="text-lg font-bold mb-3"
                style={{ color: colors.onSurface }}>New contract</h2>
            <div className="grid gap-3">
              <select value={f.plan_id}
                      onChange={(e) => setF({ ...f, plan_id: e.target.value })}
                      className="p-2 rounded-lg text-sm"
                      style={{ backgroundColor: colors.background,
                               border: `1px solid ${colors.border}` }}>
                <option value="">Plan…</option>
                {plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <select value={f.customer_id}
                      onChange={(e) => setF({ ...f, customer_id: e.target.value })}
                      className="p-2 rounded-lg text-sm"
                      style={{ backgroundColor: colors.background,
                               border: `1px solid ${colors.border}` }}>
                <option value="">Customer…</option>
                {customers.map((c) =>
                  <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <input type="date" value={f.start_date}
                     onChange={(e) => setF({ ...f, start_date: e.target.value })}
                     className="p-2 rounded-lg text-sm"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}` }} />
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setShowNew(false)}
                      className="px-4 py-2 text-sm font-bold rounded-xl"
                      style={{ backgroundColor: colors.background,
                               border: `1px solid ${colors.border}`,
                               color: colors.onSurface }}>Cancel</button>
              <button onClick={save}
                      className="px-4 py-2 text-sm font-bold rounded-xl"
                      style={{ backgroundColor: colors.brand, color: "#fff" }}
                      data-testid="warranty-new-save">Create</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function WarrantyClaims() {
  const nav = useNavigate();
  const [claims, setClaims] = useState([]);
  const load = async () => {
    const r = await api.get("/warranties/claims");
    setClaims(r.items || []);
  };
  useEffect(() => { load(); }, []);
  const setStatus = async (cid, status) => {
    await api.patch(`/warranties/claims/${cid}`, { status });
    await load();
  };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="warranty-claims">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin/warranties/plans")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <h1 className="flex-1 text-2xl font-bold flex items-center gap-2"
            style={{ color: colors.onSurface }}>
          <AlertCircle size={22} style={{ color: colors.brand }} />
          Warranty claims
        </h1>
      </div>
      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <table className="w-full text-sm">
          <thead style={{ backgroundColor: "#F1F5F9" }}>
            <tr>
              <th className="p-2 text-left">Filed</th>
              <th className="p-2 text-left">Issue</th>
              <th className="p-2 text-left">Description</th>
              <th className="p-2 text-left">Status</th>
              <th className="p-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((c) => (
              <tr key={c.id}
                  style={{ borderTop: `1px solid ${colors.border}` }}
                  data-testid={`warranty-claim-${c.id}`}>
                <td className="p-2 text-xs" style={{ color: colors.muted }}>
                  {(c.created_at || "").slice(0, 10)} · {c.filed_by_role}
                </td>
                <td className="p-2 text-xs font-bold"
                    style={{ color: colors.onSurface }}>{c.issue_type}</td>
                <td className="p-2 text-xs"
                    style={{ color: colors.onSurface }}>
                  {(c.description || "").slice(0, 80)}
                </td>
                <td className="p-2">{pill(c.status)}</td>
                <td className="p-2 flex gap-1 justify-end">
                  {c.status === "submitted" ? (
                    <button onClick={() => setStatus(c.id, "approved")}
                            className="px-2 py-1 text-xs font-bold rounded"
                            style={{ backgroundColor: "#05966915",
                                     color: "#059669" }}
                            data-testid={`warranty-claim-approve-${c.id}`}>
                      Approve
                    </button>
                  ) : null}
                  {["submitted","approved"].includes(c.status) ? (
                    <button onClick={() => setStatus(c.id, "resolved")}
                            className="px-2 py-1 text-xs font-bold rounded"
                            style={{ backgroundColor: colors.brand,
                                     color: "#fff" }}
                            data-testid={`warranty-claim-resolve-${c.id}`}>
                      Resolve
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function PortalWarranties() {
  const [contracts, setContracts] = useState([]);
  const load = async () => {
    const r = await api.get("/portal/warranties");
    setContracts(r.items || []);
  };
  useEffect(() => { load(); }, []);
  const fileClaim = async (cid) => {
    const desc = window.prompt("Describe the issue:");
    if (!desc) return;
    await api.post(`/portal/warranties/${cid}/file-claim`,
                     { description: desc, issue_type: "general" });
    await load();
    await mustAlert({ title: "Claim filed", description: "We'll get back to you shortly." });
  };
  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6"
         data-testid="portal-warranties">
      <h1 className="text-2xl font-bold mb-6 flex items-center gap-2"
          style={{ color: colors.onSurface }}>
        <Shield size={22} style={{ color: colors.brand }} />
        My warranties & service plans
      </h1>
      {contracts.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          You don't have any active warranties or service plans yet.
        </div>
      ) : (
        <div className="grid gap-3">
          {contracts.map((c) => (
            <div key={c.id} className="rounded-2xl p-4"
                 style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                 data-testid={`portal-contract-${c.id}`}>
              <div className="flex justify-between items-start mb-2">
                <div>
                  <div className="font-bold text-lg"
                       style={{ color: colors.onSurface }}>
                    {c.plan_name_snapshot}
                  </div>
                  <div className="text-xs" style={{ color: colors.muted }}>
                    {c.start_date} → {c.end_date}
                  </div>
                </div>
                {pill(c.status)}
              </div>
              {c.status === "active" ? (
                <button onClick={() => fileClaim(c.id)}
                        className="px-3 py-2 text-sm font-bold rounded-xl mt-2"
                        style={{ backgroundColor: colors.brand,
                                 color: "#fff" }}
                        data-testid={`portal-file-claim-${c.id}`}>
                  File a claim
                </button>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
