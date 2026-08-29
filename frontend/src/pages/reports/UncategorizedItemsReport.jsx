/**
 * UncategorizedItemsReport · Feb-2026.
 *
 * Landing page for the Dashboard "Revenue insights" warning banner's
 * "Review →" click-through (``/reports/uncategorized-items``). Lists
 * every invoice line item that's missing an income category AND/OR
 * a service category, with two inline autocomplete controls per row
 * for one-click resolution.
 *
 * Scope-addendum (Feb-2026): two taxonomies per row.
 *   - Income Category  (Taxonomy C) → drives Revenue-by-Category tile.
 *     Dashboard banner counts THIS one only.
 *   - Service Category (Taxonomy B) → drives Income-by-Service tile.
 *
 * A row is included if it's missing EITHER taxonomy. The filter
 * toggle at the top narrows to income-only / service-only / either /
 * both. Filter state is URL-persisted (``?missing=``) alongside
 * ``?range=`` and ``?customer=``.
 *
 * Row lifecycle: assigning ONE taxonomy clears the yellow highlight
 * on that control but does NOT remove the row — the operator can
 * fix the OTHER taxonomy without the row disappearing. Row only
 * leaves the page when both controls are populated OR the operator
 * clicks the "Mark done" X on the row (client-side dismiss).
 *
 * Undo: 5-second toast with an Undo action that clears whichever
 * taxonomy was just set (server-side DELETE with a body payload).
 *
 * All backend audit-log entries are stamped via
 * ``audit_logs.line_item.recategorize`` (both the assign path and
 * the undo path).
 */
import React, {
  useCallback, useEffect, useMemo, useState,
} from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import {
  Search, CheckCircle2, RefreshCw, AlertTriangle, X as XIcon,
} from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { PageHeader } from "@/components/ui-kit";
import CategoryPicker, {
  invalidateCategoryCache,
} from "@/components/income/CategoryPicker";


const RANGE_OPTIONS = [
  { key: "all",          label: "All Time"     },
  { key: "this_month",   label: "This Month"   },
  { key: "last_month",   label: "Last Month"   },
  { key: "this_quarter", label: "This Quarter" },
  { key: "custom",       label: "Custom"       },
];

const MISSING_OPTIONS = [
  { key: "income",  label: "Missing Income"  },
  { key: "service", label: "Missing Service" },
  { key: "either",  label: "Missing Either"  },   // default
  { key: "both",    label: "Missing Both"    },
];

const MISSING_HIGHLIGHT = "#F59E0B";                    // amber-500


function _rowKey(row) {
  return `${row.invoice_id}::${row.line_item_index}`;
}


function _fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
    return new Intl.DateTimeFormat(undefined, {
      month: "short", day: "numeric", year: "numeric",
    }).format(d);
  } catch { return String(iso).slice(0, 10); }
}


