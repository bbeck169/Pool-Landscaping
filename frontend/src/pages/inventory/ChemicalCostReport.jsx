/**
 * Phase 18 · Feb-2026 — Chemical Cost Report page.
 *
 * Admin+ only (gated at the route level in App.js). Shows aggregated
 * chemical spend from ``db.chemical_usage_events`` with filters for
 * date range, department, and technician. Cost math is snapshot-priced
 * on the backend — the UI simply renders the aggregates.
 *
 * Never rendered on the tech side — techs get the read-only mobile
 * ``my-inventory`` view which strips cost data server-side.
 */
import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";

const centsToUSD = (c) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format((Number(c) || 0) / 100);

const startOfMonthISO = () => {
  // Default to a 30-day trailing window (matches the backend default
  // when the endpoint is called without ``start``/``end``).
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - 30);
  return d.toISOString();
};

export default function ChemicalCostReport() {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [report, setReport] = useState(null);
  const [techs, setTechs] = useState([]);

  const [filters, setFilters] = useState({
    start: startOfMonthISO(),
    end: new Date().toISOString(),
    department: "",
    tech_id: "",
  });

  const load = async () => {
    setLoading(true);
    setErr("");
    try {
      const q = new URLSearchParams();
      if (filters.start) q.set("start", filters.start);
      if (filters.end) q.set("end", filters.end);
      if (filters.department) q.set("department", filters.department);
      if (filters.tech_id) q.set("tech_id", filters.tech_id);
      const r = await api.get(`/reports/chemical-costs?${q}`);
      setReport(r);
    } catch (e) {
      setErr(e.message || "Failed to load report");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // Load tech list once for the dropdown filter.
    api
      .get("/admin/users?role=technician")
      .then((r) => setTechs(Array.isArray(r) ? r : r?.items || []))
      .catch(() => setTechs([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totals = report?.totals || {};
  const perProduct = report?.per_product || [];
  const perTech = report?.per_tech || [];
  const perDept = report?.per_department || [];

  const daysInWindow = useMemo(() => {
    if (!filters.start || !filters.end) return 0;
    return Math.max(
      1,
      Math.round(
        (new Date(filters.end).getTime() - new Date(filters.start).getTime()) /
          86400000
      )
    );
  }, [filters.start, filters.end]);

  return (
    <div
      className="max-w-6xl mx-auto p-4 md:p-6 space-y-6"
      data-testid="chemical-cost-report"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h1 className="text-3xl md:text-4xl font-semibold tracking-tight">
          Chemical Cost Report
        </h1>
        <span className="text-sm text-neutral-500">
          {daysInWindow} day window
        </span>
      </div>
      <p className="text-sm text-neutral-500 max-w-2xl">
        Snapshot-priced spend rolled up from every service report's chemical
        usage. Filters apply to the whole page. Costs are wholesale — never
        shown to techs.
      </p>

      {/* Filters */}
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 p-4 bg-neutral-50 border rounded-lg"
        data-testid="chemical-cost-filters"
      >
        <label className="text-sm">
          <span className="block text-neutral-600 mb-1">From</span>
          <input
            type="date"
            data-testid="filter-start"
            className="w-full border rounded px-2 py-1.5"
            value={filters.start?.slice(0, 10) || ""}
            onChange={(e) =>
              setFilters((f) => ({
                ...f,
                start: e.target.value
                  ? new Date(e.target.value).toISOString()
                  : "",
              }))
            }
          />
        </label>
        <label className="text-sm">
          <span className="block text-neutral-600 mb-1">To</span>
          <input
            type="date"
            data-testid="filter-end"
            className="w-full border rounded px-2 py-1.5"
            value={filters.end?.slice(0, 10) || ""}
            onChange={(e) =>
              setFilters((f) => ({
                ...f,
                end: e.target.value
                  ? new Date(e.target.value + "T23:59:59Z").toISOString()
                  : "",
              }))
            }
          />
        </label>
        <label className="text-sm">
          <span className="block text-neutral-600 mb-1">Department</span>
          <select
            data-testid="filter-department"
            className="w-full border rounded px-2 py-1.5"
            value={filters.department}
            onChange={(e) =>
              setFilters((f) => ({ ...f, department: e.target.value }))
            }
          >
            <option value="">All</option>
            <option value="pool">Pool</option>
            <option value="landscape">Landscape</option>
            <option value="both">Both</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="block text-neutral-600 mb-1">Technician</span>
          <select
            data-testid="filter-tech"
            className="w-full border rounded px-2 py-1.5"
            value={filters.tech_id}
            onChange={(e) =>
              setFilters((f) => ({ ...f, tech_id: e.target.value }))
            }
          >
            <option value="">All</option>
            {techs.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name || t.email}
              </option>
            ))}
          </select>
        </label>
        <div className="sm:col-span-2 lg:col-span-4 flex justify-end">
          <button
            data-testid="apply-filters-btn"
            onClick={load}
            disabled={loading}
            className="px-4 py-2 bg-slate-900 text-white rounded hover:bg-slate-800 disabled:opacity-50"
          >
            {loading ? "Loading…" : "Apply"}
          </button>
        </div>
      </div>

      {err && (
        <div
          data-testid="report-error"
          className="p-3 border border-red-300 bg-red-50 text-red-700 rounded"
        >
          {err}
        </div>
      )}

      {/* Totals */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <SummaryCard
          label="Total Chemical Spend"
          value={centsToUSD(totals.total_cost_cents)}
          testId="total-spend"
        />
        <SummaryCard
          label="Events"
          value={String(totals.event_count ?? 0)}
          testId="total-events"
        />
        <SummaryCard
          label="Total Quantity"
          value={String(totals.total_quantity ?? 0)}
          testId="total-quantity"
        />
      </div>

      {/* By department */}
      <Section title="By Department" testId="section-department">
        <Table
          columns={[
            { key: "department", label: "Department" },
            { key: "event_count", label: "Events" },
            {
              key: "quantity_used",
              label: "Qty",
              render: (v) => Number(v).toFixed(2),
            },
            {
              key: "total_cost_cents",
              label: "Cost",
              render: (v) => centsToUSD(v),
              className: "text-right font-medium",
            },
          ]}
          rows={perDept}
          emptyText="No department data in window."
          rowTestId={(r) => `dept-row-${r.department}`}
        />
      </Section>

      {/* By tech */}
      <Section title="By Technician" testId="section-tech">
        <Table
          columns={[
            { key: "name", label: "Tech" },
            { key: "department", label: "Dept." },
            { key: "event_count", label: "Events" },
            {
              key: "quantity_used",
              label: "Qty",
              render: (v) => Number(v).toFixed(2),
            },
            {
              key: "total_cost_cents",
              label: "Cost",
              render: (v) => centsToUSD(v),
              className: "text-right font-medium",
            },
          ]}
          rows={perTech}
          emptyText="No tech-attributed usage in window."
          rowTestId={(r) => `tech-row-${r.user_id}`}
        />
      </Section>

      {/* By product */}
      <Section title="By Product" testId="section-product">
        <Table
          columns={[
            { key: "name", label: "Product" },
            { key: "product_slug", label: "SKU" },
            { key: "event_count", label: "Events" },
            {
              key: "quantity_used",
              label: "Qty",
              render: (v, r) => `${Number(v).toFixed(2)} ${r.unit || ""}`,
            },
            {
              key: "total_cost_cents",
              label: "Cost",
              render: (v) => centsToUSD(v),
              className: "text-right font-medium",
            },
          ]}
          rows={perProduct}
          emptyText="No products in window."
          rowTestId={(r) => `prod-row-${r.product_slug}`}
        />
      </Section>
    </div>
  );
}

function SummaryCard({ label, value, testId }) {
  return (
    <div
      className="p-4 border rounded-lg bg-white"
      data-testid={`summary-${testId}`}
    >
      <div className="text-xs uppercase tracking-wider text-neutral-500">
        {label}
      </div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
    </div>
  );
}

function Section({ title, testId, children }) {
  return (
    <section data-testid={testId} className="space-y-3">
      <h2 className="text-xl font-medium">{title}</h2>
      {children}
    </section>
  );
}

function Table({ columns, rows, emptyText, rowTestId }) {
  if (!rows || rows.length === 0) {
    return (
      <div className="text-sm text-neutral-500 border border-dashed rounded p-6 text-center">
        {emptyText}
      </div>
    );
  }
  return (
    <div className="overflow-x-auto border rounded-lg bg-white">
      <table className="w-full text-sm">
        <thead className="bg-neutral-50">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={`text-left px-3 py-2 font-medium text-neutral-600 ${
                  c.className || ""
                }`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={i}
              className="border-t"
              data-testid={rowTestId ? rowTestId(r) : undefined}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={`px-3 py-2 ${c.className || ""}`}
                >
                  {c.render ? c.render(r[c.key], r) : r[c.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
