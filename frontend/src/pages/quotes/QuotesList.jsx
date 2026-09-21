import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Plus, Search, FileText } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { formatCustomerName } from "@/utils/formatCustomerName";
import { CustomerLink } from "@/components/customer";
import { PageHeader, Button, Skeleton, StatusPill, EmptyState } from "@/components/ui-kit";
import CustomerFilterBar from "@/components/customers/CustomerFilterBar";

const STATUSES = ["draft", "sent", "approved", "declined", "expired"];

export default function QuotesList() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState(params.get("q") || "");
  const status = params.get("status") || "";
  // Feb-2026 · Item 2 — customer-scoped filter (URL-persisted).
  const customerFilter = params.get("customer_id") || null;
  const setCustomerFilter = (id) => {
    const s = new URLSearchParams(params);
    if (id) s.set("customer_id", id);
    else s.delete("customer_id");
    setParams(s, { replace: true });
  };

  const setStatus = (v) => {
    const s = new URLSearchParams(params);
    if (v) s.set("status", v);
    else s.delete("status");
    setParams(s, { replace: true });
  };

  // Phase C · Feb-2026 — "Has declined items" filter chip.
  const hasDeclined = params.get("has_declined") === "1";
  const setHasDeclined = (v) => {
    const s = new URLSearchParams(params);
    if (v) s.set("has_declined", "1");
    else s.delete("has_declined");
    setParams(s, { replace: true });
  };

  useEffect(() => {
    const qs = new URLSearchParams({ doc_type: "quote" });
    if (customerFilter) qs.set("customer_id", customerFilter);
    api
      .get(`/quotes?${qs.toString()}`)
      .then((r) => setRows(r || []))
      .catch(() => setRows([]));
  }, [customerFilter]);

  const filtered = (rows || [])
    .filter((r) => (status ? r.status === status || r.decision === status : true))
    .filter((r) => (hasDeclined ? Boolean(r.has_declined_lines) : true))
    .filter((r) =>
      q
        ? [r.title, r.customer_name].filter(Boolean).some((s) => s.toLowerCase().includes(q.toLowerCase()))
        : true
    );

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="quotes-page">
      <PageHeader
        title="Quotes"
        subtitle={`${filtered.length} shown`}
        right={
          <Button onClick={() => navigate("/quotes/new")} testid="quotes-new">
            <Plus size={16} /> New Quote
          </Button>
        }
      />

      <div className="mb-3">
        <CustomerFilterBar
          value={customerFilter}
          onChange={setCustomerFilter}
          testId="quotes-filter-customer"
        />
      </div>

      <div
        className="rounded-2xl p-4 mb-4 flex flex-wrap gap-3 items-center"
        style={{ backgroundColor: colors.nav.bg, border: `1px solid ${colors.nav.border}` }}
        data-testid="quotes-filters"
        data-k52-navy-strip="true"
      >
        <div className="relative flex-1 min-w-[220px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: colors.searchIcon }} />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search title, customer…"
            className="w-full pl-9 pr-3 py-2.5 rounded-lg outline-none text-sm focus:ring-2 placeholder:text-white/70"
            style={{ backgroundColor: "rgba(255,255,255,0.10)", border: `1px solid ${colors.nav.border}`, color: colors.nav.fg }}
            data-testid="quotes-search"
          />
        </div>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="text-xs font-semibold px-3 py-2 rounded-lg"
          style={{
            backgroundColor: colors.nav.bg,
            color: colors.nav.fg,
            border: `1px solid ${colors.nav.border}`,
          }}
          data-testid="quotes-filter-status"
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s[0].toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
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
      </div>

      {rows === null ? (
        <Skeleton style={{ height: 240 }} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No quotes yet"
          hint="Create a quote for a customer to see it here."
          action={<Button onClick={() => navigate("/quotes/new")}>New quote</Button>}
        />
      ) : (
        <div
          className="rounded-2xl overflow-hidden"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <table className="w-full text-sm" data-testid="quotes-table">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Quote</th>
                <th className="text-left px-3 py-2 font-semibold hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>Customer</th>
                <th className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Amount</th>
                <th className="text-right px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => navigate(`/quotes/${r.id}`)}
                  className="cursor-pointer hover:bg-zinc-50"
                  style={{ borderTop: `1px solid ${colors.divider}` }}
                  data-testid={`quote-row-${r.id}`}
                >
                  <td className="px-3 py-3 font-semibold" style={{ color: colors.onSurface }}>{r.title}</td>
                  <td className="px-3 py-3 hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }} data-testid={`quote-row-customer-${r.id}`}><CustomerLink customerId={r.customer_id} name={formatCustomerName(r)} /></td>
                  <td className="px-3 py-3 text-right font-semibold" style={{ color: colors.onSurface }}>{money(r.total)}</td>
                  <td className="px-3 py-3 text-right"><StatusPill status={r.decision || r.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
