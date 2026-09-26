/**
 * Feb-2026 · C3 · Chemical Applications admin list page.
 *
 * Route: /admin/chemical-applications (gated by ``AdminOrManager``
 * in App.js → admin + super_admin + manager). Tech accounts hit
 * chemical-applications from mobile / field-log surfaces and do
 * NOT need this admin list.
 *
 * Consumes:
 *   * ``GET /api/chemical-applications`` — cursor-paginated list
 *     ({ items, next_cursor }) with query filters ``customer_id``,
 *     ``date_from``, ``date_to``, ``technician_id``, ``target_pest``,
 *     ``limit``, ``cursor``.
 *   * ``GET /api/customers``            — customer combobox source.
 *   * ``GET /api/technicians``          — tech dropdown source.
 *
 * REI countdown badges flip client-side via ``useReiCountdown``
 * (60 s ticker) so a locked row unlocks without a page refresh.
 *
 * Row click → ``/admin/chemical-applications/:id`` (C5 will land
 * the detail page; for now the handler console.logs so the click
 * surface is wired and easy to swap in C5).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FlaskConical, RefreshCw, ShieldCheck, Lock, Filter } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import NavyFilterBar from "@/components/ui/NavyFilterBar";
import CustomerCombobox from "@/components/customers/CustomerCombobox";
import { useReiCountdown } from "@/hooks/useReiCountdown";


// ═══════════════════════════════════════════════════════════════════
// Constants
// ═══════════════════════════════════════════════════════════════════
const PAGE_SIZE = 25;
const PEST_DEBOUNCE_MS = 300;


// ═══════════════════════════════════════════════════════════════════
// Formatting helpers (pure — tested implicitly via component tests)
// ═══════════════════════════════════════════════════════════════════
function _fmtDate(iso) {
  if (!iso || typeof iso !== "string") return "—";
  // application_date is ISO date (YYYY-MM-DD) — render as-is.
  return iso.slice(0, 10);
}


function _fmtTime(iso) {
  if (!iso || typeof iso !== "string") return "—";
  // start_time / stop_time are ISO time strings (HH:MM:SS) — trim seconds.
  return iso.slice(0, 5);
}


function _customerName(customersById, customerId) {
  if (!customerId) return "Unknown customer";
  const c = customersById[customerId];
  if (!c) return customerId.slice(0, 8);
  return c.name || c.display_name || customerId.slice(0, 8);
}


// ═══════════════════════════════════════════════════════════════════
// REI badge
// ═══════════════════════════════════════════════════════════════════
export function ReiBadge({ reiUnlockAt, testid = "rei-badge" }) {
  const { isLocked, hoursRemaining, minutesRemaining } = useReiCountdown(reiUnlockAt);

  if (!reiUnlockAt) {
    // Legacy rows without a REI unlock stamp — show a neutral pill so
    // the column always has content and the regulatory auditor never
    // sees a naked empty cell.
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold"
        style={{ backgroundColor: colors.surfaceSecondary,
                  color: colors.muted,
                  border: `1px solid ${colors.border}` }}
        data-testid={`${testid}-unknown`}
      >
        No REI
      </span>
    );
  }

  if (isLocked) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold"
        style={{ backgroundColor: "#FEE2E2", color: "#991B1B",
                  border: "1px solid #FCA5A5" }}
        data-testid={`${testid}-locked`}
      >
        <Lock size={11} />
        REI Locked · {hoursRemaining}h {minutesRemaining}m
      </span>
    );
  }

  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold"
      style={{ backgroundColor: "#DCFCE7", color: "#166534",
                border: "1px solid #86EFAC" }}
      data-testid={`${testid}-unlocked`}
    >
      <ShieldCheck size={11} />
      Reentry OK
    </span>
  );
}


// ═══════════════════════════════════════════════════════════════════
// Skeleton row (loading state)
// ═══════════════════════════════════════════════════════════════════
function SkeletonRow({ i }) {
  return (
    <div
      className="flex items-center gap-4 px-4 py-3 border-b animate-pulse"
      style={{ borderColor: colors.border }}
      data-testid={`chem-app-skeleton-${i}`}
    >
      <div className="w-24 h-4 rounded" style={{ backgroundColor: colors.surfaceSecondary }} />
      <div className="flex-1 h-4 rounded" style={{ backgroundColor: colors.surfaceSecondary }} />
      <div className="w-32 h-4 rounded" style={{ backgroundColor: colors.surfaceSecondary }} />
      <div className="w-28 h-6 rounded-full" style={{ backgroundColor: colors.surfaceSecondary }} />
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
// Row (data)
// ═══════════════════════════════════════════════════════════════════
function ChemAppRow({ row, customersById, onClick }) {
  return (
    <button
      type="button"
      onClick={() => onClick(row)}
      className="w-full text-left flex items-center gap-4 px-4 py-3 border-b hover:brightness-95 transition"
      style={{ backgroundColor: colors.surface,
                borderColor: colors.border,
                color: colors.onSurface }}
      data-testid={`chem-app-row-${row.id}`}
    >
      <div className="w-28 shrink-0">
        <div className="text-sm font-semibold" data-testid={`chem-app-row-${row.id}-date`}>
          {_fmtDate(row.application_date)}
        </div>
        <div className="text-xs" style={{ color: colors.muted }}>
          {_fmtTime(row.start_time)} – {_fmtTime(row.stop_time)}
        </div>
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate" data-testid={`chem-app-row-${row.id}-customer`}>
          {_customerName(customersById, row.customer_id)}
        </div>
        <div className="text-xs truncate" style={{ color: colors.muted }}>
          by {row.technician_name || "—"}
        </div>
      </div>
      <div className="w-48 min-w-0 hidden md:block">
        <div className="text-sm truncate" data-testid={`chem-app-row-${row.id}-pest`}>
          {row.target_pest || "—"}
        </div>
        <div className="text-xs font-mono truncate" style={{ color: colors.muted }}>
          {row.chemical_name || "—"}
        </div>
      </div>
      <div className="shrink-0">
        <ReiBadge reiUnlockAt={row.rei_unlock_at} testid={`chem-app-row-${row.id}-rei`} />
      </div>
    </button>
  );
}


// ═══════════════════════════════════════════════════════════════════
// Page
// ═══════════════════════════════════════════════════════════════════
export default function ChemicalApplicationsList() {
  // Filter state
  const [customerId, setCustomerId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [technicianId, setTechnicianId] = useState("");
  const [pest, setPest] = useState("");
  const [pestDebounced, setPestDebounced] = useState("");

  // Data state
  const [rows, setRows] = useState(null);           // null = loading, [] = empty
  const [cursor, setCursor] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  // Reference data
  const [customers, setCustomers] = useState([]);
  const [technicians, setTechnicians] = useState([]);
  const customersById = useMemo(() => {
    const m = {};
    (customers || []).forEach((c) => { if (c && c.id) m[c.id] = c; });
    return m;
  }, [customers]);

  // Guard against overlapping requests when filters change quickly.
  const reqIdRef = useRef(0);

  // ── Reference-data bootstrap ────────────────────────────────
  useEffect(() => {
    api.get("/customers")
      .then((r) => setCustomers(Array.isArray(r) ? r : (r?.items || [])))
      .catch(() => setCustomers([]));
    api.get("/technicians")
      .then((r) => setTechnicians(Array.isArray(r) ? r : (r?.items || [])))
      .catch(() => setTechnicians([]));
  }, []);

  // ── Pest search debounce ─────────────────────────────────────
  useEffect(() => {
    const id = setTimeout(() => setPestDebounced(pest.trim()), PEST_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [pest]);

  // ── Filter query string ──────────────────────────────────────
  const filterParams = useMemo(() => {
    const p = new URLSearchParams();
    p.set("limit", String(PAGE_SIZE));
    if (customerId) p.set("customer_id", customerId);
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    if (technicianId) p.set("technician_id", technicianId);
    if (pestDebounced) p.set("target_pest", pestDebounced);
    return p;
  }, [customerId, dateFrom, dateTo, technicianId, pestDebounced]);

  // ── Loaders ─────────────────────────────────────────────────
  const load = useCallback(async () => {
    const myReq = ++reqIdRef.current;
    setRows(null);
    setError(null);
    setCursor(null);
    try {
      const r = await api.get(`/chemical-applications?${filterParams.toString()}`);
      if (reqIdRef.current !== myReq) return;   // superseded, drop.
      const items = Array.isArray(r?.items) ? r.items : (Array.isArray(r) ? r : []);
      setRows(items);
      setCursor(r?.next_cursor || null);
    } catch (e) {
      if (reqIdRef.current !== myReq) return;
      setError(e?.message || "Failed to load chemical applications");
      setRows([]);
    }
  }, [filterParams]);

  const loadMore = useCallback(async () => {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const p = new URLSearchParams(filterParams);
      p.set("cursor", cursor);
      const r = await api.get(`/chemical-applications?${p.toString()}`);
      const items = Array.isArray(r?.items) ? r.items : [];
      setRows((prev) => [...(prev || []), ...items]);
      setCursor(r?.next_cursor || null);
    } catch (e) {
      toast.error(e?.message || "Failed to load more");
    } finally {
      setLoadingMore(false);
    }
  }, [cursor, loadingMore, filterParams]);

  useEffect(() => { load(); }, [load]);

  const openRow = useCallback((row) => {
    // C5 will hook this to the detail page; log the click surface
    // for now so integration is obvious in dev tools.
    // eslint-disable-next-line no-console
    console.log("[C3] chem-app row clicked — detail page lands in C5", row.id);
  }, []);

  // ── Render ───────────────────────────────────────────────────
  const isInitialLoading = rows === null && !error;
  const isEmpty = Array.isArray(rows) && rows.length === 0 && !error;

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
         data-testid="chemical-applications-page">
      {/* ── Header ────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold"
              style={{ color: colors.onSurface }}
              data-testid="chemical-applications-title">
            <FlaskConical size={20} className="inline mr-2" />
            Chemical Applications
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Regulatory spray log — REI unlock badges tick live every minute.
          </p>
        </div>
        <button onClick={load}
                className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurfaceSecondary,
                          border: `1px solid ${colors.border}` }}
                data-testid="chemical-applications-refresh-btn">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {/* ── Filter bar (navy) ─────────────────────────────────── */}
      <div className="mb-4">
        <NavyFilterBar data-testid="chemical-applications-filters">
          <NavyFilterBar.Combobox label="Customer" minWidth={220}>
            <CustomerCombobox
              value={customerId}
              onChange={setCustomerId}
              customers={customers}
              testid="chemical-applications-filter-customer"
              placeholder="All customers"
            />
          </NavyFilterBar.Combobox>
          <NavyFilterBar.DatePicker
            label="From"
            value={dateFrom}
            onChange={setDateFrom}
            data-testid="chemical-applications-filter-date-from"
          />
          <NavyFilterBar.DatePicker
            label="To"
            value={dateTo}
            onChange={setDateTo}
            data-testid="chemical-applications-filter-date-to"
          />
          <NavyFilterBar.Select
            label="Tech"
            value={technicianId}
            onChange={setTechnicianId}
            data-testid="chemical-applications-filter-tech"
            ariaLabel="Filter by technician"
          >
            <option value="">All techs</option>
            {(technicians || []).map((t) => (
              <option key={t.id} value={t.id}>{t.name || t.email || t.id.slice(0, 8)}</option>
            ))}
          </NavyFilterBar.Select>
          <NavyFilterBar.Search
            label="Pest"
            value={pest}
            onChange={setPest}
            onClear={() => setPest("")}
            placeholder="Search pest…"
            data-testid="chemical-applications-filter-pest"
          />
        </NavyFilterBar>
      </div>

      {/* ── Body ──────────────────────────────────────────────── */}
      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface,
                     border: `1px solid ${colors.border}` }}>
        {isInitialLoading && (
          <div data-testid="chemical-applications-loading">
            {[0, 1, 2].map((i) => <SkeletonRow key={i} i={i} />)}
          </div>
        )}
        {error && (
          <div className="p-6 flex items-center justify-between"
               style={{ backgroundColor: "#FEF2F2", color: "#991B1B" }}
               data-testid="chemical-applications-error">
            <span className="text-sm font-medium">{error}</span>
            <button onClick={load}
                    className="text-xs font-semibold px-3 py-1.5 rounded-md"
                    style={{ backgroundColor: "#DC2626", color: "#FFFFFF" }}
                    data-testid="chemical-applications-error-retry">
              Retry
            </button>
          </div>
        )}
        {isEmpty && (
          <div className="p-10 text-center"
               data-testid="chemical-applications-empty">
            <FlaskConical size={28}
                          className="mx-auto mb-3"
                          style={{ color: colors.muted }} />
            <div className="text-sm font-medium" style={{ color: colors.onSurface }}>
              No chemical applications recorded yet.
            </div>
            <div className="text-xs mt-1" style={{ color: colors.muted }}>
              Techs can log applications from the mobile app or web form (coming in C4).
            </div>
          </div>
        )}
        {Array.isArray(rows) && rows.length > 0 && (
          <div data-testid="chemical-applications-rows">
            {rows.map((r) => (
              <ChemAppRow key={r.id}
                          row={r}
                          customersById={customersById}
                          onClick={openRow} />
            ))}
          </div>
        )}
      </div>

      {/* ── Load more ─────────────────────────────────────────── */}
      {cursor && !isInitialLoading && !error && (
        <div className="mt-4 flex justify-center">
          <button onClick={loadMore}
                  disabled={loadingMore}
                  className="text-sm font-semibold px-4 py-2 rounded-lg"
                  style={{ backgroundColor: colors.surface,
                            color: colors.onSurface,
                            border: `1px solid ${colors.border}`,
                            opacity: loadingMore ? 0.6 : 1,
                            cursor: loadingMore ? "not-allowed" : "pointer" }}
                  data-testid="chemical-applications-load-more">
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}
