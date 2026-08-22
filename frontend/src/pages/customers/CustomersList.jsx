import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation, useSearchParams } from "react-router-dom";
import { Plus, Search, Upload, Download, Filter, MoreVertical, Users, Tag, BellRing, UserCheck, UserX, Star } from "lucide-react";
import { toast as sonnerToast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { usePermissions } from "@/hooks/usePermissions";
import { PageHeader, TagChip, Chip, Skeleton, EmptyState, Button, Modal, Toast } from "@/components/ui-kit";
import CustomersTagFilterDropdown from "@/components/customers/CustomersTagFilterDropdown";
import RestoreCustomerButton from "@/components/customers/RestoreCustomerButton";
import MuteControl from "@/components/customers/MuteControl";
import CustomersPager from "@/components/customers/CustomersPager";


// Feb-2026 · P28 — tiny relative-time formatter for the Muted saved
// view's "Muted <ago>" per-row label. Purely a display helper; falls
// back to the raw ISO string when parsing fails.
function _p28RelativeTime(iso) {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (isNaN(t)) return iso;
  const diffMs = Date.now() - t;
  if (diffMs < 0) return "just now";
  const s = Math.floor(diffMs / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  const y = Math.floor(mo / 12);
  return `${y}y ago`;
}

import {
  BulkActionBar,
  BulkConfirmModal,
  LockedPill,
  SelectAllMatchingLink,
} from "@/components/bulk-select/BulkSelectToolkit";

const TAG_PRESETS = ["VIP", "Specialty"];

function useDebounced(value, delay = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

export default function CustomersList() {
  const navigate = useNavigate();
  const location = useLocation();
  const cohortParam = location.pathname.endsWith("/inactive")
    ? "inactive"
    : location.pathname.endsWith("/active")
    ? "active"
    : null;
  const [searchParams, setSearchParams] = useSearchParams();
  const { role, effectiveRole } = usePermissions();
  const isAdmin =
    role === "admin" || role === "super_admin" ||
    effectiveRole === "admin" || effectiveRole === "super_admin";
  const isAdminOrManager =
    isAdmin || role === "manager" || effectiveRole === "manager";
  // Feb-2026 · P26 — super_admin-only escape hatch to browse
  // soft-deleted customers and Restore them.  Gated to super_admin
  // to match the P25 backend contract (403 for lower roles).
  const isSuperAdmin =
    role === "super_admin" || effectiveRole === "super_admin";
  const [includeDeleted, setIncludeDeleted] = useState(false);

  // Phase 56.2 — active | inactive tabs. `all` retained as a legacy escape
  // hatch (used to be the default) — accessible via `?tab=all` for admins
  // who need to see everything in one list.
  const initialTab = cohortParam === "inactive" ? "inactive"
                    : cohortParam === "active" ? "active"
                    : (searchParams.get("tab") || "active");
  const [tab, setTab] = useState(initialTab);
  const [counts, setCounts] = useState({ active: null, inactive: null });

  const [rows, setRows] = useState(null);
  // Feb-2026 · P35 — server-side pagination. Page is URL-synced so
  // refresh preserves position. Page size is fixed at 100 to match
  // the phase brief; the response envelope drives ``total`` and
  // ``totalPages``.
  const _PAGE_SIZE = 100;
  const [page, setPage] = useState(() => {
    const raw = parseInt(searchParams.get("page") || "1", 10);
    return Number.isFinite(raw) && raw >= 1 ? raw : 1;
  });
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  // Feb-2026 · Tag chip filter bar — multi-select AND semantics.
  // Client-side filter after the initial fetch (backend GET
  // /customers only supports single-tag today).
  const [allTags, setAllTags] = useState([]);
  const [selectedTags, setSelectedTags] = useState(() => {
    try {
      const raw = new URLSearchParams(window.location.search).get("tags");
      return new Set((raw || "").split(",").map((t) => t.trim())
        .filter(Boolean));
    } catch { return new Set(); }
  });
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [scope, setScope] = useState("all"); // all | waitlist | unscheduled
  const [selected, setSelected] = useState(new Set());
  const [bulkTag, setBulkTag] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const [activationConfirm, setActivationConfirm] = useState(null); // {customer, nextActive}
  const [activationBusy, setActivationBusy] = useState(false);
  // Phase 12 · Feb 2026 — "Missing card" filter chip state must live
  // ABOVE ``load()`` since it participates in the request query.
  const [missingCardOnly, setMissingCardOnly] = useState(false);
  const searchDeb = useDebounced(q);

  // Non-admin users cannot land on the inactive or muted cohort — redirect to active.
  useEffect(() => {
    if (!isAdmin && (tab === "inactive" || tab === "muted")) setTab("active");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]);

  // Sync tab → URL so route + query stay honest across refresh / share.
  useEffect(() => {
    if (cohortParam && cohortParam !== tab && (tab === "active" || tab === "inactive")) {
      navigate(`/customers/${tab}`, { replace: true });
    } else if (!cohortParam) {
      const next = new URLSearchParams(searchParams);
      if (tab === "active") next.delete("tab"); else next.set("tab", tab);
      setSearchParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const load = async () => {
    setRows(null);
    const params = new URLSearchParams();
    if (searchDeb) params.set("search", searchDeb);
    if (tag) params.set("tag", tag);
    if (scope === "waitlist") params.set("waitlisted", "true");
    if (scope === "unscheduled") params.set("unscheduled", "true");
    if (tab === "active") params.set("is_active", "true");
    else if (tab === "inactive") params.set("is_active", "false");
    else if (tab === "muted") params.set("is_muted", "true");
    if (missingCardOnly) params.set("missing_card", "true");
    // Feb-2026 · P26 — super_admin escape hatch to see soft-deleted rows.
    if (includeDeleted && isSuperAdmin) params.set("include_deleted", "true");
    // Feb-2026 · P35 — always request the paginated envelope.
    params.set("page", String(page));
    params.set("page_size", String(_PAGE_SIZE));
    try {
      const data = await api.get(`/customers?${params.toString()}`);
      // Envelope-shaped when page/page_size present (Strategy B).
      const items = Array.isArray(data) ? data : (data?.items || []);
      setRows(items);
      setTotal(Number.isFinite(data?.total) ? data.total : items.length);
      setTotalPages(Number.isFinite(data?.total_pages)
        ? data.total_pages
        : (items.length ? 1 : 0));
      setSelected(new Set());
    } catch (e) {
      setToast({ tone: "error", message: e.message });
      setRows([]);
      setTotal(0);
      setTotalPages(0);
    }
  };

  const loadCounts = async () => {
    try {
      const promises = [
        api.get("/customers?is_active=true&count_only=true"),
        api.get("/customers?is_active=false&count_only=true"),
      ];
      // Feb-2026 · P28 — muted-count endpoint is admin/manager/
      // super_admin only; tech role 403s. Skip the call for tech to
      // avoid a noisy request that will always fail.
      if (isAdmin) {
        promises.push(api.get("/customers?is_muted=true&count_only=true"));
      }
      const results = await Promise.all(promises);
      setCounts({
        active: results[0]?.count ?? 0,
        inactive: results[1]?.count ?? 0,
        muted: isAdmin ? (results[2]?.count ?? 0) : null,
      });
    } catch { /* silent — counts are advisory */ }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchDeb, tag, scope, tab, missingCardOnly, includeDeleted, page]);

  // Feb-2026 · P35 — any filter or tab change resets pagination to
  // page 1 so the user doesn't land on an empty page after narrowing
  // the result set. The load effect above then fires with page=1.
  const _firstFilterEffect = useRef(true);
  useEffect(() => {
    if (_firstFilterEffect.current) {
      _firstFilterEffect.current = false;
      return;
    }
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchDeb, tag, scope, tab, missingCardOnly, includeDeleted]);

  // Feb-2026 · P35 — URL sync for ``page``. ``page=1`` is the default
  // so it's dropped from the URL to keep the query string tidy.
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    if (page > 1) next.set("page", String(page));
    else next.delete("page");
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  useEffect(() => {
    loadCounts();
  }, []);

  // Feb-2026 · Load tag registry for the chip filter bar. One-shot
  // on mount — recomputed usage counts land via GET /customer-tags.
  useEffect(() => {
    (async () => {
      try {
        const res = await api.get("/customer-tags");
        setAllTags(res?.items || []);
      } catch { setAllTags([]); }
    })();
  }, []);

  // URL sync — every selectedTags change updates ?tags= in-place.
  useEffect(() => {
    try {
      const p = new URLSearchParams(window.location.search);
      const arr = Array.from(selectedTags);
      if (arr.length) p.set("tags", arr.join(","));
      else p.delete("tags");
      const q = p.toString();
      window.history.replaceState(null, "",
        window.location.pathname + (q ? "?" + q : ""));
    } catch { /* silent */ }
  }, [selectedTags]);

  // AND filter on tag membership. Tag rendering (system-first,
  // alphabetical, search-filtered) is owned by
  // ``CustomersTagFilterDropdown`` — no local sortedTags needed.

  const cities = useMemo(() => {
    const s = new Set();
    (rows || []).forEach((r) => {
      const c = (r.address || "").split(",").slice(-2, -1)[0]?.trim();
      if (c) s.add(c);
    });
    return Array.from(s).sort();
  }, [rows]);

  const [city, setCity] = useState("");
  // Phase 12 · Feb 2026 — server-side filter reads ``missingCardOnly``
  // via the ``missing_card=true`` query param (set inside ``load()``).
  // The client-side ``filtered`` memo also mirrors the same predicate
  // so switching cohorts doesn't briefly show stale rows.
  const filtered = useMemo(() => {
    if (!rows) return null;
    let out = rows;
    if (city) out = out.filter((r) => (r.address || "").includes(city));
    if (missingCardOnly) out = out.filter((r) =>
      r.effective_require_card_on_file && !r.has_card_on_file);
    // Feb-2026 · Chip filter bar — AND semantics on selected tags.
    if (selectedTags.size > 0) {
      out = out.filter((r) => {
        const rowTags = new Set(r.tags || []);
        for (const t of selectedTags) if (!rowTags.has(t)) return false;
        return true;
      });
    }
    return out;
  }, [rows, city, missingCardOnly, selectedTags]);

  const toggle = (id) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  // Phase 34 · Task LL Phase 2 UI wrap-up · Feb 2026 — bulk-delete via
  // the new /customers/bulk-delete endpoint + locked-state pill.
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [lockedFailures, setLockedFailures] = useState({});
  // Feb-2026 · Unlimited bulk delete — "Select all N matching this
  // filter" flips this flag; delete then calls the backend with a
  // ``query_selector`` payload instead of a bounded ``ids`` array so
  // the super_admin ceiling (10,000) is reachable without loading
  // every id into the browser.
  const [selectAllMatching, setSelectAllMatching] = useState(false);
  // Typed-number confirm — becomes gating for large deletes to
  // prevent an accidental Enter-key mass-nuke. Threshold is the
  // same value that separates "no super_admin needed" from
  // "super_admin required" on the backend so the UI friction lines
  // up with the actual escalation.
  const _TYPED_CONFIRM_THRESHOLD = 500;
  const [confirmTypedNumber, setConfirmTypedNumber] = useState("");

  // Feb-2026 · Total matching the current tab — used both by the
  // "Select all N matching" affordance and the confirm-modal
  // headline. The endpoint at ``/customers?count_only=true`` is
  // cheap (single Mongo count). We use the tab-specific count that
  // ``loadCounts()`` already populates so the fetch cost is zero.
  const _matchingTotal = tab === "inactive"
    ? (counts.inactive || 0)
    : tab === "all"
      ? (counts.active || 0) + (counts.inactive || 0)
      : (counts.active || 0);
  const _pendingDeleteCount = selectAllMatching
    ? _matchingTotal
    : selected.size;

  // Feb-2026 · Bulk-mark-inactive — plain Confirm/Cancel modal state.
  // The prior "type INACTIVATE" gate was removed per user feedback —
  // the header count + first-5 preview is enough friction on its own.
  const [confirmInactiveOpen, setConfirmInactiveOpen] = useState(false);
  const [bulkInactiveBusy, setBulkInactiveBusy] = useState(false);

  const bulk = async (action, extra = {}) => {
    if (!selected.size) return;
    try {
      const res = await api.post("/customers/bulk", {
        ids: Array.from(selected),
        action,
        ...extra,
      });
      setToast({
        tone: "success",
        message: `Bulk ${action}: ${res.updated ?? res.deleted ?? 0} customer${
          (res.updated ?? res.deleted ?? 0) === 1 ? "" : "s"
        }`,
      });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const doBulkDelete = async () => {
    setBulkBusy(true);
    try {
      // Feb-2026 · Unlimited bulk delete — send a ``query_selector``
      // instead of ``ids`` when the user opted into "Select all N
      // matching this filter" so the backend can expand up to its
      // 10k super_admin ceiling without the browser round-tripping
      // every id. Otherwise fall back to the classic ids-array
      // payload (still soft-delete, still tenant-scoped).
      const payload = selectAllMatching
        ? {
            query_selector: {
              ...(searchDeb ? { search: searchDeb } : {}),
              ...(tag ? { tag } : {}),
              ...(tab === "active" ? { is_active: true } : {}),
              ...(tab === "inactive" ? { is_active: false } : {}),
            },
          }
        : { ids: Array.from(selected) };
      const res = await api.post("/customers/bulk-delete", payload);
      const okC = res.deleted_count || 0;
      const failed = res.failed || [];
      if (failed.length) {
        const map = {};
        failed.forEach((f) => { map[f.id] = f.reason; });
        setLockedFailures(map);
        setTimeout(() => setLockedFailures({}), 10000);
      }
      // Optimistic — hide the deleted rows locally.
      setRows((prev) => (prev || []).filter((r) => !(res.deleted || []).includes(r.id)));
      setSelected(new Set());
      setSelectAllMatching(false);
      setConfirmTypedNumber("");
      setConfirmDeleteOpen(false);
      if (failed.length === 0) {
        sonnerToast.success(`${okC} customer${okC === 1 ? "" : "s"} deleted`);
      } else {
        sonnerToast(`${okC} deleted · ${failed.length} locked`, {
          description: failed.slice(0, 3).map((f) => f.reason).join(" · "),
        });
      }
      loadCounts();
    } catch (e) {
      sonnerToast.error(e?.message || "Bulk delete failed");
    } finally { setBulkBusy(false); }
  };

  const doBulkOwner = async (nextOwnerId) => {
    try {
      const res = await api.post("/customers/bulk-update", {
        ids: Array.from(selected),
        patch: { assigned_owner_id: nextOwnerId },
      });
      sonnerToast.success(`${res.updated_count || 0} customer${(res.updated_count || 0) === 1 ? "" : "s"} reassigned`);
      setSelected(new Set());
      load();
    } catch (e) { sonnerToast.error(e?.message || "Reassign failed"); }
  };

  // Feb-2026 · Bulk-mark-inactive — optimistic UI + rollback on error.
  // The typed "INACTIVATE" gate is enforced on the modal itself; this
  // handler assumes the caller already validated it.
  const doBulkInactive = async () => {
    if (!selected.size) return;
    const ids = Array.from(selected);
    // Snapshot pre-flip state for rollback.
    const pre = new Map(
      (rows || []).filter((r) => ids.includes(r.id))
        .map((r) => [r.id, { is_active: r.is_active, status: r.status }]),
    );
    // Optimistic — flip in-place. When the user is on the Active
    // tab, the rows visually "leave" this tab (they still exist in
    // Inactive). Cheapest way: drop them from the list.
    setRows((prev) => (prev || [])
      .map((r) => ids.includes(r.id)
        ? { ...r, is_active: false, status: "inactive" }
        : r)
      .filter((r) => tab === "active" ? r.is_active !== false : true));
    setBulkInactiveBusy(true);
    try {
      const res = await api.patch("/customers/bulk-status", {
        customer_ids: ids, target_status: "inactive",
      });
      const n = res.modified ?? res.matched ?? 0;
      sonnerToast.success(
        `${n} customer${n === 1 ? "" : "s"} marked inactive`,
      );
      setSelected(new Set());
      setConfirmInactiveOpen(false);
      loadCounts();
    } catch (e) {
      // Rollback — restore pre-flip state for every row we optimistically
      // mutated. If the tab was Active, we need to re-inject the dropped
      // rows too — so re-fetch to be safe.
      sonnerToast.error(e?.message || "Bulk mark inactive failed");
      await load();
      // Restore the map onto the freshly-loaded rows in case load() missed
      // any (server-side lag). Best-effort.
      setRows((prev) => (prev || []).map((r) =>
        pre.has(r.id) ? { ...r, ...pre.get(r.id) } : r,
      ));
    } finally {
      setBulkInactiveBusy(false);
    }
  };

  const doExport = async () => {
    try {
      const res = await api.get("/export/customers");
      const blob = new Blob([res.content || ""], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = res.filename || "customers.csv";
      a.click();
      URL.revokeObjectURL(url);
      setToast({ tone: "success", message: `Exported ${res.count} customers` });
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const nextScheduled = (c) => c.next_scheduled_at || "—";

  // Phase 56.2 — inline activation toggle from list rows. Confirms via
  // modal, calls shared PATCH endpoint, optimistically updates the list.
  const openActivationConfirm = (customer, nextActive) => {
    setActivationConfirm({ customer, nextActive });
  };
  const commitActivation = async () => {
    if (!activationConfirm) return;
    const { customer, nextActive } = activationConfirm;
    setActivationBusy(true);
    // Optimistic — flip in-place, update counts.
    setRows((prev) => (prev || []).map((r) =>
      r.id === customer.id ? { ...r, is_active: nextActive } : r
    ));
    try {
      await api.patch(`/customers/${customer.id}/activation`, { is_active: nextActive });
      setToast({
        tone: "success",
        message: nextActive
          ? `${customer.name} reactivated`
          : `${customer.name} marked inactive`,
      });
      setActivationConfirm(null);
      // Row leaves the current cohort — reload the visible list and counts.
      await Promise.all([load(), loadCounts()]);
    } catch (e) {
      // Revert.
      setRows((prev) => (prev || []).map((r) =>
        r.id === customer.id ? { ...r, is_active: !nextActive } : r
      ));
      setToast({ tone: "error", message: e.message });
    } finally {
      setActivationBusy(false);
    }
  };

  const TAB_DEFS = [
    { k: "active", label: "Active", count: counts.active, testid: "tab-active" },
    { k: "inactive", label: "Inactive", count: counts.inactive, testid: "tab-inactive", adminOnly: true },
    { k: "muted", label: "Muted", count: counts.muted, testid: "tab-muted", adminOnly: true },
    { k: "all", label: "All", count: null, testid: "tab-all", adminOnly: true },
  ];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="customers-page">
      <PageHeader
        title="Customers"
        subtitle={
          total > 0
            ? `Showing ${((page - 1) * _PAGE_SIZE + 1).toLocaleString()}-`
              + `${Math.min(page * _PAGE_SIZE, total).toLocaleString()} of `
              + `${total.toLocaleString()}`
            : `${(filtered || []).length} shown`
        }
        right={
          <>
            <Button variant="ghost" onClick={doExport} testid="customers-export">
              <Download size={16} /> Export
            </Button>
            <Button variant="ghost" onClick={() => setImportOpen(true)} testid="customers-import">
              <Upload size={16} /> Import
            </Button>
            <Button onClick={() => navigate("/customers/new")} testid="customers-new-button">
              <Plus size={16} /> New Customer
            </Button>
          </>
        }
      />

      {/* Phase 56.2 — Active / Inactive segmented tabs. Counts are live. */}
      <div
        className="rounded-2xl mb-3 flex items-center gap-1 p-1"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        data-testid="customers-cohort-tabs"
      >
        {TAB_DEFS.filter((t) => !t.adminOnly || isAdmin).map((t) => (
          <button
            key={t.k}
            onClick={() => setTab(t.k)}
            className="flex-1 flex items-center justify-center gap-2 text-xs font-bold uppercase tracking-wider px-4 py-2 rounded-xl transition"
            style={{
              backgroundColor: tab === t.k ? colors.brandTertiary : "transparent",
              color: tab === t.k ? colors.onBrandTertiary : colors.muted,
            }}
            data-testid={t.testid}
          >
            <span>{t.label}</span>
            {t.count !== null && t.count !== undefined ? (
              <span
                className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                style={{
                  backgroundColor: tab === t.k ? "rgba(255,255,255,0.35)" : colors.surfaceSecondary,
                  color: tab === t.k ? colors.onBrandTertiary : colors.onSurfaceSecondary,
                }}
                data-testid={`${t.testid}-count`}
              >
                {t.count}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      {/* Filter row */}
      <div
        className="rounded-2xl p-4 mb-4 flex flex-wrap gap-3 items-center"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="relative flex-1 min-w-[220px]">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2"
            style={{ color: colors.muted }}
          />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name, email, phone, address…"
            className="w-full pl-9 pr-3 py-2.5 rounded-lg outline-none text-sm focus:ring-2"
            style={{
              backgroundColor: colors.surfaceSecondary,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="customers-search"
          />
        </div>
        <div className="flex items-center gap-1">
          <Filter size={14} style={{ color: colors.muted }} />
          {[
            { k: "all", label: "All" },
            { k: "unscheduled", label: "Unscheduled" },
            { k: "waitlist", label: "Waitlist" },
          ].map((s) => (
            <button
              key={s.k}
              onClick={() => setScope(s.k)}
              className="text-xs font-semibold px-3 py-1.5 rounded-full transition"
              style={{
                backgroundColor: scope === s.k ? colors.brandTertiary : colors.surfaceSecondary,
                color: scope === s.k ? colors.onBrandTertiary : colors.onSurfaceSecondary,
                border: `1px solid ${scope === s.k ? colors.brandTertiary : colors.border}`,
              }}
              data-testid={`customers-scope-${s.k}`}
            >
              {s.label}
            </button>
          ))}
        </div>
        <select
          value={tag}
          onChange={(e) => setTag(e.target.value)}
          className="text-xs font-semibold px-3 py-1.5 rounded-lg"
          style={{
            backgroundColor: colors.surfaceSecondary,
            color: colors.onSurfaceSecondary,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="customers-filter-tag"
        >
          <option value="">All tags</option>
          {TAG_PRESETS.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
        {cities.length ? (
          <select
            value={city}
            onChange={(e) => setCity(e.target.value)}
            className="text-xs font-semibold px-3 py-1.5 rounded-lg"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurfaceSecondary,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="customers-filter-city"
          >
            <option value="">All cities</option>
            {cities.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        ) : null}
        {/* Phase 12 · Feb 2026 — "Missing card" filter chip. Admin +
            manager only. Server-side filter (requires the
            missing_card=true query param). */}
        {isAdminOrManager && (
          <button
            onClick={() => setMissingCardOnly((v) => !v)}
            data-testid="customers-filter-missing-card"
            className="text-xs font-semibold px-3 py-1.5 rounded-lg inline-flex items-center gap-1.5"
            style={{
              backgroundColor: missingCardOnly ? "#FEF3C7" : colors.surfaceSecondary,
              color: missingCardOnly ? "#92400E" : colors.onSurfaceSecondary,
              border: `1px solid ${missingCardOnly ? "#FDE68A" : colors.border}`,
            }}
          >
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ backgroundColor: missingCardOnly ? "#B45309" : "#94A3B8" }}
            />
            Missing card
          </button>
        )}
        {/* Feb-2026 · P26 — super_admin-only "Show deleted" toggle. */}
        {isSuperAdmin && (
          <button
            onClick={() => setIncludeDeleted((v) => !v)}
            data-testid="customers-filter-include-deleted"
            className="text-xs font-semibold px-3 py-1.5 rounded-lg inline-flex items-center gap-1.5"
            style={{
              backgroundColor: includeDeleted ? "#FEE2E2" : colors.surfaceSecondary,
              color: includeDeleted ? "#991B1B" : colors.onSurfaceSecondary,
              border: `1px solid ${includeDeleted ? "#FCA5A5" : colors.border}`,
            }}
            title="Super_admin: include soft-deleted customers in the list"
          >
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ backgroundColor: includeDeleted ? "#B91C1C" : "#94A3B8" }}
            />
            Show deleted
          </button>
        )}
      </div>

      {/* Bulk-actions toolbar (visible when selection exists) */}
      {selected.size > 0 ? (
        <div
          className="mb-3 flex flex-wrap gap-2 items-center rounded-xl px-4 py-2.5"
          style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}
          data-testid="bulk-toolbar"
        >
          <span className="text-sm font-semibold mr-2">{selected.size} selected</span>
          <select
            value={bulkTag}
            onChange={(e) => setBulkTag(e.target.value)}
            className="text-xs font-semibold px-2 py-1 rounded"
            style={{
              backgroundColor: "#fff",
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
          >
            <option value="">Choose tag…</option>
            {TAG_PRESETS.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <Button variant="ghost" onClick={() => bulk("add_tag", { tag: bulkTag })} testid="bulk-add-tag">
            <Tag size={14} /> Add tag
          </Button>
          <Button variant="ghost" onClick={() => bulk("remove_tag", { tag: bulkTag })}>
            Remove tag
          </Button>
          <Button variant="ghost" onClick={() => bulk("add_waitlist")} testid="bulk-add-waitlist">
            <BellRing size={14} /> Add to waitlist
          </Button>
          <Button variant="ghost" onClick={() => bulk("remove_waitlist")}>
            Remove from waitlist
          </Button>
        </div>
      ) : null}

      {/* Data table */}
      <div
        className="rounded-2xl overflow-hidden"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        {filtered === null ? (
          <div className="p-4 space-y-3">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} style={{ height: 52 }} />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={Users}
            title={tab === "muted" ? "No muted customers" : "No customers"}
            hint={
              tab === "muted"
                ? "Muted customers are excluded from marketing, autobilling, route optimization, and lead alerts. Nothing to review right now."
                : "Try adjusting filters or import a CSV to get started."
            }
          />
        ) : (
          <>
          {/* Feb-2026 P1 · Customers list Tag filter — swap from
              147-chip bar to a searchable multi-select dropdown.
              System tags pinned; multi-select AND semantics + URL
              sync preserved verbatim. */}
          {allTags.length > 0 && (
            <CustomersTagFilterDropdown
              allTags={allTags}
              selectedTags={selectedTags}
              setSelectedTags={setSelectedTags}
            />
          )}
          {/* Feb-2026 · P35 — top pager. Hides itself when total_pages
              < 2. Shares state with the bottom pager below. */}
          <CustomersPager
            page={page}
            total_pages={totalPages}
            total={total}
            page_size={_PAGE_SIZE}
            onPageChange={setPage}
            testidPrefix="customers-pager-top"
          />
          <table className="w-full text-sm" data-testid="customers-table">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                <th className="text-left px-3 py-2 w-8">
                  <input
                    type="checkbox"
                    checked={filtered.length > 0 && filtered.every((r) => selected.has(r.id))}
                    ref={(el) => {
                      if (el) el.indeterminate = filtered.some((r) => selected.has(r.id))
                        && !filtered.every((r) => selected.has(r.id));
                    }}
                    onChange={(e) => {
                      if (e.target.checked) setSelected(new Set(filtered.map((r) => r.id)));
                      else setSelected(new Set());
                    }}
                    aria-label="Select all customers on this page"
                    data-testid="bulk-select-all"
                    className="cursor-pointer"
                  />
                </th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>
                  Name
                </th>
                <th className="text-left px-3 py-2 font-semibold hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>
                  Contact
                </th>
                <th className="text-left px-3 py-2 font-semibold hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }}>
                  Address
                </th>
                <th className="text-left px-3 py-2 font-semibold hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>
                  Next visit
                </th>
                <th className="w-8 px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr
                  key={c.id}
                  className="cursor-pointer hover:bg-zinc-50 transition"
                  style={{
                    borderTop: `1px solid ${colors.divider}`,
                    // Feb-2026 · P26 — soft-deleted rows visually
                    // distinct so super_admin can tell them apart
                    // from the active list at a glance.
                    opacity: c.deleted_at ? 0.6 : 1,
                  }}
                  onClick={() => navigate(`/customers/${c.id}`)}
                  data-testid={`customer-row-${c.id}`}
                >
                  <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(c.id)}
                      onChange={() => toggle(c.id)}
                      aria-label={`Select customer ${c.name}`}
                      data-testid={`bulk-select-row-${c.id}`}
                      className="cursor-pointer"
                    />
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      {/* Phase 12 · Feb 2026 — yellow dot when the row
                          effectively requires a card AND has none.
                          Admin-visible only (isAdmin gate). */}
                      {isAdmin
                        && c.effective_require_card_on_file
                        && !c.has_card_on_file ? (
                        <span
                          className="inline-block w-2 h-2 rounded-full shrink-0"
                          style={{ backgroundColor: "#F59E0B" }}
                          data-testid={`row-${c.id}-missing-card-dot`}
                          title="Card on file required — none saved"
                        />
                      ) : null}
                      <span
                        className="font-semibold"
                        style={{
                          color: colors.onSurface,
                          textDecoration: c.deleted_at ? "line-through" : "none",
                        }}
                      >
                        {c.name}
                      </span>
                      {/* Feb-2026 · P26 — Restore pill for super_admin. */}
                      {c.deleted_at && isSuperAdmin ? (
                        <RestoreCustomerButton
                          customer={c}
                          onRestored={(res) => {
                            setToast({
                              tone: "success",
                              message: res?.was_anonymized
                                ? "Customer restored (PII stays scrubbed)"
                                : "Customer restored",
                            });
                            load();
                          }}
                          onError={(msg) =>
                            setToast({ tone: "error", message: msg })
                          }
                        />
                      ) : null}
                      {/* Feb-2026 · P27 — Muted badge + Mute/Unmute pill. */}
                      {c.is_muted ? (
                        <span
                          className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                          style={{
                            backgroundColor: "#450A0A",
                            color: "#FCA5A5",
                          }}
                          data-testid={`muted-badge-${c.id}`}
                          title="Muted — silent mode across marketing, autobilling, route optimization, and lead alerts"
                        >
                          MUTED
                        </span>
                      ) : null}
                      {/* Feb-2026 · P28 — relative-time muted-at label on the Muted saved view. */}
                      {c.is_muted && tab === "muted" && c.muted_at ? (
                        <span
                          className="text-[10px] font-normal"
                          style={{ color: colors.muted }}
                          data-testid={`muted-since-${c.id}`}
                          title={c.muted_at}
                        >
                          Muted {_p28RelativeTime(c.muted_at)}
                        </span>
                      ) : null}
                      {/* Feb-2026 · P29 — muted reason snapshot. Blank for historical rows. */}
                      {c.is_muted && tab === "muted" && c.muted_reason ? (
                        <span
                          className="text-[10px] font-normal italic"
                          style={{ color: colors.muted }}
                          data-testid={`muted-reason-${c.id}`}
                          title={c.muted_reason}
                        >
                          · {c.muted_reason}
                        </span>
                      ) : null}
                      {/* Feb-2026 · P37-UX — On the Muted tab the
                          Mark Muted / Unmute pill stays inline with
                          the row's status chips so operators can
                          audit + unmute in place. On Active / Inactive
                          / All tabs the control moves into the
                          right-aligned action-button cluster (see
                          below) so all row-level actions sit
                          together. */}
                      {!c.deleted_at && isAdmin && tab === "muted" ? (
                        <MuteControl
                          customer={c}
                          canMute={isAdmin}
                          canUnmute={isAdmin}
                          onChange={(res) => {
                            const label = res?.muted
                              ? "Customer muted"
                              : res?.unmuted
                              ? "Customer unmuted"
                              : res?.reason === "already_muted"
                              ? "Customer was already muted"
                              : res?.reason === "not_muted"
                              ? "Customer was not muted"
                              : "Done";
                            setToast({ tone: "success", message: label });
                            load();
                          }}
                          onError={(msg) =>
                            setToast({ tone: "error", message: msg })
                          }
                        />
                      ) : null}
                      {lockedFailures[c.id] ? (
                        <LockedPill reason={lockedFailures[c.id]}
                                     testid={`bulk-locked-pill-${c.id}`} />
                      ) : null}
                      {c.is_vip ? (
                        <span
                          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
                          style={{
                            backgroundColor: "#FEF3C7",
                            color: "#92400E",
                            border: "1px solid #F59E0B",
                          }}
                          data-testid={`row-${c.id}-vip-badge`}
                          title="VIP customer"
                        >
                          <Star size={10} fill="#F59E0B" color="#F59E0B" /> VIP
                        </span>
                      ) : null}
                      {/* Feb-2026 · P33 — Per-row tag chips removed by
                          product ask. Tag data still lives on `c.tags`
                          and remains editable on the customer detail
                          / edit form; only the row rendering is gone.
                          The tenant catalog + "All tags" filter above
                          are now the authoritative surface. */}
                      {c.waitlisted ? <Chip label="Waitlist" tone="warning" /> : null}
                      {(c.properties_count || 0) >= 2 ? (
                        <Chip
                          label={`${c.properties_count} properties`}
                          tone="brandTertiary"
                          testid={`row-${c.id}-props-chip`}
                        />
                      ) : null}
                      {c.is_active === false ? (
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
                          style={{
                            backgroundColor: "#E5E7EB",
                            color: "#4B5563",
                            border: "1px solid #9CA3AF",
                          }}
                          data-testid={`row-${c.id}-inactive-pill`}
                        >
                          Inactive
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td className="px-3 py-3 hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>
                    <div>{c.phone || "—"}</div>
                    <div className="text-xs" style={{ color: colors.muted }}>
                      {c.email || "—"}
                    </div>
                  </td>
                  <td className="px-3 py-3 hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }}>
                    {c.address || "—"}
                  </td>
                  <td className="px-3 py-3 hidden md:table-cell text-xs" style={{ color: colors.muted }}>
                    {nextScheduled(c)}
                  </td>
                  <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center gap-1 justify-end">
                      {isAdmin ? (
                        c.is_active === false ? (
                          <button
                            onClick={() => openActivationConfirm(c, true)}
                            className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded transition"
                            style={{
                              color: "#166534",
                              backgroundColor: "#DCFCE7",
                              border: "1px solid #86EFAC",
                            }}
                            data-testid={`row-${c.id}-reactivate`}
                            title="Reactivate customer"
                          >
                            <UserCheck size={12} /> Reactivate
                          </button>
                        ) : (
                          <button
                            onClick={() => openActivationConfirm(c, false)}
                            className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded transition"
                            style={{
                              color: "#991B1B",
                              backgroundColor: "#FEF2F2",
                              border: "1px solid #FCA5A5",
                            }}
                            data-testid={`row-${c.id}-deactivate`}
                            title="Mark customer inactive"
                          >
                            <UserX size={12} /> Mark inactive
                          </button>
                        )
                      ) : null}
                      {/* Feb-2026 · P37-UX — Mark Muted / Unmute pill
                          lives next to the Mark inactive (Active tab)
                          or Reactivate (Inactive tab) button so all
                          row-level actions sit together on the right.
                          On the Muted tab the pill stays inline with
                          the status chips (see above) — this branch
                          intentionally skips render there. */}
                      {!c.deleted_at && isAdmin && tab !== "muted" ? (
                        <MuteControl
                          customer={c}
                          canMute={isAdmin}
                          canUnmute={isAdmin}
                          onChange={(res) => {
                            const label = res?.muted
                              ? "Customer muted"
                              : res?.unmuted
                              ? "Customer unmuted"
                              : res?.reason === "already_muted"
                              ? "Customer was already muted"
                              : res?.reason === "not_muted"
                              ? "Customer was not muted"
                              : "Done";
                            setToast({ tone: "success", message: label });
                            load();
                          }}
                          onError={(msg) =>
                            setToast({ tone: "error", message: msg })
                          }
                        />
                      ) : null}
                      <button
                        onClick={() => navigate(`/customers/${c.id}`)}
                        className="opacity-60 hover:opacity-100 ml-1"
                        aria-label="Open customer"
                      >
                        <MoreVertical size={16} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* Feb-2026 · P35 — bottom pager. Same state as the top pager. */}
          <CustomersPager
            page={page}
            total_pages={totalPages}
            total={total}
            page_size={_PAGE_SIZE}
            onPageChange={setPage}
            testidPrefix="customers-pager-bottom"
          />
          </>
        )}
      </div>

      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} onDone={() => { setImportOpen(false); load(); loadCounts(); }} setToast={setToast} />

      <Modal
        open={!!activationConfirm}
        onClose={() => (activationBusy ? null : setActivationConfirm(null))}
        title={activationConfirm?.nextActive ? "Reactivate customer?" : "Mark customer inactive?"}
        testid="customers-activation-confirm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setActivationConfirm(null)} disabled={activationBusy}>
              Cancel
            </Button>
            <Button
              variant={activationConfirm?.nextActive ? "primary" : "danger"}
              onClick={commitActivation}
              disabled={activationBusy}
              testid="customers-activation-confirm-submit"
            >
              {activationBusy
                ? "Working…"
                : activationConfirm?.nextActive
                ? "Reactivate"
                : "Mark inactive"}
            </Button>
          </>
        }
      >
        {activationConfirm ? (
          <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
            {activationConfirm.nextActive ? (
              <>Reactivate <strong>{activationConfirm.customer.name}</strong>? Their jobs will need to be re-scheduled manually.</>
            ) : (
              <>Marking <strong>{activationConfirm.customer.name}</strong> inactive will auto-cancel their scheduled jobs. Continue?</>
            )}
          </p>
        ) : null}
      </Modal>

      <Toast toast={toast} onClose={() => setToast(null)} />

      {/* Phase 34 · Task LL Phase 2 UI wrap-up · Feb 2026 — shared
          bulk-action bar (delete + reassign owner). The legacy
          add/remove tag + waitlist toolbar above is retained until
          the /customers/bulk endpoint is fully deprecated. */}
      <BulkActionBar
        selectedCount={selectAllMatching ? _matchingTotal : selected.size}
        onClear={() => { setSelected(new Set()); setSelectAllMatching(false); }}
        actions={[
          ...(isAdmin ? [{
            key: "owner", label: "Reassign owner",
            dropdown: [{ value: "", label: "Unassigned" }],
            onClick: (v) => doBulkOwner(v || null),
          }] : []),
          // Feb-2026 · Mark inactive — only shown to admin/manager and
          // only when the current tab isn't already "inactive" (no-op
          // to flip inactives to inactive again from the UI).
          ...(isAdminOrManager && tab !== "inactive" ? [{
            key: "mark-inactive", label: "Mark inactive",
            onClick: () => {
              setConfirmInactiveOpen(true);
            },
          }] : []),
          { key: "delete", label: "Delete selected", tone: "danger",
            onClick: () => setConfirmDeleteOpen(true) },
        ]}
      />
      {/* Feb-2026 · Unlimited bulk delete — surfaces the "Select all
          N matching this filter" affordance INSIDE the floating
          action bar's own container so it lines up with the
          existing "Clear selection" link. Only visible when the
          on-page select-all is checked and the tenant has more
          matching rows than are currently visible. */}
      {selected.size > 0 && !selectAllMatching ? (
        <div
          className="fixed left-1/2 -translate-x-1/2 z-30 mt-16 rounded-xl px-3 py-1.5"
          style={{
            top: 0,
            backgroundColor: "rgba(15, 23, 42, 0.92)",
            color: "#fff",
          }}
          data-testid="customers-select-all-matching-wrap"
        >
          <SelectAllMatchingLink
            pageCount={selected.size}
            totalMatching={_matchingTotal}
            onSelectAllMatching={() => setSelectAllMatching(true)}
          />
        </div>
      ) : null}
      {selectAllMatching ? (
        <div
          className="fixed left-1/2 -translate-x-1/2 z-30 mt-16 rounded-xl px-3 py-1.5"
          style={{
            top: 0,
            backgroundColor: "rgba(15, 23, 42, 0.92)",
            color: "#fff",
            fontSize: 12,
          }}
          data-testid="customers-select-all-matching-active"
        >
          Selected all {_matchingTotal} matching this filter ·{" "}
          <button
            type="button"
            onClick={() => setSelectAllMatching(false)}
            className="underline font-semibold"
            data-testid="customers-select-all-matching-undo"
          >
            Undo
          </button>
        </div>
      ) : null}
      {/* Feb-2026 · Unlimited bulk delete — modal replaces the plain
          ``<BulkConfirmModal>`` when the delete blast radius crosses
          ``_TYPED_CONFIRM_THRESHOLD`` (500). Small deletes still use
          the classic confirm to keep the everyday flow ergonomic. */}
      {confirmDeleteOpen && _pendingDeleteCount < _TYPED_CONFIRM_THRESHOLD ? (
        <BulkConfirmModal
          open={confirmDeleteOpen}
          onClose={() => { setConfirmDeleteOpen(false); setConfirmTypedNumber(""); }}
          onConfirm={doBulkDelete}
          title={`Delete ${_pendingDeleteCount} customer${_pendingDeleteCount === 1 ? "" : "s"}?`}
          description="Customers with active invoices will show as locked and be skipped."
          confirmLabel={bulkBusy ? "Deleting…" : `Delete ${_pendingDeleteCount}`}
          busy={bulkBusy}
        />
      ) : null}
      {confirmDeleteOpen && _pendingDeleteCount >= _TYPED_CONFIRM_THRESHOLD ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !bulkBusy) {
              setConfirmDeleteOpen(false);
              setConfirmTypedNumber("");
            }
          }}
          data-testid="customers-bulk-delete-typed-modal"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold"
                style={{ color: "#DC2626" }}
                data-testid="customers-bulk-delete-typed-title">
              Delete {_pendingDeleteCount} customer{_pendingDeleteCount === 1 ? "" : "s"}?
            </h2>
            <p className="text-sm mt-2"
                style={{ color: colors.onSurfaceSecondary || colors.muted }}>
              This is a large delete. Customers with active invoices
              will be locked and skipped. Deleted customers are
              soft-deleted (recoverable via backend restore) — but
              from the UI they're gone.
            </p>
            <div className="mt-4">
              <label className="text-xs font-semibold uppercase tracking-wider block mb-1"
                      style={{ color: colors.onSurfaceSecondary }}
                      htmlFor="typed-confirm-input">
                Type <span style={{ color: "#DC2626" }}>{_pendingDeleteCount}</span> to confirm
              </label>
              <input
                id="typed-confirm-input"
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                autoFocus
                value={confirmTypedNumber}
                onChange={(e) => setConfirmTypedNumber(e.target.value)}
                className="w-full px-3 py-2 rounded-xl text-sm"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                disabled={bulkBusy}
                data-testid="customers-bulk-delete-typed-input"
              />
            </div>
            {bulkBusy ? (
              <div
                className="mt-3 flex items-center gap-2 text-sm"
                style={{ color: colors.onSurfaceSecondary }}
                data-testid="customers-bulk-delete-progress"
              >
                <span
                  className="inline-block w-3 h-3 rounded-full animate-spin"
                  style={{
                    border: "2px solid rgba(220,38,38,0.25)",
                    borderTopColor: "#DC2626",
                  }}
                />
                <span>Deleting {_pendingDeleteCount} customer{_pendingDeleteCount === 1 ? "" : "s"}…</span>
              </div>
            ) : null}
            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => { setConfirmDeleteOpen(false); setConfirmTypedNumber(""); }}
                disabled={bulkBusy}
                className="px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-60"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurface }}
                data-testid="customers-bulk-delete-typed-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={doBulkDelete}
                disabled={
                  bulkBusy
                  || String(confirmTypedNumber).trim() !== String(_pendingDeleteCount)
                }
                className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
                style={{ backgroundColor: "#DC2626" }}
                data-testid="customers-bulk-delete-typed-btn"
              >
                {bulkBusy ? "Deleting…" : `Delete ${_pendingDeleteCount}`}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Feb-2026 · Bulk-mark-inactive hard-confirm modal. Simplified
          per user feedback to a plain Confirm / Cancel — the header
          count + first-5 name preview provide enough context; the
          typed-word gate was unnecessary friction. */}
      {confirmInactiveOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) {
              setConfirmInactiveOpen(false);
            }
          }}
          data-testid="bulk-mark-inactive-modal"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold"
                style={{ color: colors.onSurface }}>
              Mark {selected.size} customer{selected.size === 1 ? "" : "s"} inactive?
            </h2>
            <p className="text-sm mt-2"
               style={{ color: colors.onSurfaceSecondary || colors.muted }}>
              These customers will move to the Inactive tab and their
              scheduled jobs may be cancelled.
            </p>

            {/* First 5 preview */}
            <ul className="mt-3 text-sm space-y-1"
                style={{ color: colors.onSurface }}
                data-testid="bulk-mark-inactive-preview-list">
              {(rows || [])
                .filter((r) => selected.has(r.id))
                .slice(0, 5)
                .map((r) => (
                  <li key={r.id} className="truncate">
                    · {r.name || r.first_name || r.email || r.id}
                  </li>
                ))}
              {selected.size > 5 ? (
                <li className="text-xs italic"
                    style={{ color: colors.muted }}>
                  … and {selected.size - 5} more
                </li>
              ) : null}
            </ul>

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmInactiveOpen(false)}
                className="px-4 py-2 rounded-xl text-sm font-semibold"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurface }}
                data-testid="bulk-mark-inactive-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={bulkInactiveBusy}
                onClick={doBulkInactive}
                className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-40"
                style={{ backgroundColor: "#B45309" }}
                data-testid="bulk-mark-inactive-confirm"
              >
                {bulkInactiveBusy ? "Marking…" :
                  `Mark ${selected.size} inactive`}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ImportModal({ open, onClose, onDone, setToast }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [progressHint, setProgressHint] = useState("");
  const fileRef = useRef();

  const upload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setResult(null);
    // Show a friendly hint for large files so the modal doesn't feel frozen.
    const sizeMb = file.size / (1024 * 1024);
    if (sizeMb > 0.5) {
      setProgressHint(`Uploading ${sizeMb.toFixed(1)} MB — this may take up to a minute for large files…`);
    } else {
      setProgressHint("Uploading…");
    }
    try {
      const text = await file.text();
      const res = await api.post("/import/customers", { csv: text });
      setResult(res);
      const imported = Number(res?.imported ?? res?.imported_count ?? 0);
      const skipped = Number(res?.skipped ?? res?.skipped_count ?? 0);
      const warnCount = Number(res?.warnings_total ?? (res?.warnings?.length || 0));
      const suffix = [
        skipped ? `${skipped} skipped` : null,
        warnCount ? `${warnCount} warning${warnCount === 1 ? "" : "s"}` : null,
      ].filter(Boolean).join(" · ");
      setToast({
        tone: skipped > 0 ? "warning" : "success",
        message: `${imported} imported${suffix ? " · " + suffix : ""}`,
      });
      if (skipped === 0 && warnCount === 0) onDone();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    } finally {
      setBusy(false);
      setProgressHint("");
    }
  };

  const downloadTemplate = async () => {
    try {
      const url = `${process.env.REACT_APP_BACKEND_URL || ""}/api/import/customers/template`;
      const tok = localStorage.getItem("token") || "";
      const resp = await fetch(url, { headers: tok ? { Authorization: `Bearer ${tok}` } : {} });
      const text = await resp.text();
      const blob = new Blob([text], { type: "text/csv" });
      const dl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = dl;
      a.download = "customers-template.csv";
      a.click();
      URL.revokeObjectURL(dl);
    } catch { /* silent */ }
  };

  const HEADERS = [
    ["Customer Since", "Optional. Tolerant parser: 'Jul 01 2026', 'Jun 23', '6/23/2026', '2026-06-23'. Year defaults to current."],
    ["Email", "Optional. Basic email validation."],
    ["Service address Street", "Required."],
    ["City", "Required."],
    ["State", "Required. 2-letter code (auto-uppercased)."],
    ["Postal Code", "Required. Kept as text — leading zeros preserved."],
    ["Phone", "Optional. Landline. Normalized to E.164 (+1XXXXXXXXXX)."],
    ["Mobile", "Optional. Normalized to E.164. If both Phone & Mobile present, both stored."],
    ["First Name", "Required."],
    ["Last Name", "Required."],
    ["Tags", "Optional. Comma-separated: 'VIP, Weekly'."],
    ["Notes", "Optional. Free-form."],
  ];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Import Customers (CSV)"
      testid="customer-import-modal"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{result ? "Close" : "Cancel"}</Button>
          <Button onClick={upload} testid="customer-import-upload">
            {busy ? "Uploading…" : "Upload CSV"}
          </Button>
        </>
      }
    >
      {!result ? (
        <>
          <p className="text-sm mb-2" style={{ color: colors.onSurfaceSecondary }}>
            Expected columns (case-insensitive; leading/trailing whitespace tolerated; comma OR semicolon delimiter auto-detected):
          </p>
          <div className="rounded-lg mb-3 overflow-hidden border" style={{ borderColor: colors.border }}>
            <table className="w-full text-xs">
              <thead style={{ backgroundColor: colors.surfaceSecondary }}>
                <tr>
                  <th className="text-left px-3 py-1.5 font-bold" style={{ color: colors.onSurface }}>#</th>
                  <th className="text-left px-3 py-1.5 font-bold" style={{ color: colors.onSurface }}>Header</th>
                  <th className="text-left px-3 py-1.5 font-bold" style={{ color: colors.onSurface }}>Notes</th>
                </tr>
              </thead>
              <tbody>
                {HEADERS.map(([h, n], i) => (
                  <tr key={h} style={{ borderTop: `1px solid ${colors.border}` }}>
                    <td className="px-3 py-1.5 text-right" style={{ color: colors.muted, width: 28 }}>{i + 1}</td>
                    <td className="px-3 py-1.5 font-mono font-semibold" style={{ color: colors.onSurface }}>{h}</td>
                    <td className="px-3 py-1.5" style={{ color: colors.onSurfaceSecondary }}>{n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button onClick={downloadTemplate}
                  className="text-xs font-semibold mb-3 inline-flex items-center gap-1"
                  style={{ color: colors.brand }}
                  data-testid="customer-import-template">
            Download template CSV
          </button>
          <input ref={fileRef} type="file" accept=".csv,text/csv" data-testid="customer-import-file" className="block" />
          {busy && progressHint ? (
            <div className="mt-3 text-xs px-3 py-2 rounded"
                 style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurfaceSecondary,
                          border: `1px solid ${colors.border}` }}
                 data-testid="customer-import-progress">
              {progressHint}
            </div>
          ) : null}
        </>
      ) : (
        <div data-testid="customer-import-result">
          <div className="grid grid-cols-4 gap-2 mb-3">
            {[
              ["Total", result.total_rows, colors.onSurface],
              ["Created", result.created_count, "#166534"],
              ["Updated", result.updated_count, "#3730A3"],
              ["Skipped", result.skipped_count, result.skipped_count ? "#991B1B" : colors.muted],
            ].map(([label, val, color]) => (
              <div key={label} className="rounded-lg p-3 text-center"
                   style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}>
                <div className="text-[10px] uppercase font-bold tracking-wider" style={{ color: colors.muted }}>{label}</div>
                <div className="text-xl font-bold mt-0.5" style={{ color }}>{val ?? 0}</div>
              </div>
            ))}
          </div>
          {result.deprecation_warnings?.length ? (
            <div className="rounded-lg p-3 mb-3 text-xs"
                 style={{ backgroundColor: "#FEF3C7", color: "#92400E", border: "1px solid #FCD34D" }}
                 data-testid="customer-import-deprecation">
              {result.deprecation_warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
            </div>
          ) : null}
          {(result.warnings_total ?? result.warnings?.length) ? (
            <div className="rounded-lg overflow-hidden border mb-3" style={{ borderColor: colors.border }}
                 data-testid="customer-import-warnings">
              <div className="px-3 py-2 text-xs font-bold uppercase tracking-wider flex items-center justify-between"
                   style={{ backgroundColor: colors.surfaceSecondary, color: colors.muted }}>
                <span>Row warnings ({result.warnings_total ?? result.warnings.length})</span>
                {result.warnings_truncated ? (
                  <span className="normal-case font-semibold" style={{ color: "#92400E" }}
                        data-testid="customer-import-warnings-truncated">
                    showing first {result.warnings.length} — full log at
                    <code className="ml-1 text-[10px]">{result.import_id}</code>
                  </span>
                ) : null}
              </div>
              <div className="max-h-40 overflow-y-auto">
                {(result.warnings || []).map((w, i) => (
                  <div key={i} className="px-3 py-1.5 text-xs" style={{ borderTop: `1px solid ${colors.border}` }}>
                    <span className="font-mono font-bold" style={{ color: "#92400E" }}>Row {w.row}</span>
                    <span className="ml-2" style={{ color: colors.onSurface }}>{w.message}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {result.errors?.length ? (
            <div className="rounded-lg overflow-hidden border" style={{ borderColor: colors.border }}>
              <div className="px-3 py-2 text-xs font-bold uppercase tracking-wider"
                   style={{ backgroundColor: colors.surfaceSecondary, color: colors.muted }}>
                Row errors ({result.errors.length})
              </div>
              <div className="max-h-48 overflow-y-auto">
                {result.errors.map((e, i) => (
                  <div key={i} className="px-3 py-1.5 text-xs" style={{ borderTop: `1px solid ${colors.border}` }}
                       data-testid={`customer-import-error-${i}`}>
                    <span className="font-mono font-bold" style={{ color: "#991B1B" }}>Row {e.row}</span>
                    <span className="ml-2" style={{ color: colors.onSurface }}>{e.reason}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </Modal>
  );
}