export default function UncategorizedItemsReport() {
  const [searchParams, setSearchParams] = useSearchParams();

  const range = searchParams.get("range") || "all";
  const from  = searchParams.get("from") || "";
  const to    = searchParams.get("to") || "";
  const customerFilter = searchParams.get("customer") || "";
  const missingFilter  = searchParams.get("missing") || "either";

  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Row-level busy — one map keyed by row+field so double-clicks on
  // different pickers on the same row don't race.
  const [busyKey, setBusyKey] = useState(null);      // "invId::idx::income" | ...

  // Selected rows for bulk assign.
  const [selected, setSelected] = useState(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  // Bulk picker target — which taxonomy the bulk assign will set.
  const [bulkTarget, setBulkTarget] = useState("income");     // "income" | "service"
  const [bulkPickerOpen, setBulkPickerOpen] = useState(false);
  // Client-side row dismissals (only affect the current session /
  // page view; refresh brings them back).
  const [dismissed, setDismissed] = useState(() => new Set());

  // Optimistic patch state — mirrors the resolved values on the row
  // WITHOUT waiting for a re-fetch. Keyed by row key.
  const [rowPatches, setRowPatches] = useState({});

  const _updateParam = (patch) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(patch).forEach(([k, v]) => {
      if (v == null || v === "") next.delete(k);
      else next.set(k, v);
    });
    setSearchParams(next, { replace: true });
  };

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const qs = new URLSearchParams();
      qs.set("range", range);
      qs.set("missing", missingFilter);
      if (range === "custom") {
        if (!from || !to) {
          setLoading(false);
          setRows([]); setTotal(0);
          return;
        }
        qs.set("from", from);
        qs.set("to", to);
      }
      const r = await api.get(`/reports/uncategorized-items?${qs.toString()}`);
      const items = Array.isArray(r?.items) ? r.items : [];
      setRows(items);
      setTotal(typeof r?.total === "number" ? r.total : items.length);
      setSelected(new Set());
      setDismissed(new Set());
      setRowPatches({});
    } catch (e) {
      setError(e?.message || "Failed to load uncategorized items.");
      setRows([]); setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [range, from, to, missingFilter]);

  useEffect(() => { load(); }, [load]);

  // Effective row = row + any optimistic patches applied.
  const _effectiveRow = useCallback((row) => {
    const patch = rowPatches[_rowKey(row)];
    if (!patch) return row;
    return {
      ...row,
      income_category_id: patch.income_category_id ?? row.income_category_id,
      income_category_name: patch.income_category_name ?? row.income_category_name,
      service_category_id: patch.service_category_id ?? row.service_category_id,
      service_category_name: patch.service_category_name ?? row.service_category_name,
      missing_income:
        patch.income_category_id != null
          ? patch.income_category_id === ""
          : row.missing_income,
      missing_service:
        patch.service_category_id != null
          ? patch.service_category_id === ""
          : row.missing_service,
    };
  }, [rowPatches]);

  const _isFullyCategorized = (row) =>
    !row.missing_income && !row.missing_service;

  // Client-visible rows: not dismissed, filter matches, fully-categorized
  // rows also fade out (opacity 0) but stay in DOM briefly for the
  // "row leaves" animation → then removed by the load()-driven refresh
  // on the next filter change.
  const visibleRows = useMemo(() => {
    const q = (customerFilter || "").trim().toLowerCase();
    const list = [];
    for (const raw of rows) {
      const key = _rowKey(raw);
      if (dismissed.has(key)) continue;
      const row = _effectiveRow(raw);
      // Customer filter — client-side substring on name.
      if (q && !(row.customer_name || "").toLowerCase().includes(q)) continue;
      list.push(row);
    }
    return list;
  }, [rows, customerFilter, dismissed, _effectiveRow]);

  // The row count shown in the header — reflects patches + dismissals.
  const visibleCount = visibleRows.length;

  const _onAssign = async (row, field, categoryId) => {
    if (!categoryId) return;
    const key = _rowKey(row);
    const opKey = `${key}::${field}`;
    if (busyKey === opKey) return;
    setBusyKey(opKey);
    try {
      const bodyField = field === "income"
        ? "income_category_id"
        : "service_category_id";
      const res = await api.post(
        `/reports/uncategorized-items/${encodeURIComponent(row.invoice_id)}/${row.line_item_index}/assign`,
        { [bodyField]: categoryId },
      );
      const catName = (res && res[field === "income" ? "income_category" : "service_category"]?.name)
        || "category";
      // Optimistic patch — sets the resolved id + name locally so
      // the highlight clears without a re-fetch.
      setRowPatches((prev) => ({
        ...prev,
        [key]: {
          ...(prev[key] || {}),
          [`${field}_category_id`]: (res?.[field === "income" ? "income_category" : "service_category"]?.id) || categoryId,
          [`${field}_category_name`]: catName,
          // Reset the missing_* flag for THIS field so the highlight
          // clears immediately. The other field's missing flag is
          // left as-is.
          ...(field === "income"
            ? { income_category_id: (res?.income_category?.id) || categoryId,
                income_category_name: catName }
            : { service_category_id: (res?.service_category?.id) || categoryId,
                service_category_name: catName }),
        },
      }));
      const otherLabel = field === "income" ? "Service" : "Income";
      const stillMissing = field === "income"
        ? row.missing_service
        : row.missing_income;
      toast.success(`Categorized as ${catName}`, {
        duration: 5000,
        description: stillMissing
          ? `Still missing ${otherLabel} category on this row.`
          : "Row fully categorized · will leave the list.",
        action: {
          label: "Undo",
          onClick: async () => {
            try {
              await api.del(
                `/reports/uncategorized-items/${encodeURIComponent(row.invoice_id)}/${row.line_item_index}/assign`,
                { clear_income: field === "income",
                  clear_service: field === "service" },
              );
              // Roll back the optimistic patch on this taxonomy.
              setRowPatches((prev) => {
                const next = { ...prev };
                const cur = { ...(next[key] || {}) };
                if (field === "income") {
                  cur.income_category_id = "";
                  cur.income_category_name = "";
                } else {
                  cur.service_category_id = "";
                  cur.service_category_name = "";
                }
                next[key] = cur;
                return next;
              });
              toast.info("Assignment undone");
            } catch (err) {
              toast.error(err?.message || "Undo failed");
            }
          },
        },
      });
    } catch (e) {
      toast.error(e?.message || "Failed to assign category");
    } finally {
      setBusyKey(null);
    }
  };

  const _onBulkAssign = async (categoryId) => {
    if (!categoryId || bulkBusy || selected.size === 0) return;
    setBulkBusy(true);
    try {
      const keys = Array.from(selected);
      const items = keys.map((k) => {
        const [invId, idx] = k.split("::");
        return { invoice_id: invId, line_item_index: Number(idx) };
      });
      const field = bulkTarget === "income"
        ? "income_category_id" : "service_category_id";
      const res = await api.post(
        "/reports/uncategorized-items/bulk-assign",
        { items, [field]: categoryId },
      );
      const catName = (res?.[bulkTarget === "income" ? "income_category" : "service_category"]?.name)
        || "category";
      const assigned = Number(res?.assigned || 0);
      const failed = Number(res?.failed || 0);
      // Patch all affected rows locally.
      setRowPatches((prev) => {
        const next = { ...prev };
        for (const k of keys) {
          const cur = { ...(next[k] || {}) };
          if (bulkTarget === "income") {
            cur.income_category_id = categoryId;
            cur.income_category_name = catName;
          } else {
            cur.service_category_id = categoryId;
            cur.service_category_name = catName;
          }
          next[k] = cur;
        }
        return next;
      });
      setSelected(new Set());
      setBulkPickerOpen(false);
      toast.success(
        `Bulk-assigned ${assigned} row${assigned === 1 ? "" : "s"} — ${bulkTarget} = ${catName}`
          + (failed ? ` · ${failed} failed` : ""),
      );
    } catch (e) {
      toast.error(e?.message || "Bulk assign failed");
    } finally {
      setBulkBusy(false);
    }
  };

  const _toggleSelected = (key) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const _toggleSelectAllVisible = () => {
    setSelected((prev) => {
      const eligible = visibleRows.map(_rowKey);
      const allSelected = eligible.length > 0
        && eligible.every((k) => prev.has(k));
      const next = new Set(prev);
      if (allSelected) {
        eligible.forEach((k) => next.delete(k));
      } else {
        eligible.forEach((k) => next.add(k));
      }
      return next;
    });
  };

  const _refreshCategoriesAndReload = () => {
    invalidateCategoryCache();
    load();
  };

  const _dismissRow = (key) => {
    setDismissed((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
  };

  const headerSubtitle =
    total === 0 ? "0 uncategorized line items"
    : `${visibleCount} of ${total} uncategorized line item${total === 1 ? "" : "s"}`;

  return (
    <div
      className="p-4 md:p-6 max-w-7xl mx-auto"
      data-testid="uncategorized-items-report"
    >
      <PageHeader
        title="Uncategorized Line Items"
        subtitle={
          <span data-testid="uncategorized-items-count">
            {headerSubtitle}
          </span>
        }
        right={(
          <button
            type="button"
            onClick={_refreshCategoriesAndReload}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold"
            style={{ background: colors.surfaceSecondary,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}` }}
            data-testid="uncategorized-refresh-btn"
          >
            <RefreshCw size={13} /> Refresh
          </button>
        )}
      />

      {/* ── Filter bar ────────────────────────────────────────── */}
      <div
        className="rounded-2xl p-3 mb-3 flex flex-wrap items-center gap-2"
        style={{ background: colors.surface,
                  border: `1px solid ${colors.border}` }}
        data-testid="uncategorized-filter-bar"
      >
        <span className="text-xs font-bold uppercase tracking-wider mr-1"
              style={{ color: colors.onSurfaceSecondary }}>
          Range
        </span>
        {RANGE_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            type="button"
            onClick={() => _updateParam({
              range: opt.key,
              from: opt.key === "custom" ? from : "",
              to:   opt.key === "custom" ? to   : "",
            })}
            className="px-3 py-1.5 rounded-full text-xs font-semibold transition"
            style={{
              background: range === opt.key
                ? colors.brand : colors.surfaceSecondary,
              color: range === opt.key ? "#fff" : colors.onSurface,
              border: `1px solid ${range === opt.key ? colors.brand : colors.border}`,
            }}
            data-testid={`uncategorized-range-${opt.key}`}
            aria-pressed={range === opt.key}
          >
            {opt.label}
          </button>
        ))}
        {range === "custom" ? (
          <div className="flex items-center gap-1.5">
            <input
              type="date"
              value={from}
              onChange={(e) => _updateParam({ from: e.target.value })}
              className="px-2 py-1.5 rounded-lg text-xs"
              style={{ background: colors.surface,
                        color: colors.onSurface,
                        border: `1px solid ${colors.border}` }}
              data-testid="uncategorized-custom-from"
              aria-label="Custom range · from"
            />
            <span style={{ color: colors.muted }}>→</span>
            <input
              type="date"
              value={to}
              onChange={(e) => _updateParam({ to: e.target.value })}
              className="px-2 py-1.5 rounded-lg text-xs"
              style={{ background: colors.surface,
                        color: colors.onSurface,
                        border: `1px solid ${colors.border}` }}
              data-testid="uncategorized-custom-to"
              aria-label="Custom range · to"
            />
          </div>
        ) : null}
      </div>

      {/* ── Missing-side toggle ───────────────────────────────── */}
      <div
        className="rounded-2xl p-3 mb-3 flex flex-wrap items-center gap-2"
        style={{ background: colors.surface,
                  border: `1px solid ${colors.border}` }}
        data-testid="uncategorized-missing-toggle"
      >
        <span className="text-xs font-bold uppercase tracking-wider mr-1"
              style={{ color: colors.onSurfaceSecondary }}>
          Show
        </span>
        {MISSING_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            type="button"
            onClick={() => _updateParam({ missing: opt.key })}
            className="px-3 py-1.5 rounded-full text-xs font-semibold transition"
            style={{
              background: missingFilter === opt.key
                ? "#F59E0B" : colors.surfaceSecondary,
              color: missingFilter === opt.key ? "#fff" : colors.onSurface,
              border: `1px solid ${missingFilter === opt.key ? "#F59E0B" : colors.border}`,
            }}
            data-testid={`uncategorized-missing-${opt.key}`}
            aria-pressed={missingFilter === opt.key}
          >
            {opt.label}
          </button>
        ))}
        <div className="flex-1 min-w-[180px] relative">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2" style={{ color: colors.muted }} />
          <input
            type="text"
            value={customerFilter}
            onChange={(e) => _updateParam({ customer: e.target.value })}
            placeholder="Filter by customer name…"
            className="w-full pl-7 pr-2 py-1.5 rounded-lg text-xs"
            style={{ background: colors.surface,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}` }}
            data-testid="uncategorized-customer-filter"
          />
        </div>
      </div>

      {/* ── Bulk toolbar (only when rows selected) ─────────────── */}
      {selected.size > 0 ? (
        <div
          className="rounded-xl p-3 mb-4 flex flex-wrap items-center gap-2"
          style={{ background: "#EEF2FF", color: "#3730A3",
                    border: "1px solid #C7D2FE" }}
          data-testid="uncategorized-bulk-toolbar"
        >
          <span className="text-sm font-semibold">
            {selected.size} row{selected.size === 1 ? "" : "s"} selected
          </span>
          <div className="inline-flex gap-1 ml-2">
            <button
              type="button"
              onClick={() => { setBulkTarget("income"); setBulkPickerOpen(false); }}
              className="px-2.5 py-1 rounded-full text-[11px] font-semibold"
              style={{
                background: bulkTarget === "income" ? "#3730A3" : "#fff",
                color: bulkTarget === "income" ? "#fff" : "#3730A3",
                border: "1px solid #C7D2FE",
              }}
              data-testid="uncategorized-bulk-target-income"
              aria-pressed={bulkTarget === "income"}
            >
              Income
            </button>
            <button
              type="button"
              onClick={() => { setBulkTarget("service"); setBulkPickerOpen(false); }}
              className="px-2.5 py-1 rounded-full text-[11px] font-semibold"
              style={{
                background: bulkTarget === "service" ? "#3730A3" : "#fff",
                color: bulkTarget === "service" ? "#fff" : "#3730A3",
                border: "1px solid #C7D2FE",
              }}
              data-testid="uncategorized-bulk-target-service"
              aria-pressed={bulkTarget === "service"}
            >
              Service
            </button>
          </div>
          <div className="flex-1" />
          {bulkPickerOpen ? (
            <div className="min-w-[240px]"
                 data-testid="uncategorized-bulk-picker-wrap">
              <CategoryPicker
                testid="uncategorized-bulk-picker"
                placeholder={`Bulk assign ${bulkTarget} to…`}
                source={bulkTarget}
                onChange={(catId) => _onBulkAssign(catId)}
                disabled={bulkBusy}
              />
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setBulkPickerOpen(true)}
              disabled={bulkBusy}
              className="px-3 py-1.5 rounded-lg text-xs font-bold text-white disabled:opacity-60"
              style={{ background: colors.brand }}
              data-testid="uncategorized-bulk-assign-btn"
            >
              Bulk assign to…
            </button>
          )}
          <button
            type="button"
            onClick={() => { setSelected(new Set()); setBulkPickerOpen(false); }}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold"
            style={{ background: "#fff", color: "#3730A3",
                      border: "1px solid #C7D2FE" }}
            data-testid="uncategorized-bulk-clear-btn"
          >
            Clear selection
          </button>
        </div>
      ) : null}

      {/* ── Body ──────────────────────────────────────────────── */}
      {error ? (
        <div
          className="rounded-xl p-3 flex items-start gap-2"
          style={{ background: "#FEE2E2", color: "#7F1D1D",
                    border: "1px solid #FCA5A5" }}
          data-testid="uncategorized-error"
        >
          <AlertTriangle size={16} className="shrink-0 mt-0.5" />
          <span className="text-sm">{error}</span>
        </div>
      ) : loading ? (
        <div
          className="text-sm py-8 text-center"
          style={{ color: colors.muted }}
          data-testid="uncategorized-loading"
        >
          Loading…
        </div>
      ) : total === 0 ? (
        <div
          className="rounded-2xl p-6 text-center"
          style={{ background: "#ECFDF5", color: "#065F46",
                    border: "1px solid #A7F3D0" }}
          data-testid="uncategorized-empty-state"
        >
          <CheckCircle2 size={32} className="mx-auto mb-2" />
          <div className="text-base font-bold">
            All line items are categorized
          </div>
          <div className="text-xs mt-1" style={{ color: "#047857" }}>
            Nothing left to review for the current filter.
          </div>
        </div>
      ) : (
        <div
          className="rounded-2xl overflow-hidden"
          style={{ background: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid="uncategorized-table-wrap"
        >
          <div className="overflow-x-auto">
            <table
              className="w-full text-sm"
              data-testid="uncategorized-table"
            >
              <thead style={{ background: colors.surfaceSecondary }}>
                <tr style={{ color: colors.onSurfaceSecondary }}>
                  <th className="px-3 py-2 text-left w-8">
                    <input
                      type="checkbox"
                      checked={
                        visibleRows.length > 0
                        && visibleRows.every((r) => selected.has(_rowKey(r)))
                      }
                      onChange={_toggleSelectAllVisible}
                      data-testid="uncategorized-select-all"
                      aria-label="Select all visible rows"
                    />
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-bold uppercase tracking-wider">Date</th>
                  <th className="px-3 py-2 text-left text-xs font-bold uppercase tracking-wider">Customer</th>
                  <th className="px-3 py-2 text-left text-xs font-bold uppercase tracking-wider">Invoice</th>
                  <th className="px-3 py-2 text-left text-xs font-bold uppercase tracking-wider">Description</th>
                  <th className="px-3 py-2 text-right text-xs font-bold uppercase tracking-wider">Amount</th>
                  <th className="px-3 py-2 text-left text-xs font-bold uppercase tracking-wider w-48">Income Category</th>
                  <th className="px-3 py-2 text-left text-xs font-bold uppercase tracking-wider w-48">Service Category</th>
                  <th className="px-3 py-2 w-8" aria-label="Dismiss row" />
                </tr>
              </thead>
              <tbody>
                {visibleRows.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-3 py-8 text-center text-xs"
                        style={{ color: colors.muted }}
                        data-testid="uncategorized-no-match">
                      No rows match the current filter.
                    </td>
                  </tr>
                ) : visibleRows.map((row) => {
                  const key = _rowKey(row);
                  const isFullyCategorized = _isFullyCategorized(row);
                  const isBusyIncome = busyKey === `${key}::income`;
                  const isBusyService = busyKey === `${key}::service`;
                  return (
                    <tr
                      key={key}
                      style={{
                        borderTop: `1px solid ${colors.border}`,
                        opacity: isFullyCategorized ? 0.55 : 1,
                        transition: "opacity 200ms ease-out",
                      }}
                      data-testid={`uncategorized-row-${key}`}
                    >
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          checked={selected.has(key)}
                          onChange={() => _toggleSelected(key)}
                          data-testid={`uncategorized-row-select-${key}`}
                          aria-label={`Select ${row.description || "row"}`}
                        />
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap"
                          style={{ color: colors.onSurfaceSecondary }}>
                        {_fmtDate(row.created_at)}
                      </td>
                      <td className="px-3 py-2"
                          style={{ color: colors.onSurface }}>
                        {row.customer_name || "Unknown Customer"}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap"
                          style={{ color: colors.onSurfaceSecondary }}>
                        {row.invoice_number || row.invoice_id.slice(0, 8)}
                      </td>
                      <td className="px-3 py-2"
                          style={{ color: colors.onSurface }}>
                        {row.description || <span style={{ color: colors.muted }}>—</span>}
                      </td>
                      <td className="px-3 py-2 text-right whitespace-nowrap"
                          style={{ color: colors.onSurface }}>
                        {money(row.amount || 0)}
                      </td>
                      <td className="px-3 py-2">
                        <div
                          style={{
                            paddingLeft: 6,
                            borderLeft: row.missing_income
                              ? `3px solid ${MISSING_HIGHLIGHT}`
                              : "3px solid transparent",
                          }}
                          data-testid={`uncategorized-income-cell-${key}`}
                          data-missing-income={row.missing_income ? "true" : "false"}
                        >
                          {row.missing_income ? (
                            <CategoryPicker
                              testid={`uncategorized-income-picker-${key}`}
                              placeholder="Assign Income category"
                              source="income"
                              onChange={(catId) => _onAssign(row, "income", catId)}
                              disabled={isBusyIncome}
                            />
                          ) : (
                            <span
                              className="text-xs font-semibold"
                              style={{ color: colors.onSurface }}
                              data-testid={`uncategorized-income-chip-${key}`}
                            >
                              {row.income_category_name || "None"}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <div
                          style={{
                            paddingLeft: 6,
                            borderLeft: row.missing_service
                              ? `3px solid ${MISSING_HIGHLIGHT}`
                              : "3px solid transparent",
                          }}
                          data-testid={`uncategorized-service-cell-${key}`}
                          data-missing-service={row.missing_service ? "true" : "false"}
                        >
                          {row.missing_service ? (
                            <CategoryPicker
                              testid={`uncategorized-service-picker-${key}`}
                              placeholder="Assign Service category"
                              source="service"
                              onChange={(catId) => _onAssign(row, "service", catId)}
                              disabled={isBusyService}
                            />
                          ) : (
                            <span
                              className="text-xs font-semibold"
                              style={{ color: colors.onSurface }}
                              data-testid={`uncategorized-service-chip-${key}`}
                            >
                              {row.service_category_name || "None"}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() => _dismissRow(key)}
                          className="p-1 rounded-md hover:brightness-95"
                          style={{ background: colors.surfaceSecondary,
                                    color: colors.onSurfaceSecondary,
                                    border: `1px solid ${colors.border}` }}
                          data-testid={`uncategorized-dismiss-${key}`}
                          aria-label="Mark row done"
                          title="Dismiss row"
                        >
                          <XIcon size={12} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
