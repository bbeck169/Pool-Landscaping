// Feb-2026 · Slice H4 — Leads dashboard.
//
// Table + drawer detail. Filters (source, status, date range). Convert
// action calls existing POST /api/leads/{id}/convert.
import React, { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "@/api";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Search, ArrowRight, X, Trash2, ChevronDown, Mail, MessageCircle } from "lucide-react";
import { colors } from "@/theme";
import { useAuth } from "@/auth";
import LeadComposeModal from "./LeadComposeModal";
import { PhoneLink, AddressLink, CustomerLink } from "@/components/customer";

// Phase K52.1a · Feb-2026 — the local ``colors`` const previously
// shadowed the shared ``@/theme`` export.  It carried a slate-tinted
// zinc-adjacent palette (brand #0EA5E9, muted #64748B, border
// #E2E8F0) that pre-dated the K50/K52 nav-chrome tokens — and
// crucially, DID NOT export a ``nav.*`` sub-object.  The K52.1
// filter-strip additions referenced ``colors.nav.bg`` /
// ``colors.nav.fg`` / ``colors.nav.fgMuted`` / ``colors.nav.border``
// and blew up at render with ``Cannot read properties of undefined
// (reading 'bg')``.  Fix: delete the shadow, consume the shared
// ``colors`` export — this eliminates the class of bug (a local
// shadow silently drifting from the theme) and matches how the
// other 4 K52.1 pages resolve tokens.  Downstream visual delta:
// swaps a small handful of slate-tinted values for their zinc
// equivalents (brand #0EA5E9 → #0284C7, muted #64748B → #71717A,
// border #E2E8F0 → #E4E4E7, surfaceSecondary #F8FAFC → #F4F4F5) —
// this aligns the leads page with every other admin surface.

// Phase 34 · Task CC · Feb 2026 — canonical status enum (must match
// backend `_CANONICAL_STATUSES` in routers/leads.py). Order matters —
// the dropdown renders in this order everywhere the enum is exposed.
const LEAD_STATUS_OPTIONS = [
  { value: "new",           label: "New" },
  { value: "contacted",     label: "Contacted" },
  { value: "quoted",        label: "Quoted" },
  { value: "closed_won",    label: "Closed – Won" },
  { value: "closed_lost",   label: "Closed – Lost" },
];

// ── Phase P48 · Feb-2026 · Active / Archive tab groupings ───────────
// The default landing view surfaces only "still working" leads
// (Active tab).  Closed rows collapse into the Archive tab so the
// primary list doesn't get cluttered by every historical win / loss.
// Server-side filtering — the backend endpoint accepts a
// comma-separated ``status`` value (P48 extension); this map drives
// what gets sent on the wire per tab.
const LEAD_TABS = {
  active:  { label: "Active",  statuses: ["new", "contacted", "quoted"] },
  archive: { label: "Archive", statuses: ["closed_won", "closed_lost"] },
};
const LEAD_TAB_ORDER = ["active", "archive"];
const LEAD_TAB_DEFAULT = "active";
const _isValidLeadTab = (t) => LEAD_TAB_ORDER.includes(t);

const STATUS_COLORS = {
  new:          { bg: "#DBEAFE", fg: "#1E3A8A" },
  contacted:    { bg: "#FEF3C7", fg: "#854D0E" },
  quoted:       { bg: "#EDE9FE", fg: "#6D28D9" },
  closed_won:   { bg: "#DCFCE7", fg: "#166534" },
  closed_lost:  { bg: "#F3F4F6", fg: "#374151" },
};

const STATUS_LABEL = (v) => {
  const found = LEAD_STATUS_OPTIONS.find((o) => o.value === v);
  return found ? found.label : (v || "new");
};

const SOURCE_LABEL = (src) => {
  if (!src) return "—";
  if (src === "chat_widget") return "Chat widget";
  if (src.startsWith("form:")) return `Form · ${src.slice(5)}`;
  if (src.startsWith("referral_from_customer:")) return "Referral";
  return src;
};

const isReferral = (l) =>
  typeof l?.source === "string" && l.source.startsWith("referral_from_customer:");

