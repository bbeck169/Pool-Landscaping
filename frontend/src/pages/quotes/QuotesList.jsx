import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Plus, Search, FileText, Eye, DollarSign, Hash, Layers } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { formatCustomerName } from "@/utils/formatCustomerName";
import { CustomerLink } from "@/components/customer";
import { PageHeader, Button, Skeleton, StatusPill, EmptyState } from "@/components/ui-kit";
import CustomerFilterBar from "@/components/customers/CustomerFilterBar";
import { formatRelativeFromIso } from "@/lib/relativeTime";
// QUOTES-SUMMARY · Feb-2026 — shared summary card (extracted from
// InvoicesList's inline helper) so the two pages read on identical
// tile shells.
import SummaryTile from "@/components/SummaryTile";

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

  // QUOTES-SUMMARY · Feb-2026 — client-side summary numbers derived
  // from the full loaded ``rows`` set (NOT ``filtered``) so the
  // dashboard tiles reflect the account-wide picture regardless of
  // the search / status / customer filter currently applied to the
  // table.  Row-level status resolution matches the ``StatusPill``
  // resolution in the table body: ``decision`` beats ``status`` so a
  // customer-accepted quote counts as Accepted even if the sender
  // never bumped ``status``.
  const summary = useMemo(() => {
    const list = rows || [];
    const totalValue = list.reduce(
      (acc, r) => acc + (Number(r.total) || 0),
      0,
    );
    const bucket = { draft: 0, sent: 0, accepted: 0, approved: 0, declined: 0 };
    for (const r of list) {
      const effective = r.decision || r.status;
      if (effective in bucket) bucket[effective] += 1;
    }
    return { totalValue, totalCount: list.length, stages: bucket };
  }, [rows]);

  // Pill palette for the Stage Breakdown tile.  Direct hex on the
  // pills — this is an admin-side page so no ``.portal-dark``
  // overrides apply, and inline hex is immune to any global class
  // remaps.
  const STAGE_PILLS = [
    { key: "draft",    fg: "#3F3F46", bg: "#E4E4E7" },
    { key: "sent",     fg: "#1D4ED8", bg: "#DBEAFE" },
    { key: "accepted", fg: "#047857", bg: "#D1FAE5" },
    { key: "approved", fg: "#047857", bg: "#D1FAE5" },
    { key: "declined", fg: "#B91C1C", bg: "#FEE2E2" },
  ];

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

      {/* QUOTES-SUMMARY · Feb-2026 — Summary tiles.  Rendered
          BETWEEN the PageHeader and the customer-scoped filter bar
          so the dashboard numbers are always visible before the
          filter/table region. */}
      {rows !== null ? (
        <div
          className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-4"
          data-testid="quotes-summary-tiles"
        >
          <SummaryTile
            icon={DollarSign}
            tone={colors.success}
            label="Total Value"
            value={money(summary.totalValue)}
            testid="quotes-summary-tile-value"
          />
          <SummaryTile
            icon={Hash}
            tone="#4338CA"
            label="Total Count"
            value={String(summary.totalCount)}
            testid="quotes-summary-tile-count"
          />
          <SummaryTile
            icon={Layers}
            tone="#0891B2"
            label="Stage Breakdown"
            testid="quotes-summary-tile-stages"
          >
            <div className="flex flex-wrap gap-1.5">
              {STAGE_PILLS.map((s) => (
                <span
                  key={s.key}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold"
                  style={{ backgroundColor: s.bg, color: s.fg }}
                  data-testid={`quotes-summary-stage-${s.key}`}
                >
                  <span className="capitalize">{s.key}</span>
                  <span
                    className="tabular-nums"
                    data-testid={`quotes-summary-stage-${s.key}-count`}
                  >
                    {summary.stages[s.key]}
                  </span>
                </span>
              ))}
            </div>
          </SummaryTile>
        </div>
      ) : null}

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
            className="w-full pl-9 pr-3 py-2.5 rounded-lg outline-none text-sm focus:ring-2 placeholder:text-zinc-400"
            style={{ backgroundColor: colors.surface, border: '1px solid ' + colors.border, color: colors.onSurface }}
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
                {/* QV-ui · Feb-2026 — customer-engagement signal.
                    Populated by the QV-service view tracker
                    (portal-authenticated customer views + public
                    tokenized magic-link opens). Hidden on <lg
                    screens to match the InvoicesList sibling. */}
                <th className="text-left px-3 py-2 font-semibold hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }}>Viewed</th>
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
                  {/* QV-ui · Feb-2026 — Viewed indicator cell. Wire
                      target for the ``quote-viewed-${id}`` testid.
                      Uses the shared ``formatRelativeFromIso`` so
                      the wording matches the InvoicesList sibling
                      byte-for-byte. */}
                  <td
                    className="px-3 py-3 hidden lg:table-cell"
                    style={{ color: colors.onSurfaceSecondary }}
                    data-testid={`quote-viewed-${r.id}`}
                  >
                    {r.first_viewed_at ? (
                      <span title={r.last_viewed_at || r.first_viewed_at} className="inline-flex items-center gap-1 text-xs">
                        <Eye size={12} aria-hidden />
                        {formatRelativeFromIso(r.last_viewed_at || r.first_viewed_at) || "seen"}
                        {r.view_count > 1 ? (
                          <span className="ml-1 text-[10px]" style={{ color: colors.muted }} data-testid={`quote-view-count-${r.id}`}>
                            ({r.view_count}×)
                          </span>
                        ) : null}
                      </span>
                    ) : (
                      <span className="text-xs" style={{ color: colors.muted }}>—</span>
                    )}
                  </td>
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
