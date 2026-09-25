/**
 * Task N · Phase N · Feb-2026 — Notes Archive admin page.
 *
 * Route: ``/admin/comms/notes-archive`` (see App.js AdminRoute wire).
 * Backed by ``GET /api/service-reports/archive`` (Commit 1).
 *
 * Reuses ``NavyFilterBar`` verbatim per the Task E compound API and
 * matches the sidebar Communications group's chrome.
 *
 * Columns:
 *   1. Date         — SR.submitted_at (locale-formatted)
 *   2. Customer     — joined jobs.customer_id → customers.name
 *   3. Tech Name    — joined SR.tech_id → users.name
 *   4. Industry     — Pool / Landscaping / Service (template → industry map)
 *   5. Note Content — 3 stacked labeled paragraphs (notes /
 *                     internal_notes / customer_notes).  Each field
 *                     truncated at 140 chars with a ``See more`` /
 *                     ``See less`` per-field toggle. Empty fields
 *                     are omitted so single-note SRs render compact.
 *
 * Filters (NavyFilterBar):
 *   • Search       (customer_search)
 *   • Date From    (date_from, YYYY-MM-DD)
 *   • Date To      (date_to,   YYYY-MM-DD)
 *   • Tech         (tech_id — dropdown populated from /api/technicians)
 *   • Industry     (Pool / Landscaping / Service / All)
 *
 * Pagination: server-side offset (page, page_size).  25 / 50 / 100
 * selector; default 50 per user spec.
 *
 * Admin-only route guard is applied in App.js — this page renders
 * as if the caller is admin.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { colors } from "@/theme";
import { api } from "@/api";
import NavyFilterBar from "@/components/ui/NavyFilterBar";


const NOTE_FIELDS = [
  { key: "notes", label: "Notes" },
  { key: "internal_notes", label: "Internal" },
  { key: "customer_notes", label: "Customer" },
];
const TRUNCATE_AT = 140;


function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}


function ExpandableNote({ srId, fieldKey, label, text }) {
  const [expanded, setExpanded] = useState(false);
  if (!text) return null;
  const isLong = text.length > TRUNCATE_AT;
  const previewText = isLong ? `${text.slice(0, TRUNCATE_AT)}…` : text;
  return (
    <div className="mb-1 last:mb-0 text-xs leading-relaxed">
      <span
        className="font-semibold mr-1"
        style={{ color: colors.onSurfaceSecondary }}
      >
        {label}:
      </span>
      {(!expanded || !isLong) ? (
        <span
          data-testid={`notes-archive-row-${srId}-${fieldKey}-preview`}
          style={{ color: colors.onSurface }}
        >
          {previewText}
        </span>
      ) : (
        <span
          data-testid={`notes-archive-row-${srId}-${fieldKey}-full`}
          style={{ color: colors.onSurface }}
        >
          {text}
        </span>
      )}
      {isLong ? (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          data-testid={`notes-archive-row-${srId}-${fieldKey}-toggle`}
          className="ml-1.5 text-xs underline"
          style={{ color: colors.brand || colors.inputBorder }}
        >
          {expanded ? "See less" : "See more"}
        </button>
      ) : null}
    </div>
  );
}


export default function NotesArchive() {
  const [q, setQ] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [techId, setTechId] = useState("");
  const [industry, setIndustry] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [rows, setRows] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [techs, setTechs] = useState([]);

  // ── Fetch tech dropdown once on mount ───────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get("/technicians");
        if (cancelled) return;
        setTechs(Array.isArray(res) ? res : (res?.technicians || []));
      } catch (_) {
        // Non-blocking; tech filter simply stays empty.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // ── Build the archive query string ─────────────────────────
  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    if (q.trim()) params.set("customer_search", q.trim());
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    if (techId) params.set("tech_id", techId);
    if (industry) params.set("industry", industry);
    return params.toString();
  }, [q, dateFrom, dateTo, techId, industry, page, pageSize]);

  // ── Fetch archive on filter/page change ────────────────────
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.get(`/service-reports/archive?${queryString}`);
      setRows(res?.rows || []);
      setTotalCount(res?.total_count || 0);
    } catch (e) {
      setError(String(e?.message || e || "failed to load archive"));
      setRows([]);
      setTotalCount(0);
    } finally {
      setLoading(false);
    }
  }, [queryString]);

  useEffect(() => { load(); }, [load]);

  // ── Reset page when filters change ─────────────────────────
  useEffect(() => { setPage(1); },
    [q, dateFrom, dateTo, techId, industry, pageSize]);

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));

  // ── Render ─────────────────────────────────────────────────
  return (
    <div
      className="p-6"
      data-testid="notes-archive-page"
      style={{ color: colors.onSurface }}
    >
      <h1
        className="text-2xl font-bold mb-2"
        style={{ color: colors.onSurface }}
      >
        Notes Archive
      </h1>
      <p
        className="text-sm mb-4"
        style={{ color: colors.onSurfaceSecondary }}
      >
        Submitted service reports with any note field populated —
        merged across pool + landscape visits.
      </p>

      <NavyFilterBar data-testid="notes-archive-filters">
        <NavyFilterBar.Search
          value={q}
          onChange={setQ}
          placeholder="Search customer name…"
          ariaLabel="Search customer name"
          onClear={() => setQ("")}
          data-testid="notes-archive-search"
        />
        <NavyFilterBar.DatePicker
          label="From"
          value={dateFrom}
          onChange={setDateFrom}
          ariaLabel="Date from"
          data-testid="notes-archive-date-from"
        />
        <NavyFilterBar.DatePicker
          label="To"
          value={dateTo}
          onChange={setDateTo}
          ariaLabel="Date to"
          data-testid="notes-archive-date-to"
        />
        <NavyFilterBar.Select
          label="Tech"
          value={techId}
          onChange={setTechId}
          ariaLabel="Filter by tech"
          data-testid="notes-archive-tech-filter"
          minWidth={160}
        >
          <option value="">All techs</option>
          {techs.map((t) => (
            <option key={t.id} value={t.id}>{t.name || t.email || t.id}</option>
          ))}
        </NavyFilterBar.Select>
        <NavyFilterBar.Select
          label="Industry"
          value={industry}
          onChange={setIndustry}
          ariaLabel="Filter by industry"
          data-testid="notes-archive-industry-filter"
          minWidth={140}
        >
          <option value="">All industries</option>
          <option value="Pool">Pool</option>
          <option value="Landscaping">Landscaping</option>
          <option value="Service">Service</option>
        </NavyFilterBar.Select>
      </NavyFilterBar>

      {loading ? (
        <div
          className="py-8 text-center text-sm"
          data-testid="notes-archive-loading"
          style={{ color: colors.onSurfaceSecondary }}
        >
          Loading…
        </div>
      ) : error ? (
        <div
          className="py-6 px-4 rounded-lg text-sm"
          data-testid="notes-archive-error"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
            color: colors.onSurface,
          }}
        >
          {error}
        </div>
      ) : rows.length === 0 ? (
        <div
          className="py-8 text-center text-sm"
          data-testid="notes-archive-empty"
          style={{ color: colors.onSurfaceSecondary }}
        >
          No notes found matching filters.
        </div>
      ) : (
        <div
          className="rounded-2xl overflow-hidden"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
        >
          <table
            className="w-full text-sm"
            data-testid="notes-archive-table"
          >
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary || colors.surface }}>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Date</th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Customer</th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Tech Name</th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Industry</th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Note Content</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.sr_id}
                  data-testid={`notes-archive-row-${row.sr_id}`}
                  style={{ borderTop: `1px solid ${colors.border}` }}
                >
                  <td className="px-3 py-2 align-top whitespace-nowrap" data-testid={`notes-archive-row-${row.sr_id}-date`}>
                    {formatDate(row.submitted_at)}
                  </td>
                  <td className="px-3 py-2 align-top" data-testid={`notes-archive-row-${row.sr_id}-customer`}>
                    {row.customer_name || <span style={{ color: colors.onSurfaceSecondary }}>—</span>}
                  </td>
                  <td className="px-3 py-2 align-top" data-testid={`notes-archive-row-${row.sr_id}-tech`}>
                    {row.tech_name || <span style={{ color: colors.onSurfaceSecondary }}>—</span>}
                  </td>
                  <td className="px-3 py-2 align-top" data-testid={`notes-archive-row-${row.sr_id}-industry`}>
                    {row.industry}
                  </td>
                  <td className="px-3 py-2 align-top" data-testid={`notes-archive-row-${row.sr_id}-notes-cell`}>
                    {NOTE_FIELDS.map((f) => (
                      <ExpandableNote
                        key={f.key}
                        srId={row.sr_id}
                        fieldKey={f.key}
                        label={f.label}
                        text={row[f.key] || ""}
                      />
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination footer */}
      <div
        className="mt-4 flex flex-wrap items-center gap-3 text-sm"
        data-testid="notes-archive-pagination"
        style={{ color: colors.onSurfaceSecondary }}
      >
        <span data-testid="notes-archive-page-indicator">
          Page {page} of {totalPages} · {totalCount} rows
        </span>
        <button
          type="button"
          disabled={page <= 1 || loading}
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          data-testid="notes-archive-prev-btn"
          className="px-3 py-1.5 rounded-lg text-xs font-semibold"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
            color: colors.onSurface,
            opacity: page <= 1 || loading ? 0.4 : 1,
            cursor: page <= 1 || loading ? "not-allowed" : "pointer",
          }}
        >
          Prev
        </button>
        <button
          type="button"
          disabled={page >= totalPages || loading}
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          data-testid="notes-archive-next-btn"
          className="px-3 py-1.5 rounded-lg text-xs font-semibold"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
            color: colors.onSurface,
            opacity: page >= totalPages || loading ? 0.4 : 1,
            cursor: page >= totalPages || loading ? "not-allowed" : "pointer",
          }}
        >
          Next
        </button>
        <label className="flex items-center gap-2">
          <span>Per page:</span>
          <select
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
            data-testid="notes-archive-page-size"
            className="text-xs px-2 py-1 rounded"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </label>
      </div>
    </div>
  );
}
