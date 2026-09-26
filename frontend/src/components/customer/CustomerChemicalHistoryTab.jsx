/**
 * Feb-2026 · C5 · CustomerDetail → "Chemical History" tab.
 *
 * Lists every ``/chemical-applications`` row scoped to this customer
 * (via ``GET /api/chemical-applications?customer_id=<id>``, cursor-
 * paginated per C1 backend) and surfaces the C4 create form as a
 * one-click deep-link (``/admin/chemical-applications/new?customer_id=<id>``).
 *
 * Reuses:
 *   * ``ReiBadge``      from ``/pages/chemical/ChemicalApplicationsList``
 *   * ``useReiCountdown`` from ``/hooks/useReiCountdown``
 *   * ``filterCustomerTabs``     from ``/components/customer/CustomerMeasurementsTab``
 *
 * Filter chips (client-side, no extra fetch):
 *   * All (default)
 *   * REI Locked   — ``rei_unlock_at > now`` only
 *   * Reentry OK   — ``rei_unlock_at <= now`` only
 *   * Last 30 days — ``application_date`` within 30 days of now
 *
 * Role gate: admin / super_admin / manager. Techs create sprays
 * from mobile / field-log surfaces and do NOT see the tab.
 * Customers never see the tab.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FlaskConical, Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { ReiBadge } from "@/pages/chemical/ChemicalApplicationsList";


// Role set locked here so the test can assert the shape in one place.
export const CHEMICAL_HISTORY_TAB_ROLES = ["admin", "super_admin", "manager"];


// ═══════════════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════════════
function _fmtCompact(d) {
  if (!d) return "";
  try {
    return new Date(d).toLocaleDateString(undefined,
      { month: "short", day: "numeric", year: "numeric" });
  } catch (e) {
    return String(d).slice(0, 10);
  }
}


function _fmt12Hour(t) {
  if (!t) return "—";
  const [hStr, mStr] = String(t).split(":");
  const h = parseInt(hStr, 10);
  if (!Number.isFinite(h)) return String(t).slice(0, 5);
  const period = h >= 12 ? "PM" : "AM";
  const h12 = ((h + 11) % 12) + 1;
  return `${h12}:${(mStr || "00").slice(0, 2)} ${period}`;
}


const _ONE_DAY_MS = 24 * 60 * 60 * 1000;


// ═══════════════════════════════════════════════════════════════════
// Filter chip primitive
// ═══════════════════════════════════════════════════════════════════
function FilterChip({ active, onClick, label, testid, count }) {
  return (
    <button type="button"
            onClick={onClick}
            className="text-xs font-semibold px-3 py-1.5 rounded-full inline-flex items-center gap-1.5 transition"
            style={{
              backgroundColor: active ? colors.brand : colors.surfaceSecondary,
              color:           active ? colors.onBrandPrimary : colors.onSurfaceSecondary,
              border: `1px solid ${active ? colors.brand : colors.border}`,
            }}
            data-testid={testid}
            aria-pressed={active}>
      {label}
      {typeof count === "number" && (
        <span className="text-[10px] font-bold opacity-80"
              style={{ marginLeft: 2 }}>
          {count}
        </span>
      )}
    </button>
  );
}


// ═══════════════════════════════════════════════════════════════════
// Row
// ═══════════════════════════════════════════════════════════════════
function ChemAppRow({ row, onClick }) {
  return (
    <button type="button"
            onClick={() => onClick(row)}
            className="w-full text-left flex items-center gap-4 px-4 py-3 border-b hover:brightness-95 transition"
            style={{ backgroundColor: colors.surface,
                      borderColor: colors.border,
                      color: colors.onSurface }}
            data-testid={`chem-history-row-${row.id}`}>
      <div className="w-40 shrink-0">
        <div className="text-sm font-semibold"
             data-testid={`chem-history-row-${row.id}-date`}>
          {_fmtCompact(row.application_date)}
        </div>
        <div className="text-xs" style={{ color: colors.muted }}>
          {_fmt12Hour(row.start_time)} → {_fmt12Hour(row.stop_time)}
        </div>
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate"
             data-testid={`chem-history-row-${row.id}-pest`}>
          {row.target_pest || "—"}
        </div>
        <div className="text-xs font-mono truncate"
             style={{ color: colors.muted }}
             data-testid={`chem-history-row-${row.id}-chemical`}>
          {row.chemical_name || "—"}
        </div>
      </div>
      <div className="hidden md:block w-40 min-w-0 text-right">
        <div className="text-xs truncate"
             style={{ color: colors.onSurfaceSecondary }}
             data-testid={`chem-history-row-${row.id}-tech`}>
          {row.technician_name || "—"}
        </div>
        {row.license_number && (
          <div className="text-[10px] truncate"
               style={{ color: colors.muted }}
               data-testid={`chem-history-row-${row.id}-license`}>
            Lic {row.license_number}
          </div>
        )}
      </div>
      <div className="shrink-0">
        <ReiBadge reiUnlockAt={row.rei_unlock_at}
                   testid={`chem-history-row-${row.id}-rei`} />
      </div>
    </button>
  );
}


// ═══════════════════════════════════════════════════════════════════
// Skeleton row
// ═══════════════════════════════════════════════════════════════════
function SkeletonRow({ i }) {
  return (
    <div className="flex items-center gap-4 px-4 py-3 border-b animate-pulse"
         style={{ borderColor: colors.border }}
         data-testid={`chem-history-skeleton-${i}`}>
      <div className="w-32 h-4 rounded" style={{ backgroundColor: colors.surfaceSecondary }} />
      <div className="flex-1 h-4 rounded" style={{ backgroundColor: colors.surfaceSecondary }} />
      <div className="w-28 h-6 rounded-full" style={{ backgroundColor: colors.surfaceSecondary }} />
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
// Tab
// ═══════════════════════════════════════════════════════════════════
export default function CustomerChemicalHistoryTab({ customer }) {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);           // null = loading
  const [cursor, setCursor] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("all");
  const [nowMs, setNowMs] = useState(() => Date.now());

  const customerId = customer?.id;

  const load = useCallback(async () => {
    if (!customerId) return;
    setRows(null);
    setError(null);
    setCursor(null);
    try {
      const params = new URLSearchParams();
      params.set("customer_id", customerId);
      params.set("limit", "25");
      const r = await api.get(`/chemical-applications?${params.toString()}`);
      const items = Array.isArray(r?.items) ? r.items : (Array.isArray(r) ? r : []);
      setRows(items);
      setCursor(r?.next_cursor || null);
    } catch (e) {
      setError(e?.message || "Failed to load chemical history");
      setRows([]);
    }
  }, [customerId]);

  const loadMore = useCallback(async () => {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const params = new URLSearchParams();
      params.set("customer_id", customerId);
      params.set("limit", "25");
      params.set("cursor", cursor);
      const r = await api.get(`/chemical-applications?${params.toString()}`);
      const items = Array.isArray(r?.items) ? r.items : [];
      setRows((prev) => [...(prev || []), ...items]);
      setCursor(r?.next_cursor || null);
    } catch (e) {
      toast.error(e?.message || "Failed to load more");
    } finally {
      setLoadingMore(false);
    }
  }, [customerId, cursor, loadingMore]);

  useEffect(() => { load(); }, [load]);

  // Refresh ``nowMs`` every 60 s so the "REI Locked" / "Reentry OK" /
  // "Last 30 days" chip counts + filtered lists roll forward without
  // a manual refresh. Same cadence as ReiBadge's internal tick.
  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  const openNewForm = useCallback(() => {
    navigate(`/admin/chemical-applications/new?customer_id=${encodeURIComponent(customerId)}`);
  }, [customerId, navigate]);

  const openRow = useCallback((row) => {
    navigate(`/admin/chemical-applications/${row.id}`);
  }, [navigate]);

  // ── Client-side filter ──────────────────────────────────────
  const filteredRows = useMemo(() => {
    if (!Array.isArray(rows)) return null;
    switch (filter) {
      case "locked":
        return rows.filter((r) => r.rei_unlock_at
                                        && new Date(r.rei_unlock_at).getTime() > nowMs);
      case "unlocked":
        return rows.filter((r) => !r.rei_unlock_at
                                        || new Date(r.rei_unlock_at).getTime() <= nowMs);
      case "last30":
        return rows.filter((r) => {
          if (!r.application_date) return false;
          const ts = new Date(r.application_date).getTime();
          if (!Number.isFinite(ts)) return false;
          return (nowMs - ts) <= 30 * _ONE_DAY_MS && ts <= nowMs + _ONE_DAY_MS;
        });
      case "all":
      default:
        return rows;
    }
  }, [rows, filter, nowMs]);

  // ── Chip counts (based on full ``rows``, not the filtered slice) ──
  const chipCounts = useMemo(() => {
    if (!Array.isArray(rows)) return { all: 0, locked: 0, unlocked: 0, last30: 0 };
    let locked = 0; let unlocked = 0; let last30 = 0;
    for (const r of rows) {
      const unlockTs = r.rei_unlock_at ? new Date(r.rei_unlock_at).getTime() : NaN;
      if (Number.isFinite(unlockTs) && unlockTs > nowMs) locked += 1;
      else unlocked += 1;
      const appTs = r.application_date ? new Date(r.application_date).getTime() : NaN;
      if (Number.isFinite(appTs)
              && (nowMs - appTs) <= 30 * _ONE_DAY_MS
              && appTs <= nowMs + _ONE_DAY_MS) last30 += 1;
    }
    return { all: rows.length, locked, unlocked, last30 };
  }, [rows, nowMs]);

  // ── Render ──────────────────────────────────────────────────
  const isInitialLoading = rows === null && !error;
  const isEmpty = Array.isArray(rows) && rows.length === 0 && !error;
  const isFilteredEmpty = !isEmpty
                             && Array.isArray(filteredRows)
                             && filteredRows.length === 0
                             && !error;

  return (
    <div className="space-y-4" data-testid="chemical-history-tab">
      {/* ── Header ───────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <FlaskConical size={18} style={{ color: colors.brand }} />
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}
              data-testid="chemical-history-tab-title">
            Chemical History
          </h2>
          {Array.isArray(rows) && (
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full"
                  style={{ backgroundColor: colors.surfaceSecondary,
                            color: colors.onSurfaceSecondary,
                            border: `1px solid ${colors.border}` }}
                  data-testid="chemical-history-count-badge">
              {rows.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={load}
                  className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
                  style={{ backgroundColor: colors.surfaceSecondary,
                            color: colors.onSurfaceSecondary,
                            border: `1px solid ${colors.border}` }}
                  data-testid="chemical-history-refresh-btn">
            <RefreshCw size={12} /> Refresh
          </button>
          <button onClick={openNewForm}
                  className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
                  style={{ backgroundColor: colors.nav.bg,
                            color: colors.nav.fg,
                            border: `1px solid ${colors.nav.border}` }}
                  data-testid="chemical-history-new-btn">
            <Plus size={12} /> New Application
          </button>
        </div>
      </div>

      {/* ── Filter chips ─────────────────────────────────────── */}
      <div className="flex items-center flex-wrap gap-2"
           data-testid="chemical-history-filter-chips">
        <FilterChip active={filter === "all"}
                     onClick={() => setFilter("all")}
                     label="All"
                     count={chipCounts.all}
                     testid="chemical-history-chip-all" />
        <FilterChip active={filter === "locked"}
                     onClick={() => setFilter("locked")}
                     label="REI Locked"
                     count={chipCounts.locked}
                     testid="chemical-history-chip-locked" />
        <FilterChip active={filter === "unlocked"}
                     onClick={() => setFilter("unlocked")}
                     label="Reentry OK"
                     count={chipCounts.unlocked}
                     testid="chemical-history-chip-unlocked" />
        <FilterChip active={filter === "last30"}
                     onClick={() => setFilter("last30")}
                     label="Last 30 days"
                     count={chipCounts.last30}
                     testid="chemical-history-chip-last30" />
      </div>

      {/* ── Body ─────────────────────────────────────────────── */}
      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface,
                     border: `1px solid ${colors.border}` }}>
        {isInitialLoading && (
          <div data-testid="chemical-history-loading">
            {[0, 1, 2].map((i) => <SkeletonRow key={i} i={i} />)}
          </div>
        )}
        {error && (
          <div className="p-6 flex items-center justify-between"
               style={{ backgroundColor: "#FEF2F2", color: "#991B1B" }}
               data-testid="chemical-history-error">
            <span className="text-sm font-medium">{error}</span>
            <button onClick={load}
                    className="text-xs font-semibold px-3 py-1.5 rounded-md"
                    style={{ backgroundColor: "#DC2626", color: "#FFFFFF" }}
                    data-testid="chemical-history-error-retry">
              Retry
            </button>
          </div>
        )}
        {isEmpty && (
          <div className="p-10 text-center"
               data-testid="chemical-history-empty">
            <FlaskConical size={26}
                          className="mx-auto mb-3"
                          style={{ color: colors.muted }} />
            <div className="text-sm font-medium" style={{ color: colors.onSurface }}>
              No chemical applications recorded for this customer yet.
            </div>
            <div className="text-xs mt-1 mb-4" style={{ color: colors.muted }}>
              Log the first spray to start the regulatory record.
            </div>
            <button onClick={openNewForm}
                    className="text-sm font-semibold px-4 py-2 rounded-lg inline-flex items-center gap-1.5"
                    style={{ backgroundColor: colors.brand,
                              color: colors.onBrandPrimary }}
                    data-testid="chemical-history-empty-cta">
              <Plus size={13} /> Log First Application
            </button>
          </div>
        )}
        {isFilteredEmpty && (
          <div className="p-8 text-center"
               data-testid="chemical-history-filtered-empty">
            <div className="text-sm" style={{ color: colors.muted }}>
              No matches for this filter. Try another chip.
            </div>
          </div>
        )}
        {Array.isArray(filteredRows) && filteredRows.length > 0 && (
          <div data-testid="chemical-history-rows">
            {filteredRows.map((r) => (
              <ChemAppRow key={r.id} row={r} onClick={openRow} />
            ))}
          </div>
        )}
      </div>

      {/* ── Load more (cursor pagination) ───────────────────── */}
      {cursor && !isInitialLoading && !error && (
        <div className="flex justify-center">
          <button onClick={loadMore}
                  disabled={loadingMore}
                  className="text-sm font-semibold px-4 py-2 rounded-lg"
                  style={{ backgroundColor: colors.surface,
                            color: colors.onSurface,
                            border: `1px solid ${colors.border}`,
                            opacity: loadingMore ? 0.6 : 1,
                            cursor: loadingMore ? "not-allowed" : "pointer" }}
                  data-testid="chemical-history-load-more">
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}
