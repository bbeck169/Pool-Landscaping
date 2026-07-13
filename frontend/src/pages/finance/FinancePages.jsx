import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, Download, Search, RefreshCw, Play, Plus, Trash2,
  Upload, FileDown, ExternalLink, Copy, Check,
} from "lucide-react";
import { api } from "@/api";
import { colors, money, brandGradient } from "@/theme";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";

function Card({ children, className = "", testId }) {
  return (
    <div
      className={`rounded-2xl ${className}`}
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid={testId}
    >
      {children}
    </div>
  );
}

function Header({ title, subtitle, right }) {
  const nav = useNavigate();
  return (
    <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
      <div className="flex items-center gap-3">
        <button onClick={() => nav(-1)}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="back-btn">
          <ArrowLeft size={16} />
        </button>
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>{title}</h1>
          {subtitle ? <p className="text-xs mt-0.5" style={{ color: colors.muted }}>{subtitle}</p> : null}
        </div>
      </div>
      {right}
    </div>
  );
}

function Toast({ msg, onDone }) {
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(onDone, 3000);
    return () => clearTimeout(t);
  }, [msg, onDone]);
  if (!msg) return null;
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-xl text-sm font-semibold shadow-lg"
         style={{ backgroundColor: colors.onSurface, color: "#fff" }}
         data-testid="finance-toast">
      {msg}
    </div>
  );
}

function downloadFile(name, content, mime = "text/csv") {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  URL.revokeObjectURL(url);
}

