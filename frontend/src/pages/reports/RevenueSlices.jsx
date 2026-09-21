import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import { ArrowLeft, Search, Download } from "lucide-react";
import { api } from "@/api";
import { colors, money, gradients } from "@/theme";
import { CustomerLink } from "@/components/customer";
import DateRangePicker, { useDateRange } from "@/components/DateRangePicker";

// One reusable slice-report shell used by all 5 slice pages + Gross Sales + Invoiced Items.

function downloadCsv(filename, rows, cols) {
  const header = cols.map((c) => c.header).join(",");
  const body = rows.map((r) => cols.map((c) => {
    const val = c.value(r);
    const s = val == null ? "" : String(val);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }).join(",")).join("\n");
  const csv = `${header}\n${body}`;
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function SliceShell({
  title, subtitle, endpoint, columns, sortDefault, chartLabelKey,
  chartValueKey = "amount", summaryFn, testId, extraTop = null,
}) {
  const nav = useNavigate();
  const { start, end } = useDateRange("this-month");
  const [data, setData] = useState({ rows: [], summary: {} });
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState(sortDefault || (columns[0] && columns[0].key));
  const [sortDir, setSortDir] = useState("desc");

  useEffect(() => {
    let live = true;
    setLoading(true);
    api.get(`${endpoint}?start=${start}&end=${end}`)
      .then((r) => { if (live) { setData(r); setLoading(false); } })
      .catch(() => live && setLoading(false));
    return () => { live = false; };
  }, [endpoint, start, end]);

  const filtered = useMemo(() => {
    const rows = (data.rows || []).filter((r) =>
      !q || columns.some((c) => String(c.value(r) ?? "").toLowerCase().includes(q.toLowerCase()))
    );
    const col = columns.find((c) => c.key === sortKey) || columns[0];
    rows.sort((a, b) => {
      const av = col.value(a);
      const bv = col.value(b);
      if (typeof av === "number" && typeof bv === "number") return sortDir === "asc" ? av - bv : bv - av;
      return sortDir === "asc"
        ? String(av ?? "").localeCompare(String(bv ?? ""))
        : String(bv ?? "").localeCompare(String(av ?? ""));
    });
    return rows;
  }, [data, q, sortKey, sortDir, columns]);

  const chartData = (data.rows || []).slice(0, 8).map((r) => ({
    label: String(r[chartLabelKey] ?? "").slice(0, 14),
    value: Number(r[chartValueKey] || 0),
  }));

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto" data-testid={testId}>
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <button onClick={() => nav("/reports")}
                  className="p-2 rounded-lg hover:brightness-95"
                  style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                  data-testid="back-to-reports">
            <ArrowLeft size={16} />
          </button>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>{title}</h1>
            <p className="text-xs mt-0.5" style={{ color: colors.muted }}>{subtitle}</p>
          </div>
        </div>
        <DateRangePicker />
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        {(summaryFn ? summaryFn(data.summary || {}) : []).map((s, i) => (
          <div key={i} className="rounded-2xl p-4"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
               data-testid={`summary-${s.label.toLowerCase().replace(/\s+/g, "-")}`}>
            <div className="text-xs" style={{ color: colors.muted }}>{s.label}</div>
            <div className="text-xl font-bold mt-1" style={{ color: colors.onSurface }}>{s.value}</div>
          </div>
        ))}
      </div>

      {extraTop}

      {/* Chart */}
      <div className="rounded-2xl p-5 mb-4"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="slice-chart">
        <div className="text-sm font-semibold mb-3" style={{ color: colors.onSurface }}>Top {Math.min(8, chartData.length)}</div>
        {loading ? (
          <div className="animate-pulse rounded-xl h-56" style={{ backgroundColor: colors.surfaceTertiary }} />
        ) : chartData.length === 0 ? (
          <div className="py-10 text-center text-sm" style={{ color: colors.muted }}>No data in this window</div>
        ) : (
          <div style={{ height: 240 }}>
            <ResponsiveContainer>
              <BarChart data={chartData} layout="vertical" margin={{ left: 40 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
                <XAxis type="number" stroke={colors.muted} fontSize={11} />
                <YAxis dataKey="label" type="category" stroke={colors.muted} fontSize={11} width={110} />
                <Tooltip formatter={(v) => money(v)} />
                <Bar dataKey="value" fill={gradients.navyToGreen.stops[0]} radius={[0, 6, 6, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Table */}
      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="flex flex-wrap items-center justify-between gap-2 p-4"
             style={{ borderBottom: `1px solid ${colors.border}` }}>
          <div className="flex items-center gap-2 flex-1 min-w-[220px]">
            <Search size={14} style={{ color: colors.searchIcon }} />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search…"
              className="flex-1 px-2 py-1.5 text-sm outline-none rounded-lg"
              style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
              data-testid="slice-search"
            />
          </div>
          <button
            onClick={() => downloadCsv(`${testId}.csv`, filtered, columns)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg hover:brightness-95"
            style={{ backgroundColor: colors.brand, color: "#fff" }}
            data-testid="slice-export"
          >
            <Download size={12} /> Export CSV
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                {columns.map((c) => (
                  <th key={c.key}
                      onClick={() => {
                        if (sortKey === c.key) setSortDir((d) => d === "asc" ? "desc" : "asc");
                        else { setSortKey(c.key); setSortDir("desc"); }
                      }}
                      className="text-left px-4 py-2.5 font-semibold text-xs uppercase tracking-wide cursor-pointer select-none"
                      style={{ color: colors.muted }}
                      data-testid={`col-${c.key}`}>
                    {c.header}{sortKey === c.key ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={columns.length} className="py-10 text-center text-sm" style={{ color: colors.muted }}>Loading…</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={columns.length} className="py-10 text-center text-sm" style={{ color: colors.muted }}>No rows</td></tr>
              ) : filtered.map((r, i) => (
                <tr key={i} style={{ borderTop: `1px solid ${colors.border}` }}>
                  {columns.map((c) => (
                    <td key={c.key} className="px-4 py-2.5" style={{ color: colors.onSurface }}>
                      {c.render ? c.render(r) : c.value(r)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export function RevenueByCity() {
  return (
    <SliceShell
      title="Revenue by City"
      subtitle="Paid invoices grouped by customer city"
      endpoint="/reports/revenue-by-city"
      chartLabelKey="city"
      sortDefault="amount"
      testId="revenue-by-city-page"
      summaryFn={(s) => [
        { label: "Total", value: money(s.total) },
        { label: "Cities", value: s.cities ?? 0 },
        { label: "Invoices", value: s.invoices ?? 0 },
      ]}
      columns={[
        { key: "city", header: "City", value: (r) => r.city, render: (r) => r.city },
        { key: "amount", header: "Revenue", value: (r) => Number(r.amount || 0),
          render: (r) => <span className="font-semibold" style={{ color: colors.brand }}>{money(r.amount)}</span> },
      ]}
    />
  );
}

export function RevenueByCrew() {
  return (
    <SliceShell
      title="Revenue by Crew"
      subtitle="Attribution follows converted-quote job, else customer's most-recent job"
      endpoint="/reports/revenue-by-crew"
      chartLabelKey="crew"
      sortDefault="amount"
      testId="revenue-by-crew-page"
      summaryFn={(s) => [
        { label: "Total", value: money(s.total) },
        { label: "Crews", value: s.crews ?? 0 },
        { label: "Invoices", value: s.invoices ?? 0 },
      ]}
      columns={[
        { key: "crew", header: "Crew", value: (r) => r.crew, render: (r) => r.crew },
        { key: "amount", header: "Revenue", value: (r) => Number(r.amount || 0),
          render: (r) => <span className="font-semibold" style={{ color: colors.brand }}>{money(r.amount)}</span> },
      ]}
    />
  );
}

export function RevenueByCustomer() {
  return (
    <SliceShell
      title="Revenue by Customer"
      subtitle="Top payers in the selected window"
      endpoint="/reports/revenue-by-customer"
      chartLabelKey="customer_name"
      sortDefault="amount"
      testId="revenue-by-customer-page"
      summaryFn={(s) => [
        { label: "Total", value: money(s.total) },
        { label: "Customers", value: s.customers ?? 0 },
        { label: "Invoices", value: s.invoices ?? 0 },
      ]}
      columns={[
        { key: "customer_name", header: "Customer", value: (r) => r.customer_name,
          render: (r) => <CustomerLink customerId={r.customer_id} name={r.customer_name} /> },
        { key: "invoices", header: "Invoices", value: (r) => Number(r.invoices || 0),
          render: (r) => r.invoices },
        { key: "amount", header: "Revenue", value: (r) => Number(r.amount || 0),
          render: (r) => <span className="font-semibold" style={{ color: colors.brand }}>{money(r.amount)}</span> },
      ]}
    />
  );
}

export function GrossSales() {
  return (
    <SliceShell
      title="Gross Sales"
      subtitle="All invoices issued in window — paid + unpaid"
      endpoint="/reports/gross-sales"
      chartLabelKey="title"
      sortDefault="total"
      testId="gross-sales-page"
      summaryFn={(s) => [
        { label: "Gross", value: money(s.gross) },
        { label: "Collected", value: money(s.collected) },
        { label: "Outstanding", value: money(s.outstanding) },
        { label: "Invoices", value: s.count ?? 0 },
      ]}
      columns={[
        { key: "created_at", header: "Date", value: (r) => r.created_at || "",
          render: (r) => (r.created_at || "").slice(0, 10) },
        { key: "customer_name", header: "Customer", value: (r) => r.customer_name,
          render: (r) => <CustomerLink customerId={r.customer_id} name={r.customer_name} /> },
        { key: "title", header: "Invoice", value: (r) => r.title },
        { key: "total", header: "Total", value: (r) => Number(r.total || 0),
          render: (r) => money(r.total) },
        { key: "payment_status", header: "Status", value: (r) => r.payment_status,
          render: (r) => <StatusPill s={r.payment_status} /> },
      ]}
    />
  );
}

export function InvoicedItems() {
  return (
    <SliceShell
      title="Invoiced Items"
      subtitle="Per-line-item aggregation across all invoices in window"
      endpoint="/reports/invoiced-items"
      chartLabelKey="description"
      sortDefault="amount"
      testId="invoiced-items-page"
      summaryFn={(s) => [
        { label: "Total", value: money(s.total) },
        { label: "Unique items", value: s.unique_items ?? 0 },
        { label: "Invoices", value: s.invoices ?? 0 },
      ]}
      columns={[
        { key: "description", header: "Item", value: (r) => r.description },
        { key: "category", header: "Category", value: (r) => r.category || "Pool" },
        { key: "quantity", header: "Qty", value: (r) => Number(r.quantity || 0) },
        { key: "invoices", header: "Invoices", value: (r) => Number(r.invoices || 0) },
        { key: "amount", header: "Revenue", value: (r) => Number(r.amount || 0),
          render: (r) => <span className="font-semibold" style={{ color: colors.brand }}>{money(r.amount)}</span> },
      ]}
    />
  );
}

function StatusPill({ s }) {
  const map = {
    paid: { bg: "#DCFCE7", fg: "#16A34A" },
    unpaid: { bg: "#FEF9C3", fg: "#A16207" },
    partial: { bg: "#DBEAFE", fg: "#1D4ED8" },
    processing: { bg: "#EDE9FE", fg: "#6D28D9" },
  };
  const m = map[s] || { bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary };
  return <span className="px-2 py-0.5 rounded-md text-xs font-semibold"
                style={{ backgroundColor: m.bg, color: m.fg }}>{s || "unpaid"}</span>;
}
