import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Plus, Search, FileText, Layers, Clock, TrendingUp, AlertCircle, Trash2, X as XIcon } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors, money } from "@/theme";
import {
  PageHeader,
  Button,
  Skeleton,
  Chip,
  EmptyState,
} from "@/components/ui-kit";

export default function InvoicesList() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState(null);
  const [summary, setSummary] = useState(null);
  const [q, setQ] = useState(params.get("q") || "");
  const status = params.get("status") || "";
  const hasLateFee = params.get("late_fee") === "1";
  // Phase 34 · Task BB · Feb 2026 — bulk-select state.
  const [selected, setSelected] = useState(() => new Set());
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const setStatus = (v) => {
    const s = new URLSearchParams(params);
    if (v) s.set("status", v);
    else s.delete("status");
    setParams(s, { replace: true });
  };

  const setLateFeeFilter = (v) => {
    const s = new URLSearchParams(params);
    if (v) s.set("late_fee", "1");
    else s.delete("late_fee");
    setParams(s, { replace: true });
  };

  useEffect(() => {
    api.get("/quotes?doc_type=invoice").then((r) => setRows(r || [])).catch(() => setRows([]));
    api.get("/payments/summary").then(setSummary).catch(() => {});
  }, []);

  const today = new Date();
  const aging = useMemo(() => {
    const b = { current: 0, "1-30": 0, "31-60": 0, "61-90": 0, "90+": 0 };
    (rows || []).forEach((r) => {
      const bal = Math.max(0, Number(r.total || 0) - Number(r.amount_paid || 0));
      if (bal <= 0) return;
      if (!r.due_date) {
        b["current"] += bal;
        return;
      }
      const due = new Date(r.due_date);
      const diff = Math.round((today - due) / (24 * 3600 * 1000));
      if (diff <= 0) b["current"] += bal;
      else if (diff <= 30) b["1-30"] += bal;
      else if (diff <= 60) b["31-60"] += bal;
      else if (diff <= 90) b["61-90"] += bal;
      else b["90+"] += bal;
    });
    return b;
  }, [rows, today]);

  const filtered = (rows || [])
    .filter((r) => (status ? (r.payment_status || "unpaid") === status : true))
    .filter((r) => (hasLateFee ? (r.line_items || []).some((li) => li.is_late_fee) : true))
    .filter((r) =>
      q
        ? [r.title, r.customer_name].filter(Boolean).some((s) => s.toLowerCase().includes(q.toLowerCase()))
        : true
    );

  // Phase 34 · Task BB · Feb 2026 — visible-page selection helpers.
  const visibleIds = filtered.map((r) => r.id);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));
  const someVisibleSelected = visibleIds.some((id) => selected.has(id));
  const indeterminate = someVisibleSelected && !allVisibleSelected;
  const selectedCount = selected.size;

  const toggleAll = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) visibleIds.forEach((id) => next.delete(id));
      else visibleIds.forEach((id) => next.add(id));
      return next;
    });
  };
  const toggleOne = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const clearSelection = () => setSelected(new Set());

  const doBulkDelete = async () => {
    setBusy(true);
    const ids = Array.from(selected);
    try {
      const res = await api.post("/invoices/bulk-delete", { ids });
      const okCount = res.deleted_count || 0;
      const failCount = (res.failed || []).length;
      // Optimistic remove from the visible list.
      setRows((prev) => (prev || []).filter((r) => !res.deleted.includes(r.id)));
      clearSelection();
      setConfirmOpen(false);
      if (failCount === 0) {
        toast.success(`${okCount} invoice${okCount === 1 ? "" : "s"} deleted`);
      } else {
        toast(`${okCount} deleted · ${failCount} failed`, {
          description: (res.failed || []).slice(0, 3).map((f) => f.reason).join(" · "),
        });
      }
    } catch (e) {
      toast.error(e?.message || "Bulk delete failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="invoices-page">
      <PageHeader
        title="Invoices"
        subtitle={summary ? summary.month_label : ""}
        right={
          <>
            <Button variant="ghost" onClick={() => navigate("/invoices/master")} testid="inv-master-list">
              <Layers size={16} /> Master invoices
            </Button>
            <Button onClick={() => navigate("/invoices/new")} testid="inv-new">
              <Plus size={16} /> New Invoice
            </Button>
          </>
        }
      />

      {/* Summary + aging */}
      {summary ? (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-4">
          <SummaryTile icon={TrendingUp} tone={colors.success} label="Collected this month" value={money(summary.collected_this_month)} />
          <SummaryTile icon={Clock} tone="#A16207" label="Outstanding" value={money(summary.outstanding_total)} sub={`${summary.outstanding_count} inv`} />
          <SummaryTile icon={AlertCircle} tone={colors.error} label="Overdue count" value={String(summary.overdue?.length ?? 0)} />
        </div>
      ) : null}

      <div
        className="rounded-2xl p-4 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="text-xs uppercase font-semibold mb-2" style={{ color: colors.muted }}>
          Aging (open balances)
        </div>
        <div className="grid grid-cols-5 gap-2 text-sm">
          {Object.entries(aging).map(([k, v]) => (
            <div key={k} className="text-center rounded-lg p-2" style={{ backgroundColor: colors.surfaceSecondary }} data-testid={`aging-${k}`}>
              <div className="text-xs font-semibold" style={{ color: colors.muted }}>{k}</div>
              <div className="font-bold" style={{ color: colors.onSurface }}>{money(v)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Filters */}
      <div
        className="rounded-2xl p-4 mb-4 flex flex-wrap gap-3 items-center"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="relative flex-1 min-w-[220px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.muted }} />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search title, customer…"
            className="w-full pl-9 pr-3 py-2.5 rounded-lg outline-none text-sm focus:ring-2"
            style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
            data-testid="inv-search"
          />
        </div>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="text-xs font-semibold px-3 py-2 rounded-lg"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurfaceSecondary, border: `1px solid ${colors.border}` }}
          data-testid="inv-filter-status"
        >
          <option value="">All statuses</option>
          <option value="unpaid">Unpaid</option>
          <option value="partial">Partial</option>
          <option value="paid">Paid</option>
        </select>
        <button
          onClick={() => setLateFeeFilter(!hasLateFee)}
          className="text-xs font-semibold px-3 py-2 rounded-lg transition"
          style={{
            backgroundColor: hasLateFee ? "#FEE2E2" : colors.surfaceSecondary,
            color: hasLateFee ? "#B91C1C" : colors.onSurfaceSecondary,
            border: `1px solid ${hasLateFee ? "#FCA5A5" : colors.border}`,
          }}
          data-testid="inv-filter-late-fee"
        >
          Has late fee{hasLateFee ? " ✓" : ""}
        </button>
      </div>

      {rows === null ? (
        <Skeleton style={{ height: 240 }} />
      ) : filtered.length === 0 ? (
        <EmptyState icon={FileText} title="No invoices" hint="Create an invoice to see it here." />
      ) : (
        <div
          className="rounded-2xl overflow-hidden"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <table className="w-full text-sm" data-testid="invoices-table">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                {/* Phase 34 · Task BB · leftmost checkbox column. */}
                <th className="px-3 py-2 w-8" style={{ color: colors.onSurfaceSecondary }}>
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    ref={(el) => { if (el) el.indeterminate = indeterminate; }}
                    onChange={toggleAll}
                    aria-label="Select all invoices on this page"
                    data-testid="bulk-select-all"
                    className="cursor-pointer"
                  />
                </th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Invoice #</th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Invoice</th>
                <th className="text-left px-3 py-2 font-semibold hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>Customer</th>
                <th className="text-left px-3 py-2 font-semibold hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }}>Due</th>
                <th className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Amount</th>
                <th className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr
                  key={r.id}
                  className="cursor-pointer hover:bg-zinc-50"
                  style={{
                    borderTop: `1px solid ${colors.divider}`,
                    backgroundColor: selected.has(r.id) ? "#EFF6FF" : "transparent",
                  }}
                  data-testid={`invoice-row-${r.id}`}
                >
                  <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(r.id)}
                      onChange={() => toggleOne(r.id)}
                      aria-label={`Select invoice ${r.invoice_number || r.id}`}
                      data-testid={`bulk-select-row-${r.id}`}
                      className="cursor-pointer"
                    />
                  </td>
                  <td className="px-3 py-3 font-mono text-xs" style={{ color: colors.onSurface }} data-testid={`invoice-number-${r.id}`} onClick={() => navigate(`/invoices/${r.id}`)}>{r.invoice_number || "—"}</td>
                  <td className="px-3 py-3 font-semibold" style={{ color: colors.onSurface }} onClick={() => navigate(`/invoices/${r.id}`)}>{r.title}</td>
                  <td className="px-3 py-3 hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }} onClick={() => navigate(`/invoices/${r.id}`)}>{r.customer_name}</td>
                  <td className="px-3 py-3 hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }} onClick={() => navigate(`/invoices/${r.id}`)}>{r.due_date || "—"}</td>
                  <td className="px-3 py-3 text-right font-semibold" style={{ color: colors.onSurface }} onClick={() => navigate(`/invoices/${r.id}`)}>{money(r.total)}</td>
                  <td className="px-3 py-3 text-right" onClick={() => navigate(`/invoices/${r.id}`)}>
                    <Chip
                      label={r.payment_status || "unpaid"}
                      tone={r.payment_status === "paid" ? "success" : r.payment_status === "partial" ? "warning" : "danger"}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Phase 34 · Task BB · Feb 2026 — floating bulk-action bar.
          Sticky at the bottom-center once ≥1 row is selected. Actions:
          count · Delete selected · Clear selection. Reuses the shared
          soft-delete pattern from Schedule Phase 28. */}
      {selectedCount > 0 ? (
        <div
          className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-2xl shadow-2xl flex items-center gap-3 px-4 py-3 z-40"
          style={{
            backgroundColor: colors.onSurface,
            color: "#FFFFFF",
            border: "1px solid rgba(255,255,255,0.08)",
          }}
          data-testid="bulk-action-bar"
        >
          <div className="text-sm font-semibold" data-testid="bulk-action-bar-count">
            {selectedCount} selected
          </div>
          <button
            type="button"
            onClick={() => setConfirmOpen(true)}
            disabled={busy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold"
            style={{ backgroundColor: "#DC2626", color: "#FFFFFF" }}
            data-testid="bulk-delete-button"
          >
            <Trash2 size={12} /> Delete selected
          </button>
          <button
            type="button"
            onClick={clearSelection}
            className="text-xs font-semibold underline"
            style={{ color: "rgba(255,255,255,0.85)" }}
            data-testid="bulk-clear-selection"
          >
            Clear selection
          </button>
        </div>
      ) : null}

      {/* Confirmation modal. */}
      {confirmOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) setConfirmOpen(false); }}
          data-testid="bulk-delete-confirm"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
                  Delete {selectedCount} invoice{selectedCount === 1 ? "" : "s"}?
                </h2>
                <p className="text-sm mt-1" style={{ color: colors.muted }}>
                  {selectedCount > 100
                    ? "This is a large batch — please confirm. It can be restored from the archive."
                    : "This can be restored from the archive."}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                className="p-1"
                style={{ color: colors.muted }}
                aria-label="Close"
              >
                <XIcon size={18} />
              </button>
            </div>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                className="px-4 py-2 rounded-xl text-sm font-semibold"
                style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                data-testid="bulk-delete-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={doBulkDelete}
                disabled={busy}
                className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#DC2626" }}
                data-testid="bulk-delete-confirm-btn"
              >
                {busy ? "Deleting…" : `Delete ${selectedCount}`}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function SummaryTile({ icon: Icon, tone, label, value, sub }) {
  return (
    <div
      className="rounded-2xl p-4"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
    >
      <div className="flex items-center gap-1.5" style={{ color: tone }}>
        <Icon size={14} />
        <span className="text-xs font-semibold">{label}</span>
      </div>
      <div className="text-xl font-bold mt-1" style={{ color: colors.onSurface }}>{value}</div>
      {sub ? <div className="text-xs mt-0.5" style={{ color: colors.muted }}>{sub}</div> : null}
    </div>
  );
}