export default function LeadsDashboardPage() {
  const auth = useAuth() || {};
  const { t } = useTranslation("leads");
  const isPrivileged = ["admin", "super_admin", "owner", "manager"].includes(auth.user?.role);
  // ── Phase P48 · URL-synced tab state ────────────────────────────
  // ``?tab=active|archive`` — persists across back/forward + hard
  // refresh.  Unknown / missing values fall back to
  // ``LEAD_TAB_DEFAULT`` ("active").
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab");
  const activeTab = _isValidLeadTab(rawTab) ? rawTab : LEAD_TAB_DEFAULT;
  const setActiveTab = (t) => {
    const next = _isValidLeadTab(t) ? t : LEAD_TAB_DEFAULT;
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  };
  const tabStatuses = LEAD_TABS[activeTab].statuses;
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState({ source: "", status: "", search: "" });
  const [selected, setSelected] = useState(null);
  // Phase L3 · Feb-2026 — row-level compose modal.
  const [composeTarget, setComposeTarget] = useState(null);   // { lead, channel } | null
  // Phase 34 · Task BB · Feb 2026 — bulk-select state.
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // Phase 34 · Task HH · Feb 2026 — bulk-status-change state.
  const [statusMenuOpen, setStatusMenuOpen] = useState(false);
  const [statusConfirmTarget, setStatusConfirmTarget] = useState(null);
  // Phase LD1 · Feb 2026 — hard-delete confirmation acknowledge gate.
  const [hardConfirmOpen, setHardConfirmOpen] = useState(false);
  const [hardAcknowledged, setHardAcknowledged] = useState(false);
  // F1.3 · Feb-2026 — additional DELETE-text gate for large batches
  // (>20 selected). Case-sensitive exact match required before the
  // destructive button becomes enabled.
  const [hardDeleteText, setHardDeleteText] = useState("");
  // Phase LD1 · density toggle persisted to localStorage.
  const [density, setDensity] = useState(() => {
    try {
      const raw = localStorage.getItem("leads-density");
      return raw === "compact" ? "compact" : "comfortable";
    } catch { return "comfortable"; }
  });
  useEffect(() => {
    try { localStorage.setItem("leads-density", density); } catch { /* noop */ }
  }, [density]);
  const rowPad = density === "compact" ? "py-1.5" : "py-3";
  const headerPad = density === "compact" ? "py-1.5" : "py-2";

  const refresh = () => {
    setLoading(true);
    // ── Phase P48 · server-side status filter ───────────────────
    // Send the current tab's status set (or the specific status
    // when the user narrows via the dropdown).  Pre-P48 this
    // route fetched every lead + sliced in Python — that made the
    // Archive tab impossible to isolate cleanly and kept 200
    // rows in memory even when the user only wanted 3 open leads.
    const effectiveStatuses = (
      filters.status ? [filters.status] : tabStatuses
    );
    const statusParam = effectiveStatuses.join(",");
    const url = "/leads?include_archived=1&page_size=200"
      + `&status=${encodeURIComponent(statusParam)}`;
    api.get(url)
      .then((r) => {
        // Phase 8 · Feb 2026 — the endpoint now returns
        // {rows,total,page,page_size}. Legacy callers get an array
        // fall-through so both shapes render.
        const arr = Array.isArray(r) ? r : (r?.rows || r?.leads || []);
        setRows(arr);
      })
      .catch((e) => setError(e?.message || "Failed to load"))
      .finally(() => setLoading(false));
  };
  // Phase P48 · re-fetch when the tab changes OR the user narrows
  // the status via the dropdown.  The dropdown value is a subset of
  // the current tab's status set — see ``tabScopedStatusOptions``
  // below — so switching tabs while a specific status is selected
  // is forbidden by construction (the dropdown resets when the
  // ``activeTab`` effect below runs).
  useEffect(() => { refresh(); }, [activeTab, filters.status]);

  // Phase P48 · reset the specific-status dropdown whenever the tab
  // switches so a stale "Contacted" filter can't leak into the
  // Archive tab.  Search + source persist because they're
  // orthogonal to the Active/Archive split.
  useEffect(() => {
    setFilters((f) => ({ ...f, status: "" }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  const visible = useMemo(() => {
    const q = filters.search.toLowerCase().trim();
    return rows.filter((l) => {
      // ── Phase P48 · status filter moved to the server ──────────
      // ``filters.status`` is sent on the wire (see ``refresh()``)
      // so the client-side ``l.status !== filters.status`` guard
      // is redundant — but keep a defensive belt for the milliseconds
      // between a tab-switch and the next fetch settling.
      if (filters.status && l.status !== filters.status) return false;
      // Defensive belt for the tab boundary — even if the server
      // ever returned a mis-scoped row, hide it here.
      if (!tabStatuses.includes(l.status)) return false;
      if (filters.source) {
        if (filters.source === "chat_widget" && l.source !== "chat_widget") return false;
        if (filters.source === "form" && !(l.source || "").startsWith("form:")) return false;
        if (filters.source === "manual"
            && (l.source && l.source !== "manual" && l.source !== "")) return false;
        if (filters.source === "referral" && !isReferral(l)) return false;
      }
      if (q) {
        const hay = `${l.name || ""} ${l.email || ""} ${l.phone || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [rows, filters, tabStatuses]);

  // Phase P48 · dropdown options are scoped to the current tab —
  // the Archive tab dropdown lists only Closed – Won / Closed – Lost;
  // the Active tab lists only New / Contacted / Quoted.  Prevents
  // the "select Contacted while on the Archive tab" no-op that
  // pre-P48 would have surfaced 0 rows silently.
  const tabScopedStatusOptions = useMemo(
    () => LEAD_STATUS_OPTIONS.filter((o) => tabStatuses.includes(o.value)),
    [tabStatuses],
  );

  const sources = useMemo(() => {
    const s = new Set();
    rows.forEach((l) => l.source && s.add(l.source.startsWith("form:") ? "form" : l.source));
    return Array.from(s);
  }, [rows]);

  // Phase 34 · Task BB — visible-page selection helpers.
  const visibleIds = visible.map((l) => l.id);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
  const indeterminate = visibleIds.some((id) => selectedIds.has(id)) && !allVisibleSelected;
  const selectedCount = selectedIds.size;
  const toggleAll = () => setSelectedIds((prev) => {
    const next = new Set(prev);
    if (allVisibleSelected) visibleIds.forEach((id) => next.delete(id));
    else visibleIds.forEach((id) => next.add(id));
    return next;
  });
  const toggleOne = (id) => setSelectedIds((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const clearSelection = () => setSelectedIds(new Set());
  const doBulkDelete = async () => {
    setBusy(true);
    try {
      const res = await api.post("/leads/bulk-delete", { ids: Array.from(selectedIds) });
      const ok = res.deleted_count || 0;
      const failCount = (res.failed || []).length;
      setRows((prev) => prev.filter((r) => !res.deleted.includes(r.id)));
      clearSelection();
      setConfirmOpen(false);
      if (failCount === 0) toast.success(`${ok} lead${ok === 1 ? "" : "s"} deleted`);
      else toast(`${ok} deleted · ${failCount} locked`, {
        description: (res.failed || []).slice(0, 3).map((f) => f.reason).join(" · "),
      });
    } catch (e) {
      toast.error(e?.message || "Bulk delete failed");
    } finally { setBusy(false); }
  };

  // Phase P6 · Feb-2026 — bulk HARD delete (irreversible).
  //
  // Endpoint: ``POST /api/leads/bulk-hard-delete``. Response shape
  // (Option B reconciled — see backend/routers/leads.py):
  //
  //   { requested, deleted, skipped:[{lead_id, code}], bulk_op_id }
  //
  // Skip codes on the wire are the whitelist:
  //   * ``not_found_or_cross_tenant`` — collapses 404 + cross-
  //     tenant + internal infra failures into one ambiguous code
  //     so the response can't be used to enumerate cross-tenant
  //     existence.
  //   * ``converted_lock``  — Closed-Won w/ linked customer/job/quote.
  //   * ``open_tasks_lock`` — non-empty open_task_ids.
  //
  // If ``skipped[]`` is non-empty we group the codes and surface a
  // secondary toast like:
  //   "12 skipped · 8 converted, 3 open tasks, 1 not accessible"
  //
  // 422 responses are surfaced through the axios/error wrapper's
  // ``err.body`` / ``err.response.data`` shape.  ``bulk_cap_exceeded``
  // (paranoia — the button is disabled at N > 100) gets its own
  // targeted toast so ops know why it bounced.
  const _p6_skipCopy = (code) => (
    code === "converted_lock"    ? "converted"
    : code === "open_tasks_lock" ? "open tasks"
    : /* not_found_or_cross_tenant + defensive default */ "not accessible"
  );

  const _p6_groupedSkipDescription = (skipped) => {
    if (!Array.isArray(skipped) || skipped.length === 0) return "";
    const counts = { converted_lock: 0, open_tasks_lock: 0,
                       not_found_or_cross_tenant: 0 };
    for (const s of skipped) {
      const c = s && s.code;
      counts[c] = (counts[c] || 0) + 1;
    }
    // Preserve a stable, human-readable order: converted → open
    // tasks → not accessible.  Zero-count buckets are dropped.
    const order = ["converted_lock", "open_tasks_lock",
                    "not_found_or_cross_tenant"];
    return order
      .filter((c) => counts[c] > 0)
      .map((c) => `${counts[c]} ${_p6_skipCopy(c)}`)
      .join(", ");
  };

  const doBulkHardDelete = async () => {
    if (!hardAcknowledged) return;
    // F1.3 · Feb-2026 — DELETE-text gate for large batches.
    if (selectedCount > 20 && hardDeleteText !== "DELETE") return;
    setBusy(true);
    try {
      const res = await api.post("/leads/bulk-hard-delete", {
        lead_ids: Array.from(selectedIds),
      });
      const requested = res.requested ?? 0;
      const deleted   = res.deleted   ?? 0;
      const skipped   = Array.isArray(res.skipped) ? res.skipped : [];

      // Optimistic row purge — only the ids the server confirms
      // it deleted.  Anything in ``skipped[]`` stays in the list
      // so the user sees WHY the safety lock fired.
      const skippedIdSet = new Set(skipped.map((s) => s.lead_id));
      const requestedIds = Array.from(selectedIds);
      const deletedIds = requestedIds.filter(
        (id) => !skippedIdSet.has(id),
      );
      setRows((prev) => prev.filter((r) => !deletedIds.includes(r.id)));
      clearSelection();
      setHardConfirmOpen(false);
      setHardAcknowledged(false);
      setHardDeleteText("");

      // Primary toast — matches the P6 brief's success wording.
      const primary = deleted === requested
        ? `Deleted ${deleted} lead${deleted === 1 ? "" : "s"}`
        : `Deleted ${deleted} of ${requested} leads`;
      // Grouped skip toast (secondary line under the primary).
      const description = skipped.length > 0
        ? `${skipped.length} skipped · ${_p6_groupedSkipDescription(skipped)}`
        : undefined;
      if (skipped.length === 0) {
        toast.success(primary);
      } else {
        toast(primary, { description });
      }
    } catch (e) {
      // Surface the P6 422 codes distinctly so the user sees WHY
      // the request bounced.  The axios/api wrapper stashes the
      // response body on ``e.body`` (or ``.response.data``).
      const raw = (e && (e.body || e.response?.data)) || {};
      const detail = raw.detail || raw;
      const status = e && (e.status || e.response?.status);
      if (status === 422 && detail && detail.code === "bulk_cap_exceeded") {
        toast.error("You can delete at most 100 leads at once.");
      } else if (status === 403) {
        toast.error("You do not have permission.");
      } else {
        toast.error("Bulk delete failed. Nothing was deleted.");
      }
    } finally { setBusy(false); }
  };

  // Phase 34 · Task HH · Feb 2026 — bulk status change handler. The
  // `LEAD_STATUS_OPTIONS` array (see top of file) drives the dropdown,
  // so any future enum change picks up automatically.
  const doBulkStatusChange = async () => {
    if (!statusConfirmTarget) return;
    setBusy(true);
    try {
      const res = await api.post("/leads/bulk-update-status", {
        ids: Array.from(selectedIds),
        new_status: statusConfirmTarget.value,
      });
      const ok = res.updated_count || 0;
      const failCount = (res.failed || []).length;
      setRows((prev) => prev.map((r) => (
        res.updated.includes(r.id) ? { ...r, status: statusConfirmTarget.value } : r
      )));
      clearSelection();
      setStatusConfirmTarget(null);
      if (failCount === 0) {
        toast.success(`${ok} lead${ok === 1 ? "" : "s"} updated to ${statusConfirmTarget.label}`);
      } else {
        toast(`${ok} updated · ${failCount} skipped`, {
          description: (res.failed || []).slice(0, 3).map((f) => f.reason).join(" · "),
        });
      }
    } catch (e) {
      toast.error(e?.message || "Bulk status update failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto" data-testid="admin-leads-page">
      <div className="mb-4">
        <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
          Leads
        </h1>
        <p className="text-sm" style={{ color: colors.muted }}>
          Every chat conversation with contact info and every form submission
          lands here. Convert to a customer with one click.
        </p>
      </div>

      {/* ── Phase P48 · Feb-2026 · Active / Archive tab switcher ─────
          Sits ABOVE the filter strip so the user always sees which
          bucket they're in.  URL-synced via ``?tab=`` so a hard
          refresh preserves the selection.  Server-side filter — the
          selected tab drives the ``status=`` query param on the
          ``/leads`` GET.  Empty state per tab lands in the table
          body below when ``visible.length === 0``. */}
      <div
        className="mb-3 inline-flex rounded-lg p-1 gap-1"
        style={{
          border: `1px solid ${colors.nav.border}`,
          background: colors.nav.bg,
        }}
        role="tablist"
        aria-label="Lead status tab"
        data-testid="leads-tab-switcher"
      >
        {LEAD_TAB_ORDER.map((tabKey) => {
          const isActive = activeTab === tabKey;
          return (
            <button
              key={tabKey}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveTab(tabKey)}
              className="px-3 py-1.5 text-sm font-semibold rounded-md transition-colors"
              style={{
                color: isActive ? colors.onSurface : colors.nav.fg,
                backgroundColor: isActive ? "#FFFFFF" : "transparent",
              }}
              data-testid={`leads-tab-${tabKey}`}
            >
              {t(`tabs.${tabKey}`, LEAD_TABS[tabKey].label)}
            </button>
          );
        })}
      </div>

      {/* Filter strip — Phase K52.1 · Feb-2026: promoted from a
          bare flex row to a proper navy K52 strip. */}
      <div
        className="rounded-2xl p-3 mb-4 flex items-center gap-2 flex-wrap"
        style={{ backgroundColor: colors.nav.bg, border: `1px solid ${colors.nav.border}` }}
        data-testid="leads-filters"
        data-k52-navy-strip="true"
      >
        {/*
         * Phase N1 · Feb-2026 — Universal input restyle. Search box
         * paints solid-white bg + #0284C7 navy text + blue-500 focus
         * ring, matching the app-wide theme. Icon adopts the same
         * navy. Wrapping div drops its translucent-white overlay so
         * the input renders as a clean white card on the K52.1 navy
         * strip.
         */}
        <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-white border border-slate-200 focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-blue-500 transition-colors">
          <Search size={14} style={{ color: colors.searchIcon }} />
          <input value={filters.search}
                 onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
                 placeholder={t("search_placeholder", "Search name, email, phone")}
                 className="outline-none text-sm bg-white w-56 text-[#0284C7] placeholder:text-[#0284C7]/55"
                 data-testid="lead-search-input" />
        </div>
        <select value={filters.source}
                onChange={(e) => setFilters((f) => ({ ...f, source: e.target.value }))}
                className="text-sm px-2 py-1.5 rounded-lg outline-none"
                style={{ border: `1px solid ${colors.nav.border}`, background: colors.nav.bg, color: colors.nav.fg }}
                data-testid="lead-filter-source-select">
          <option value="">All sources</option>
          <option value="chat_widget">Chat widget</option>
          <option value="form">Any form</option>
          <option value="manual">Manual</option>
          <option value="referral">Referrals only</option>
          {sources.filter((s) => !["chat_widget", "form", "manual"].includes(s) && !s.startsWith("referral_from_customer:")).map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select value={filters.status}
                onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
                className="text-sm px-2 py-1.5 rounded-lg outline-none"
                style={{ border: `1px solid ${colors.nav.border}`, background: colors.nav.bg, color: colors.nav.fg }}
                data-testid="lead-filter-status-select">
          <option value="">{t("filter_all_statuses", "All statuses")}</option>
          {/* Phase P48 · scoped to the current tab.  Archive tab
              lists Closed – Won / Closed – Lost only; Active tab
              lists New / Contacted / Quoted only. */}
          {tabScopedStatusOptions.map((o) => (
            <option key={o.value} value={o.value} data-testid={`lead-status-option-${o.value}`}>
              {t(`status.${o.value}`, o.label)}
            </option>
          ))}
        </select>
        <div className="ml-auto flex items-center gap-3">
          <div
            className="inline-flex items-center rounded-lg p-0.5"
            style={{ border: `1px solid ${colors.nav.border}`, background: "rgba(255,255,255,0.10)" }}
            data-testid="leads-density-toggle"
          >
            {[
              { v: "comfortable", label: "Comfortable" },
              { v: "compact", label: "Compact" },
            ].map((o) => (
              <button
                key={o.v}
                type="button"
                onClick={() => setDensity(o.v)}
                aria-pressed={density === o.v}
                className="px-2 py-0.5 text-[11px] font-semibold rounded-md transition-colors"
                style={{
                  color: density === o.v ? colors.onSurface : colors.nav.fg,
                  backgroundColor: density === o.v ? "#FFFFFF" : "transparent",
                }}
                data-testid={`leads-density-${o.v}`}
              >
                {o.label}
              </button>
            ))}
          </div>
          <div className="text-xs" style={{ color: colors.nav.fgMuted }}>
            {visible.length} of {rows.length}
          </div>
        </div>
      </div>

      {error && <div className="mb-3 text-sm p-2 rounded-lg"
                     style={{ color: "#991B1B", background: "#FEE2E2" }}>{error}</div>}

      <Card className="p-0 overflow-hidden">
        <div className={`grid grid-cols-12 gap-2 px-4 ${headerPad} text-[11px] uppercase font-semibold items-center sticky top-0 z-10`}
             style={{ color: colors.muted, background: colors.surfaceSecondary,
                      borderBottom: `1px solid ${colors.border}` }}
             data-testid="leads-table-header">
          <div className="col-span-1 flex items-center">
            <input
              type="checkbox"
              checked={allVisibleSelected}
              ref={(el) => { if (el) el.indeterminate = indeterminate; }}
              onChange={toggleAll}
              aria-label="Select all leads on this page"
              data-testid="bulk-select-all"
              className="cursor-pointer"
            />
          </div>
          <div className="col-span-1">Date</div>
          <div className="col-span-2">Name</div>
          <div className="col-span-2">Contact</div>
          <div className="col-span-2">Address</div>
          <div className="col-span-1">Service</div>
          <div className="col-span-1">Source</div>
          <div className="col-span-2">Status</div>
        </div>
        {loading && <div className="p-6 text-sm" style={{ color: colors.muted }}>Loading…</div>}
        {!loading && visible.length === 0 && (
          <div className="p-10 text-sm text-center" style={{ color: colors.muted }}
               data-testid="admin-leads-empty">
            {rows.length === 0 ? (
              <div className="flex flex-col items-center gap-1"
                   data-testid={`admin-leads-empty-${activeTab}`}>
                <div className="font-semibold" style={{ color: colors.onSurface }}>
                  {/* Phase P48 · tab-scoped empty state.  Active tab
                      falls through to the historical copy ("No leads
                      yet.").  Archive tab gets a distinct message so
                      a first-time user doesn't think closed leads are
                      permanently missing. */}
                  {activeTab === "archive"
                    ? t("empty.archive.title", "No archived leads yet.")
                    : t("empty.active.title", "No active leads yet.")}
                </div>
                <div style={{ color: colors.muted }}>
                  {activeTab === "archive"
                    ? t("empty.archive.subtitle", "Leads move here when marked Closed – Won or Closed – Lost.")
                    : t("empty.active.subtitle", "New leads land here from the website form, chat widget, and manual entries.")}
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-1"
                   data-testid="admin-leads-empty-search">
                <div className="font-semibold" style={{ color: colors.onSurface }}>
                  {t("empty.search.title", "No leads match your filters")}
                </div>
                <button
                  type="button"
                  onClick={() => setFilters({ source: "", status: "", search: "" })}
                  className="text-xs font-semibold underline"
                  style={{ color: colors.brand }}
                  data-testid="admin-leads-clear-filters"
                >
                  {t("empty.search.clear", "Clear filters")}
                </button>
              </div>
            )}
          </div>
        )}
        {visible.map((l) => (
          <div key={l.id}
               data-testid={`lead-row-${l.id}`}
               className={`grid grid-cols-12 gap-2 px-4 ${rowPad} items-center text-sm hover:bg-slate-50 cursor-pointer transition-colors`}
               style={{
                 borderBottom: `1px solid ${colors.border}`,
                 backgroundColor: selectedIds.has(l.id) ? "#EFF6FF" : "transparent",
               }}
               onClick={() => setSelected(l)}>
            <div className="col-span-1" onClick={(e) => e.stopPropagation()}>
              <input
                type="checkbox"
                checked={selectedIds.has(l.id)}
                onChange={() => toggleOne(l.id)}
                aria-label={`Select lead ${l.name || l.id}`}
                data-testid={`bulk-select-row-${l.id}`}
                className="cursor-pointer"
              />
            </div>
            <div className="col-span-1 text-xs" style={{ color: colors.muted }}>
              {(l.created_at || "").slice(0, 10)}
            </div>
            <div className="col-span-2 font-semibold" style={{ color: colors.onSurface }}>
              <CustomerLink customerId={l.customer_id} name={l.name || "—"} />
              {/* Phase F5 · Feb-2026 — company_name subtitle when
                  the form submission carried one. */}
              {l.company_name ? (
                <div
                  className="text-[11px] font-normal"
                  style={{ color: colors.muted }}
                  data-testid={`lead-company-${l.id}`}
                >
                  {l.company_name}
                </div>
              ) : null}
            </div>
            <div className="col-span-2 text-xs" style={{ color: colors.muted }}>
              {l.email && <div>{l.email}</div>}
              {l.phone && <div><PhoneLink phone={l.phone} /></div>}
            </div>
            {/* Feb-2026 · Address column — added between Contact and
                Source per user request.  Truncates to a single line
                with the full string on ``title=`` hover for cases
                where the address exceeds the column width.
                Phase P0.5 · Feb-2026 — when the row has NO address
                data at all (no street blob AND no discrete city /
                state / zip) render an explicit muted
                "No address provided" line instead of an em-dash so
                ops can tell the visitor left the field blank vs the
                UI dropping data. */}
            <div
              className="col-span-2 text-xs truncate"
              style={{ color: colors.muted }}
              title={[l.address || l.service_address,
                       [l.city, l.state].filter(Boolean).join(", "),
                       l.zip].filter(Boolean).join(" · ") || ""}
              data-testid={`lead-address-${l.id}`}
            >
              {(() => {
                const line1 = l.address || l.service_address;
                const csz = [l.city, l.state].filter(Boolean).join(", ");
                const cszZip = [csz, l.zip].filter(Boolean).join(" ");
                if (!line1 && !cszZip) {
                  return (
                    <span
                      style={{ opacity: 0.6, fontStyle: "italic" }}
                      data-testid={`lead-address-empty-${l.id}`}
                    >
                      No address provided
                    </span>
                  );
                }
                return (
                  <>
                    {line1 ? (
                      <div className="truncate">
                        <AddressLink address={line1} />
                      </div>
                    ) : null}
                    {cszZip ? (
                      <div className="truncate" style={{ opacity: 0.8 }}>
                        <AddressLink
                          address={[line1, cszZip].filter(Boolean).join(", ")}
                        >
                          {cszZip}
                        </AddressLink>
                      </div>
                    ) : null}
                  </>
                );
              })()}
            </div>
            {/* Phase P0.5 · Feb-2026 — Service column surfaces
                ``service_interest`` (previously only visible in the
                detail card).  When empty, render a muted em-dash so
                the column is never blank. */}
            <div
              className="col-span-1 text-xs truncate"
              style={{ color: colors.muted }}
              title={l.service_interest || ""}
              data-testid={`lead-service-${l.id}`}
            >
              {l.service_interest ? (
                <span style={{ color: colors.onSurface }}>{l.service_interest}</span>
              ) : (
                <span style={{ opacity: 0.5 }}>—</span>
              )}
            </div>
            <div className="col-span-1">
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                    style={{ background: "#F1F5F9", color: "#475569" }}>
                {SOURCE_LABEL(l.source)}
              </span>
              {isReferral(l) ? (
                <span
                  className="ml-1 text-[10px] font-bold px-1.5 py-0.5 rounded-full uppercase"
                  style={{ background: "#FEF3C7", color: "#92400E" }}
                  data-testid={`lead-referral-badge-${l.id}`}
                  title={l.referrer_customer_name
                    ? `Referred by ${l.referrer_customer_name}`
                    : "Referred by an existing customer"}
                >
                  Referral
                </span>
              ) : null}
              {l.duplicate_of_existing_contact ? (
                <span
                  className="ml-1 text-[10px] font-bold px-1.5 py-0.5 rounded-full uppercase"
                  style={{ background: "#FEE2E2", color: "#991B1B" }}
                  title="This contact matches an existing customer or a recent lead."
                >
                  Dup
                </span>
              ) : null}
            </div>
            <div className="col-span-2 flex items-center justify-between gap-1">
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                    style={{
                      background: (STATUS_COLORS[l.status] || STATUS_COLORS.new).bg,
                      color: (STATUS_COLORS[l.status] || STATUS_COLORS.new).fg,
                    }}>
                {t(`status.${l.status}`, STATUS_LABEL(l.status))}
              </span>
              {isPrivileged && (
                <div
                  className="flex items-center gap-1"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    type="button"
                    disabled={!l.phone}
                    onClick={() => l.phone && setComposeTarget({ lead: l, channel: "sms" })}
                    title={l.phone ? `Send SMS to ${l.name || l.phone}` : "No phone on file"}
                    aria-label={`Send SMS to ${l.name || l.phone || "lead"}`}
                    className="p-1 rounded hover:bg-slate-100 text-slate-500 disabled:opacity-30 disabled:cursor-not-allowed"
                    data-testid={`lead-row-sms-${l.id}`}
                  >
                    <MessageCircle size={14} />
                  </button>
                  <button
                    type="button"
                    disabled={!l.email}
                    onClick={() => l.email && setComposeTarget({ lead: l, channel: "email" })}
                    title={l.email ? `Send email to ${l.name || l.email}` : "No email on file"}
                    aria-label={`Send email to ${l.name || l.email || "lead"}`}
                    className="p-1 rounded hover:bg-slate-100 text-slate-500 disabled:opacity-30 disabled:cursor-not-allowed"
                    data-testid={`lead-row-email-${l.id}`}
                  >
                    <Mail size={14} />
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
      </Card>

      {selected && (
        <LeadDetailDrawer
          lead={selected}
          onClose={() => setSelected(null)}
          onUpdated={() => { setSelected(null); refresh(); }}
        />
      )}

      {composeTarget && (
        <LeadComposeModal
          lead={composeTarget.lead}
          channel={composeTarget.channel}
          onClose={() => setComposeTarget(null)}
          onSent={() => refresh()}
        />
      )}

      {/* Phase 34 · Task BB · Feb 2026 — floating bulk-action bar. */}
      {selectedCount > 0 ? (
        <div
          className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-2xl shadow-2xl flex items-center gap-3 px-4 py-3 z-40"
          style={{ backgroundColor: colors.onSurface, color: "#FFFFFF",
                    border: "1px solid rgba(255,255,255,0.08)" }}
          data-testid="bulk-action-bar"
        >
          <div className="text-sm font-semibold" data-testid="bulk-action-bar-count">
            {selectedCount} selected
          </div>

          {/* Phase 34 · Task HH · bulk status-change dropdown. */}
          <div className="relative">
            <button type="button"
                      onClick={() => setStatusMenuOpen((v) => !v)}
                      disabled={busy}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold"
                      style={{ backgroundColor: "#1D4ED8", color: "#FFFFFF" }}
                      data-testid="bulk-status-change-button">
              Change status <ChevronDown size={12} />
            </button>
            {statusMenuOpen ? (
              <div
                className="absolute bottom-full mb-2 left-0 w-56 rounded-xl shadow-2xl overflow-hidden"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="bulk-status-menu"
              >
                {LEAD_STATUS_OPTIONS.map((o) => (
                  <button
                    key={o.value}
                    type="button"
                    onClick={() => { setStatusMenuOpen(false); setStatusConfirmTarget(o); }}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50"
                    style={{ color: colors.onSurface }}
                    data-testid={`bulk-status-option-${o.value}`}
                  >
                    <span
                      className="inline-block w-2.5 h-2.5 rounded-full mr-2 align-middle"
                      style={{ background: (STATUS_COLORS[o.value] || STATUS_COLORS.new).bg,
                                border: `1px solid ${(STATUS_COLORS[o.value] || STATUS_COLORS.new).fg}` }}
                    />
                    {o.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <button type="button" onClick={() => setConfirmOpen(true)} disabled={busy}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold"
                    style={{ backgroundColor: "#B45309", color: "#FFFFFF" }}
                    data-testid="bulk-delete-button">
            <Trash2 size={12} /> Archive selected
          </button>
          <button type="button" onClick={() => { setHardConfirmOpen(true); setHardAcknowledged(false); setHardDeleteText(""); }} disabled={busy}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold"
                    style={{ backgroundColor: "#DC2626", color: "#FFFFFF" }}
                    data-testid="bulk-hard-delete-button">
            <Trash2 size={12} /> Delete permanently ({selectedCount})
          </button>
          <button type="button" onClick={clearSelection}
                    className="text-xs font-semibold underline"
                    style={{ color: "rgba(255,255,255,0.85)" }}
                    data-testid="bulk-clear-selection">
            Clear selection
          </button>
        </div>
      ) : null}

      {/* Phase 34 · Task HH · confirmation modal for bulk status change. */}
      {statusConfirmTarget ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
              style={{ background: "rgba(15,23,42,0.55)" }}
              onMouseDown={(e) => { if (e.target === e.currentTarget) setStatusConfirmTarget(null); }}
              data-testid="bulk-status-confirm-modal">
          <div className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                onMouseDown={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
                  Change {selectedCount} lead{selectedCount === 1 ? "" : "s"} to "{statusConfirmTarget.label}"?
                </h2>
                <p className="text-sm mt-1" style={{ color: colors.muted }}>
                  This will overwrite existing statuses. Leads already at
                  "{statusConfirmTarget.label}" will be skipped.
                </p>
              </div>
              <button type="button" onClick={() => setStatusConfirmTarget(null)}
                        className="p-1" style={{ color: colors.muted }} aria-label="Close">
                <X size={18} />
              </button>
            </div>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button type="button" onClick={() => setStatusConfirmTarget(null)}
                        className="px-4 py-2 rounded-xl text-sm font-semibold"
                        style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                        data-testid="bulk-status-confirm-cancel">
                Cancel
              </button>
              <button type="button" onClick={doBulkStatusChange} disabled={busy}
                        className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
                        style={{ backgroundColor: "#1D4ED8" }}
                        data-testid="bulk-status-confirm-btn">
                {busy ? "Updating…" : `Change ${selectedCount}`}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {confirmOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
              style={{ background: "rgba(15,23,42,0.55)" }}
              onMouseDown={(e) => { if (e.target === e.currentTarget) setConfirmOpen(false); }}
              data-testid="bulk-delete-confirm">
          <div className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                onMouseDown={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
                  Archive {selectedCount} lead{selectedCount === 1 ? "" : "s"}?
                </h2>
                <p className="text-sm mt-1" style={{ color: colors.muted }}>
                  {selectedCount > 100
                    ? "This is a large batch — please confirm. Archived leads can be restored. Closed–Won leads with linked customers/jobs are protected and will show up as \"locked\" in the result."
                    : "Archived leads can be restored. Closed–Won leads with linked customers/jobs are protected."}
                </p>
              </div>
              <button type="button" onClick={() => setConfirmOpen(false)} className="p-1"
                        style={{ color: colors.muted }} aria-label="Close">
                <X size={18} />
              </button>
            </div>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button type="button" onClick={() => setConfirmOpen(false)}
                        className="px-4 py-2 rounded-xl text-sm font-semibold"
                        style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                        data-testid="bulk-delete-cancel">
                Cancel
              </button>
              <button type="button" onClick={doBulkDelete} disabled={busy}
                        className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
                        style={{ backgroundColor: "#B45309" }}
                        data-testid="bulk-delete-confirm-btn">
                {busy ? "Archiving…" : `Archive ${selectedCount}`}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Phase LD1 · Feb 2026 — bulk HARD delete confirmation. Requires
          the admin to tick the acknowledge checkbox before the destructive
          button becomes enabled, mirroring the pattern used by other
          irreversible flows in the app. */}
      {hardConfirmOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
              style={{ background: "rgba(15,23,42,0.65)" }}
              onMouseDown={(e) => {
                if (e.target === e.currentTarget) {
                  setHardConfirmOpen(false); setHardAcknowledged(false); setHardDeleteText("");
                }
              }}
              data-testid="bulk-hard-delete-confirm">
          <div className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                onMouseDown={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-lg font-bold" style={{ color: "#991B1B" }}>
                  Permanently delete {selectedCount} lead{selectedCount === 1 ? "" : "s"}?
                </h2>
                <p className="text-sm mt-1" style={{ color: colors.muted }}>
                  This action cannot be undone. The lead row, its timeline,
                  and any linked notes will be removed from the database.
                  Closed–Won leads with linked customers/jobs are protected
                  and will surface as "locked" in the result.
                </p>
              </div>
              <button type="button"
                        onClick={() => { setHardConfirmOpen(false); setHardAcknowledged(false); setHardDeleteText(""); }}
                        className="p-1" style={{ color: colors.muted }} aria-label="Close">
                <X size={18} />
              </button>
            </div>
            <label className="flex items-start gap-2 mt-4 text-sm cursor-pointer select-none"
                      style={{ color: colors.onSurface }}
                      data-testid="bulk-hard-delete-ack-label">
              <input
                type="checkbox"
                checked={hardAcknowledged}
                onChange={(e) => setHardAcknowledged(e.target.checked)}
                className="mt-0.5 cursor-pointer"
                data-testid="bulk-hard-delete-ack"
              />
              <span>
                I understand this is permanent and cannot be recovered.
              </span>
            </label>
            {/* F1.3 · Feb-2026 — extra DELETE-text gate when the
                selection exceeds 20 rows. Backend also rate-limits
                but this gives the operator a physical typing beat
                they can't accidentally skip. */}
            {selectedCount > 20 ? (
              <div className="mt-4" data-testid="bulk-hard-delete-text-gate">
                <label className="block text-[10px] font-bold uppercase mb-1"
                          style={{ color: colors.muted }}>
                  Type <span className="font-mono" style={{ color: "#DC2626" }}>DELETE</span> to confirm
                </label>
                <input
                  type="text"
                  value={hardDeleteText}
                  onChange={(e) => setHardDeleteText(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="DELETE"
                  className="w-full px-3 py-2 rounded-lg text-sm outline-none font-mono"
                  style={{ border: `1px solid ${colors.border}`,
                            background: "#FFF" }}
                  data-testid="bulk-hard-delete-text-input"
                />
              </div>
            ) : null}
            <div className="mt-5 flex items-center justify-end gap-2">
              <button type="button"
                        onClick={() => { setHardConfirmOpen(false); setHardAcknowledged(false); setHardDeleteText(""); }}
                        className="px-4 py-2 rounded-xl text-sm font-semibold"
                        style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                        data-testid="bulk-hard-delete-cancel">
                Cancel
              </button>
              <button type="button" onClick={doBulkHardDelete}
                        disabled={busy
                          || !hardAcknowledged
                          || (selectedCount > 20 && hardDeleteText !== "DELETE")}
                        className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-40 disabled:cursor-not-allowed"
                        style={{ backgroundColor: "#DC2626" }}
                        data-testid="bulk-hard-delete-confirm-btn">
                {busy ? "Deleting…" : `Delete ${selectedCount} permanently`}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}


function LeadDetailDrawer({ lead, onClose, onUpdated }) {
  const { t } = useTranslation("leads");
  const [status, setStatus] = useState(lead.status || "new");
  const [notes, setNotes] = useState(lead.notes || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Feb-2026 · Raw form submission lazy-load. Only fetches when the
  // lead has a linked submission (``meta.submission_id``); otherwise
  // the panel stays hidden. Endpoint enforces the tenant scope + role
  // gate again server-side — this hook trusts the 404 to hide the
  // panel gracefully on cross-tenant / missing rows.
  const submissionId = lead?.meta?.submission_id || null;
  const [rawSub, setRawSub] = useState(null);
  const [rawState, setRawState] = useState(submissionId ? "idle" : "none");
  const [rawErr, setRawErr] = useState("");
  useEffect(() => {
    if (!submissionId) { setRawState("none"); return; }
    let cancelled = false;
    setRawState("loading"); setRawErr("");
    api.get(`/leads/${lead.id}/raw-submission`)
      .then((d) => { if (!cancelled) { setRawSub(d); setRawState("ready"); } })
      .catch((e) => {
        if (cancelled) return;
        // 404 → no linked submission (legacy leads) → hide panel.
        // Any other error → surface message but still keep panel closed.
        if (String(e?.status || e?.message || "").includes("404")) {
          setRawState("none");
        } else {
          setRawErr(e?.message || "Failed to load submission");
          setRawState("error");
        }
      });
    return () => { cancelled = true; };
  }, [lead.id, submissionId]);

  const save = async () => {
    setBusy(true); setError("");
    try {
      await api.put(`/leads/${lead.id}`, { status, notes });
      onUpdated();
    } catch (e) { setError(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  const convert = async () => {
    const ok = await mustConfirm({
      title: `Convert "${lead.name || lead.email}" into a customer?`,
      description: "The lead will be closed as converted and a new customer record created.",
      confirmText: "Convert",
    });
    if (!ok) return;
    setBusy(true); setError("");
    try {
      await api.post(`/leads/${lead.id}/convert`, {});
      onUpdated();
    } catch (e) { setError(e?.message || "Convert failed"); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end"
         style={{ background: "rgba(15,23,42,.35)" }}
         onClick={onClose}
         data-testid="lead-detail-drawer">
      <div className="bg-white w-full max-w-lg overflow-y-auto"
           style={{ height: "100vh" }}
           onClick={(e) => e.stopPropagation()}>
        <div className="p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-xl font-bold" style={{ color: colors.onSurface }}>
                {lead.name || "Lead"}
              </h2>
              {/* Phase F5 · Feb-2026 — company_name subtitle. */}
              {lead.company_name ? (
                <div
                  className="text-sm font-semibold"
                  style={{ color: colors.muted }}
                  data-testid="lead-company"
                >
                  {lead.company_name}
                </div>
              ) : null}
              <div className="text-xs" style={{ color: colors.muted }}>
                {SOURCE_LABEL(lead.source)} · {(lead.created_at || "").slice(0, 10)}
              </div>
            </div>
            <button onClick={onClose} data-testid="lead-close-btn"
                    className="p-1"><X size={18} color={colors.muted} /></button>
          </div>

          <div className="mb-4 text-sm" data-testid="lead-contact-block">
            {lead.email && <div><b>Email:</b> {lead.email}</div>}
            {/* Phase L1.7 · Feb-2026 — smart-link sweep: wrap the
                lead's phone in <PhoneLink> so tapping opens the
                dialer / SMS composer per operator role. */}
            {lead.phone && (
              <div><b>Phone:</b> <PhoneLink phone={lead.phone} /></div>
            )}
            {/* Feb-2026 · Lead detail display fix — surface the
                street address on its own labeled row above the
                City/State/Zip line. Falls back through
                ``address → service_address`` because widget-form
                submissions persist under ``service_address`` while
                admin-manual creates persist under ``address``. */}
            {(lead.address || lead.service_address) && (
              <div data-testid="lead-detail-address">
                <b>Address:</b> {lead.address || lead.service_address}
              </div>
            )}
            {lead.service_address && lead.address
              && lead.service_address !== lead.address && (
              <div data-testid="lead-service-address">
                <b>Service address:</b> {lead.service_address}
              </div>
            )}
            {/* Phase F5 · Feb-2026 — City/State/Zip line when any
                of them are populated.  Renders as the single
                canonical address second line. */}
            {(lead.city || lead.state || lead.zip) ? (
              <div data-testid="lead-city-state-zip">
                <b>{lead.city && lead.state
                     ? "City / State / Zip:"
                     : lead.zip
                     ? "Zip:"
                     : lead.city
                     ? "City:"
                     : "State:"}</b>{" "}
                {[lead.city, lead.state].filter(Boolean).join(", ")}
                {lead.zip
                  ? (lead.city || lead.state ? " " : "") + lead.zip
                  : ""}
              </div>
            ) : null}
            {/* Feb-2026 · Lead detail display fix — dedicated row
                for the customer's requested service, previously
                labeled "Interested in:" which was easy to miss.
                Renamed to match the widget's front-end label
                ("Requested Service") + testid the admins can rely
                on across UI tests. */}
            {lead.service_interest && (
              <div data-testid="lead-detail-service-interest">
                <b>Requested Service:</b> {lead.service_interest}
              </div>
            )}
          </div>

          {/* Feb-2026 · P17 — display the customer's inquiry
              message when the widget captured one.  Falls back
              silently for legacy leads that never had a message
              field (e.g. pre-P17 "Website Visitor" rows). */}
          {lead.message && (
            <div
              className="mb-4 p-3 rounded-lg text-sm"
              style={{ background: "#F0F9FF", border: "1px solid #BAE6FD" }}
              data-testid="lead-message-block"
            >
              <div
                className="text-[10px] font-bold uppercase mb-1"
                style={{ color: "#075985" }}
              >
                Inquiry message
              </div>
              <div style={{ color: "#0C4A6E", whiteSpace: "pre-wrap" }}>
                {lead.message}
              </div>
            </div>
          )}

          {isReferral(lead) ? (
            <div
              className="mb-4 p-3 rounded-lg text-sm"
              style={{ background: "#FEF3C7", border: "1px solid #FCD34D" }}
              data-testid="lead-referrer-info"
            >
              <div className="text-[10px] font-bold uppercase" style={{ color: "#92400E" }}>
                Referred by
              </div>
              <div className="font-semibold mt-0.5" style={{ color: "#92400E" }}>
                {lead.referrer_customer_name || "Existing customer"}
              </div>
              {lead.referrer_customer_id ? (
                <a
                  href={`/customers/${lead.referrer_customer_id}`}
                  className="text-xs font-semibold underline"
                  style={{ color: "#78350F" }}
                  data-testid="lead-referrer-link"
                >
                  Open referrer's profile →
                </a>
              ) : null}
              {lead.service_of_interest ? (
                <div className="text-xs mt-1" style={{ color: "#78350F" }}>
                  Interested in: <b>{lead.service_of_interest}</b>
                </div>
              ) : null}
            </div>
          ) : null}

          {lead.meta && Object.keys(lead.meta).length > 0 && (
            <details className="mb-4 text-sm">
              <summary className="cursor-pointer font-semibold"
                       style={{ color: colors.muted }}>Extra fields</summary>
              <pre className="text-xs font-mono p-2 rounded mt-2"
                   style={{ background: colors.surfaceSecondary }}>
{JSON.stringify(lead.meta, null, 2)}
              </pre>
            </details>
          )}

          {/* Feb-2026 · Raw form submission panel. Only renders when
              the lead has a linked submission the caller can actually
              see (server enforces tenant + role gate).  ``rawState``
              is ``"none"`` for legacy leads and pre-P17 rows — we hide
              the panel entirely rather than showing an empty box. */}
          {rawState !== "none" ? (
            <details
              className="mb-4 text-sm"
              data-testid="lead-raw-submission-panel"
              open
            >
              <summary
                className="cursor-pointer font-semibold"
                style={{ color: colors.muted }}
              >
                Raw form submission
              </summary>
              {rawState === "loading" && (
                <div
                  className="text-xs p-2"
                  style={{ color: colors.muted }}
                  data-testid="lead-raw-submission-loading"
                >
                  Loading submission…
                </div>
              )}
              {rawState === "error" && (
                <div
                  className="text-xs p-2 rounded"
                  style={{ color: "#991B1B", background: "#FEE2E2" }}
                  data-testid="lead-raw-submission-error"
                >
                  {rawErr}
                </div>
              )}
              {rawState === "ready" && rawSub ? (
                <div className="mt-2">
                  {rawSub.page_url ? (
                    <div
                      className="text-[10px] font-mono mb-1"
                      style={{ color: colors.muted }}
                      data-testid="lead-raw-submission-page-url"
                    >
                      {rawSub.page_url}
                    </div>
                  ) : null}
                  <pre
                    className="text-xs font-mono p-2 rounded overflow-x-auto"
                    style={{ background: colors.surfaceSecondary }}
                    data-testid="lead-raw-submission-json"
                  >
{JSON.stringify(rawSub.values || {}, null, 2)}
                  </pre>
                </div>
              ) : null}
            </details>
          ) : null}

          <label className="block text-[10px] font-bold uppercase mb-1"
                 style={{ color: colors.muted }}>Status</label>
          <select value={status}
                  onChange={(e) => setStatus(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg text-sm outline-none mb-3"
                  style={{ border: `1px solid ${colors.border}`, background: "#fff" }}
                  data-testid="lead-status-select">
            {LEAD_STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}
                        data-testid={`lead-status-edit-option-${o.value}`}>
                {t(`status.${o.value}`, o.label)}
              </option>
            ))}
          </select>

          <label className="block text-[10px] font-bold uppercase mb-1"
                 style={{ color: colors.muted }}>Notes</label>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)}
                    rows={4}
                    className="w-full px-3 py-2 rounded-lg text-sm outline-none mb-3"
                    style={{ border: `1px solid ${colors.border}` }}
                    data-testid="lead-notes-input" />

          {error && <div className="mb-3 text-sm p-2 rounded-lg"
                         style={{ color: "#991B1B", background: "#FEE2E2" }}>{error}</div>}

          <div className="flex justify-end gap-2">
            <button onClick={save} disabled={busy}
                    className="px-3 py-2 rounded-xl text-sm font-semibold"
                    style={{ border: `1px solid ${colors.border}`,
                             color: colors.onSurface, background: "#fff" }}
                    data-testid="lead-save-btn">
              Save
            </button>
            {lead.status !== "converted" && (
              <button onClick={convert} disabled={busy}
                      className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
                      style={{ background: colors.brand }}
                      data-testid="lead-convert-btn">
                Convert to customer <ArrowRight size={14} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