// ─── /payments — payments ledger ─────────────────────────────────────────────
export function PaymentsLedger() {
  const { start, end } = useDateRange("this-month");
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [totalAmount, setTotalAmount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [method, setMethod] = useState("all");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const [toast, setToast] = useState("");

  const load = () => {
    setLoading(true);
    const p = new URLSearchParams();
    if (start) p.set("start", start);
    if (end) p.set("end", end);
    if (method && method !== "all") p.set("method", method);
    if (status) p.set("status", status);
    p.set("page", page); p.set("page_size", pageSize);
    api.get(`/payments/list?${p.toString()}`)
      .then((r) => {
        setRows(r.rows || []); setTotal(r.total || 0);
        setTotalAmount(r.total_amount || 0); setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  useEffect(load, [start, end, method, status, page]);

  const filtered = useMemo(
    () => rows.filter((r) => !q || (r.customer_name + r.invoice_title).toLowerCase().includes(q.toLowerCase())),
    [rows, q]
  );

  const exportCsv = () => {
    const header = "Date,Customer,Invoice,Amount,Method,Status,Stripe PI";
    const body = filtered.map((r) => [
      (r.paid_at || r.created_at || "").slice(0, 10),
      `"${(r.customer_name || "").replace(/"/g, '""')}"`,
      `"${(r.invoice_title || "").replace(/"/g, '""')}"`,
      r.amount,
      r.method,
      r.status,
      r.stripe_pi_id || "",
    ].join(",")).join("\n");
    downloadFile("payments.csv", `${header}\n${body}`);
    setToast("Downloaded payments.csv");
  };

  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto" data-testid="payments-ledger-page">
      <Header title="Payments Ledger" subtitle="All received payments with filters + CSV export"
              right={<DateRangePicker />} />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <Card testId="payments-total-count" className="p-4">
          <div className="text-xs" style={{ color: colors.muted }}>Records</div>
          <div className="text-2xl font-bold" style={{ color: colors.onSurface }}>{total}</div>
        </Card>
        <Card testId="payments-total-amount" className="p-4">
          <div className="text-xs" style={{ color: colors.muted }}>Total collected</div>
          <div className="text-2xl font-bold" style={{ color: colors.brand }}>{money(totalAmount)}</div>
        </Card>
        <Card testId="payments-filter-method" className="p-4">
          <div className="text-xs mb-1" style={{ color: colors.muted }}>Method</div>
          <select value={method} onChange={(e) => { setMethod(e.target.value); setPage(1); }}
                  className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                  style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid="method-select">
            <option value="all">All methods</option>
            <option>Card</option><option>Stripe</option><option>Venmo</option>
            <option>Zelle</option><option>Cash</option><option>Check</option>
          </select>
        </Card>
        <Card testId="payments-filter-status" className="p-4">
          <div className="text-xs mb-1" style={{ color: colors.muted }}>Status</div>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}
                  className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                  style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid="status-select">
            <option value="">All statuses</option>
            <option value="paid">Paid</option>
            <option value="processing">Processing</option>
            <option value="partial">Partial</option>
          </select>
        </Card>
      </div>

      <Card>
        <div className="flex items-center justify-between p-4 gap-2 flex-wrap"
             style={{ borderBottom: `1px solid ${colors.border}` }}>
          <div className="flex items-center gap-2 flex-1 min-w-[220px]">
            <Search size={14} style={{ color: colors.muted }} />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search customer or invoice…"
                   className="flex-1 px-2 py-1.5 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                   data-testid="payments-search" />
          </div>
          <button onClick={exportCsv}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg hover:brightness-95"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="payments-export">
            <Download size={12} /> Export CSV
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                {["Date", "Customer", "Invoice", "Amount", "Method", "Status", "Stripe"].map((h) => (
                  <th key={h} className="text-left px-4 py-2.5 font-semibold text-xs uppercase tracking-wide"
                      style={{ color: colors.muted }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="py-10 text-center text-sm" style={{ color: colors.muted }}>Loading…</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={7} className="py-10 text-center text-sm" style={{ color: colors.muted }}>No payments</td></tr>
              ) : filtered.map((r, i) => (
                <tr key={r.id + i} style={{ borderTop: `1px solid ${colors.border}` }}>
                  <td className="px-4 py-2.5" style={{ color: colors.onSurface }}>
                    {(r.paid_at || r.created_at || "").slice(0, 10)}
                  </td>
                  <td className="px-4 py-2.5" style={{ color: colors.onSurface }}>{r.customer_name || "—"}</td>
                  <td className="px-4 py-2.5" style={{ color: colors.onSurface }}>
                    <a href={`/invoices/${r.id}`} className="hover:underline">{r.invoice_title || r.id.slice(0, 8)}</a>
                  </td>
                  <td className="px-4 py-2.5 font-semibold" style={{ color: colors.brand }}>{money(r.amount)}</td>
                  <td className="px-4 py-2.5" style={{ color: colors.onSurface }}>{r.method}</td>
                  <td className="px-4 py-2.5">
                    <span className="px-2 py-0.5 rounded-md text-xs font-semibold"
                          style={{
                            backgroundColor: r.status === "paid" ? "#DCFCE7" : "#DBEAFE",
                            color: r.status === "paid" ? "#16A34A" : "#1D4ED8",
                          }}>{r.status}</span>
                  </td>
                  <td className="px-4 py-2.5 text-xs" style={{ color: colors.muted }}>
                    {r.stripe_pi_id ? (
                      <a target="_blank" rel="noreferrer"
                         href={`https://dashboard.stripe.com/test/payments/${r.stripe_pi_id}`}
                         className="inline-flex items-center gap-1 hover:underline">
                        {r.stripe_pi_id.slice(0, 10)}… <ExternalLink size={10} />
                      </a>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {pageCount > 1 && (
          <div className="flex items-center justify-between p-4"
               style={{ borderTop: `1px solid ${colors.border}` }}>
            <span className="text-xs" style={{ color: colors.muted }}>Page {page} / {pageCount}</span>
            <div className="flex gap-2">
              <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}
                      className="px-3 py-1.5 text-xs font-semibold rounded-lg disabled:opacity-40"
                      style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}>
                Prev
              </button>
              <button disabled={page >= pageCount} onClick={() => setPage(p => p + 1)}
                      className="px-3 py-1.5 text-xs font-semibold rounded-lg disabled:opacity-40"
                      style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}>
                Next
              </button>
            </div>
          </div>
        )}
      </Card>

      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}

// ─── /auto-billing — recurring billing scheduler ─────────────────────────────
export function AutoBilling() {
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [confirmRun, setConfirmRun] = useState(false);
  const [running, setRunning] = useState(false);
  const [toast, setToast] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [customers, setCustomers] = useState([]);
  const [newPlan, setNewPlan] = useState({ customer_id: "", service: "Monthly Pool Service", frequency: "monthly", amount: 150, next_run: "" });

  const load = () => {
    setLoading(true);
    api.get("/billing-plans")
      .then((r) => { setPlans(Array.isArray(r) ? r : []); setLoading(false); })
      .catch(() => setLoading(false));
  };
  useEffect(load, []);

  useEffect(() => {
    if (!showNew) return;
    api.get("/customers").then((r) => setCustomers(Array.isArray(r) ? r : [])).catch(() => {});
  }, [showNew]);

  const nextRun = useMemo(() => {
    const active = plans.filter((p) => p.active !== false && p.next_run);
    if (!active.length) return null;
    return active.map((p) => p.next_run).sort()[0];
  }, [plans]);

  const runAll = async () => {
    setConfirmRun(false);
    setRunning(true);
    try {
      const res = await api.post("/billing-plans/run", {});
      setToast(`Fired ${res.fired ?? 0} plan(s). Invoices created.`);
      load();
    } catch (e) {
      setToast(e.message || "Run failed");
    } finally {
      setRunning(false);
    }
  };

  const toggleActive = async (p) => {
    try {
      await api.put(`/billing-plans/${p.id}`, { active: !(p.active !== false) });
      load();
    } catch (e) { setToast(e.message); }
  };

  const runOne = async (p) => {
    try {
      const r = await api.post(`/billing-plans/${p.id}/run`, {});
      setToast(`Invoice created (next run ${r.next_run})`);
      load();
    } catch (e) { setToast(e.message); }
  };

  const createPlan = async () => {
    try {
      await api.post("/billing-plans", newPlan);
      setShowNew(false);
      setNewPlan({ customer_id: "", service: "Monthly Pool Service", frequency: "monthly", amount: 150, next_run: "" });
      setToast("Plan created");
      load();
    } catch (e) { setToast(e.message); }
  };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="auto-billing-page">
      <Header title="Auto-Billing" subtitle="Recurring billing scheduler — chemical + monthly service plans"
              right={
                <div className="flex gap-2">
                  <button onClick={() => setShowNew(true)}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg"
                          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                          data-testid="new-plan-btn">
                    <Plus size={14} /> New plan
                  </button>
                  <button onClick={() => setConfirmRun(true)}
                          disabled={running}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg disabled:opacity-60"
                          style={{ backgroundColor: colors.brand, color: "#fff" }}
                          data-testid="run-all-btn">
                    <Play size={14} /> Run all due
                  </button>
                </div>
              } />

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-4">
        <Card className="p-4" testId="ab-next-run">
          <div className="text-xs" style={{ color: colors.muted }}>Next scheduled run</div>
          <div className="text-xl font-bold mt-1" style={{ color: colors.onSurface }}>
            {nextRun || "—"}
          </div>
        </Card>
        <Card className="p-4" testId="ab-active-count">
          <div className="text-xs" style={{ color: colors.muted }}>Active plans</div>
          <div className="text-xl font-bold mt-1" style={{ color: colors.onSurface }}>
            {plans.filter((p) => p.active !== false).length}
          </div>
        </Card>
        <Card className="p-4" testId="ab-mrr">
          <div className="text-xs" style={{ color: colors.muted }}>Est. monthly value</div>
          <div className="text-xl font-bold mt-1" style={{ color: colors.brand }}>
            {money(plans.filter((p) => p.active !== false).reduce((s, p) => s + (Number(p.amount) || 0), 0))}
          </div>
        </Card>
      </div>

      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                {["Customer", "Service", "Cadence", "Amount", "Last run", "Next run", "Active", ""].map((h) => (
                  <th key={h} className="text-left px-4 py-2.5 font-semibold text-xs uppercase tracking-wide"
                      style={{ color: colors.muted }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="py-10 text-center text-sm" style={{ color: colors.muted }}>Loading…</td></tr>
              ) : plans.length === 0 ? (
                <tr><td colSpan={8} className="py-10 text-center text-sm" style={{ color: colors.muted }}>No plans yet</td></tr>
              ) : plans.map((p) => {
                const active = p.active !== false;
                return (
                  <tr key={p.id} style={{ borderTop: `1px solid ${colors.border}` }}>
                    <td className="px-4 py-2.5" style={{ color: colors.onSurface }}>{p.customer_name || "—"}</td>
                    <td className="px-4 py-2.5" style={{ color: colors.onSurface }}>{p.service}</td>
                    <td className="px-4 py-2.5" style={{ color: colors.onSurface }}>{p.frequency}</td>
                    <td className="px-4 py-2.5 font-semibold" style={{ color: colors.brand }}>{money(p.amount)}</td>
                    <td className="px-4 py-2.5 text-xs" style={{ color: colors.muted }}>
                      {p.last_run ? p.last_run.slice(0, 10) : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-xs" style={{ color: colors.muted }}>
                      {p.next_run ? p.next_run.slice(0, 10) : "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      <button onClick={() => toggleActive(p)}
                              className="w-11 h-6 rounded-full relative transition"
                              style={{ backgroundColor: active ? colors.brand : colors.surfaceTertiary }}
                              data-testid={`toggle-${p.id}`}>
                        <span className="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all shadow"
                              style={{ left: active ? 22 : 2 }} />
                      </button>
                    </td>
                    <td className="px-4 py-2.5">
                      <button onClick={() => runOne(p)}
                              className="text-xs font-semibold px-2 py-1 rounded-lg hover:brightness-95"
                              style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                              data-testid={`run-${p.id}`}>
                        <Play size={11} className="inline mr-1" /> Run
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {confirmRun && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ backgroundColor: "rgba(0,0,0,0.4)" }}
             onClick={() => setConfirmRun(false)}>
          <div className="rounded-2xl p-6 max-w-md w-full"
               style={{ backgroundColor: colors.surface }}
               onClick={(e) => e.stopPropagation()}
               data-testid="run-confirm-modal">
            <h3 className="text-lg font-bold mb-2" style={{ color: colors.onSurface }}>
              Run all due plans?
            </h3>
            <p className="text-sm mb-4" style={{ color: colors.muted }}>
              This will create invoices for every active plan whose next-run date is today or earlier and advance each schedule. Customers are notified.
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setConfirmRun(false)}
                      className="px-4 py-2 rounded-lg text-sm font-semibold"
                      style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                      data-testid="cancel-run">
                Cancel
              </button>
              <button onClick={runAll}
                      className="px-4 py-2 rounded-lg text-sm font-semibold"
                      style={{ backgroundColor: colors.brand, color: "#fff" }}
                      data-testid="confirm-run">
                <Play size={12} className="inline mr-1" /> Run now
              </button>
            </div>
          </div>
        </div>
      )}

      {showNew && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ backgroundColor: "rgba(0,0,0,0.4)" }}
             onClick={() => setShowNew(false)}>
          <div className="rounded-2xl p-6 max-w-md w-full space-y-3"
               style={{ backgroundColor: colors.surface }}
               onClick={(e) => e.stopPropagation()}
               data-testid="new-plan-modal">
            <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>New billing plan</h3>
            <select value={newPlan.customer_id}
                    onChange={(e) => setNewPlan({ ...newPlan, customer_id: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                    data-testid="new-plan-customer">
              <option value="">Select customer…</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <input value={newPlan.service}
                   onChange={(e) => setNewPlan({ ...newPlan, service: e.target.value })}
                   className="w-full px-3 py-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                   placeholder="Service"
                   data-testid="new-plan-service" />
            <div className="grid grid-cols-2 gap-2">
              <select value={newPlan.frequency}
                      onChange={(e) => setNewPlan({ ...newPlan, frequency: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg text-sm"
                      style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="new-plan-freq">
                <option>weekly</option><option>monthly</option><option>quarterly</option>
              </select>
              <input type="number" value={newPlan.amount}
                     onChange={(e) => setNewPlan({ ...newPlan, amount: parseFloat(e.target.value) || 0 })}
                     className="w-full px-3 py-2 rounded-lg text-sm"
                     style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                     placeholder="Amount"
                     data-testid="new-plan-amount" />
            </div>
            <input type="date" value={newPlan.next_run}
                   onChange={(e) => setNewPlan({ ...newPlan, next_run: e.target.value })}
                   className="w-full px-3 py-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                   data-testid="new-plan-next-run" />
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowNew(false)}
                      className="px-4 py-2 rounded-lg text-sm font-semibold"
                      style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}>
                Cancel
              </button>
              <button onClick={createPlan}
                      disabled={!newPlan.customer_id}
                      className="px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-60"
                      style={{ backgroundColor: colors.brand, color: "#fff" }}
                      data-testid="create-plan-btn">
                Create
              </button>
            </div>
          </div>
        </div>
      )}

      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}

// ─── /impexp — Import / Export center ────────────────────────────────────────
const ENTITY_CFG = {
  customers: {
    label: "Customers",
    exportPath: "/export/customers",
    importPath: "/import/customers",
    template: "name,email,phone,address,billing_address,gate_code,notes\nJane Doe,jane@example.com,555-0100,123 Main St,,,VIP client",
    canImport: true,
  },
  items: {
    label: "Items (Price book)",
    exportPath: "/export/items",
    importPath: "/import/items",
    template: "name,category,unit,unit_price,taxable\nMonthly Service,Pool,each,150,true",
    canImport: true,
  },
  jobs: {
    label: "Jobs",
    exportPath: "/export/jobs",
    importPath: null,
    template: null,
    canImport: false,
  },
  invoices: {
    label: "Invoices",
    exportPath: "/export/invoices",
    importPath: null,
    template: null,
    canImport: false,
  },
};

export function ImpExp() {
  const [tab, setTab] = useState("import");
  const [entity, setEntity] = useState("customers");
  const [csvText, setCsvText] = useState("");
  const [fileName, setFileName] = useState("");
  const [result, setResult] = useState(null);
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const [exportStart, setExportStart] = useState("");
  const [exportEnd, setExportEnd] = useState("");
  const cfg = ENTITY_CFG[entity];

  const doExport = async () => {
    setBusy(true);
    try {
      const params = new URLSearchParams();
      if (exportStart) params.set("start", exportStart);
      if (exportEnd) params.set("end", exportEnd);
      const q = params.toString();
      const r = await api.get(`${cfg.exportPath}${q ? `?${q}` : ""}`);
      downloadFile(r.filename, r.content);
      setToast(`Exported ${r.count} ${cfg.label.toLowerCase()}`);
    } catch (e) { setToast(e.message); }
    finally { setBusy(false); }
  };

  const onFile = (f) => {
    if (!f) return;
    setFileName(f.name);
    const rd = new FileReader();
    rd.onload = () => setCsvText(String(rd.result || ""));
    rd.readAsText(f);
  };

  const doImport = async () => {
    if (!cfg.canImport || !csvText.trim()) {
      setToast("Paste or upload a CSV first");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post(cfg.importPath, { csv: csvText });
      setResult(r);
      setToast(`Import complete · ${r.created} new · ${r.updated} updated`);
    } catch (e) { setToast(e.message); }
    finally { setBusy(false); }
  };

  const dlTemplate = () => {
    if (!cfg.template) return;
    downloadFile(`${entity}-template.csv`, cfg.template);
  };

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto" data-testid="impexp-page">
      <Header title="Import · Export" subtitle="Bulk data in and out of the CRM" />

      <div className="flex gap-2 mb-4 rounded-xl p-1"
           style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, width: "fit-content" }}>
        {[
          { key: "import", label: "Import", icon: Upload },
          { key: "export", label: "Export", icon: FileDown },
        ].map((t) => {
          const Ic = t.icon;
          return (
            <button key={t.key} onClick={() => setTab(t.key)}
                    className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-semibold transition"
                    style={{
                      backgroundColor: tab === t.key ? colors.surface : "transparent",
                      color: tab === t.key ? colors.brand : colors.muted,
                      boxShadow: tab === t.key ? "0 1px 2px rgba(0,0,0,0.04)" : "none",
                    }}
                    data-testid={`impexp-tab-${t.key}`}>
              <Ic size={14} /> {t.label}
            </button>
          );
        })}
      </div>

      <Card className="p-5">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-5">
          <label className="md:col-span-1">
            <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Entity</div>
            <select value={entity} onChange={(e) => { setEntity(e.target.value); setResult(null); setCsvText(""); setFileName(""); }}
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                    data-testid="impexp-entity">
              {Object.entries(ENTITY_CFG).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
          </label>
          {tab === "export" && (
            <>
              <label>
                <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Start (optional)</div>
                <input type="date" value={exportStart} onChange={(e) => setExportStart(e.target.value)}
                       className="w-full px-3 py-2 rounded-lg text-sm"
                       style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                       data-testid="export-start" />
              </label>
              <label>
                <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>End (optional)</div>
                <input type="date" value={exportEnd} onChange={(e) => setExportEnd(e.target.value)}
                       className="w-full px-3 py-2 rounded-lg text-sm"
                       style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                       data-testid="export-end" />
              </label>
            </>
          )}
        </div>

        {tab === "import" ? (
          !cfg.canImport ? (
            <div className="py-10 text-center text-sm" style={{ color: colors.muted }} data-testid="import-not-supported">
              Import isn't supported for {cfg.label.toLowerCase()} — use Export only.
            </div>
          ) : (
            <>
              <div className="flex flex-wrap gap-2 mb-3">
                <label className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg cursor-pointer"
                       style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}>
                  <Upload size={12} /> Upload CSV
                  <input type="file" accept=".csv,text/csv" className="hidden"
                         onChange={(e) => onFile(e.target.files?.[0])}
                         data-testid="upload-input" />
                </label>
                <button onClick={dlTemplate}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg hover:brightness-95"
                        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                        data-testid="download-template">
                  <FileDown size={12} /> Download template
                </button>
                {fileName && (
                  <span className="text-xs px-3 py-1.5 rounded-lg" style={{ color: colors.muted }}>{fileName}</span>
                )}
              </div>
              <textarea
                value={csvText}
                onChange={(e) => setCsvText(e.target.value)}
                placeholder="Paste CSV here or upload a file above…"
                className="w-full px-3 py-2 rounded-lg text-xs font-mono outline-none"
                rows={10}
                style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                data-testid="csv-textarea"
              />
              <div className="mt-3 flex justify-end">
                <button onClick={doImport} disabled={busy}
                        className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-lg disabled:opacity-60"
                        style={{ backgroundColor: colors.brand, color: "#fff" }}
                        data-testid="run-import">
                  <Upload size={14} /> {busy ? "Importing…" : "Run import"}
                </button>
              </div>
              {result && (
                <div className="mt-3 p-3 rounded-lg text-xs"
                     style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                     data-testid="import-result">
                  <div><b>{result.created}</b> new, <b>{result.updated}</b> updated, <b>{result.skipped}</b> skipped.</div>
                  {(result.errors || []).length > 0 && (
                    <ul className="mt-2 list-disc list-inside" style={{ color: colors.error }}>
                      {result.errors.map((er, i) => <li key={i}>{er}</li>)}
                    </ul>
                  )}
                </div>
              )}
            </>
          )
        ) : (
          <div className="flex justify-end">
            <button onClick={doExport} disabled={busy}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-lg disabled:opacity-60"
                    style={{ backgroundColor: colors.brand, color: "#fff" }}
                    data-testid="run-export">
              <Download size={14} /> {busy ? "Exporting…" : `Download ${cfg.label} CSV`}
            </button>
          </div>
        )}
      </Card>
      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}

// ─── /income-categories — CRUD ──────────────────────────────────────────────
export function IncomeCategoriesCrud() {
  const [cats, setCats] = useState([]);
  const [loading, setLoading] = useState(true);
  const [newCat, setNewCat] = useState("");
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    setLoading(true);
    api.get("/income-categories")
      .then((r) => { setCats(r.categories || []); setLoading(false); })
      .catch(() => setLoading(false));
  };
  useEffect(load, []);

  const add = async () => {
    if (!newCat.trim()) return;
    setBusy(true);
    try {
      await api.post("/income-categories", { name: newCat.trim() });
      setNewCat("");
      setToast("Category added");
      load();
    } catch (e) { setToast(e.message); }
    finally { setBusy(false); }
  };

  const remove = async (name) => {
    if (!window.confirm(`Remove "${name}"? Existing line items keep the label.`)) return;
    setBusy(true);
    try {
      await api.del(`/income-categories/${encodeURIComponent(name)}`);
      setToast("Category removed");
      load();
    } catch (e) { setToast(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="income-categories-page">
      <Header title="Income Categories" subtitle="Labels applied to invoice line items for reporting" />
      <Card className="p-5">
        <div className="flex gap-2 mb-4">
          <input value={newCat} onChange={(e) => setNewCat(e.target.value)}
                 placeholder="Add a category (e.g. Repairs)"
                 className="flex-1 px-3 py-2 rounded-lg text-sm outline-none"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="new-cat-input" />
          <button onClick={add} disabled={busy}
                  className="flex items-center gap-1.5 px-3 py-2 text-sm font-semibold rounded-lg disabled:opacity-60"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="new-cat-add">
            <Plus size={14} /> Add
          </button>
        </div>
        {loading ? (
          <div className="py-10 text-center text-sm" style={{ color: colors.muted }}>Loading…</div>
        ) : (
          <ul>
            {cats.map((c) => (
              <li key={c} className="flex items-center justify-between py-2.5"
                  style={{ borderTop: `1px solid ${colors.border}` }}
                  data-testid={`cat-row-${c}`}>
                <div className="flex items-center gap-2">
                  <Check size={14} style={{ color: colors.success }} />
                  <span style={{ color: colors.onSurface }}>{c}</span>
                </div>
                <button onClick={() => remove(c)}
                        className="text-xs font-semibold text-red-600 hover:brightness-95 flex items-center gap-1"
                        data-testid={`cat-del-${c}`}>
                  <Trash2 size={12} /> Remove
                </button>
              </li>
            ))}
            {cats.length === 0 && <li className="py-8 text-center text-sm" style={{ color: colors.muted }}>No categories</li>}
          </ul>
        )}
      </Card>
      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}
