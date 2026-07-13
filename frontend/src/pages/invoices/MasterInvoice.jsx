import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Plus, Layers, DollarSign, Trash2, Link2 } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import {
  PageHeader,
  Button,
  Skeleton,
  Chip,
  EmptyState,
  Modal,
  TextInput,
  Toast,
} from "@/components/ui-kit";

// ────── List ──────
export function MasterInvoicesList() {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  useEffect(() => {
    api.get("/invoices/master").then((r) => setRows(r || [])).catch(() => setRows([]));
  }, []);
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="master-list-page">
      <button onClick={() => navigate("/invoices")} className="flex items-center gap-1 text-sm font-semibold mb-4" style={{ color: colors.muted }}>
        <ArrowLeft size={14} /> Invoices
      </button>
      <PageHeader
        title="Master Invoices"
        subtitle="Combine multiple invoices (HOA / family) into one payable."
        right={<Button onClick={() => navigate("/invoices/master/new")} testid="master-new"><Plus size={16} /> New master invoice</Button>}
      />
      {rows === null ? (
        <Skeleton style={{ height: 240 }} />
      ) : rows.length === 0 ? (
        <EmptyState icon={Layers} title="No master invoices yet" hint="Roll up multiple open invoices under one bill." action={<Button onClick={() => navigate("/invoices/master/new")}>Create master</Button>} />
      ) : (
        <div className="rounded-2xl overflow-hidden" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                <th className="text-left px-3 py-2 font-semibold">Label</th>
                <th className="text-left px-3 py-2 font-semibold hidden md:table-cell">Invoices</th>
                <th className="text-right px-3 py-2 font-semibold">Total</th>
                <th className="text-right px-3 py-2 font-semibold">Balance</th>
                <th className="text-right px-3 py-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} onClick={() => navigate(`/invoices/master/${r.id}`)} className="cursor-pointer hover:bg-zinc-50" style={{ borderTop: `1px solid ${colors.divider}` }} data-testid={`master-row-${r.id}`}>
                  <td className="px-3 py-3 font-semibold">{r.label}</td>
                  <td className="px-3 py-3 hidden md:table-cell text-xs" style={{ color: colors.muted }}>{r.invoice_ids?.length} invoices</td>
                  <td className="px-3 py-3 text-right font-semibold">{money(r.total)}</td>
                  <td className="px-3 py-3 text-right" style={{ color: r.balance > 0 ? "#A16207" : colors.success }}>{money(Math.max(0, r.total - (r.amount_paid || 0)))}</td>
                  <td className="px-3 py-3 text-right"><Chip label={r.payment_status || "unpaid"} tone={r.payment_status === "paid" ? "success" : r.payment_status === "partial" ? "warning" : "danger"} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ────── Create ──────
export function MasterInvoiceNew() {
  const navigate = useNavigate();
  const [invoices, setInvoices] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [pickedCustomers, setPickedCustomers] = useState(new Set());
  const [pickedInvoices, setPickedInvoices] = useState(new Set());
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    api.get("/quotes?doc_type=invoice").then((r) =>
      setInvoices((r || []).filter((i) => i.payment_status !== "paid"))
    ).catch(() => {});
    api.get("/customers").then(setCustomers).catch(() => {});
  }, []);

  const filtered = useMemo(() => {
    if (!pickedCustomers.size) return invoices;
    return invoices.filter((i) => pickedCustomers.has(i.customer_id));
  }, [invoices, pickedCustomers]);

  const total = useMemo(
    () => invoices.filter((i) => pickedInvoices.has(i.id)).reduce((sum, i) => sum + Number(i.total || 0), 0),
    [invoices, pickedInvoices]
  );

  const toggle = (setState) => (id) => {
    setState((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const submit = async () => {
    if (pickedInvoices.size < 1) {
      setToast({ tone: "error", message: "Pick at least 1 invoice" });
      return;
    }
    setBusy(true);
    try {
      const r = await api.post("/invoices/master", {
        label: label || undefined,
        customer_ids: Array.from(pickedCustomers),
        invoice_ids: Array.from(pickedInvoices),
      });
      navigate(`/invoices/master/${r.id}`);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="master-new-page">
      <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-sm font-semibold mb-4" style={{ color: colors.muted }}>
        <ArrowLeft size={14} /> Back
      </button>
      <PageHeader title="New Master Invoice" subtitle="Combine open invoices under one bill." />

      <div className="rounded-2xl p-5 mb-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <TextInput label="LABEL (optional)" value={label} onChange={(e) => setLabel(e.target.value)} testid="master-label" />
      </div>

      {/* Payers */}
      <div className="rounded-2xl p-5 mb-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="text-xs uppercase font-semibold mb-2" style={{ color: colors.muted }}>Payers (customers)</div>
        <div className="flex flex-wrap gap-2">
          {customers.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => toggle(setPickedCustomers)(c.id)}
              className="text-xs font-semibold px-3 py-1.5 rounded-full"
              style={{
                backgroundColor: pickedCustomers.has(c.id) ? colors.brandTertiary : colors.surfaceSecondary,
                color: pickedCustomers.has(c.id) ? colors.onBrandTertiary : colors.onSurfaceSecondary,
                border: `1px solid ${pickedCustomers.has(c.id) ? colors.brandTertiary : colors.border}`,
              }}
              data-testid={`master-payer-${c.id}`}
            >
              {c.name}
            </button>
          ))}
        </div>
      </div>

      {/* Invoices */}
      <div className="rounded-2xl p-5 mb-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>Open invoices to combine</div>
          <div className="text-sm font-semibold" style={{ color: colors.brand }}>Selected total: {money(total)}</div>
        </div>
        {filtered.length === 0 ? (
          <p className="text-sm" style={{ color: colors.muted }}>No open invoices for the selected payers.</p>
        ) : (
          <ul className="space-y-1">
            {filtered.map((i) => (
              <li key={i.id} className="flex items-center gap-3 p-2 rounded-lg" style={{ backgroundColor: pickedInvoices.has(i.id) ? colors.brandTertiary : "transparent" }}>
                <input
                  type="checkbox"
                  checked={pickedInvoices.has(i.id)}
                  onChange={() => toggle(setPickedInvoices)(i.id)}
                  data-testid={`master-invoice-${i.id}`}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{i.title}</div>
                  <div className="text-xs" style={{ color: colors.muted }}>{i.customer_name} · Due {i.due_date || "—"}</div>
                </div>
                <div className="text-sm font-semibold">{money(i.total)}</div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex justify-end gap-2 pb-8">
        <Button variant="ghost" onClick={() => navigate(-1)}>Cancel</Button>
        <Button onClick={submit} disabled={busy} testid="master-submit">{busy ? "Creating…" : "Create master invoice"}</Button>
      </div>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

// ────── Detail ──────
export function MasterInvoiceDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState(null);
  const [payOpen, setPayOpen] = useState(false);
  const [toast, setToast] = useState(null);

  const load = () => api.get(`/invoices/master/${id}`).then(setDoc).catch(() => {});
  useEffect(() => { load(); }, [id]);

  if (!doc) return <div className="max-w-4xl mx-auto p-6"><Skeleton style={{ height: 180 }} /></div>;

  const balance = Math.max(0, doc.total - (doc.amount_paid || 0));

  const del = async () => {
    try {
      await api.del(`/invoices/master/${id}`);
      setToast({ tone: "success", message: "Deleted" });
      setTimeout(() => navigate("/invoices/master"), 400);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="master-detail">
      <button onClick={() => navigate("/invoices/master")} className="flex items-center gap-1 text-sm font-semibold mb-4" style={{ color: colors.muted }}>
        <ArrowLeft size={14} /> All master invoices
      </button>

      <div className="rounded-2xl p-6 mb-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <Chip label={doc.payment_status || "unpaid"} tone={doc.payment_status === "paid" ? "success" : doc.payment_status === "partial" ? "warning" : "danger"} />
            <h1 className="text-2xl md:text-3xl font-bold mt-2" style={{ color: colors.onSurface }}>{doc.label}</h1>
            <p className="text-sm mt-1" style={{ color: colors.muted }}>{doc.invoice_ids?.length} invoices</p>
          </div>
          <div className="text-right">
            <div className="text-3xl font-bold" style={{ color: colors.brand }}>{money(doc.total)}</div>
            <div className="text-xs mt-1" style={{ color: colors.muted }}>Paid {money(doc.amount_paid || 0)} · Balance {money(balance)}</div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 mt-5">
          {balance > 0 ? (
            <Button onClick={() => setPayOpen(true)} testid="master-apply-payment"><DollarSign size={14} /> Apply payment</Button>
          ) : null}
          <Button variant="danger" onClick={del}><Trash2 size={14} /> Delete</Button>
        </div>
      </div>

      <div className="rounded-2xl p-6 mb-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <h2 className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>Rolled-up invoices</h2>
        <ul className="space-y-2">
          {(doc.invoice_snapshot || []).map((s) => (
            <li key={s.id} className="flex items-center gap-3 p-3 rounded-xl" style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }} data-testid={`master-child-${s.id}`}>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{s.title}</div>
                <div className="text-xs" style={{ color: colors.muted }}>{s.customer_name}</div>
              </div>
              <div className="text-right">
                <div className="text-sm font-semibold">{money(s.total)}</div>
                <Chip label={s.payment_status || "unpaid"} tone={s.payment_status === "paid" ? "success" : s.payment_status === "partial" ? "warning" : "danger"} />
              </div>
              <button onClick={() => navigate(`/invoices/${s.id}`)} className="opacity-70 hover:opacity-100"><Link2 size={14} /></button>
            </li>
          ))}
        </ul>
      </div>

      <ApplyPaymentModal open={payOpen} onClose={() => setPayOpen(false)} master={doc}
        onDone={async (m) => { setPayOpen(false); setToast({ tone: "success", message: m }); await load(); }}
        onError={(e) => setToast({ tone: "error", message: e })} />

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

function ApplyPaymentModal({ open, onClose, master, onDone, onError }) {
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) setAmount(String(Math.max(0, master.total - (master.amount_paid || 0)).toFixed(2)));
  }, [open, master]);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/invoices/master/${master.id}/apply-payment`, { amount: Number(amount) });
      onDone(`Applied ${money(r.applied)} across children`);
    } catch (e) { onError(e.message); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Apply payment to master"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={busy} testid="master-pay-submit">{busy ? "Applying…" : "Apply"}</Button></>}>
      <TextInput label="AMOUNT" type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
      <p className="text-xs mt-2" style={{ color: colors.muted }}>Applied proportionally to each child invoice's remaining balance.</p>
    </Modal>
  );
}
