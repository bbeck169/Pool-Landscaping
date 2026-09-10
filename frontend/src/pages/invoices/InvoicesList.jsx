import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Plus, Search, FileText, Layers, Clock, TrendingUp, AlertCircle, Trash2, X as XIcon, CreditCard, Landmark, ArrowUp, ArrowDown } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { formatCustomerName } from "@/utils/formatCustomerName";
import BulkChargeModal from "@/components/invoices/BulkChargeModal";
import CustomerFilterBar from "@/components/customers/CustomerFilterBar";
import {
  PageHeader,
  Button,
  Skeleton,
  Chip,
  EmptyState,
} from "@/components/ui-kit";

// ─── Pure helpers · exported for Vitest ────────────────────────────
// Feb-2026 · Bulk-pay iteration 1. These live at module scope so the
// unit tests can import them without mounting the router-heavy page.

const _NON_CHARGEABLE_STATUSES = new Set([
  "draft", "void", "voided", "cancelled", "paid",
]);

/** True iff the invoice can plausibly be bulk-charged in this
 *  iteration — status must be issued-but-unpaid AND the customer's
 *  card-on-file (Stripe PM) must be present. Mirrors the backend
 *  pre-filter in ``routers/payments.py::bulk_charge_on_file``.
 */
export function isChargeableInvoice(row) {
  if (!row) return false;
  const status = String(row.status || "").toLowerCase();
  const pstatus = String(row.payment_status || "").toLowerCase();
  if (_NON_CHARGEABLE_STATUSES.has(status)) return false;
  if (pstatus === "paid" || pstatus === "voided") return false;
  if (!row.has_payment_method) return false;
  return true;
}

/** Reason bucket for a selected invoice that's NOT chargeable — used
 *  by the confirm-modal disclosure ("N invoices skipped: no card X,
 *  draft Y, etc"). Draft / paid / void wins over no_card so users
 *  aren't misled about the root cause. */
export function nonChargeableReason(row) {
  if (!row) return "unknown";
  const status = String(row.status || "").toLowerCase();
  const pstatus = String(row.payment_status || "").toLowerCase();
  if (_NON_CHARGEABLE_STATUSES.has(status)) return status;
  if (pstatus === "paid") return "paid";
  if (pstatus === "voided") return "voided";
  if (!row.has_payment_method) return "no_card";
  return "unknown";
}

/** Aggregate a bulk-charge response into per-status counts for the
 *  summary modal. Accepts either the raw array of ``results`` or the
 *  wrapper ``{results, summary}`` — the backend already returns a
 *  ``summary`` but tests need this shape-agnostic helper. */
export function summarizeBulkChargeResult(input) {
  const results = Array.isArray(input) ? input : (input?.results || []);
  const counts = {
    total: results.length,
    succeeded: 0, processing: 0, requires_action: 0,
    no_card: 0, not_chargeable: 0, failed: 0, not_found: 0,
  };
  for (const r of results) {
    const s = String(r?.status || "").toLowerCase();
    if (s in counts) counts[s] += 1;
    else counts.failed += 1;
  }
  return counts;
}

