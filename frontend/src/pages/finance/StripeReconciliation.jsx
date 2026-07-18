/**
 * Phase 53 · Stripe reconciliation dashboard.
 * /admin/finance/stripe-payments
 *
 * Reads the `db.stripe_payments` ledger and shows a per-payment audit
 * trail with fees, refunds, and net. Rows link to the underlying
 * invoice + Stripe receipt (when available). Admin-only.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Filter, DollarSign, Receipt, RefreshCcw, ExternalLink } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { RefundButton } from "@/components/stripe/StripePayments";

const STATUSES = ["", "initiated", "processing", "paid", "refunded", "failed"];

function fmtMoney(cents) {
  return `$${((Number(cents) || 0) / 100).toFixed(2)}`;
}
function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
const STATUS_STYLE = {
  paid:       { bg: "#DCFCE7", fg: "#166534" },
  refunded:   { bg: "#E0E7FF", fg: "#3730A3" },
  processing: { bg: "#FEF3C7", fg: "#92400E" },
  initiated:  { bg: "#E5E7EB", fg: "#374151" },
  failed:     { bg: "#FEE2E2", fg: "#991B1B" },
};

export default function StripeReconciliation() {
  const nav = useNavigate();
  const [rows, setRows] = useState([]);
  const [rollup, setRollup] = useState({ paid_cents: 0, refunded_cents: 0, net_cents: 0, count: 0 });
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(true);
  const [toast, setToast] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const q = new URLSearchParams();
      if (status) q.set("status", status);
      q.set("limit", "200");
      const r = await api.get(`/stripe/payments?${q.toString()}`);
      setRows(r?.rows || []);
      setRollup(r?.rollup || rollup);
    } catch { /* silent */ }
    setBusy(false);
  }, [status]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const onRefunded = (r) => {
    setToast(`Refunded ${fmtMoney(r.amount_cents)}`);
    setTimeout(() => setToast(""), 2500);
    load();
  };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="stripe-reconciliation-page">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <button onClick={() => nav(-1)} className="p-2 rounded-lg"
                  style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                  data-testid="stripe-recon-back">
            <ArrowLeft size={16} />
          </button>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold flex items-center gap-2" style={{ color: colors.onSurface }}>
              <DollarSign size={22} /> Stripe payments
            </h1>
            <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
              Reconciliation ledger — every captured / refunded payment
            </p>
          </div>
        </div>
        <button onClick={load}
                className="px-3 py-2 rounded-lg text-sm font-semibold inline-flex items-center gap-1.5"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                data-testid="stripe-recon-refresh">
          <RefreshCcw size={14} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <div className="rounded-2xl p-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }} data-testid="rollup-count">
          <div className="text-[10px] uppercase font-bold tracking-wider" style={{ color: colors.muted }}>Payments</div>
          <div className="text-2xl font-bold mt-1" style={{ color: colors.onSurface }}>{rollup.count}</div>
        </div>
        <div className="rounded-2xl p-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }} data-testid="rollup-paid">
          <div className="text-[10px] uppercase font-bold tracking-wider" style={{ color: colors.muted }}>Gross paid</div>
          <div className="text-2xl font-bold mt-1" style={{ color: colors.onSurface }}>{fmtMoney(rollup.paid_cents)}</div>
        </div>
        <div className="rounded-2xl p-4" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }} data-testid="rollup-refunded">
          <div className="text-[10px] uppercase font-bold tracking-wider" style={{ color: colors.muted }}>Refunded</div>
          <div className="text-2xl font-bold mt-1" style={{ color: colors.onSurface }}>{fmtMoney(rollup.refunded_cents)}</div>
        </div>
        <div className="rounded-2xl p-4" style={{ backgroundColor: colors.brand, border: `1px solid ${colors.brand}` }} data-testid="rollup-net">
          <div className="text-[10px] uppercase font-bold tracking-wider" style={{ color: "#fff", opacity: 0.9 }}>Net</div>
          <div className="text-2xl font-bold mt-1" style={{ color: "#fff" }}>{fmtMoney(rollup.net_cents)}</div>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <span className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider" style={{ color: colors.muted }}>
          <Filter size={12} /> Status
        </span>
        {STATUSES.map((s) => (
          <button key={s || "all"} onClick={() => setStatus(s)}
                  className="text-xs px-2.5 py-1 rounded-full border capitalize"
                  style={{
                    borderColor: status === s ? colors.brand : colors.border,
                    backgroundColor: status === s ? colors.brand : "transparent",
                    color: status === s ? "#fff" : colors.onSurface,
                  }}
                  data-testid={`stripe-recon-filter-${s || "all"}`}>
            {s || "All"}
          </button>
        ))}
        {toast ? (
          <span className="ml-2 text-xs font-semibold px-2 py-1 rounded"
                style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
                data-testid="stripe-recon-toast">
            {toast}
          </span>
        ) : null}
      </div>

      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="grid grid-cols-[110px_1fr_100px_110px_110px_110px_120px] items-center px-4 py-3 border-b text-[11px] font-bold uppercase tracking-wider"
             style={{ borderColor: colors.border, backgroundColor: colors.surfaceSecondary, color: colors.muted }}>
          <div>When</div>
          <div>Invoice / Customer</div>
          <div>Kind</div>
          <div>Amount</div>
          <div>Refunded</div>
          <div>Status</div>
          <div className="text-right">Actions</div>
        </div>
        {busy ? (
          <div className="p-6 text-sm text-center" style={{ color: colors.muted }} data-testid="stripe-recon-loading">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="p-10 text-center text-sm" style={{ color: colors.muted }} data-testid="stripe-recon-empty">
            <Receipt size={28} className="mx-auto opacity-40 mb-2" />
            No payments yet.
          </div>
        ) : (
          rows.map((r) => {
            const st = STATUS_STYLE[r.status] || { bg: colors.surfaceSecondary, fg: colors.onSurface };
            return (
              <div key={r.id}
                   className="grid grid-cols-[110px_1fr_100px_110px_110px_110px_120px] items-center px-4 py-3 border-b text-sm"
                   style={{ borderColor: colors.border }}
                   data-testid={`stripe-recon-row-${r.id}`}>
                <div className="text-xs" style={{ color: colors.muted }}>{fmtDate(r.created_at)}</div>
                <div className="min-w-0">
                  <div className="font-semibold truncate" style={{ color: colors.onSurface }}>
                    {r.invoice_id ? (
                      <Link to={`/invoices/${r.invoice_id}`} className="hover:underline">
                        #{String(r.invoice_id).slice(0, 8)}
                      </Link>
                    ) : "—"}
                  </div>
                  <div className="text-[11px] truncate" style={{ color: colors.muted }}>
                    {r.customer_email || r.customer_id || ""}
                  </div>
                </div>
                <div className="text-xs capitalize" style={{ color: colors.muted }}>{r.kind}</div>
                <div className="font-bold" style={{ color: colors.onSurface }}>{fmtMoney(r.amount_cents)}</div>
                <div style={{ color: colors.muted }}>{fmtMoney(r.refunded_cents)}</div>
                <div>
                  <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded"
                        style={{ backgroundColor: st.bg, color: st.fg }}>
                    {r.status}
                  </span>
                </div>
                <div className="text-right flex items-center gap-1 justify-end">
                  {r.receipt_url ? (
                    <a href={r.receipt_url} target="_blank" rel="noreferrer"
                       className="text-xs font-semibold px-2 py-1 rounded inline-flex items-center gap-1"
                       style={{ color: colors.brand }}
                       data-testid={`receipt-${r.id}`}>
                      Receipt <ExternalLink size={10} />
                    </a>
                  ) : null}
                  {r.status === "paid" ? (
                    <RefundButton payment={r} onRefunded={onRefunded} onError={(m) => { setToast(m); setTimeout(()=>setToast(""), 2500); }} />
                  ) : null}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
