/**
 * Phase 24 · Check Writer — admin pages in one file.
 * Exports: CheckRegister (default), CheckNew, CheckDetail, CheckBanks,
 *          CheckPayees, CheckAnalytics.
 * All admin-only via App.js AdminOnly wrapper.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { mustConfirm, mustAlert } from "@/components/ui/confirm-dialog";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, Plus, Printer, Ban, CheckCircle2, RotateCcw, FileText,
  DollarSign, Landmark, Users, BarChart3, AlertTriangle, Trash2, Building,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Gate } from "@/hooks/usePermissions";

/* ─── helpers ────────────────────────────────────────────────────────── */
const STATUS_COLORS = {
  draft:    ["#6B7280", "Draft"],
  printed:  ["#0EA5E9", "Printed"],
  cleared:  ["#059669", "Cleared"],
  voided:   ["#DC2626", "Voided"],
};

function statusPill(status) {
  const [c, l] = STATUS_COLORS[status] || ["#6B7280", status];
  return (
    <span className="inline-block px-2 py-0.5 rounded-full text-[10px] font-bold"
          style={{ backgroundColor: `${c}15`, color: c }}
          data-testid={`check-status-${status}`}>
      {l}
    </span>
  );
}

/* ═════════ REGISTER ═══════════════════════════════════════════════════ */
export default function CheckRegister() {
  const nav = useNavigate();
  const [checks, setChecks] = useState([]);
  const [banks, setBanks] = useState([]);
  const [bankFilter, setBankFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = new URLSearchParams();
      if (bankFilter) q.set("bank_account_id", bankFilter);
      if (statusFilter) q.set("status", statusFilter);
      const [c, b] = await Promise.all([
        api.get(`/checks/checks?${q.toString()}`),
        api.get("/checks/bank-accounts"),
      ]);
      setChecks(c.items || []);
      setBanks(b.items || []);
    } finally { setLoading(false); }
  }, [bankFilter, statusFilter]);

  useEffect(() => { load(); }, [load]);

  const bankById = useMemo(
    () => Object.fromEntries(banks.map((b) => [b.id, b])),
    [banks],
  );

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="check-register">
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <button onClick={() => nav("/")} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="check-back-btn">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-[200px]">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <FileText size={22} style={{ color: colors.brand }} />
            Check register
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Vendor payments, contractor payroll, refunds, and general bill
            payments. Admin only.
          </p>
        </div>
        <button onClick={() => nav("/admin/checks/bank-accounts")}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="check-banks-link">
          <Building size={14} /> Banks
        </button>
        <button onClick={() => nav("/admin/checks/payees")}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="check-payees-link">
          <Users size={14} /> Payees
        </button>
        <button onClick={() => nav("/admin/checks/analytics")}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="check-analytics-link">
          <BarChart3 size={14} /> Analytics
        </button>
        <button onClick={() => nav("/admin/checks/new")}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="check-new-btn">
          <Plus size={14} /> New Check
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        <select value={bankFilter} onChange={(e) => setBankFilter(e.target.value)}
                className="px-3 py-2 text-sm rounded-xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="check-bank-filter">
          <option value="">All bank accounts</option>
          {banks.map((b) => (
            <option key={b.id} value={b.id}>
              {b.nickname} · ****{b.account_number_last4}
            </option>
          ))}
        </select>
        <select value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="px-3 py-2 text-sm rounded-xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="check-status-filter">
          <option value="">All statuses</option>
          {Object.keys(STATUS_COLORS).map((s) => (
            <option key={s} value={s}>{STATUS_COLORS[s][1]}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="p-8 text-center text-sm"
             style={{ color: colors.muted }}>Loading…</div>
      ) : checks.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          No checks match this filter.
          <div className="mt-3">
            <button onClick={() => nav("/admin/checks/new")}
                    className="px-3 py-2 text-sm font-bold rounded-xl"
                    style={{ backgroundColor: colors.brand, color: "#fff" }}>
              Write your first check
            </button>
          </div>
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: "#F1F5F9" }}>
              <tr>
                <th className="p-2 text-left">#</th>
                <th className="p-2 text-left">Date</th>
                <th className="p-2 text-left">Payee</th>
                <th className="p-2 text-left">Bank</th>
                <th className="p-2 text-left">Memo</th>
                <th className="p-2 text-right">Amount</th>
                <th className="p-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {checks.map((c) => (
                <tr key={c.id}
                    style={{ borderTop: `1px solid ${colors.border}`,
                             cursor: "pointer",
                             textDecoration:
                               c.status === "voided" ? "line-through" : "none",
                             opacity: c.status === "voided" ? 0.55 : 1 }}
                    onClick={() => nav(`/admin/checks/${c.id}`)}
                    data-testid={`check-row-${c.id}`}>
                  <td className="p-2 font-mono font-bold"
                      style={{ color: colors.onSurface }}>
                    {c.check_number}
                  </td>
                  <td className="p-2 text-xs" style={{ color: colors.muted }}>
                    {c.date}
                  </td>
                  <td className="p-2 font-bold"
                      style={{ color: colors.onSurface }}>
                    {c.payee_name_snapshot}
                  </td>
                  <td className="p-2 text-xs" style={{ color: colors.muted }}>
                    {(bankById[c.bank_account_id]?.nickname) || "—"}
                  </td>
                  <td className="p-2 text-xs" style={{ color: colors.muted }}>
                    {c.memo || ""}
                  </td>
                  <td className="p-2 text-right font-bold"
                      style={{ color: colors.onSurface }}>
                    ${Number(c.amount).toFixed(2)}
                  </td>
                  <td className="p-2">{statusPill(c.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ═════════ NEW ════════════════════════════════════════════════════════ */
export function CheckNew() {
  const nav = useNavigate();
  const [banks, setBanks] = useState([]);
  const [payees, setPayees] = useState([]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [f, setF] = useState({
    bank_account_id: "", payee_id: "", amount: 0, memo: "",
    date: new Date().toISOString().slice(0, 10),
    category: "", ref_type: "manual",
  });
  const [wordsPreview, setWordsPreview] = useState("");
  const [showNewPayee, setShowNewPayee] = useState(false);

  useEffect(() => {
    api.get("/checks/bank-accounts").then((r) => setBanks(r.items || []));
    api.get("/checks/payees").then((r) => setPayees(r.items || []));
  }, []);

  useEffect(() => {
    // client-side words preview mirrors the server helper.
    const n = Number(f.amount || 0);
    if (Number.isNaN(n) || n <= 0) { setWordsPreview(""); return; }
    setWordsPreview(clientAmountToWords(n));
  }, [f.amount]);

  const save = async () => {
    if (!f.bank_account_id) { setErr("Choose a bank account"); return; }
    if (!f.payee_id) { setErr("Choose a payee"); return; }
    if (Number(f.amount) <= 0) { setErr("Amount must be > 0"); return; }
    setSaving(true); setErr("");
    try {
      const r = await api.post("/checks/checks", {
        ...f, amount: Number(f.amount),
      });
      nav(`/admin/checks/${r.id}`);
    } catch (e) { setErr(e.message || "Failed"); }
    finally { setSaving(false); }
  };

  return (
    <div className="max-w-3xl mx-auto p-4 md:p-6" data-testid="check-new">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin/checks")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="check-new-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <Plus size={22} style={{ color: colors.brand }} />
            Write new check
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            The next check number for the chosen bank account is auto-assigned
            on save.
          </p>
        </div>
      </div>

      <div className="rounded-2xl p-5"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <label className="block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Bank account</div>
            <select value={f.bank_account_id}
                    onChange={(e) => setF({ ...f, bank_account_id: e.target.value })}
                    className="w-full p-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.background,
                             border: `1px solid ${colors.border}` }}
                    data-testid="check-new-bank">
              <option value="">Select…</option>
              {banks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.nickname} · next #{b.next_check_number}
                  {b.live_mode ? "" : " · SAMPLE mode"}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <div className="text-xs font-bold mb-1 flex items-center justify-between"
                 style={{ color: colors.muted }}>
              <span>Payee</span>
              <button onClick={() => setShowNewPayee(true)}
                      className="text-[10px] font-bold px-2 py-0.5 rounded"
                      style={{ backgroundColor: colors.brandTertiary,
                               color: colors.brand }}
                      data-testid="check-new-add-payee">
                + New payee
              </button>
            </div>
            <select value={f.payee_id}
                    onChange={(e) => setF({ ...f, payee_id: e.target.value })}
                    className="w-full p-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.background,
                             border: `1px solid ${colors.border}` }}
                    data-testid="check-new-payee">
              <option value="">Select…</option>
              {payees.map((p) => (
                <option key={p.id} value={p.id}>{p.name} ({p.kind})</option>
              ))}
            </select>
          </label>
          <label className="block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Amount ($)</div>
            <input type="number" step="0.01" value={f.amount}
                   onChange={(e) => setF({ ...f, amount: e.target.value })}
                   className="w-full p-2 rounded-lg text-lg font-mono font-bold"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid="check-new-amount" />
          </label>
          <label className="block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Date</div>
            <input type="date" value={f.date}
                   onChange={(e) => setF({ ...f, date: e.target.value })}
                   className="w-full p-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid="check-new-date" />
          </label>
          <label className="col-span-1 md:col-span-2 block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Amount in words (preview)</div>
            <div className="w-full p-2 rounded-lg text-sm italic"
                 style={{ backgroundColor: colors.background,
                          border: `1px dashed ${colors.border}`,
                          color: wordsPreview ? colors.onSurface : colors.muted }}
                 data-testid="check-new-wordspreview">
              {wordsPreview || "Enter amount above"}
            </div>
          </label>
          <label className="block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Category (optional)</div>
            <input value={f.category}
                   onChange={(e) => setF({ ...f, category: e.target.value })}
                   placeholder="supplies, payroll, refund…"
                   className="w-full p-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid="check-new-category" />
          </label>
          <label className="block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Type</div>
            <select value={f.ref_type || ""}
                    onChange={(e) => setF({ ...f, ref_type: e.target.value })}
                    className="w-full p-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.background,
                             border: `1px solid ${colors.border}` }}
                    data-testid="check-new-reftype">
              <option value="manual">Manual</option>
              <option value="invoice">Invoice pay</option>
              <option value="payroll">Payroll</option>
              <option value="refund">Refund</option>
            </select>
          </label>
          <label className="col-span-1 md:col-span-2 block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Memo (optional)</div>
            <input value={f.memo}
                   onChange={(e) => setF({ ...f, memo: e.target.value })}
                   className="w-full p-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid="check-new-memo" />
          </label>
        </div>
        {err ? (
          <div className="mt-3 text-xs" style={{ color: "#DC2626" }}>{err}</div>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={() => nav("/admin/checks")}
                  className="px-4 py-2 text-sm font-bold rounded-xl"
                  style={{ backgroundColor: colors.background,
                           border: `1px solid ${colors.border}`,
                           color: colors.onSurface }}
                  data-testid="check-new-cancel">
            Cancel
          </button>
          <button onClick={save} disabled={saving}
                  className="px-4 py-2 text-sm font-bold rounded-xl"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="check-new-save">
            {saving ? "Saving…" : "Save draft"}
          </button>
        </div>
      </div>

      {showNewPayee ? (
        <NewPayeeModal
          onClose={() => setShowNewPayee(false)}
          onCreated={async (p) => {
            const r = await api.get("/checks/payees");
            setPayees(r.items || []);
            setF({ ...f, payee_id: p.id });
            setShowNewPayee(false);
          }} />
      ) : null}
    </div>
  );
}

