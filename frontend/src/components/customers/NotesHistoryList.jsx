/**
 * Task N Round 2 · Phase N.7 · Feb-2026 — Notes History list component.
 *
 * Renders paginated per-customer SR notes with the SAME row shape
 * as the tenant-wide archive.  Backed by
 * ``GET /api/customers/{cid}/notes-history``.
 *
 * Two modes:
 *   1. Full (default): all filters absent (backend serves newest-
 *      first with page_size=20), Prev/Next pagination footer, all
 *      states (loading/empty/error).  Used in the CustomerDetail
 *      "Notes" tab.
 *   2. Compact (``compact`` prop): fetches page_size=3, hides the
 *      pagination footer, shows a "See all N notes →" link when
 *      ``total_count > 3``.  Used in the CustomerDetail "About"
 *      section preview.
 *
 * Note-content rendering matches the archive page: 3 stacked
 * labeled paragraphs (notes / internal / customer) per row, each
 * truncated at 140 chars with a per-field ``See more`` /
 * ``See less`` toggle.  Empty fields omitted from the cell.
 *
 * Testid contract (mirrors the archive's Add-B contract for
 * consistency + so vitest suites can drive it identically):
 *   - notes-history-list                    · root container
 *   - notes-history-loading                 · loading state
 *   - notes-history-error                   · error banner
 *   - notes-history-empty                   · empty state
 *   - notes-history-row-{sr_id}             · row root
 *   - notes-history-row-{sr_id}-{field}-preview  · truncated preview
 *   - notes-history-row-{sr_id}-{field}-full     · full text
 *   - notes-history-row-{sr_id}-{field}-toggle   · See more/less
 *   - notes-history-see-all                 · "See all → " link (compact)
 *   - notes-history-prev-btn / -next-btn    · pagination (full)
 *   - notes-history-page-indicator          · "Page X of Y"
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { colors } from "@/theme";
import { api } from "@/api";


const NOTE_FIELDS = [
  { key: "notes", label: "Notes" },
  { key: "internal_notes", label: "Internal" },
  { key: "customer_notes", label: "Customer" },
];
const TRUNCATE_AT = 140;
const COMPACT_PAGE_SIZE = 3;
const FULL_PAGE_SIZE = 20;


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
          data-testid={`notes-history-row-${srId}-${fieldKey}-preview`}
          style={{ color: colors.onSurface }}
        >
          {previewText}
        </span>
      ) : (
        <span
          data-testid={`notes-history-row-${srId}-${fieldKey}-full`}
          style={{ color: colors.onSurface }}
        >
          {text}
        </span>
      )}
      {isLong ? (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          data-testid={`notes-history-row-${srId}-${fieldKey}-toggle`}
          className="ml-1.5 text-xs underline"
          style={{ color: colors.brand || colors.inputBorder }}
        >
          {expanded ? "See less" : "See more"}
        </button>
      ) : null}
    </div>
  );
}


export default function NotesHistoryList({
  customerId, compact = false, onSeeAll = null,
}) {
  const pageSize = compact ? COMPACT_PAGE_SIZE : FULL_PAGE_SIZE;
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!customerId) return;
    setLoading(true);
    setError("");
    try {
      const res = await api.get(
        `/customers/${customerId}/notes-history?page=${page}&page_size=${pageSize}`,
      );
      setRows(res?.rows || []);
      setTotalCount(res?.total_count || 0);
    } catch (e) {
      setError(String(e?.message || e || "failed to load notes history"));
      setRows([]);
      setTotalCount(0);
    } finally {
      setLoading(false);
    }
  }, [customerId, page, pageSize]);

  useEffect(() => { load(); }, [load]);

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));

  if (loading) {
    return (
      <div
        className="py-6 text-center text-sm"
        data-testid="notes-history-loading"
        style={{ color: colors.onSurfaceSecondary }}
      >
        Loading…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="py-4 px-4 rounded-lg text-sm"
        data-testid="notes-history-error"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
          color: colors.onSurface,
        }}
      >
        {error}
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div
        className="py-6 text-center text-sm"
        data-testid="notes-history-empty"
        style={{ color: colors.onSurfaceSecondary }}
      >
        No notes on file yet.
      </div>
    );
  }

  return (
    <div data-testid="notes-history-list" className="space-y-2">
      {rows.map((row) => (
        <div
          key={row.sr_id}
          data-testid={`notes-history-row-${row.sr_id}`}
          className="p-3 rounded-lg"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
        >
          <div
            className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-1"
            style={{ color: colors.onSurface }}
          >
            <span className="text-sm font-semibold">
              {formatDate(row.submitted_at)}
            </span>
            <span
              className="text-xs"
              style={{ color: colors.onSurfaceSecondary }}
            >
              {row.industry}
            </span>
            {row.tech_name ? (
              <span
                className="text-xs"
                style={{ color: colors.onSurfaceSecondary }}
              >
                · Tech: {row.tech_name}
              </span>
            ) : null}
          </div>
          {NOTE_FIELDS.map((f) => (
            <ExpandableNote
              key={f.key}
              srId={row.sr_id}
              fieldKey={f.key}
              label={f.label}
              text={row[f.key] || ""}
            />
          ))}
        </div>
      ))}

      {compact && totalCount > COMPACT_PAGE_SIZE && onSeeAll ? (
        <button
          type="button"
          onClick={onSeeAll}
          data-testid="notes-history-see-all"
          className="text-xs underline"
          style={{ color: colors.brand || colors.inputBorder }}
        >
          See all {totalCount} notes →
        </button>
      ) : null}

      {!compact ? (
        <div
          className="mt-3 flex flex-wrap items-center gap-3 text-sm"
          style={{ color: colors.onSurfaceSecondary }}
        >
          <span data-testid="notes-history-page-indicator">
            Page {page} of {totalPages} · {totalCount} notes
          </span>
          <button
            type="button"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            data-testid="notes-history-prev-btn"
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
            data-testid="notes-history-next-btn"
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
        </div>
      ) : null}
    </div>
  );
}
