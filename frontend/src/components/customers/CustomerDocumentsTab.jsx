/**
 * Feb-2026 · Customer detail — unified "Sent documents" tab.
 *
 * Ships the admin ask: "on customer page admin give easy access to
 * view all sent quotes estimates invoices". Consolidates FOUR
 * per-customer document lists into one filterable+sortable table
 * so an admin doesn't have to bounce between the Quotes tab,
 * Invoices tab, and (in the future) Estimator screens to see
 * everything a customer has been sent.
 *
 * Sources merged (fan-out on the frontend — no new backend endpoint;
 * per audit brief §3, "reuse existing per-doc-type list endpoints"):
 *   1. GET /api/quotes?customer_id=X&doc_type=quote
 *   2. GET /api/quotes?customer_id=X&doc_type=invoice
 *      (invoices live in ``db.quotes`` since Phase 11 unification —
 *       legacy ``db.invoices`` was retired)
 *   3. GET /api/estimator/estimates?customer_id=X
 *      (current estimator collection ``db.estimator_estimates``)
 *   4. GET /api/estimates?customer_id=X
 *      (DEPRECATED but LIVE — legacy ``db.estimates`` still holds
 *       ~155 rows. Both estimate collections coexist per the
 *       Chunk 2.c audit — retirement is a scoped migration.)
 *
 * Row schema (unified):
 *   { id, type: "quote"|"invoice"|"estimate", number, title,
 *     date_iso, status, amount, _source: "quote"|"invoice"|
 *     "estimator"|"estimate-legacy" }
 *
 * Actions per row:
 *   * View  → ``/quotes/{id}`` for quote/invoice (Outcome C
 *             canonical), ``/estimator/estimates/{id}`` for estimator
 *             rows, ``/estimator/estimates/{id}`` alias-safe for
 *             legacy estimates (both surface the same viewer).
 *   * PDF   → opens ``/api/quotes/{id}/pdf`` for quote/invoice.
 *             Estimator rows expose the PDF via the viewer, so we
 *             route them to View instead. (No PDF endpoint exists
 *             for legacy ``db.estimates`` — hide the button for
 *             that source.)
 *   * Resend → POST ``/api/quotes/{qid}/send-reminder`` for INVOICE
 *             rows (existing endpoint; admin-only; unpaid-only).
 *             Estimator rows: POST
 *             ``/api/estimator/estimates/{eid}/send-to-customer``.
 *             Quote rows: no first-class "resend" endpoint —
 *             button hidden (View + regenerate flow lives on the
 *             quote detail page).
 *
 * Auth: matches the parent CustomerDetail page's ``<NoTech>`` gate
 * (admin, manager, owner, super_admin — techs not permitted). No
 * additional gate here — the tab only renders when the parent has
 * already rendered.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { FileText, Download, Eye, RefreshCw, Filter as FilterIcon } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { Skeleton, EmptyState, Toast, Button } from "@/components/ui-kit";

// ── Type-badge palette (visually distinguishes the three types
// at-a-glance; no dependency on the tech-color palette so a
// customer's docs read consistently regardless of tenant colors).
const TYPE_STYLES = {
  quote:    { bg: "#DBEAFE", fg: "#1E3A8A", label: "Quote" },
  invoice:  { bg: "#DCFCE7", fg: "#166534", label: "Invoice" },
  estimate: { bg: "#FEF3C7", fg: "#92400E", label: "Estimate" },
};

// ── Status pill palette. Draft is muted; sent = amber (in flight);
// accepted / paid = green; declined / void = red. Unknown statuses
// fall through to a neutral slate so we never crash on unexpected
// data.
const STATUS_STYLES = {
  draft:     { bg: "#F1F5F9", fg: "#334155" },
  sent:      { bg: "#FEF3C7", fg: "#92400E" },
  viewed:    { bg: "#DBEAFE", fg: "#1E3A8A" },
  accepted:  { bg: "#DCFCE7", fg: "#166534" },
  declined:  { bg: "#FEE2E2", fg: "#991B1B" },
  paid:      { bg: "#DCFCE7", fg: "#166534" },
  unpaid:    { bg: "#FEF3C7", fg: "#92400E" },
  overdue:   { bg: "#FEE2E2", fg: "#991B1B" },
  void:      { bg: "#FEE2E2", fg: "#991B1B" },
  cancelled: { bg: "#FEE2E2", fg: "#991B1B" },
};

function _statusLabel(row) {
  // For invoices, payment_status is the operationally-interesting
  // status ("paid" / "unpaid" / "overdue") — surface that ahead of
  // the workflow "status" ("sent" / etc.). Falls back to workflow
  // status when payment_status is missing.
  if (row.type === "invoice") {
    const ps = (row.payment_status || "").toLowerCase();
    if (ps) return ps;
  }
  return (row.status || "sent").toLowerCase();
}

function _pill(text) {
  const style = STATUS_STYLES[text] || { bg: "#F1F5F9", fg: "#334155" };
  return (
    <span
      className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
      style={{ background: style.bg, color: style.fg }}
    >
      {text}
    </span>
  );
}

function _typeBadge(type) {
  const s = TYPE_STYLES[type] || TYPE_STYLES.quote;
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide"
      style={{ background: s.bg, color: s.fg }}
      data-testid={`customer-docs-type-badge-${type}`}
    >
      <FileText size={10} />
      {s.label}
    </span>
  );
}

// ── Row normalisers — each source returns a slightly different
// shape so we flatten into a common row schema before the merge.
function _normalizeQuote(q) {
  return {
    id: q.id,
    type: "quote",
    number: q.number || q.id?.slice(-6),
    title: q.title || q.customer_name || "(untitled quote)",
    date_iso: q.updated_at || q.created_at || q.sent_at,
    status: q.status || "sent",
    payment_status: q.payment_status,
    amount: Number(q.total || 0),
    _source: "quote",
  };
}

function _normalizeInvoice(q) {
  return {
    ..._normalizeQuote(q),
    type: "invoice",
    _source: "invoice",
  };
}

function _normalizeEstimatorEstimate(e) {
  return {
    id: e.id,
    type: "estimate",
    number: e.number || e.id?.slice(-6),
    title: e.title || e.customer_name || "(untitled estimate)",
    date_iso: e.sent_at || e.updated_at || e.created_at,
    status: e.status || "draft",
    amount: Number(e.total || e.subtotal || 0),
    _source: "estimator",
  };
}

function _normalizeLegacyEstimate(e) {
  return {
    id: e.id,
    type: "estimate",
    number: e.number || e.id?.slice(-6),
    title: e.title || e.customer_name || "(untitled estimate)",
    date_iso: e.updated_at || e.created_at,
    status: e.status || "draft",
    amount: Number(e.total || e.subtotal || 0),
    _source: "estimate-legacy",
  };
}

function _fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleDateString(undefined, {
      year: "numeric", month: "short", day: "numeric",
    });
  } catch { return "—"; }
}


export default function CustomerDocumentsTab({ customerId }) {
  const [rows, setRows] = useState(null);       // null = loading, [] = empty, [...] = data
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);
  // Filters. Types = multi-select bitmap; single-doc-type toggles
  // are the common UX (Quotes only, Invoices only, etc.), so we
  // model them as a Set instead of an array.
  const [typeFilter, setTypeFilter] = useState(new Set(["quote", "invoice", "estimate"]));
  const [statusFilter, setStatusFilter] = useState("all");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [sending, setSending] = useState(null);   // row.id currently being resent

  // ── Fan-out fetch. Runs on mount and whenever ``customerId``
  // changes. Any single failure logs to console but doesn't
  // prevent the other three from rendering (the deprecated
  // /estimates endpoint is the most likely to 404 on new tenants
  // and shouldn't take the tab down with it).
  const load = React.useCallback(async () => {
    if (!customerId) return;
    setRows(null);
    setError(null);
    const [q, i, es, ee] = await Promise.allSettled([
      api.get(`/quotes?customer_id=${customerId}&doc_type=quote`),
      api.get(`/quotes?customer_id=${customerId}&doc_type=invoice`),
      api.get(`/estimator/estimates?customer_id=${customerId}`),
      api.get(`/estimates?customer_id=${customerId}`),
    ]);
    // Endpoint response-shape normaliser. ``/quotes`` and the
    // legacy ``/estimates`` return a bare array; ``/estimator/
    // estimates`` returns ``{items, total}``. Coerce both to an
    // array before mapping so a shape drift doesn't crash the tab.
    const _arr = (v) => Array.isArray(v) ? v
                    : (v && Array.isArray(v.items) ? v.items : []);
    const flat = [
      ...(q.status === "fulfilled" ? _arr(q.value).map(_normalizeQuote) : []),
      ...(i.status === "fulfilled" ? _arr(i.value).map(_normalizeInvoice) : []),
      ...(es.status === "fulfilled" ? _arr(es.value).map(_normalizeEstimatorEstimate) : []),
      ...(ee.status === "fulfilled" ? _arr(ee.value).map(_normalizeLegacyEstimate) : []),
    ];
    // Default sort: newest first.
    flat.sort((a, b) => (b.date_iso || "").localeCompare(a.date_iso || ""));
    setRows(flat);
  }, [customerId]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    if (!rows) return null;
    return rows.filter((r) => {
      if (!typeFilter.has(r.type)) return false;
      if (statusFilter !== "all") {
        const s = _statusLabel(r);
        if (s !== statusFilter) return false;
      }
      if (fromDate && r.date_iso && r.date_iso.slice(0, 10) < fromDate) return false;
      if (toDate && r.date_iso && r.date_iso.slice(0, 10) > toDate) return false;
      return true;
    });
  }, [rows, typeFilter, statusFilter, fromDate, toDate]);

  const toggleType = (t) => {
    setTypeFilter((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  };

  const _API_BASE = process.env.REACT_APP_BACKEND_URL || "";

  const onPdf = (row) => {
    if (row.type === "estimate") return;   // No PDF endpoint for estimator/legacy — routed to View.
    // /quotes/{id}/pdf covers both doc_type=quote and doc_type=invoice.
    const url = `${_API_BASE}/api/quotes/${encodeURIComponent(row.id)}/pdf`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const onResend = async (row) => {
    setSending(row.id);
    try {
      if (row.type === "invoice") {
        // Reminder is the only "resend" surface for invoices.
        // Backend guards against paid invoices and missing customer.
        await api.post(`/quotes/${encodeURIComponent(row.id)}/send-reminder`);
        setToast({ tone: "success", message: "Reminder queued" });
      } else if (row._source === "estimator") {
        await api.post(`/estimator/estimates/${encodeURIComponent(row.id)}/send-to-customer`);
        setToast({ tone: "success", message: "Estimate sent" });
      } else {
        // Quote / legacy estimate — no first-class resend endpoint.
        // Row-level UI hides the button; this is a defensive no-op.
        setToast({ tone: "error", message: "No resend endpoint for this document type" });
      }
    } catch (e) {
      setToast({ tone: "error", message: e?.message || "Failed to resend" });
    } finally {
      setSending(null);
    }
  };

  const _viewHrefFor = (row) => {
    if (row.type === "estimate") {
      return `/estimator/estimates/${encodeURIComponent(row.id)}`;
    }
    // Outcome C canonical — quote & invoice share the /quotes/:id
    // viewer.
    return `/quotes/${encodeURIComponent(row.id)}`;
  };

  if (rows === null) {
    return (
      <div data-testid="customer-docs-loading">
        <Skeleton style={{ height: 320 }} />
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="customer-documents-tab">
      {/* ── Filter row ── */}
      <div
        className="flex flex-wrap items-end gap-3 p-3 rounded-xl"
        style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
        data-testid="customer-docs-filters"
      >
        <div>
          <div className="text-[10px] font-bold uppercase mb-1" style={{ color: colors.muted }}>
            Type
          </div>
          <div className="flex items-center gap-1">
            {["quote", "invoice", "estimate"].map((t) => {
              const on = typeFilter.has(t);
              const s = TYPE_STYLES[t];
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => toggleType(t)}
                  className="text-xs font-semibold px-2 py-1 rounded-md"
                  style={{
                    background: on ? s.bg : colors.surface,
                    color: on ? s.fg : colors.muted,
                    border: `1px solid ${on ? s.fg : colors.border}`,
                  }}
                  data-testid={`customer-docs-filter-type-${t}`}
                  data-active={on ? "true" : "false"}
                >
                  {s.label}
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <div className="text-[10px] font-bold uppercase mb-1" style={{ color: colors.muted }}>
            Status
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-xs rounded-md px-2 py-1"
            style={{
              background: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="customer-docs-filter-status"
          >
            <option value="all">All statuses</option>
            <option value="draft">Draft</option>
            <option value="sent">Sent</option>
            <option value="viewed">Viewed</option>
            <option value="accepted">Accepted</option>
            <option value="declined">Declined</option>
            <option value="paid">Paid</option>
            <option value="unpaid">Unpaid</option>
            <option value="overdue">Overdue</option>
            <option value="void">Void</option>
          </select>
        </div>

        <div>
          <div className="text-[10px] font-bold uppercase mb-1" style={{ color: colors.muted }}>
            From
          </div>
          <input
            type="date"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
            className="text-xs rounded-md px-2 py-1"
            style={{
              background: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="customer-docs-filter-from"
          />
        </div>
        <div>
          <div className="text-[10px] font-bold uppercase mb-1" style={{ color: colors.muted }}>
            To
          </div>
          <input
            type="date"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
            className="text-xs rounded-md px-2 py-1"
            style={{
              background: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="customer-docs-filter-to"
          />
        </div>

        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs" style={{ color: colors.muted }}>
            {filtered ? filtered.length : 0} of {rows.length}
          </span>
          <Button
            variant="ghost"
            onClick={load}
            testid="customer-docs-refresh"
          >
            <RefreshCw size={12} /> Refresh
          </Button>
        </div>
      </div>

      {/* ── Table ── */}
      {(filtered || []).length === 0 ? (
        <div data-testid="customer-docs-empty">
          <EmptyState
            icon={FileText}
            title="No documents sent yet"
            hint="Quotes, invoices and estimates for this customer will appear here."
          />
        </div>
      ) : (
        <div
          className="rounded-xl overflow-hidden"
          style={{ border: `1px solid ${colors.border}` }}
          data-testid="customer-docs-list"
        >
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: colors.surfaceSecondary }}>
                <th className="text-left px-3 py-2 text-[10px] uppercase font-bold" style={{ color: colors.muted }}>Type</th>
                <th className="text-left px-3 py-2 text-[10px] uppercase font-bold" style={{ color: colors.muted }}>Number / Title</th>
                <th className="text-left px-3 py-2 text-[10px] uppercase font-bold" style={{ color: colors.muted }}>Date</th>
                <th className="text-left px-3 py-2 text-[10px] uppercase font-bold" style={{ color: colors.muted }}>Status</th>
                <th className="text-right px-3 py-2 text-[10px] uppercase font-bold" style={{ color: colors.muted }}>Amount</th>
                <th className="text-right px-3 py-2 text-[10px] uppercase font-bold" style={{ color: colors.muted }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => {
                const canResend =
                  row.type === "invoice" || row._source === "estimator";
                const canPdf = row.type !== "estimate";
                return (
                  <tr
                    key={`${row._source}-${row.id}`}
                    data-testid={`customer-docs-row-${row.id}`}
                    data-doc-type={row.type}
                    style={{ borderTop: `1px solid ${colors.border}` }}
                  >
                    <td className="px-3 py-2">{_typeBadge(row.type)}</td>
                    <td className="px-3 py-2">
                      <div className="font-semibold" style={{ color: colors.onSurface }}>
                        #{row.number}
                      </div>
                      <div className="text-xs" style={{ color: colors.muted }}>
                        {row.title}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-xs" style={{ color: colors.onSurface }}>
                      {_fmtDate(row.date_iso)}
                    </td>
                    <td className="px-3 py-2">{_pill(_statusLabel(row))}</td>
                    <td className="px-3 py-2 text-right font-semibold" style={{ color: colors.onSurface }}>
                      {money ? money(row.amount) : `$${row.amount.toFixed(2)}`}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center justify-end gap-1">
                        <Link
                          to={_viewHrefFor(row)}
                          className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-md"
                          style={{
                            background: colors.surfaceSecondary,
                            color: colors.brand,
                            border: `1px solid ${colors.border}`,
                          }}
                          data-testid={`customer-docs-action-view-${row.id}`}
                        >
                          <Eye size={11} /> View
                        </Link>
                        {canPdf ? (
                          <button
                            type="button"
                            onClick={() => onPdf(row)}
                            className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-md"
                            style={{
                              background: colors.surfaceSecondary,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}`,
                            }}
                            data-testid={`customer-docs-action-pdf-${row.id}`}
                          >
                            <Download size={11} /> PDF
                          </button>
                        ) : null}
                        {canResend ? (
                          <button
                            type="button"
                            disabled={sending === row.id}
                            onClick={() => onResend(row)}
                            className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-md"
                            style={{
                              background: colors.surfaceSecondary,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}`,
                              opacity: sending === row.id ? 0.5 : 1,
                            }}
                            data-testid={`customer-docs-action-resend-${row.id}`}
                          >
                            <RefreshCw size={11} />
                            {sending === row.id ? "Sending…" : "Resend"}
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}
