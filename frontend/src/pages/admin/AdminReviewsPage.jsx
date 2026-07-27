import React, { useEffect, useMemo, useState } from "react";
import { Star, RefreshCcw, ExternalLink, X as XIcon } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

/**
 * Feb-2026 · Slice 6 — Admin Reviews Dashboard.
 *
 * Lists every customer-portal review for the tenant (private + public)
 * with filters, quick status transitions, and a detail drawer for
 * admin notes / status changes.  Read-only cross-tenant safe — the
 * backend query is scoped by ``tenant_id`` on every read.
 */
export default function AdminReviewsPage() {
  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState({ total: 0, new_count: 0 });
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    status: "",
    is_public: "",
    min_rating: "",
    max_rating: "",
  });
  const [selected, setSelected] = useState(null);

  const load = () => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.is_public) params.set("is_public", filters.is_public);
    if (filters.min_rating) params.set("min_rating", filters.min_rating);
    if (filters.max_rating) params.set("max_rating", filters.max_rating);
    params.set("limit", "200");
    setLoading(true);
    api
      .get(`/admin/reviews?${params.toString()}`)
      .then((r) => {
        setRows(r.reviews || []);
        setMeta({
          total: r.total || 0,
          new_count: r.new_count || 0,
        });
      })
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };
  useEffect(load, [filters]);

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="admin-reviews-page">
      <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
            Reviews
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            {meta.total} total review{meta.total === 1 ? "" : "s"} · {meta.new_count} new
          </p>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold"
          style={{
            backgroundColor: colors.surfaceSecondary,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="admin-reviews-refresh"
        >
          <RefreshCcw size={14} /> Refresh
        </button>
      </div>

      {/* Filters */}
      <div
        className="rounded-xl p-3 mb-4 grid grid-cols-2 sm:grid-cols-4 gap-2"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
      >
        <FilterSelect
          label="STATUS"
          value={filters.status}
          onChange={(v) => setFilters((f) => ({ ...f, status: v }))}
          options={[
            { v: "", l: "Any" },
            { v: "new", l: "New" },
            { v: "read", l: "Read" },
            { v: "resolved", l: "Resolved" },
            { v: "escalated", l: "Escalated" },
          ]}
          testid="admin-reviews-filter-status"
        />
        <FilterSelect
          label="VISIBILITY"
          value={filters.is_public}
          onChange={(v) => setFilters((f) => ({ ...f, is_public: v }))}
          options={[
            { v: "", l: "Any" },
            { v: "true", l: "Public (≥4★)" },
            { v: "false", l: "Private (<4★)" },
          ]}
          testid="admin-reviews-filter-public"
        />
        <FilterSelect
          label="MIN RATING"
          value={filters.min_rating}
          onChange={(v) => setFilters((f) => ({ ...f, min_rating: v }))}
          options={[
            { v: "", l: "Any" },
            { v: "1", l: "1★" }, { v: "2", l: "2★" }, { v: "3", l: "3★" },
            { v: "4", l: "4★" }, { v: "5", l: "5★" },
          ]}
          testid="admin-reviews-filter-min"
        />
        <FilterSelect
          label="MAX RATING"
          value={filters.max_rating}
          onChange={(v) => setFilters((f) => ({ ...f, max_rating: v }))}
          options={[
            { v: "", l: "Any" },
            { v: "1", l: "1★" }, { v: "2", l: "2★" }, { v: "3", l: "3★" },
            { v: "4", l: "4★" }, { v: "5", l: "5★" },
          ]}
          testid="admin-reviews-filter-max"
        />
      </div>

      {/* Table */}
      <div
        className="rounded-2xl overflow-hidden"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
      >
        {loading ? (
          <div className="p-6 text-sm text-center" style={{ color: colors.muted }}>
            Loading reviews…
          </div>
        ) : rows.length === 0 ? (
          <div className="p-6 text-sm text-center" style={{ color: colors.muted }}>
            No reviews match these filters yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.divider}` }}>
                {["Date", "Customer", "Rating", "Comment", "Public", "Status"].map((h) => (
                  <th
                    key={h}
                    className="text-left py-2 px-3 text-xs font-bold uppercase tracking-wide"
                    style={{ color: colors.muted }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                // Phase 34 · Task T · Feb 2026 — surface two operational
                // signals inline on the row:
                //  * red "needs response" dot for any low-rating review
                //    (≤3★) that still sits in ``new`` — those are the
                //    tickets we want to intervene on before the customer
                //    escalates elsewhere.
                //  * "Posted to Google" pill for public 4-5★ reviews
                //    where the tenant's Google CTA was rendered
                //    (``google_redirect=true`` on the portal row, or
                //    ``google_click_at`` for magic-link Task T rows).
                const rating = r.rating || r.star_rating || 0;
                const status = (r.status || "").toLowerCase();
                const needsResponse = rating > 0 && rating <= 3 && status !== "resolved";
                const postedToGoogle = !!(r.google_click_at || r.google_redirect);
                return (
                <tr
                  key={r.id}
                  onClick={() => setSelected(r)}
                  className="cursor-pointer hover:brightness-95"
                  style={{ borderBottom: `1px solid ${colors.divider}` }}
                  data-testid={`admin-review-row-${r.id}`}
                >
                  <td className="py-3 px-3" style={{ color: colors.muted }}>
                    {String(r.created_at || "").slice(0, 10)}
                  </td>
                  <td className="py-3 px-3" style={{ color: colors.onSurface }}>
                    <span className="inline-flex items-center gap-1.5">
                      {needsResponse ? (
                        <span
                          className="inline-block rounded-full"
                          style={{
                            width: 8,
                            height: 8,
                            backgroundColor: "#DC2626",
                            boxShadow: "0 0 0 2px rgba(220,38,38,0.15)",
                          }}
                          title="Low-rating review needs a response"
                          aria-label="Needs response"
                          data-testid={`admin-review-needs-response-${r.id}`}
                        />
                      ) : null}
                      {r.customer_name || "—"}
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    <StarsInline value={rating} />
                  </td>
                  <td className="py-3 px-3 max-w-[300px] truncate"
                       style={{ color: colors.onSurfaceSecondary }}>
                    {r.comment || <span style={{ color: colors.muted }}>(no comment)</span>}
                  </td>
                  <td className="py-3 px-3">
                    <div className="inline-flex items-center gap-1">
                      <PublicBadge on={!!r.is_public} />
                      {postedToGoogle ? (
                        <span
                          className="text-[10px] font-bold px-1.5 py-0.5 rounded-full inline-flex items-center gap-1"
                          style={{ backgroundColor: "#DBEAFE", color: "#1E3A8A" }}
                          title="Customer was routed to Google to leave a public review"
                          data-testid={`admin-review-posted-google-${r.id}`}
                        >
                          <ExternalLink size={9} /> GOOGLE
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td className="py-3 px-3">
                    <StatusBadge status={r.status} />
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {selected ? (
        <ReviewDrawer
          review={selected}
          onClose={() => setSelected(null)}
          onSaved={(updated) => {
            setSelected(null);
            setRows((prev) =>
              prev.map((r) => (r.id === updated.id ? { ...r, ...updated } : r)),
            );
          }}
        />
      ) : null}
    </div>
  );
}

function FilterSelect({ label, value, onChange, options, testid }) {
  return (
    <label className="flex flex-col gap-1">
      <span
        className="text-[10px] font-bold uppercase tracking-wider"
        style={{ color: colors.muted }}
      >
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="px-2 py-1.5 rounded-lg text-sm outline-none"
        style={{
          backgroundColor: colors.surface,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid={testid}
      >
        {options.map((o) => (
          <option key={o.v} value={o.v}>
            {o.l}
          </option>
        ))}
      </select>
    </label>
  );
}

function StarsInline({ value }) {
  return (
    <span className="inline-flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((n) => (
        <Star
          key={n}
          size={13}
          fill={n <= value ? "#FBBF24" : "transparent"}
          style={{ color: n <= value ? "#FBBF24" : colors.border }}
        />
      ))}
      <span className="ml-1 text-xs" style={{ color: colors.muted }}>
        {value}/5
      </span>
    </span>
  );
}

function PublicBadge({ on }) {
  return (
    <span
      className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
      style={{
        backgroundColor: on ? "#DCFCE7" : "#FEF3C7",
        color: on ? "#166534" : "#92400E",
      }}
    >
      {on ? "PUBLIC" : "PRIVATE"}
    </span>
  );
}

function StatusBadge({ status }) {
  const style = {
    new:       { bg: "#DBEAFE", fg: "#1E3A8A" },
    read:      { bg: "#F1F5F9", fg: "#334155" },
    resolved:  { bg: "#DCFCE7", fg: "#166534" },
    escalated: { bg: "#FEE2E2", fg: "#991B1B" },
  }[status] || { bg: "#F1F5F9", fg: "#334155" };
  return (
    <span
      className="text-[10px] font-bold px-1.5 py-0.5 rounded-full uppercase tracking-wide"
      style={{ backgroundColor: style.bg, color: style.fg }}
    >
      {status || "—"}
    </span>
  );
}


function ReviewDrawer({ review, onClose, onSaved }) {
  const [status, setStatus] = useState(review.status || "new");
  const [notes, setNotes] = useState(review.admin_notes || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.patch(`/admin/reviews/${review.id}`, {
        status,
        admin_notes: notes,
        read: true,
      });
      onSaved?.(r);
    } catch (err) {
      setError(err?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose?.();
      }}
      data-testid="admin-review-detail"
    >
      <div
        className="w-full sm:w-[440px] h-full shadow-2xl flex flex-col"
        style={{
          backgroundColor: colors.surface,
          borderLeft: `1px solid ${colors.border}`,
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between px-5 pt-4 pb-3"
          style={{ borderBottom: `1px solid ${colors.divider}` }}
        >
          <div>
            <div className="text-xs" style={{ color: colors.muted }}>
              {String(review.created_at || "").slice(0, 16).replace("T", " ")}
            </div>
            <div className="text-lg font-bold" style={{ color: colors.onSurface }}>
              {review.customer_name || "Review"}
            </div>
            <div className="mt-1">
              <StarsInline value={review.rating || 0} />
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg"
            style={{ color: colors.muted }}
            aria-label="Close"
          >
            <XIcon size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          <div>
            <div
              className="text-[10px] font-bold uppercase tracking-wider mb-1"
              style={{ color: colors.muted }}
            >
              COMMENT
            </div>
            <div
              className="rounded-lg p-3 text-sm whitespace-pre-wrap"
              style={{
                backgroundColor: colors.surfaceSecondary,
                color: colors.onSurface,
                border: `1px solid ${colors.divider}`,
              }}
            >
              {review.comment || (
                <span style={{ color: colors.muted }}>(no comment provided)</span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 text-xs">
            <PublicBadge on={!!review.is_public} />
            {review.google_redirect ? (
              <span
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full"
                style={{
                  backgroundColor: "#DBEAFE",
                  color: "#1E3A8A",
                  fontWeight: 700,
                }}
              >
                <ExternalLink size={11} /> GOOGLE CTA SHOWN
              </span>
            ) : null}
            {review.customer_id ? (
              <a
                href={`/customers/${review.customer_id}`}
                className="text-xs font-semibold"
                style={{ color: colors.brand }}
              >
                Open customer →
              </a>
            ) : null}
          </div>

          <div>
            <div
              className="text-[10px] font-bold uppercase tracking-wider mb-1"
              style={{ color: colors.muted }}
            >
              STATUS
            </div>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-sm outline-none"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="admin-review-status-select"
            >
              {["new", "read", "resolved", "escalated"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          <div>
            <div
              className="text-[10px] font-bold uppercase tracking-wider mb-1"
              style={{ color: colors.muted }}
            >
              ADMIN NOTES
            </div>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={6}
              placeholder="Internal notes on how this review was handled…"
              className="w-full px-3 py-2 rounded-lg text-sm outline-none"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="admin-review-notes-input"
            />
          </div>

          {error ? (
            <div className="text-sm" style={{ color: colors.error }}>
              {error}
            </div>
          ) : null}
        </div>

        <div
          className="p-4 flex items-center justify-end gap-2"
          style={{ borderTop: `1px solid ${colors.divider}` }}
        >
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-sm font-semibold"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurface,
            }}
          >
            Cancel
          </button>
          <button
            onClick={save}
            disabled={busy}
            className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
            style={{ background: colors.brand }}
            data-testid="admin-review-save-btn"
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