export default function InvoicesList() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState(null);
  // ``pmByInvoice`` — map of {invoice_id: {has_payment_method, pm_label}}
  // populated from ``/invoices/overview`` (which enriches with PM data)
  // and merged into the display rows on render. Backend contract for
  // /quotes is intentionally left untouched.
  const [pmByInvoice, setPmByInvoice] = useState({});
  const [summary, setSummary] = useState(null);
  const [q, setQ] = useState(params.get("q") || "");
  const status = params.get("status") || "";
  const hasLateFee = params.get("late_fee") === "1";
  // Phase C · Feb-2026 — "Has declined items" filter chip.
  const hasDeclined = params.get("has_declined") === "1";
  const setHasDeclined = (v) => {
    const s = new URLSearchParams(params);
    if (v) s.set("has_declined", "1");
    else s.delete("has_declined");
    setParams(s, { replace: true });
  };
  // Feb-2026 · Bulk-pay iteration 1 — card-on-file filter + sort state.
  const cardFilter = params.get("card") || "any"; // any | yes | no
  // Feb-2026 · Item 2 — customer-scoped filter. URL-persisted so
  // filtered views are shareable / bookmarkable.
  const customerFilter = params.get("customer_id") || null;
  const setCustomerFilter = (id) => {
    const s = new URLSearchParams(params);
    if (id) s.set("customer_id", id);
    else s.delete("customer_id");
    setParams(s, { replace: true });
    setSelected(new Set());
  };
  const [sort, _setSort] = useState({ col: null, dir: null }); // dir: asc|desc|null
  // Phase 34 · Task BB — bulk-select state.
  const [selected, setSelected] = useState(() => new Set());
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // Bulk-pay modals + results.
  const [_payConfirmOpen, setPayConfirmOpen] = useState(false);
  const [_paySummaryOpen, setPaySummaryOpen] = useState(false);
  const [_payResults, setPayResults] = useState(null);
  const [paying, setPaying] = useState(false);
  // Phase 14b · Feb-2026 — category multi-select + bulk-charge modal state.
  const [categoryOptions, setCategoryOptions] = useState([]);
  const initialCategories = params.getAll("category");
  const [selectedCategories, setSelectedCategories] = useState(initialCategories);
  const [bulkChargeOpen, setBulkChargeOpen] = useState(false);
  // Phase K38 · Feb-2026 — separate flag for the ACH-on-file bulk modal.
  const [bulkChargeAchOpen, setBulkChargeAchOpen] = useState(false);

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

  const setCardFilter = (v) => {
    const s = new URLSearchParams(params);
    if (v && v !== "any") s.set("card", v);
    else s.delete("card");
    setParams(s, { replace: true });
  };

  const loadRows = () => {
    const qs = new URLSearchParams();
    qs.set("doc_type", "invoice");
    for (const c of selectedCategories) qs.append("category", c);
    // Feb-2026 · Item 2 — customer-scoped filter, additive to every
    // other filter. Backend enforces tenant scope.
    if (customerFilter) qs.set("customer_id", customerFilter);
    api.get(`/quotes?${qs.toString()}`).then((r) => setRows(r || [])).catch(() => setRows([]));
    api.get("/payments/summary").then(setSummary).catch(() => {});
    // Bulk-pay iteration 1 · pull PM enrichment from /invoices/overview.
    // /overview only returns outstanding invoices (paid excluded), which
    // is exactly the set we'd want to bulk-charge anyway. Rows not in
    // the map default to has_payment_method:false.
    api.get("/invoices/overview").then((o) => {
      const rows = (o && Array.isArray(o.invoices)) ? o.invoices : [];
      const map = {};
      for (const r of rows) {
        map[r.id] = {
          has_payment_method: !!r.has_payment_method,
          pm_label: r.pm_label || "",
        };
      }
      setPmByInvoice(map);
    }).catch(() => setPmByInvoice({}));
  };

  useEffect(() => {
    loadRows();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCategories.join("|"), customerFilter]);

  // Phase 14b — load category dropdown options once (admin surfaces only).
  useEffect(() => {
    api
      .get("/invoices/line-item-categories")
      .then((r) => setCategoryOptions((r && r.categories) || []))
      .catch(() => setCategoryOptions([]));
  }, []);

  const toggleCategory = (cat) => {
    const next = selectedCategories.includes(cat)
      ? selectedCategories.filter((c) => c !== cat)
      : [...selectedCategories, cat];
    setSelectedCategories(next);
    const s = new URLSearchParams(params);
    s.delete("category");
    for (const c of next) s.append("category", c);
    setParams(s, { replace: true });
    // Clear selection when filters change per spec.
    setSelected(new Set());
  };
  const clearCategories = () => {
    setSelectedCategories([]);
    const s = new URLSearchParams(params);
    s.delete("category");
    setParams(s, { replace: true });
    setSelected(new Set());
  };

  const today = new Date(); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: derived value stable-by-reference; downstream useMemo already tracks the real source deps
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
  }, [rows, today]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: memoized deps are stable by value; wrapping the source in its own useMemo would obscure the read

  const filtered = useMemo(() => {
    // Merge PM enrichment onto every row before filtering / sorting so
    // the Card column, filter, and Pay Now predicate all see the same
    // shape.
    const enriched = (rows || []).map((r) => {
      const pm = pmByInvoice[r.id] || {};
      return {
        ...r,
        has_payment_method: !!pm.has_payment_method,
        pm_label: pm.pm_label || "",
      };
    });
    let out = enriched
      .filter((r) => (status ? (r.payment_status || "unpaid") === status : true))
      .filter((r) => (hasLateFee ? (r.line_items || []).some((li) => li.is_late_fee) : true))
      .filter((r) => (hasDeclined ? Boolean(r.has_declined_lines) : true))
      .filter((r) =>
        q
          ? [r.title, r.customer_name].filter(Boolean).some((s) => s.toLowerCase().includes(q.toLowerCase()))
          : true
      )
      .filter((r) => {
        if (cardFilter === "yes") return !!r.has_payment_method;
        if (cardFilter === "no") return !r.has_payment_method;
        return true;
      });

    // Bulk-pay iteration 1 · client-side sort on the enriched rows.
    if (sort.col && sort.dir) {
      const getVal = (r) => {
        switch (sort.col) {
          case "due_date": return r.due_date || "";
          case "total": return Number(r.total || 0);
          case "customer_name": return String(r.customer_name || "").toLowerCase();
          case "has_payment_method": return r.has_payment_method ? 1 : 0;
          default: return "";
        }
      };
      const mult = sort.dir === "asc" ? 1 : -1;
      out = [...out].sort((a, b) => {
        const va = getVal(a), vb = getVal(b);
        if (va < vb) return -1 * mult;
        if (va > vb) return 1 * mult;
        return 0;
      });
    }
    return out;
  }, [rows, pmByInvoice, status, hasLateFee, hasDeclined, q, cardFilter, sort]);

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
      setConfirmDeleteOpen(false);
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

  // ─── Bulk-pay iteration 1 · Stripe path · Feb-2026 ────────────────
  // Selection buckets used by both the button-enable check and the
  // confirmation modal's disclosure.
  const selectionBuckets = useMemo(() => {
    const chargeable = [];
    const skips = { no_card: [], draft: [], paid: [], other: [] };
    for (const r of filtered) {
      if (!selected.has(r.id)) continue;
      if (isChargeableInvoice(r)) chargeable.push(r);
      else {
        const reason = nonChargeableReason(r);
        if (reason === "no_card") skips.no_card.push(r);
        else if (reason === "draft") skips.draft.push(r);
        else if (reason === "paid" || reason === "voided") skips.paid.push(r);
        else skips.other.push(r);
      }
    }
    const totalAmount = chargeable.reduce(
      (acc, r) => acc + Math.max(0, Number(r.total || 0) - Number(r.amount_paid || 0)),
      0,
    );
    const uniqueCustomers = new Set(chargeable.map((r) => r.customer_id)).size;
    return { chargeable, skips, totalAmount, uniqueCustomers };
  }, [filtered, selected]);

  const _doBulkPay = async () => {
    if (paying) return;
    const invoice_ids = selectionBuckets.chargeable.map((r) => r.id);
    if (invoice_ids.length === 0) return;
    setPaying(true);
    try {
      const res = await api.post("/payments/bulk-charge-on-file", { invoice_ids });
      setPayResults(res);
      setPayConfirmOpen(false);
      setPaySummaryOpen(true);
    } catch (e) {
      toast.error(e?.message || "Bulk charge failed");
      setPayConfirmOpen(false);
    } finally { setPaying(false); }
  };

  const _closeBulkPaySummary = () => {
    setPaySummaryOpen(false);
    setPayResults(null);
    clearSelection();
    loadRows();
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

      {/* Feb-2026 · Item 2 — customer-scoped filter (admin+super+manager
          only). Rendered above the existing filter bar so it's the
          first-touch control for narrowing to one customer. */}
      <div className="mb-3">
        <CustomerFilterBar
          value={customerFilter}
          onChange={setCustomerFilter}
          testId="invoices-filter-customer"
        />
      </div>

      {/* Filters — Phase K52.1 · Feb-2026: navy chrome strip. */}
      <div
        className="rounded-2xl p-4 mb-4 flex flex-wrap gap-3 items-center"
        style={{ backgroundColor: colors.nav.bg, border: `1px solid ${colors.nav.border}` }}
        data-testid="invoices-filters"
        data-k52-navy-strip="true"
      >
        <div className="relative flex-1 min-w-[220px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.nav.fgMuted }} />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search title, customer…"
            className="w-full pl-9 pr-3 py-2.5 rounded-lg outline-none text-sm focus:ring-2 placeholder:text-white/70"
            style={{ backgroundColor: "rgba(255,255,255,0.10)", border: `1px solid ${colors.nav.border}`, color: colors.nav.fg }}
            data-testid="inv-search"
          />
        </div>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="text-xs font-semibold px-3 py-2 rounded-lg"
          style={{ backgroundColor: colors.nav.bg, color: colors.nav.fg, border: `1px solid ${colors.nav.border}` }}
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
            // Phase K52.1 · Feb-2026 — "Has late fee" is a filter
            // state chip.  Active = gradient (matches K52 active
            // affordance).  Idle = transparent w/ white outline.
            background: hasLateFee ? colors.gradient.css : "transparent",
            color: colors.nav.fg,
            border: `1px solid ${hasLateFee ? "transparent" : colors.nav.fgMuted}`,
            textShadow: hasLateFee ? colors.gradient.textShadow : undefined,
          }}
          data-testid="inv-filter-late-fee"
        >
          Has late fee{hasLateFee ? " ✓" : ""}
        </button>
        {/* Phase C · Feb-2026 — Has-declined-items filter chip. */}
        <button
          onClick={() => setHasDeclined(!hasDeclined)}
          className="text-xs font-semibold px-3 py-2 rounded-lg transition"
          style={{
            backgroundColor: hasDeclined ? "#FEE2E2" : "transparent",
            color: hasDeclined ? "#7F1D1D" : colors.nav.fg,
            border: `1px solid ${hasDeclined ? "#FCA5A5" : colors.nav.fgMuted}`,
          }}
          data-testid="docs-filter-has-declined-items"
        >
          Has declined items{hasDeclined ? " ✓" : ""}
        </button>
        {/* Bulk-pay iteration 1 · card-on-file filter */}
        <select
          value={cardFilter}
          onChange={(e) => setCardFilter(e.target.value)}
          className="text-xs font-semibold px-3 py-2 rounded-lg"
          style={{ backgroundColor: colors.nav.bg, color: colors.nav.fg, border: `1px solid ${colors.nav.border}` }}
          data-testid="inv-filter-card"
        >
          <option value="any">Card on file: Any</option>
          <option value="yes">Card on file: Yes</option>
          <option value="no">Card on file: No</option>
        </select>

        {/* Phase 14b · Feb-2026 — Category multi-select. Renders as a dropdown
            + selected-chip strip. Populated from /api/invoices/line-item-categories. */}
        {categoryOptions.length > 0 ? (
          <div className="flex items-center gap-2" data-testid="inv-filter-category">
            <select
              value=""
              onChange={(e) => {
                const v = e.target.value;
                if (v) toggleCategory(v);
              }}
              className="text-xs font-semibold px-3 py-2 rounded-lg"
              style={{ backgroundColor: colors.nav.bg, color: colors.nav.fg, border: `1px solid ${colors.nav.border}` }}
              data-testid="inv-filter-category-select"
            >
              <option value="">Add category…</option>
              {categoryOptions
                .filter((c) => !selectedCategories.includes(c))
                .map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
            </select>
            {selectedCategories.map((c) => (
              <span
                key={c}
                className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-semibold"
                style={{
                  // Phase K52.1 · Feb-2026 — selected-category chip
                  // reads as an active filter state → K52 gradient.
                  background: colors.gradient.css,
                  color: colors.gradient.fg,
                  textShadow: colors.gradient.textShadow,
                }}
                data-testid={`inv-category-chip-${c}`}
              >
                {c}
                <button
                  type="button"
                  onClick={() => toggleCategory(c)}
                  aria-label={`Remove ${c}`}
                  className="text-white/90"
                  data-testid={`inv-category-chip-remove-${c}`}
                >
                  <XIcon size={11} />
                </button>
              </span>
            ))}
            {selectedCategories.length > 0 ? (
              <button
                type="button"
                onClick={clearCategories}
                className="text-xs font-semibold underline"
                style={{ color: colors.nav.fgMuted }}
                data-testid="inv-category-clear"
              >
                Clear
              </button>
            ) : null}
          </div>
        ) : null}
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
                {/* Phase K47 · Feb-2026 — "Viewed" indicator column
                    shows a small eye icon + relative "Nd ago" for
                    any invoice with ``first_viewed_at`` populated.
                    Empty for invoices that have never been opened. */}
                <th className="text-left px-3 py-2 font-semibold hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }}>Viewed</th>
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
                  <td className="px-3 py-3 hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }} onClick={() => navigate(`/invoices/${r.id}`)} data-testid={`invoice-row-customer-${r.id}`}>{formatCustomerName(r)}</td>
                  <td className="px-3 py-3 hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }} onClick={() => navigate(`/invoices/${r.id}`)}>{r.due_date || "—"}</td>
                  <td className="px-3 py-3 text-right font-semibold" style={{ color: colors.onSurface }} onClick={() => navigate(`/invoices/${r.id}`)}>{money(r.total)}</td>
                  {/* Phase K47 · Feb-2026 — Viewed indicator */}
                  <td
                    className="px-3 py-3 hidden lg:table-cell"
                    style={{ color: colors.onSurfaceSecondary }}
                    onClick={() => navigate(`/invoices/${r.id}`)}
                    data-testid={`invoice-viewed-${r.id}`}
                  >
                    {r.first_viewed_at ? (
                      <span title={r.last_viewed_at || r.first_viewed_at} className="inline-flex items-center gap-1 text-xs">
                        <span aria-hidden>👁</span>
                        {(() => {
                          const iso = r.last_viewed_at || r.first_viewed_at;
                          const ts = Date.parse(iso);
                          if (Number.isNaN(ts)) return "seen";
                          const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
                          if (diffSec < 60) return `${diffSec}s ago`;
                          const m = Math.floor(diffSec / 60);
                          if (m < 60) return `${m}m ago`;
                          const h = Math.floor(m / 60);
                          if (h < 24) return `${h}h ago`;
                          const d = Math.floor(h / 24);
                          if (d < 30) return `${d}d ago`;
                          return `${Math.floor(d / 30)}mo ago`;
                        })()}
                        {r.view_count > 1 ? (
                          <span className="ml-1 text-[10px]" style={{ color: colors.muted }} data-testid={`invoice-view-count-${r.id}`}>
                            ({r.view_count}×)
                          </span>
                        ) : null}
                      </span>
                    ) : (
                      <span className="text-xs" style={{ color: colors.muted }}>—</span>
                    )}
                  </td>
                  <td className="px-3 py-3" onClick={() => navigate(`/invoices/${r.id}`)} data-testid={`invoice-card-${r.id}`}>
                    {r.has_payment_method
                      ? <span className="text-xs font-semibold" style={{ color: colors.success }}>✓ {r.pm_label || "On file"}</span>
                      : <span className="text-xs" style={{ color: colors.muted }}>—</span>}
                  </td>
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
          {/* LZ3 · Feb 2026 — Bulk-Pay button removed. Lumino
              hosted-checkout does not currently offer a batch API.
              Per-invoice pay via the invoice detail page.
              Phase 14b · Feb 2026 — new Stripe-based Bulk Charge button. */}
          <button
            type="button"
            onClick={() => setBulkChargeOpen(true)}
            disabled={busy || selectedCount === 0 || selectedCount > 100}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold disabled:opacity-50"
            style={{ backgroundColor: "#059669", color: "#FFFFFF" }}
            data-testid="bulk-charge-button"
            title={selectedCount > 100 ? "Max 100 invoices per batch" : ""}
          >
            <CreditCard size={12} /> Charge cards on file
          </button>
          {/* Phase K38 · Feb 2026 — ACH-on-file bulk charge (mirrors K14). */}
          <button
            type="button"
            onClick={() => setBulkChargeAchOpen(true)}
            disabled={busy || selectedCount === 0 || selectedCount > 100}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold disabled:opacity-50"
            style={{ backgroundColor: "#0369A1", color: "#FFFFFF" }}
            data-testid="bulk-charge-ach-button"
            title={selectedCount > 100 ? "Max 100 invoices per batch" : ""}
          >
            <Landmark size={12} /> Charge ACH on file
          </button>
          <button
            type="button"
            onClick={() => setConfirmDeleteOpen(true)}
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

      {/* Confirmation modal — delete. */}
      {confirmDeleteOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) setConfirmDeleteOpen(false); }}
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
                onClick={() => setConfirmDeleteOpen(false)}
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
                onClick={() => setConfirmDeleteOpen(false)}
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

      {/* LZ3 · Feb 2026 — Bulk-Pay confirm + summary modals removed.
          Bulk-select is retained for other bulk actions (delete etc.). */}

      {/* Phase 14b · Feb 2026 — new Stripe-based bulk-charge modal. */}
      {bulkChargeOpen ? (
        <BulkChargeModal
          invoiceIds={Array.from(selected)}
          paymentMethod="card"
          onClose={(runId) => {
            setBulkChargeOpen(false);
            if (runId) {
              clearSelection();
              loadRows();
            }
          }}
        />
      ) : null}
      {/* Phase K38 · Feb 2026 — Stripe ACH bulk-charge modal. */}
      {bulkChargeAchOpen ? (
        <BulkChargeModal
          invoiceIds={Array.from(selected)}
          paymentMethod="ach"
          onClose={(runId) => {
            setBulkChargeAchOpen(false);
            if (runId) {
              clearSelection();
              loadRows();
            }
          }}
        />
      ) : null}
    </div>
  );
}