function NewPayeeModal({ onClose, onCreated }) {
  const [f, setF] = useState({ name: "", kind: "vendor",
                                  email: "", phone: "", address: "" });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    if (!f.name.trim()) { setErr("Name required"); return; }
    setSaving(true); setErr("");
    try {
      const r = await api.post("/checks/payees", f);
      onCreated(r);
    } catch (e) { setErr(e.message || "Failed"); }
    finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
         style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
         data-testid="check-newpayee-modal">
      <div className="rounded-2xl w-full max-w-md p-5"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <h2 className="text-lg font-bold mb-4"
            style={{ color: colors.onSurface }}>New payee</h2>
        <div className="grid grid-cols-1 gap-3">
          <input value={f.name}
                 onChange={(e) => setF({ ...f, name: e.target.value })}
                 placeholder="Name"
                 className="w-full p-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.background,
                          border: `1px solid ${colors.border}` }}
                 data-testid="check-newpayee-name" />
          <select value={f.kind}
                  onChange={(e) => setF({ ...f, kind: e.target.value })}
                  className="w-full p-2 rounded-lg text-sm"
                  style={{ backgroundColor: colors.background,
                           border: `1px solid ${colors.border}` }}
                  data-testid="check-newpayee-kind">
            <option value="vendor">Vendor</option>
            <option value="employee">Employee</option>
            <option value="customer">Customer</option>
            <option value="other">Other</option>
          </select>
          <input value={f.email}
                 onChange={(e) => setF({ ...f, email: e.target.value })}
                 placeholder="Email (optional)"
                 className="w-full p-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.background,
                          border: `1px solid ${colors.border}` }} />
        </div>
        {err ? (
          <div className="mt-3 text-xs" style={{ color: "#DC2626" }}>{err}</div>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose}
                  className="px-4 py-2 text-sm font-bold rounded-xl"
                  style={{ backgroundColor: colors.background,
                           border: `1px solid ${colors.border}`,
                           color: colors.onSurface }}
                  data-testid="check-newpayee-cancel">
            Cancel
          </button>
          <button onClick={save} disabled={saving}
                  className="px-4 py-2 text-sm font-bold rounded-xl"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="check-newpayee-save">
            {saving ? "Saving…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ─── Client-side amount-to-words (matches server exactly). ─────────── */
const _ONES = ["", "one", "two", "three", "four", "five", "six", "seven",
                "eight", "nine", "ten", "eleven", "twelve", "thirteen",
                "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
                "nineteen"];
const _TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty",
                "seventy", "eighty", "ninety"];
function _ut(n) {
  if (n === 0) return "";
  if (n < 20) return _ONES[n];
  if (n < 100) return _TENS[Math.floor(n / 10)]
    + (n % 10 ? "-" + _ONES[n % 10] : "");
  return _ONES[Math.floor(n / 100)] + " hundred"
    + (n % 100 ? " " + _ut(n % 100) : "");
}
function _itw(n) {
  if (n === 0) return "zero";
  const parts = [];
  if (n >= 1_000_000) { parts.push(_ut(Math.floor(n / 1_000_000)) + " million"); n = n % 1_000_000; }
  if (n >= 1_000)     { parts.push(_ut(Math.floor(n / 1_000)) + " thousand"); n = n % 1_000; }
  if (n > 0)          { parts.push(_ut(n)); }
  return parts.filter(Boolean).join(" ");
}
function clientAmountToWords(amount) {
  const a = Math.abs(Math.round(amount * 100) / 100);
  let whole = Math.floor(a);
  let cents = Math.round((a - whole) * 100);
  if (cents === 100) { whole += 1; cents = 0; }
  const words = _itw(whole);
  return words.charAt(0).toUpperCase() + words.slice(1)
    + ` and ${String(cents).padStart(2, "0")}/100 dollars`;
}

/* ═════════ DETAIL ═════════════════════════════════════════════════════ */
export function CheckDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [c, setC] = useState(null);
  const [banks, setBanks] = useState([]);
  const [payees, setPayees] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [voidOpen, setVoidOpen] = useState(false);
  const [voidReason, setVoidReason] = useState("");

  const load = useCallback(async () => {
    const [cc, bb, pp] = await Promise.all([
      api.get(`/checks/checks/${id}`),
      api.get("/checks/bank-accounts"),
      api.get("/checks/payees"),
    ]);
    setC(cc); setBanks(bb.items || []); setPayees(pp.items || []);
  }, [id]);
  useEffect(() => { load(); }, [load]);

  if (!c) return <div className="p-6 text-sm"
                        style={{ color: colors.muted }}>Loading…</div>;

  const ba = banks.find((b) => b.id === c.bank_account_id);
  const payee = payees.find((p) => p.id === c.payee_id);

  const printCheck = async () => {
    setBusy(true); setMsg("");
    try {
      await api.post(`/checks/checks/${id}/print`);
      window.open(`${window.location.origin}/api/checks/${id}/pdf`,
                   "_blank");
      await load();
    } catch (e) { setMsg(e.message); }
    finally { setBusy(false); }
  };
  const voidIt = async () => {
    setBusy(true); setMsg("");
    try {
      await api.post(`/checks/checks/${id}/void`,
                       { reason: voidReason || "voided by admin" });
      setVoidOpen(false); setVoidReason("");
      await load();
    } catch (e) { setMsg(e.message); }
    finally { setBusy(false); }
  };
  const clearIt = async () => {
    setBusy(true); setMsg("");
    try {
      await api.post(`/checks/checks/${id}/mark-cleared`, {});
      await load();
    } catch (e) { setMsg(e.message); }
    finally { setBusy(false); }
  };
  const unclearIt = async () => {
    setBusy(true); setMsg("");
    try {
      await api.post(`/checks/checks/${id}/mark-uncleared`, {});
      await load();
    } catch (e) { setMsg(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6" data-testid="check-detail">
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <button onClick={() => nav("/admin/checks")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="check-detail-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-[200px]">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <FileText size={22} style={{ color: colors.brand }} />
            Check #{c.check_number}
            {statusPill(c.status)}
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            {c.date} · {payee?.name || c.payee_name_snapshot} · {ba?.nickname}
          </p>
        </div>
        {c.status !== "voided" ? (
          <>
            <button onClick={printCheck} disabled={busy}
                    className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                    style={{ backgroundColor: colors.brand, color: "#fff" }}
                    data-testid="check-print-btn">
              <Printer size={14} /> {c.status === "draft" ? "Print" : "Reprint"}
            </button>
            {c.status !== "cleared" ? (
              <button onClick={clearIt} disabled={busy}
                      className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                      style={{ backgroundColor: "#059669", color: "#fff" }}
                      data-testid="check-clear-btn">
                <CheckCircle2 size={14} /> Mark cleared
              </button>
            ) : (
              <button onClick={unclearIt} disabled={busy}
                      className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                      style={{ backgroundColor: colors.surface,
                               color: colors.onSurface,
                               border: `1px solid ${colors.border}` }}
                      data-testid="check-unclear-btn">
                <RotateCcw size={14} /> Unclear
              </button>
            )}
            <button onClick={() => setVoidOpen(true)} disabled={busy}
                    className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                    style={{ backgroundColor: colors.surface,
                             color: "#DC2626",
                             border: `1px solid #DC2626` }}
                    data-testid="check-void-btn">
              <Ban size={14} /> Void
            </button>
          </>
        ) : null}
      </div>

      {msg ? (
        <div className="rounded-xl p-3 mb-4 text-sm"
             style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}>
          {msg}
        </div>
      ) : null}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
        {[
          ["Amount", `$${Number(c.amount).toFixed(2)}`, colors.brand],
          ["Bank", `${ba?.bank_name || "?"} · ****${ba?.account_number_last4 || ""}`, colors.onSurface],
          ["Category", c.category || "—", colors.onSurface],
        ].map(([l, v, cc], i) => (
          <div key={i} className="rounded-2xl p-4"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}>
            <div className="text-[10px] font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>{l}</div>
            <div className="text-lg font-bold mt-1"
                 style={{ color: cc }}>{v}</div>
          </div>
        ))}
      </div>

      <div className="rounded-2xl p-5 mb-6"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <h2 className="text-lg font-bold mb-3"
            style={{ color: colors.onSurface }}>
          Amount in words
        </h2>
        <div className="p-3 rounded-lg italic"
             style={{ backgroundColor: colors.background,
                      color: colors.onSurface,
                      border: `1px dashed ${colors.border}` }}
             data-testid="check-detail-words">
          {c.amount_in_words}
        </div>
      </div>

      <div className="rounded-2xl p-5"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <h2 className="text-lg font-bold mb-3"
            style={{ color: colors.onSurface }}>
          Details
        </h2>
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          {[
            ["Memo", c.memo || "—"],
            ["Date", c.date],
            ["Created", (c.created_at || "").slice(0, 19).replace("T", " ")],
            ["Printed at", (c.printed_at || "—").slice(0, 19).replace("T", " ")],
            ["Cleared at", (c.cleared_at || "—").slice(0, 19).replace("T", " ")],
            ["Voided at", (c.voided_at || "—").slice(0, 19).replace("T", " ")],
            ["Void reason", c.void_reason || "—"],
            ["Ref", `${c.ref_type || "—"}${c.ref_id ? ` · ${c.ref_id.slice(0, 8)}` : ""}`],
          ].map(([k, v], i) => (
            <div key={i}>
              <div className="text-[10px] font-bold uppercase tracking-wider"
                   style={{ color: colors.muted }}>{k}</div>
              <div style={{ color: colors.onSurface }}>{v}</div>
            </div>
          ))}
        </dl>
        {c.pdf_url ? (
          <div className="mt-4">
            <a href={c.pdf_url} target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-1 px-3 py-2 text-sm font-bold rounded-xl"
               style={{ backgroundColor: colors.background,
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
               data-testid="check-detail-pdf">
              <FileText size={14} /> Open PDF
            </a>
          </div>
        ) : null}
      </div>

      {voidOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
             data-testid="check-void-modal">
          <div className="rounded-2xl w-full max-w-md p-5"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}>
            <h2 className="text-lg font-bold mb-3 flex items-center gap-2"
                style={{ color: "#DC2626" }}>
              <AlertTriangle size={18} /> Void check #{c.check_number}?
            </h2>
            <p className="text-xs mb-3" style={{ color: colors.muted }}>
              Voided checks stay in the register with strikethrough but do not
              affect the bank balance. This cannot be reversed.
            </p>
            <input value={voidReason}
                   onChange={(e) => setVoidReason(e.target.value)}
                   placeholder="Reason (required for records)"
                   className="w-full p-2 rounded-lg text-sm mb-4"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid="check-void-reason" />
            <div className="flex justify-end gap-2">
              <button onClick={() => setVoidOpen(false)}
                      className="px-4 py-2 text-sm font-bold rounded-xl"
                      style={{ backgroundColor: colors.background,
                               border: `1px solid ${colors.border}`,
                               color: colors.onSurface }}
                      data-testid="check-void-cancel">
                Cancel
              </button>
              <button onClick={voidIt} disabled={busy}
                      className="px-4 py-2 text-sm font-bold rounded-xl"
                      style={{ backgroundColor: "#DC2626", color: "#fff" }}
                      data-testid="check-void-confirm">
                Confirm void
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ═════════ BANK ACCOUNTS ══════════════════════════════════════════════ */
export function CheckBanks() {
  const nav = useNavigate();
  const [banks, setBanks] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/checks/bank-accounts");
      setBanks(r.items || []);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const toggleLive = async (b) => {
    if (!b.live_mode) {
      if (!(await mustConfirm({
        title: `Enable LIVE mode for ${b.nickname}?`,
        description:
          "This removes the SAMPLE watermark from printed checks. Only enable " +
          "if you have Reg-CC-compliant MICR-encoded blank stock loaded. Continue?",
        confirmText: "Enable LIVE",
        tone: "danger",
      }))) return;
    }
    await api.patch(`/checks/bank-accounts/${b.id}`,
                     { live_mode: !b.live_mode });
    await load();
  };
  const del = async (b) => {
    if (!(await mustConfirm({ title: `Delete bank account "${b.nickname}"?`, tone: "danger" }))) return;
    try {
      await api.delete(`/checks/bank-accounts/${b.id}`);
      await load();
    } catch (e) { await mustAlert({ title: e.message || "Failed" }); }
  };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="check-banks">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin/checks")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="check-banks-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <Landmark size={22} style={{ color: colors.brand }} />
            Bank accounts
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Account numbers are stored encrypted and only shown as the last
            four digits.
          </p>
        </div>
        <button onClick={() => setShowNew(true)}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="check-bank-new-btn">
          <Plus size={14} /> New account
        </button>
      </div>

      {loading ? (
        <div className="p-8 text-center text-sm"
             style={{ color: colors.muted }}>Loading…</div>
      ) : banks.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          No bank accounts configured yet.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {banks.map((b) => (
            <div key={b.id} className="rounded-2xl p-4"
                 style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                 data-testid={`check-bank-card-${b.id}`}>
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="font-bold text-lg"
                       style={{ color: colors.onSurface }}>{b.nickname}</div>
                  <div className="text-xs"
                       style={{ color: colors.muted }}>
                    {b.bank_name} · ****{b.account_number_last4}
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold"
                      style={{ backgroundColor:
                                 b.live_mode ? "#05966915" : "#F59E0B15",
                               color: b.live_mode ? "#059669" : "#F59E0B" }}
                      data-testid={`check-bank-livepill-${b.id}`}>
                  {b.live_mode ? "LIVE" : "SAMPLE"}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 mb-3">
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider"
                       style={{ color: colors.muted }}>Next check</div>
                  <div className="font-mono font-bold"
                       style={{ color: colors.onSurface }}>
                    #{b.next_check_number}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider"
                       style={{ color: colors.muted }}>Balance</div>
                  <div className="font-bold"
                       style={{ color: b.current_balance < 0
                                  ? "#DC2626" : colors.brand }}>
                    ${Number(b.current_balance).toFixed(2)}
                  </div>
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => toggleLive(b)}
                        className="flex-1 px-3 py-2 text-xs font-bold rounded-xl"
                        style={{ backgroundColor:
                                   b.live_mode ? colors.background : "#059669",
                                 color: b.live_mode ? colors.onSurface : "#fff",
                                 border: `1px solid ${
                                   b.live_mode ? colors.border : "#059669"}` }}
                        data-testid={`check-bank-live-btn-${b.id}`}>
                  {b.live_mode ? "Disable LIVE" : "Enable LIVE"}
                </button>
                <Gate perm="Settings" action="write">
                  <button onClick={() => del(b)}
                        className="p-2 rounded-xl"
                        style={{ backgroundColor: colors.background,
                                 border: `1px solid #DC2626`,
                                 color: "#DC2626" }}
                        data-testid={`check-bank-delete-${b.id}`}>
                    <Trash2 size={14} />
                  </button>
                </Gate>
              </div>
            </div>
          ))}
        </div>
      )}

      {showNew ? (
        <NewBankModal onClose={() => setShowNew(false)}
                       onCreated={() => { setShowNew(false); load(); }} />
      ) : null}
    </div>
  );
}

function NewBankModal({ onClose, onCreated }) {
  const [f, setF] = useState({
    nickname: "", bank_name: "", routing_number: "",
    account_number: "", next_check_number: 1001,
    starting_balance: 0, signature_image_url: "", live_mode: false,
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    if (!/^\d{9}$/.test(f.routing_number)) {
      setErr("Routing number must be exactly 9 digits"); return;
    }
    if (!/^\d{4,17}$/.test(f.account_number)) {
      setErr("Account number must be 4–17 digits"); return;
    }
    setSaving(true); setErr("");
    try {
      await api.post("/checks/bank-accounts", {
        ...f, next_check_number: Number(f.next_check_number),
        starting_balance: Number(f.starting_balance),
      });
      onCreated();
    } catch (e) { setErr(e.message || "Failed"); }
    finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
         style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
         data-testid="check-newbank-modal">
      <div className="rounded-2xl w-full max-w-lg p-5 max-h-[90vh] overflow-auto"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <h2 className="text-lg font-bold mb-4"
            style={{ color: colors.onSurface }}>New bank account</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {[
            ["nickname", "Nickname", "text", "Ops checking"],
            ["bank_name", "Bank name", "text", "First National"],
            ["routing_number", "Routing (9 digits)", "text", "123456789"],
            ["account_number", "Account number", "text", "9876543210"],
            ["next_check_number", "Next check number", "number", 1001],
            ["starting_balance", "Starting balance ($)", "number", 0],
          ].map(([k, l, t, p]) => (
            <label key={k} className={k === "nickname" || k === "bank_name"
                                        ? "col-span-1 md:col-span-2 block"
                                        : "block"}>
              <div className="text-xs font-bold mb-1"
                   style={{ color: colors.muted }}>{l}</div>
              <input type={t} value={f[k]}
                     onChange={(e) => setF({ ...f, [k]: e.target.value })}
                     placeholder={String(p)}
                     className="w-full p-2 rounded-lg text-sm font-mono"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}` }}
                     data-testid={`check-newbank-${k}`} />
            </label>
          ))}
        </div>
        <div className="mt-3 text-xs p-2 rounded-lg"
             style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}>
          <b>Safety default:</b> new accounts start in SAMPLE mode. Enable LIVE
          only when you have Reg-CC-compliant MICR-encoded blank stock loaded.
        </div>
        {err ? (
          <div className="mt-3 text-xs" style={{ color: "#DC2626" }}>{err}</div>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose}
                  className="px-4 py-2 text-sm font-bold rounded-xl"
                  style={{ backgroundColor: colors.background,
                           border: `1px solid ${colors.border}`,
                           color: colors.onSurface }}
                  data-testid="check-newbank-cancel">
            Cancel
          </button>
          <button onClick={save} disabled={saving}
                  className="px-4 py-2 text-sm font-bold rounded-xl"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="check-newbank-save">
            {saving ? "Saving…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═════════ PAYEES ═════════════════════════════════════════════════════ */
export function CheckPayees() {
  const nav = useNavigate();
  const [payees, setPayees] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const [typeFilter, setTypeFilter] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = typeFilter ? `?type=${typeFilter}` : "";
      const r = await api.get(`/checks/payees${q}`);
      setPayees(r.items || []);
    } finally { setLoading(false); }
  }, [typeFilter]);
  useEffect(() => { load(); }, [load]);

  const del = async (p) => {
    if (!(await mustConfirm({ title: `Delete payee "${p.name}"?`, tone: "danger" }))) return;
    try {
      await api.delete(`/checks/payees/${p.id}`);
      await load();
    } catch (e) { await mustAlert({ title: e.message || "Failed" }); }
  };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="check-payees">
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <button onClick={() => nav("/admin/checks")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="check-payees-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <Users size={22} style={{ color: colors.brand }} />
            Payees
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Vendors, employees, customers, and other payables in one list.
          </p>
        </div>
        <select value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="px-3 py-2 text-sm rounded-xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="check-payees-filter">
          <option value="">All types</option>
          <option value="vendor">Vendor</option>
          <option value="employee">Employee</option>
          <option value="customer">Customer</option>
          <option value="other">Other</option>
        </select>
        <button onClick={() => setShowNew(true)}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="check-payees-new-btn">
          <Plus size={14} /> New payee
        </button>
      </div>

      {loading ? (
        <div className="p-8 text-center text-sm"
             style={{ color: colors.muted }}>Loading…</div>
      ) : payees.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          No payees yet.
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: "#F1F5F9" }}>
              <tr>
                <th className="p-2 text-left">Name</th>
                <th className="p-2 text-left">Kind</th>
                <th className="p-2 text-left">Email</th>
                <th className="p-2 text-left">Phone</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {payees.map((p) => (
                <tr key={p.id}
                    style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`check-payee-row-${p.id}`}>
                  <td className="p-2 font-bold"
                      style={{ color: colors.onSurface }}>{p.name}</td>
                  <td className="p-2 text-xs" style={{ color: colors.muted }}>
                    {p.kind}
                  </td>
                  <td className="p-2 text-xs" style={{ color: colors.muted }}>
                    {p.email || "—"}
                  </td>
                  <td className="p-2 text-xs" style={{ color: colors.muted }}>
                    {p.phone || "—"}
                  </td>
                  <td className="p-2 text-right">
                    <Gate perm="Settings" action="write">
                      <button onClick={() => del(p)}
                            className="p-1 rounded"
                            style={{ backgroundColor: colors.background,
                                     border: `1px solid #DC2626`,
                                     color: "#DC2626" }}
                            data-testid={`check-payee-del-${p.id}`}>
                        <Trash2 size={12} />
                      </button>
                    </Gate>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showNew ? (
        <NewPayeeModal onClose={() => setShowNew(false)}
                        onCreated={() => { setShowNew(false); load(); }} />
      ) : null}
    </div>
  );
}

/* ═════════ ANALYTICS ══════════════════════════════════════════════════ */
export function CheckAnalytics() {
  const nav = useNavigate();
  const [a, setA] = useState(null);

  useEffect(() => { api.get("/checks/analytics").then(setA); }, []);

  if (!a) return <div className="p-6 text-sm"
                        style={{ color: colors.muted }}>Loading…</div>;

  const monthMax = Math.max(...(a.monthly_series || []).map((m) => m.amount), 1);
  const catMax = Math.max(...(a.category_breakdown || []).map((c) => c.amount), 1);

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6"
         data-testid="check-analytics">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin/checks")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="check-analytics-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <BarChart3 size={22} style={{ color: colors.brand }} />
            Check writer · analytics
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Totals, category breakdown, and monthly spend.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {[
          ["Total written", `$${a.total_written.toFixed(0)}`, colors.brand],
          ["Total cleared", `$${a.total_cleared.toFixed(0)}`, "#059669"],
          ["Pending", `$${a.total_pending.toFixed(0)}`, "#F59E0B"],
          ["Voided", `$${a.total_voided.toFixed(0)}`, "#DC2626"],
        ].map(([l, v, c], i) => (
          <div key={i} className="rounded-2xl p-4"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid={`check-analytics-kpi-${i}`}>
            <div className="text-[10px] font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>{l}</div>
            <div className="text-2xl font-bold mt-1"
                 style={{ color: c }}>{v}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-2xl p-5"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <h2 className="text-lg font-bold mb-3"
              style={{ color: colors.onSurface }}>
            Spend by category
          </h2>
          {(a.category_breakdown || []).length === 0 ? (
            <div className="text-xs text-center py-6"
                 style={{ color: colors.muted }}>
              No spending yet.
            </div>
          ) : (
            <div className="space-y-2">
              {a.category_breakdown.map((c) => (
                <div key={c.category}
                     data-testid={`check-analytics-cat-${c.category}`}>
                  <div className="flex justify-between text-sm mb-1">
                    <span style={{ color: colors.onSurface }}>{c.category}</span>
                    <span className="font-bold"
                          style={{ color: colors.onSurface }}>
                      ${c.amount.toFixed(0)}
                    </span>
                  </div>
                  <div className="h-4 rounded-lg overflow-hidden"
                       style={{ backgroundColor: "#F1F5F9" }}>
                    <div style={{ width: `${(c.amount / catMax) * 100}%`,
                                    height: "100%",
                                    backgroundColor: colors.brand }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-2xl p-5"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <h2 className="text-lg font-bold mb-3"
              style={{ color: colors.onSurface }}>
            Monthly spend
          </h2>
          {(a.monthly_series || []).length === 0 ? (
            <div className="text-xs text-center py-6"
                 style={{ color: colors.muted }}>
              No monthly data yet.
            </div>
          ) : (
            <div className="space-y-2">
              {a.monthly_series.map((m) => (
                <div key={m.month}
                     data-testid={`check-analytics-month-${m.month}`}>
                  <div className="flex justify-between text-sm mb-1">
                    <span style={{ color: colors.onSurface }}>{m.month}</span>
                    <span className="font-bold"
                          style={{ color: colors.onSurface }}>
                      ${m.amount.toFixed(0)}
                    </span>
                  </div>
                  <div className="h-4 rounded-lg overflow-hidden"
                       style={{ backgroundColor: "#F1F5F9" }}>
                    <div style={{ width: `${(m.amount / monthMax) * 100}%`,
                                    height: "100%",
                                    backgroundColor: "#059669" }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