// ─── SortableTh · click header to cycle unsorted → asc → desc ──────
function _SortableTh({ label, col, sort, setSort, align = "left", className = "" }) {
  const active = sort.col === col;
  const dir = active ? sort.dir : null;
  const cycle = () => {
    if (!active) setSort({ col, dir: "asc" });
    else if (dir === "asc") setSort({ col, dir: "desc" });
    else setSort({ col: null, dir: null });
  };
  return (
    <th
      onClick={cycle}
      className={`px-3 py-2 font-semibold cursor-pointer select-none text-${align} ${className}`}
      style={{ color: colors.onSurfaceSecondary }}
      data-testid={`sort-${col}`}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active && dir === "asc" ? <ArrowUp size={12} /> : null}
        {active && dir === "desc" ? <ArrowDown size={12} /> : null}
      </span>
    </th>
  );
}

// ─── Bulk-pay confirmation modal ──────────────────────────────────
function _BulkPayConfirmModal({ buckets, paying, onCancel, onCharge }) {
  const { chargeable, skips, totalAmount, uniqueCustomers } = buckets;
  const skipCount = skips.no_card.length + skips.draft.length + skips.paid.length + skips.other.length;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}
      data-testid="bulk-pay-confirm"
    >
      <div
        className="w-full max-w-lg rounded-2xl p-6 shadow-2xl"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-3">
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Charge {chargeable.length} invoice{chargeable.length === 1 ? "" : "s"}?
          </h2>
          <button type="button" onClick={onCancel} className="p-1" style={{ color: colors.muted }} aria-label="Close">
            <XIcon size={18} />
          </button>
        </div>
        <p className="text-sm" style={{ color: colors.onSurfaceSecondary }} data-testid="bulk-pay-confirm-body">
          You're about to charge <strong>{money(totalAmount)}</strong> across{" "}
          <strong>{chargeable.length}</strong> invoice{chargeable.length === 1 ? "" : "s"} for{" "}
          <strong>{uniqueCustomers}</strong> customer{uniqueCustomers === 1 ? "" : "s"} using their cards on file. Continue?
        </p>
        {skipCount > 0 ? (
          <div
            className="mt-3 rounded-lg p-3 text-xs"
            style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurfaceSecondary }}
            data-testid="bulk-pay-skip-disclosure"
          >
            <div className="font-semibold mb-1">
              {skipCount} invoice{skipCount === 1 ? "" : "s"} will be skipped:
            </div>
            <ul className="list-disc list-inside space-y-0.5">
              {skips.no_card.length ? <li>{skips.no_card.length} · no card on file</li> : null}
              {skips.draft.length ? <li>{skips.draft.length} · draft (not issued)</li> : null}
              {skips.paid.length ? <li>{skips.paid.length} · already paid / voided</li> : null}
              {skips.other.length ? <li>{skips.other.length} · other</li> : null}
            </ul>
          </div>
        ) : null}
        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 rounded-xl text-sm font-semibold"
            style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
            data-testid="bulk-pay-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onCharge}
            disabled={paying || chargeable.length === 0}
            className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
            style={{ backgroundColor: colors.brand }}
            data-testid="bulk-pay-charge-btn"
          >
            {paying ? "Charging…" : `Charge ${chargeable.length}`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Bulk-pay summary modal ──────────────────────────────────────
function _BulkPaySummaryModal({ results, onClose }) {
  const rows = results?.results || [];
  const s = results?.summary || summarizeBulkChargeResult(rows);
  const chip = (label, count, tone) =>
    count > 0 ? (
      <span
        className="text-xs font-semibold rounded-full px-2 py-0.5"
        style={{ backgroundColor: tone, color: "#FFF" }}
      >
        {label}: {count}
      </span>
    ) : null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      data-testid="bulk-pay-summary"
    >
      <div
        className="w-full max-w-2xl rounded-2xl p-6 shadow-2xl"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-3">
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Bulk charge complete
          </h2>
          <button type="button" onClick={onClose} className="p-1" style={{ color: colors.muted }} aria-label="Close">
            <XIcon size={18} />
          </button>
        </div>
        <div className="flex flex-wrap gap-2 mb-4" data-testid="bulk-pay-summary-chips">
          {chip("Succeeded", s.succeeded, colors.success)}
          {chip("Processing", s.processing, "#A16207")}
          {chip("Action required", s.requires_action, "#A16207")}
          {chip("No card", s.no_card, "#64748B")}
          {chip("Not chargeable", s.not_chargeable, "#64748B")}
          {chip("Not found", s.not_found, "#64748B")}
          {chip("Failed", s.failed, colors.error)}
        </div>
        <div className="rounded-lg overflow-hidden mb-4" style={{ border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm" data-testid="bulk-pay-summary-table">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Customer</th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Invoice</th>
                <th className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.invoice_id + i} style={{ borderTop: `1px solid ${colors.divider}` }} data-testid={`bulk-pay-row-${r.invoice_id}`}>
                  <td className="px-3 py-2" style={{ color: colors.onSurface }}>{r.customer_name || "—"}</td>
                  <td className="px-3 py-2 font-mono text-xs" style={{ color: colors.onSurfaceSecondary }}>{r.invoice_id.slice(0, 8)}</td>
                  <td className="px-3 py-2 text-right">
                    <span className="text-xs font-semibold">
                      {r.status}{r.reason ? ` · ${r.reason}` : ""}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-sm font-bold text-white"
            style={{ backgroundColor: colors.brand }}
            data-testid="bulk-pay-summary-close"
          >
            Close
          </button>
        </div>
      </div>
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
