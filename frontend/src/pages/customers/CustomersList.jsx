import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation, useSearchParams } from "react-router-dom";
import { Plus, Search, Upload, Download, Filter, MoreVertical, Users, Tag, BellRing, UserCheck, UserX, Star, Send, Mail, MapPinned } from "lucide-react";
import { toast as sonnerToast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { usePermissions } from "@/hooks/usePermissions";
import { PageHeader, Chip, Skeleton, EmptyState, Button, Modal, Toast } from "@/components/ui-kit";
import ArmToDelete from "@/components/ui/ArmToDelete";
import CustomersTagFilterDropdown from "@/components/customers/CustomersTagFilterDropdown";
import RestoreCustomerButton from "@/components/customers/RestoreCustomerButton";
import MuteControl from "@/components/customers/MuteControl";
import CustomersPager from "@/components/customers/CustomersPager";
import ImportCsvModalP41 from "@/pages/customers/ImportCsvModalP41";
import MergeCustomersModal from "@/components/customers/MergeCustomersModal";
import PortalOnboardingHealthTile from "@/components/customers/PortalOnboardingHealthTile";


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


// Feb-2026 · Phase — Customer geocoding on save + one-time backfill.
// Admin+/super_admin-only. Fires ``POST /api/admin/customers/
// backfill-geocoding`` and picks the toast variant off the response
// envelope. Kept as a small component so the top-level list page's
// header row stays legible.
function BackfillGeocodingButton() {
  const [busy, setBusy] = React.useState(false);
  const onClick = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await api.post("/admin/customers/backfill-geocoding", {});
      if (r && r.enqueued) {
        sonnerToast(
          "Backfill running in background — refresh the list in a few minutes to see updates",
          { duration: 6000 },
        );
      } else {
        const updated = r?.updated ?? 0;
        const failed = r?.failed ?? 0;
        const skipped = r?.skipped_no_address ?? 0;
        sonnerToast.success(
          `Backfill complete: ${updated} customers updated, ${failed} failed, ${skipped} skipped (no address)`,
          { duration: 6000 },
        );
      }
    } catch (e) {
      sonnerToast.error(
        `Backfill failed: ${e?.message || "unknown error"}`,
      );
    } finally { setBusy(false); }
  };
  return (
    <Button
      variant="ghost"
      onClick={onClick}
      disabled={busy}
      testid="admin-customers-backfill-geocoding-btn"
      title="Geocode every customer missing GPS coordinates"
    >
      <MapPinned size={16} /> {busy ? "Backfilling…" : "Backfill missing GPS"}
    </Button>
  );
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
  // Feb-2026 · P26 — admin-tier (admin + super_admin + owner)
  // escape hatch to browse soft-deleted customers and Restore
  // them.  Widened from super_admin-only by the Customer Delete
  // UX overhaul (Feb-2026) — the backend P25 / P26 gates were
  // widened symmetrically. ``isSuperAdmin`` is still exported for
  // the anonymized-warning affordance in the RestoreCustomerButton
  // modal (P11b) but the chip + inline Restore button are open to
  // every admin-tier role.
  const _isSuperAdmin =
    role === "super_admin" || effectiveRole === "super_admin";
  const canManageDeleted =
    isAdmin ||
    role === "owner" ||
    effectiveRole === "owner";
  const [includeDeleted, setIncludeDeleted] = useState(false);

  // Phase 56.2 — active | inactive tabs. `all` retained as a legacy escape
  // hatch (used to be the default) — accessible via `?tab=all` for admins
  // who need to see everything in one list.
  //
  // Feb-2026 · Customer Delete UX overhaul — the Dashboard KPI
  // tile-swap (Active / Inactive Customers) navigates here with
  // ``?status=active`` / ``?status=inactive``. We accept ``?status``
  // as an alias for ``?tab`` so the tile deep-link lands on the
  // right cohort. ``?tab`` still wins if both are present (existing
  // bookmarks / manual URL edits keep their meaning).
  //
  // Phase K40 · Feb-2026 — site-wide "no persistence across page
  // loads" rule. Customers is the ONE explicit exception to the
  // "default to All" policy: the tab still defaults to ``"active"``
  // when no URL param is present. The previous localStorage read
  // (F6c / H4) has been REMOVED so a page refresh always lands the
  // operator back on the Active cohort. Explicit URL params (``?tab=``
  // / ``?status=``) still win — see K40 rule #4.
  const initialTab = (() => {
    if (cohortParam === "inactive") return "inactive";
    if (cohortParam === "active") return "active";
    const urlTab = searchParams.get("tab") || searchParams.get("status");
    if (urlTab) return urlTab;
    return "active";
  })();
  const [tab, setTab] = useState(initialTab);
  // Guard so the mount-time useEffect below doesn't stomp on an
  // initial ``?page=N`` query param — we only want to reset page
  // when the operator ACTIVELY changes the tab.
  const _tabInitRef = React.useRef(true);
  useEffect(() => {
    if (_tabInitRef.current) {
      _tabInitRef.current = false;
      return;
    }
    // Filter change must reset pagination to page 1 — otherwise a user
    // on page 3 of Active flips to Inactive and lands on an empty page.
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);
  const [counts, setCounts] = useState({ active: null, inactive: null, muted: null, waitlist: null, all: null });

  const [rows, setRows] = useState(null);
  // Feb-2026 · P35 — server-side pagination. Page is URL-synced so
  // refresh preserves position. Phase K62 · Feb-2026 — page size
  // is now user-selectable (25 / 50 / 100, default 25), persisted
  // per-user in localStorage and mirrored in the URL as ``?size=``
  // so a direct-link with ``?page=3&size=50`` loads correctly. The
  // response envelope still drives ``total`` and ``totalPages``.
  const _K62_PAGE_SIZE_OPTIONS = [25, 50, 100];
  const _K62_DEFAULT_PAGE_SIZE = 25;
  const _K62_LS_KEY = "customers.pageSize";
  const [pageSize, setPageSize] = useState(() => {
    // Priority 1 — explicit ``?size=N`` URL param (deep-link honour).
    try {
      const fromRouter = parseInt(searchParams.get("size") || "", 10);
      if (Number.isFinite(fromRouter) && _K62_PAGE_SIZE_OPTIONS.includes(fromRouter)) return fromRouter;
    } catch { /* fall through */ }
    // Also honour ``window.location.search`` for consumers that
    // update the URL via ``history.replaceState`` (P46 city sync
    // does this and could leak here on a follow-up navigation).
    try {
      const raw = parseInt(new URLSearchParams(window.location.search).get("size") || "", 10);
      if (Number.isFinite(raw) && _K62_PAGE_SIZE_OPTIONS.includes(raw)) return raw;
    } catch { /* fall through */ }
    // Priority 2 — localStorage per-user preference.
    try {
      const raw = parseInt(localStorage.getItem(_K62_LS_KEY) || "", 10);
      if (Number.isFinite(raw) && _K62_PAGE_SIZE_OPTIONS.includes(raw)) return raw;
    } catch { /* fall through */ }
    // Priority 3 — K62 default.
    return _K62_DEFAULT_PAGE_SIZE;
  });
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
  // Feb 2026 · Customers list sort dropdown.
  //
  // K49 · Feb-2026 — Default changed from ``created_desc``
  // (Newest → Oldest) to ``last_name_asc`` (Last Name A-Z). Also
  // dropped the ``customers.sortBy`` localStorage persistence so
  // this dropdown obeys the K40 "reset to defaults on every mount"
  // rule (Customers page filter defaults were the last hold-out).
  // Explicit ``?sort=`` URL params still win — see the initializer
  // below (bookmark-honor exception, matches the ``?tab=`` /
  // ``?status=`` behaviour above).
  const _SORT_OPTIONS = [
    // K49 default — surfaced first so the dropdown menu opens on
    // the currently-selected value.
    { value: "last_name_asc", label: "Last Name A-Z" },
    { value: "created_desc", label: "Newest → Oldest" },
    { value: "created_asc", label: "Oldest → Newest" },
    // Feb 2026 · alphabetical options — backend supports name_asc /
    // name_desc with a stable ``_id`` tiebreaker.
    { value: "name_asc",   label: "Name A → Z" },
    { value: "name_desc",  label: "Name Z → A" },
  ];
  const _SORT_VALUES = new Set(_SORT_OPTIONS.map((o) => o.value));
  const [sortBy, setSortBy] = useState(() => {
    // K49 · Feb-2026 — honour an explicit ``?sort=`` URL param
    // (bookmark exception), otherwise fall to the K49 default. No
    // localStorage read — see the K40 rule.
    try {
      const raw = new URLSearchParams(window.location.search)
        .get("sort");
      if (raw && _SORT_VALUES.has(raw)) return raw;
    } catch { /* URL parse failure — fall through */ }
    return "last_name_asc";
  });
  // Phase G4a · Feb-2026 — Portal-activation dropdown filter.
  // Options: all (default, no filter) | activated | not_activated.
  // Stacks with the segmented cohort tabs so operators can chase
  // signups ("Inactive + Not activated", "Active + Activated" etc.).
  //
  // Phase K40 · Feb-2026 — site-wide "no persistence across page
  // loads" rule for filter dropdowns. The previous
  // ``customerListFilter.portalStatus`` localStorage read + write
  // has been REMOVED. Every mount lands on the "All" bucket
  // regardless of the operator's last selection. Explicit URL
  // params are NOT honored for the portal filter today (no deep-
  // link pathway shipped) but the initializer is a stable literal
  // so adding one later is trivial.
  const _PORTAL_STATUS_OPTIONS = [
    { value: "all",           label: "Portal: All" },
    { value: "activated",     label: "Portal: Signed in" },
    { value: "not_activated", label: "Portal: Never signed in" },
  ];
  const [portalStatus, setPortalStatus] = useState("all");
  // Mount-skip guard so the first render doesn't reset page=1 (F6c-
  // shaped invariant preserved even though persistence is gone).
  const _portalStatusInitRef = React.useRef(true);
  useEffect(() => {
    if (_portalStatusInitRef.current) {
      _portalStatusInitRef.current = false;
      return;
    }
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [portalStatus]);
  const [selected, setSelected] = useState(new Set());
  const [bulkTag, setBulkTag] = useState("");
  // Feb 2026 · Customer Merge Phase 2 — modal state + "Show merged"
  // filter chip. ``includeMerged`` propagates to the ``/customers``
  // request as ``?include_merged=true``; the backend hides merged
  // rows by default.
  const [mergeOpen, setMergeOpen] = useState(false);
  const [includeMerged, setIncludeMerged] = useState(false);
  // Feb 2026 · Customer Merge Phase 3 — "Pending merge candidates"
  // chip. Fetches the low-confidence duplicate cluster ids on mount
  // (admin+ only). Clicking the chip filters the list to just
  // those ids so the operator can open the Merge modal against a
  // relevant pair.
  const [candidateIds, setCandidateIds] = useState([]);
  const [candidateGroupsCount, setCandidateGroupsCount] = useState(0);
  const [candidateFilterActive, setCandidateFilterActive] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  // Feb-2026 · P41 — new CSV import (merge semantics). Sibling to the
  // legacy ``importOpen`` modal above.
  const [importCsvOpen, setImportCsvOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const [activationConfirm, setActivationConfirm] = useState(null); // {customer, nextActive}
  const [activationBusy, setActivationBusy] = useState(false);
  // Phase 12 · Feb 2026 — "Missing card" filter chip state must live
  // ABOVE ``load()`` since it participates in the request query.
  const [missingCardOnly, setMissingCardOnly] = useState(false);
  // Feb-2026 · P43 — data-quality chips. Hydrated from ``?missing_email=1``
  // / ``?missing_phone=1`` and re-serialized on toggle. Both chips
  // compose as AND on the backend (see routers/customers.py).
  const [missingEmail, setMissingEmail] = useState(
    () => searchParams.get("missing_email") === "1");
  const [missingPhone, setMissingPhone] = useState(
    () => searchParams.get("missing_phone") === "1");
  // Feb-2026 · P43b — "Missing address" chip. Same URL-hydrated
  // convention as the two P43 chips. Server-side filter via
  // ``?missing_address=true`` composes AND with every other filter.
  const [missingAddress, setMissingAddress] = useState(
    () => searchParams.get("missing_address") === "1");
  // P43b · standalone count for the chip badge — hydrated on mount +
  // whenever the tenant scope changes so the count reflects the
  // FULL filterable population (not the intersection of currently-
  // active filters). Deliberately does NOT compose with other
  // filters so the badge is stable while the admin toggles chips.
  const [missingAddressCount, setMissingAddressCount] = useState(null);
  // Feb-2026 · P43c — "Portal status" tri-state segmented control.
  //   ``""``            → Any (default, no filter)
  //   ``"activated"``   → ``?portal_activated=true``
  //   ``"not_activated"`` → ``?portal_activated=false``
  // Hydrated from ``?portal_activated=1|0`` in the URL (canonical
  // shorthand matching the sibling ``missing_*`` chips). Persisted
  // back to the URL on toggle so refresh + share links keep state.
  const [portalStatusFilter, setPortalStatusFilter] = useState(() => {
    const raw = searchParams.get("portal_activated");
    if (raw === "1" || raw === "true") return "activated";
    if (raw === "0" || raw === "false") return "not_activated";
    return "";
  });
  const [portalActivatedCount, setPortalActivatedCount] = useState(null);
  const [portalNotActivatedCount, setPortalNotActivatedCount] = useState(null);
  // Feb-2026 · Customer temp password + first-access — "Never logged
  // in" chip.  toggle ON  → ``?first_access=never``. Distinct from
  // Portal Status because a customer may have chosen their own
  // password (activated) but STILL never signed in. Hydrated from
  // ``?first_access=never`` in the URL and persisted back on toggle.
  const [neverLoggedIn, setNeverLoggedIn] = useState(
    () => searchParams.get("first_access") === "never");
  const [neverLoggedInCount, setNeverLoggedInCount] = useState(null);
  // Feb-2026 · Onboarding-tile clickable ship — sibling "Invited"
  // and "Signed in" chips. Same shape as ``neverLoggedIn`` — a
  // boolean toggle hydrated from + persisted back to a distinct
  // URL param. Both intersect with every other filter.
  //   Invited  chip → ``?portal_invited=any``   (has_login truthy)
  //   Signed-in chip → ``?first_access=any``    (portal_first_login_at set)
  const [portalInvitedFilter, setPortalInvitedFilter] = useState(
    () => searchParams.get("portal_invited") === "any");
  const [portalInvitedCount, setPortalInvitedCount] = useState(null);
  const [signedInFilter, setSignedInFilter] = useState(
    () => searchParams.get("first_access") === "any");
  const [signedInCount, setSignedInCount] = useState(null);
  // Feb-2026 · P44 — "No payment on file" data-quality chip.
  //   toggle ON  → ``?has_payment_method=false``
  //   toggle OFF → param dropped
  // Hydrated from ``?has_payment_method=0`` (canonical shorthand).
  // Count badge is populated by a stand-alone ``count_only`` fetch
  // that does not compose with other filters (badge stability).
  const [noPaymentFilter, setNoPaymentFilter] = useState(() => {
    const raw = searchParams.get("has_payment_method");
    return raw === "0" || raw === "false";
  });
  const [noPaymentCount, setNoPaymentCount] = useState(null);
  // Feb-2026 · P44 — Per-row busy set for the "Send payment link"
  // row action. Storing customer ids keeps concurrent clicks on
  // different rows independent while preventing double-fire on the
  // same row.
  const [sendingPaymentLink, setSendingPaymentLink] = useState(new Set());
  // Feb-2026 · P45 — controlled open state for the "More filters"
  // dropdown that consolidates the pre-P45 chip strip. Always-
  // mounted content (hidden={!open}) keeps existing filter testids
  // resolvable via RTL queries without needing to open the dropdown
  // first in tests.
  const [moreFiltersOpen, setMoreFiltersOpen] = useState(false);
  const handleSendPaymentLink = async (cust) => {
    if (!cust?.id) return;
    setSendingPaymentLink((s) => new Set(s).add(cust.id));
    try {
      const res = await api.post(
        `/customers/${cust.id}/send-card-add-link`, {},
      );
      // Phase P3 · Feb-2026 — Deliverable 4 · truthful toast.
      // The backend now returns a per-channel breakdown
      // (``outcome`` = ``"sent" | "partial"`` + ``channels.email`` /
      // ``channels.sms`` = ``{sent, status, error}``).  If ONE of the
      // two channels silently failed (e.g. RC mocked because BYO
      // creds missing), we must NOT claim full success — mirror the
      // L3 truthful-toast pattern.
      const to = [res.email_recipient, res.sms_recipient]
        .filter(Boolean).join(" and ");
      const partial = res.outcome === "partial";
      if (partial) {
        const failedChannels = [];
        if (res.channels?.email && !res.channels.email.sent) {
          failedChannels.push(
            `email (${res.channels.email.status || "no_status"})`,
          );
        }
        if (res.channels?.sms && !res.channels.sms.sent) {
          failedChannels.push(
            `SMS (${res.channels.sms.status || "no_status"})`,
          );
        }
        setToast({
          tone: "warning",
          message: to
            ? `Add-card link sent to ${to} — but ${failedChannels.join(" + ")} did not go through. Check ops logs.`
            : `Add-card link partially sent — ${failedChannels.join(" + ")} did not go through.`,
        });
      } else {
        setToast({
          tone: "success",
          message: to ? `Add-card link sent to ${to}` : "Add-card link sent",
        });
      }
    } catch (e) {
      const msg = e?.detail?.code === "RATE_LIMITED"
        ? "Please wait a few minutes before sending another link."
        : (e?.message || "Failed to send link");
      setToast({ tone: "error", message: msg });
    } finally {
      setSendingPaymentLink((s) => {
        const n = new Set(s); n.delete(cust.id); return n;
      });
    }
  };
  // Feb-2026 · P46 — ``city`` filter state must live above ``load()``
  // so its dep-array reference during render doesn't hit the TDZ.
  // Hydrated from ``?city=<value>``; URL sync lives further down.
  // Feb-2026 · P46 — ``city`` filter state must live above ``load()``
  // so its dep-array reference during render doesn't hit the TDZ.
  // Hydrated from ``?city=<value>`` on mount; URL sync lives further
  // down. Reads ``window.location.search`` (not the react-router
  // ``searchParams`` object) to stay parity-locked with the sibling
  // ``selectedTags`` initializer above — both survive full-page
  // refresh + history.replaceState round-trips identically.
  const [city, setCity] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get("city")
                || "";
    } catch { return ""; }
  });
  const searchDeb = useDebounced(q);

  // Non-admin users cannot land on the inactive, muted, or waitlist
  // cohort — redirect to active. Phase H4 · Feb-2026 folds ``waitlist``
  // into the same admin gate as inactive/muted.
  useEffect(() => {
    if (!isAdmin && (tab === "inactive" || tab === "muted" || tab === "waitlist")) setTab("active");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]);

  // Feb 2026 · Customer Merge Phase 3 — fetch pending low-confidence
  // candidates once on mount for admin+ users. Cheap read (single
  // detection scan). Refetched after every merge via ``load()``
  // completing → ``loadCandidates()`` chained below.
  const loadCandidates = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const r = await api.get(
        "/customers/merge-candidates?confidence=low",
      );
      // Feb 2026 · Schema alignment — prefer the canonical
      // ``customer_ids_sample`` / ``duplicate_groups_total`` fields;
      // fall back to the legacy ``customer_ids`` / ``count`` for
      // clients that hit an older backend during a rolling deploy.
      setCandidateIds(
        r?.customer_ids_sample || r?.customer_ids || [],
      );
      setCandidateGroupsCount(
        r?.duplicate_groups_total ?? r?.count ?? 0,
      );
    } catch {
      setCandidateIds([]);
      setCandidateGroupsCount(0);
    }
  }, [isAdmin]);

  useEffect(() => { loadCandidates(); }, [loadCandidates]);

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
    // Phase H4 · Feb-2026 — Waitlist cohort tab. Sends the backend
    // ``?waitlisted=true`` predicate (canonical ``customers.waitlisted``
    // field toggled by the Add/Remove-from-waitlist bulk actions).
    // Waitlist is orthogonal to active/inactive/muted — those filters
    // are intentionally omitted so a waitlisted-and-muted row still
    // shows here. Stacks as intersection with the G4a portal filter.
    else if (tab === "waitlist") params.set("waitlisted", "true");
    if (missingCardOnly) params.set("missing_card", "true");
    // Phase G4a · Feb-2026 — Portal-activation filter. Only send the
    // param when the operator has selected a non-default value so
    // the wire log stays clean and the backend never sees ``all``
    // (harmless no-op today but explicit intent > accidental
    // dependence on the server-side alias).
    if (portalStatus && portalStatus !== "all") {
      params.set("portal_status", portalStatus);
    }
    // Feb-2026 · P43 — data-quality filters.
    if (missingEmail) params.set("missing_email", "true");
    if (missingPhone) params.set("missing_phone", "true");
    if (missingAddress) params.set("missing_address", "true");
    // Feb-2026 · P43c — Portal status tri-state.
    if (portalStatusFilter === "activated") params.set("portal_activated", "true");
    else if (portalStatusFilter === "not_activated") params.set("portal_activated", "false");
    // Feb-2026 · P44 — "No payment on file" chip.
    if (noPaymentFilter) params.set("has_payment_method", "false");
    // Feb-2026 · Customer temp password + first-access — "Never
    // logged in" chip. Distinct filter from portal_activated.
    if (neverLoggedIn) params.set("first_access", "never");
    // Feb-2026 · Onboarding-tile clickable ship — sibling
    // Invited / Signed-in chips. Mutual exclusion with
    // ``never`` on the shared ``first_access`` param is enforced
    // by the toggle handlers below; here we just pass the state
    // through so the backend sees the intended predicate.
    else if (signedInFilter) params.set("first_access", "any");
    if (portalInvitedFilter) params.set("portal_invited", "any");
    // Feb-2026 · P46 — city + multi-tag now flow through the backend
    // so pagination + tab counts stay honest. Repeat the ``tags``
    // key per selected value so backend gets a proper list.
    if (city && city.trim()) params.set("city", city.trim());
    for (const t of selectedTags) params.append("tags", t);
    // Feb-2026 · P26 — admin-tier escape hatch (widened by the
    // Customer Delete UX overhaul) to see soft-deleted rows.
    if (includeDeleted && canManageDeleted) params.set("include_deleted", "true");
    // Feb 2026 · Customer Merge Phase 2 — surface merged rows when
    // "Show merged" is on. Backend default is false, so a merged
    // customer normally disappears from the list post-merge.
    if (includeMerged) params.set("include_merged", "true");
    // Feb-2026 · P35 — always request the paginated envelope.
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    // Feb 2026 · Sort dropdown — passthrough. Backend defaults to
    // ``created_desc`` when omitted (same default as the UI) so
    // this line is defensive but strictly clarifies intent on the
    // wire log.
    if (sortBy) params.set("sort", sortBy);
    try {
      const data = await api.get(`/customers?${params.toString()}`);
      // Envelope-shaped when page/page_size present (Strategy B).
      const items = Array.isArray(data) ? data : (data?.items || []);
      setRows(items);
      setTotal(Number.isFinite(data?.total) ? data.total : items.length);
      setTotalPages(Number.isFinite(data?.total_pages)
        ? data.total_pages
        : (items.length ? 1 : 0));
      // Phase K68 · Feb-2026 — consume the paginated envelope's
      // ``counts_by_status`` block so the tab badges refresh in a
      // single round-trip. Falls back to the legacy separate-fanout
      // in ``loadCounts()`` when the server doesn't ship the block
      // (e.g. stale API). Non-admin users only see ``active`` — we
      // still overwrite for correctness (admin-only tabs are hidden
      // upstream, so writing them is harmless).
      const cbs = data?.counts_by_status;
      if (cbs && typeof cbs === "object") {
        setCounts({
          active: Number.isFinite(cbs.active) ? cbs.active : 0,
          inactive: Number.isFinite(cbs.inactive) ? cbs.inactive : 0,
          muted: isAdmin && Number.isFinite(cbs.muted) ? cbs.muted : null,
          waitlist: isAdmin && Number.isFinite(cbs.waitlist)
            ? cbs.waitlist : null,
          all: isAdmin && Number.isFinite(cbs.all) ? cbs.all : null,
        });
      }
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
      // Feb-2026 · P43 — tab counts must reflect the active P43 chips
      // so the badges stay in sync with the list (P40 unified-predicate
      // contract). Compose the shared suffix once.
      const p43 = [];
      if (missingEmail) p43.push("missing_email=true");
      if (missingPhone) p43.push("missing_phone=true");
      if (missingAddress) p43.push("missing_address=true");
      if (portalStatusFilter === "activated") p43.push("portal_activated=true");
      else if (portalStatusFilter === "not_activated") p43.push("portal_activated=false");
      // Feb-2026 · P44 — include "No payment on file" in the tab-count
      // shared suffix so the tab badges stay in sync with the list.
      if (noPaymentFilter) p43.push("has_payment_method=false");
      // Feb-2026 · P46 — tab counts must also honor city + multi-tag
      // filters so tab badges match the paginated envelope's total.
      if (city && city.trim()) {
        p43.push(`city=${encodeURIComponent(city.trim())}`);
      }
      for (const t of selectedTags) {
        p43.push(`tags=${encodeURIComponent(t)}`);
      }
      const p43Suffix = p43.length ? `&${p43.join("&")}` : "";
      const promises = [
        api.get(`/customers?is_active=true&count_only=true${p43Suffix}`),
        api.get(`/customers?is_active=false&count_only=true${p43Suffix}`),
      ];
      // Feb-2026 · P28 — muted-count endpoint is admin/manager/
      // super_admin only; tech role 403s. Skip the call for tech to
      // avoid a noisy request that will always fail.
      // Phase H4 · Feb-2026 — the Waitlist tab is also admin-only
      // (same gate as inactive/muted); tag its count call onto the
      // admin batch so tech never hits an unnecessary request.
      if (isAdmin) {
        promises.push(api.get(
          `/customers?is_muted=true&count_only=true${p43Suffix}`));
        promises.push(api.get(
          `/customers?waitlisted=true&count_only=true${p43Suffix}`));
      }
      const results = await Promise.all(promises);
      setCounts({
        active: results[0]?.count ?? 0,
        inactive: results[1]?.count ?? 0,
        muted: isAdmin ? (results[2]?.count ?? 0) : null,
        waitlist: isAdmin ? (results[3]?.count ?? 0) : null,
        // Phase K68 · Feb-2026 — legacy fanout doesn't compute the
        // "All" bucket; leave as-is when the primary envelope path
        // hasn't populated it yet. This fallback branch fires only
        // when the paginated envelope is missing ``counts_by_status``
        // (older server).
        all: isAdmin
          ? ((results[0]?.count ?? 0)
              + (results[1]?.count ?? 0)
              + (isAdmin ? (results[2]?.count ?? 0) : 0))
          : null,
      });
    } catch { /* silent — counts are advisory */ }
  };

  useEffect(() => {
    load();
    // Phase K68 · Feb-2026 — ``load()`` now populates the tab
    // counts via the paginated envelope's ``counts_by_status``
    // block, so the legacy 3-4-request fan-out in ``loadCounts()``
    // is no longer invoked on every filter/tab/page change. The
    // helper is retained as a defensive fallback for the rare
    // callers that still trigger it directly (mutation paths
    // below) — those callers keep their existing wiring so
    // nothing regresses in the edge case where the envelope is
    // missing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchDeb, tag, scope, tab, missingCardOnly, missingEmail,
       missingPhone, missingAddress, portalStatusFilter, noPaymentFilter, neverLoggedIn, portalInvitedFilter, signedInFilter, includeDeleted, includeMerged, page, pageSize, city, selectedTags, sortBy, portalStatus]);

  // Feb-2026 · P43 — URL sync + page reset on chip toggle. Skip the
  // first invocation so hydrating chips from the URL on mount does
  // not thrash the page cursor.
  const _p43FirstToggle = useRef(true);
  useEffect(() => {
    if (_p43FirstToggle.current) {
      _p43FirstToggle.current = false;
      return;
    }
    const next = new URLSearchParams(searchParams);
    if (missingEmail) next.set("missing_email", "1");
    else next.delete("missing_email");
    if (missingPhone) next.set("missing_phone", "1");
    else next.delete("missing_phone");
    if (missingAddress) next.set("missing_address", "1");
    else next.delete("missing_address");
    if (portalStatusFilter === "activated") next.set("portal_activated", "1");
    else if (portalStatusFilter === "not_activated") next.set("portal_activated", "0");
    else next.delete("portal_activated");
    if (noPaymentFilter) next.set("has_payment_method", "0");
    else next.delete("has_payment_method");
    // Feb-2026 · Customer temp password + first-access — URL sync.
    // ``first_access`` param is shared between "Never logged in"
    // and "Signed in" chips (mutual exclusion enforced in toggle
    // handlers).
    if (neverLoggedIn) next.set("first_access", "never");
    else if (signedInFilter) next.set("first_access", "any");
    else next.delete("first_access");
    // Feb-2026 · Onboarding-tile clickable ship — Invited chip.
    if (portalInvitedFilter) next.set("portal_invited", "any");
    else next.delete("portal_invited");
    setSearchParams(next, { replace: true });
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [missingEmail, missingPhone, missingAddress, portalStatusFilter, noPaymentFilter, neverLoggedIn, portalInvitedFilter, signedInFilter]);

  // Feb-2026 · P43b — Fetch the total "missing address" count once
  // on mount (and whenever the tenant scope changes) so the chip
  // badge shows a stable "(N)" count. Deliberately does NOT compose
  // with other active filters — the badge represents the FULL
  // population of address-less customers in the current tenant so
  // the number doesn't jump as the admin toggles other chips.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get(
          "/customers?count_only=true&missing_address=true",
        );
        if (!cancelled) setMissingAddressCount(r?.count ?? 0);
      } catch {
        if (!cancelled) setMissingAddressCount(null);
      }
    })();
    return () => { cancelled = true; };
  }, [scope]);

  // Feb-2026 · P43c — Fetch both "activated" and "not activated"
  // counts on mount (parallel). Same stability contract as the
  // missing-address count — deliberately does NOT compose with
  // other filters so the segmented badges stay stable while the
  // admin narrows other criteria.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [a, na] = await Promise.all([
        api.get("/customers?count_only=true&portal_activated=true").catch(() => null),
        api.get("/customers?count_only=true&portal_activated=false").catch(() => null),
      ]);
      if (cancelled) return;
      setPortalActivatedCount(a?.count ?? null);
      setPortalNotActivatedCount(na?.count ?? null);
    })();
    return () => { cancelled = true; };
  }, [scope]);

  // Feb-2026 · P44 — "No payment on file" count. Standalone fetch;
  // does NOT compose with other filters so the badge stays stable
  // as the admin narrows the list.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get(
          "/customers?count_only=true&has_payment_method=false",
        );
        if (!cancelled) setNoPaymentCount(r?.count ?? 0);
      } catch {
        if (!cancelled) setNoPaymentCount(null);
      }
    })();
    return () => { cancelled = true; };
  }, [scope]);

  // Feb-2026 · Customer temp password + first-access — "Never logged
  // in" standalone count. Same stability contract as the P43/P44
  // badges: does not compose with other filters so the badge stays
  // put while the admin narrows other criteria.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get(
          "/customers?count_only=true&first_access=never",
        );
        if (!cancelled) setNeverLoggedInCount(r?.count ?? 0);
      } catch {
        if (!cancelled) setNeverLoggedInCount(null);
      }
    })();
    return () => { cancelled = true; };
  }, [scope]);

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
  }, [searchDeb, tag, scope, tab, missingCardOnly, includeDeleted,
       includeMerged, city, selectedTags, sortBy]);

  // Feb-2026 · P35 — URL sync for ``page``. ``page=1`` is the default
  // so it's dropped from the URL to keep the query string tidy.
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    if (page > 1) next.set("page", String(page));
    else next.delete("page");
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  // Phase K62 · Feb-2026 — URL + localStorage sync for the
  // page-size selector. ``size=`` is dropped when it matches the
  // K62 default (25) so a plain ``/customers`` URL stays tidy.
  // The size change ALSO resets pagination to page 1 so the
  // operator doesn't land on an empty page after enlarging /
  // shrinking the window.
  const _k62SizeInitRef = React.useRef(true);
  useEffect(() => {
    try { localStorage.setItem(_K62_LS_KEY, String(pageSize)); }
    catch { /* SSR / private mode — silent */ }
    const next = new URLSearchParams(searchParams);
    if (pageSize !== _K62_DEFAULT_PAGE_SIZE) next.set("size", String(pageSize));
    else next.delete("size");
    setSearchParams(next, { replace: true });
    if (_k62SizeInitRef.current) {
      _k62SizeInitRef.current = false;
      return;
    }
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageSize]);

  useEffect(() => {
    // Feb-2026 · P40 — one-shot on mount is fine; the effect above
    // that runs on filter/tab/page changes also fires ``loadCounts``,
    // so this initial-mount call primes the badges before the first
    // filter change.
    loadCounts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Feb-2026 · Load tag registry for the chip filter bar. One-shot
  // on mount — recomputed usage counts land via GET /customer-tags.
  useEffect(() => {
    (async () => {
      try {
        // Feb-2026 · P44 — the customers-list "All tags" dropdown only
        // shows tags that are currently in use on ≥1 non-soft-deleted
        // customer. Do NOT propagate ``only_used`` to the settings page
        // or the customer edit-form tag picker — both need the full
        // catalog for archive / re-use flows.
        const res = await api.get("/customer-tags?only_used=true");
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

  // Feb-2026 · P46 — URL sync for ``city`` (state declared above near
  // the P43 chips so its dep-array reference in ``load()`` doesn't
  // hit the TDZ). Strips the param on empty.
  useEffect(() => {
    try {
      const p = new URLSearchParams(window.location.search);
      if (city && city.trim()) p.set("city", city.trim());
      else p.delete("city");
      const q = p.toString();
      window.history.replaceState(null, "",
        window.location.pathname + (q ? "?" + q : ""));
    } catch { /* silent */ }
  }, [city]);

  const cities = useMemo(() => {
    const s = new Set();
    (rows || []).forEach((r) => {
      const c = (r.address || "").split(",").slice(-2, -1)[0]?.trim();
      if (c) s.add(c);
    });
    return Array.from(s).sort();
  }, [rows]);

  // Phase 12 · Feb 2026 — server-side filter reads ``missingCardOnly``
  // via the ``missing_card=true`` query param (set inside ``load()``).
  // The client-side ``filtered`` memo also mirrors the same predicate
  // so switching cohorts doesn't briefly show stale rows.
  // Feb-2026 · P46 — ``city`` and ``selectedTags`` filters now flow
  // through the backend as query params so pagination + tab counts
  // stay honest. Only ``missingCardOnly`` stays as a defensive
  // client-side mirror of the same server predicate.
  const filtered = useMemo(() => {
    if (!rows) return null;
    let out = rows;
    if (missingCardOnly) out = out.filter((r) =>
      r.effective_require_card_on_file && !r.has_card_on_file);
    // Feb 2026 · Customer Merge Phase 3 — client-side narrow to the
    // pending merge candidates when the operator has the chip on.
    if (candidateFilterActive && candidateIds.length) {
      const set = new Set(candidateIds);
      out = out.filter((r) => set.has(r.id));
    }
    return out;
  }, [rows, missingCardOnly, candidateFilterActive, candidateIds]);

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
  // Feb 2026 · This threshold used to separate "typed-number
  // confirm" from "plain confirm". Type-to-confirm was retired
  // app-wide, so the threshold now separates "single-click
  // confirm" (small deletes) from "2-click arm-and-execute"
  // (mass delete >=500, catastrophic) — the state machine lives
  // in the shared <ArmToDelete/> primitive.
  const _CATASTROPHIC_THRESHOLD = 500;
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
      // Feb-2026 · ArmToDelete primitive owns its own reset via
      // unmount when the modal closes below.
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
      // Feb-2026 · P40 — refresh counts alongside; assigned_owner
      // change doesn't shift cohorts today but keeping the pattern
      // consistent avoids a future regression.
      load();
      loadCounts();
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

  // ─── Phase H1 · Feb-2026 — Bulk portal invite ───────────────────────
  const [h1ConfirmOpen, setH1ConfirmOpen] = useState(false);
  const [h1Busy, setH1Busy] = useState(false);
  const [h1Result, setH1Result] = useState(null); // {counts, failures}
  // Feb-2026 · Bulk-Portal-Invite-from-CustomersList follow-up —
  // batch tester caught that Cancel + backdrop-click close paths
  // did NOT refetch the customers list (only the success path did,
  // inside ``doBulkPortalInvite``). This helper unifies the three
  // close paths (backdrop-click, Cancel, success) so every exit
  // from the modal invalidates the list. Idempotent on success —
  // the earlier ``load()`` inside ``doBulkPortalInvite`` is now
  // gone (moved here) so we don't double-fire.
  const closeH1ConfirmModal = useCallback(() => {
    setH1ConfirmOpen(false);
    load();
  }, [load]);
  const _h1SelectedRows = () =>
    (rows || []).filter((r) => selected.has(r.id));
  const _h1AlreadyActivatedCount = () =>
    _h1SelectedRows().filter((r) => r.has_login === true).length;
  const doBulkPortalInvite = async () => {
    if (!selected.size) return;
    const ids = Array.from(selected);
    setH1Busy(true);
    try {
      const res = await api.post(
        "/admin/customers/portal-invite/bulk",
        { customer_ids: ids },
      );
      setH1Result(res);
      const parts = [];
      parts.push(`Sent ${res.sent}`);
      const skipTotal = (res.skipped_already_activated || 0)
        + (res.skipped_no_contact || 0)
        + (res.skipped_wrong_tenant || 0);
      if (skipTotal) {
        parts.push(
          `Skipped ${skipTotal} (${res.skipped_already_activated} already `
          + `activated, ${res.skipped_no_contact} no contact)`,
        );
      }
      if (res.failed_send) parts.push(`Failed ${res.failed_send}`);
      setToast({ tone: res.failed_send ? "warning" : "success",
                    message: parts.join(". ") + "." });
      setSelected(new Set());
      // ``closeH1ConfirmModal`` handles both the modal-close AND the
      // customers-list refetch. See the helper comment above.
      closeH1ConfirmModal();
    } catch (e) {
      const msg = e?.data?.detail?.message || e?.message
        || "Bulk portal invite failed";
      setToast({ tone: "error", message: msg });
    } finally {
      setH1Busy(false);
    }
  };

  // Feb-2026 · P45 — "Next visit" formatter.
  // • null / empty / unparseable  → "—"
  // • current year                → "Aug 23"
  // • different year              → "Aug 23, 2027"
  // Tolerates both full-ISO ("2026-08-23T09:00:00+00:00") and
  // date-only ("2026-09-01") shapes from ``db.jobs.scheduled_date``.
  const nextScheduled = (c) => {
    const raw = c.next_scheduled_at;
    if (!raw) return "—";
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return "—";
    const thisYear = new Date().getFullYear();
    const opts = d.getFullYear() === thisYear
      ? { month: "short", day: "numeric" }
      : { month: "short", day: "numeric", year: "numeric" };
    return d.toLocaleDateString(undefined, opts);
  };

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
    // Phase H4 · Feb-2026 — Waitlist cohort tab. Fifth segment,
    // admin-only (same gate as inactive/muted). Count sourced from
    // ``GET /customers?waitlisted=true&count_only=true`` and stacks
    // as intersection with the G4a portal-activation filter.
    { k: "waitlist", label: "Waitlist", count: counts.waitlist, testid: "tab-waitlist", adminOnly: true },
    { k: "all", label: "All", count: counts.all, testid: "tab-all", adminOnly: true },
  ];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="customers-page">
      <PageHeader
        title="Customers"
        subtitle={
          total > 0
            ? `Showing ${((page - 1) * pageSize + 1).toLocaleString()}-`
              + `${Math.min(page * pageSize, total).toLocaleString()} of `
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
            {isAdminOrManager ? (
              <Button
                variant="ghost"
                onClick={() => setImportCsvOpen(true)}
                testid="import-csv-btn"
              >
                <Upload size={16} /> Import CSV
              </Button>
            ) : null}
            <Button onClick={() => navigate("/customers/new")} testid="customers-new-button">
              <Plus size={16} /> New Customer
            </Button>
            {/* Feb-2026 · Bulk Portal Invite from customers top-menu.
                Reuses the pre-existing Phase H1 modal
                (test-id "h1-modal-portal-invite") rather than
                extracting a common shell — that modal is a mature
                superset of the ChaseStalledInvitesModal (adds the
                already-activated pre-warning, filter-state pill,
                and failure-details side-panel). See
                /app/memory/FEATURE_BULK_PORTAL_INVITE_CUSTOMERS_LIST.md.
                Gate is ``isAdmin`` (admin + super_admin only) —
                tighter than the read gate on the list. */}
            {isAdmin ? (
              <Button
                variant="ghost"
                onClick={() => setH1ConfirmOpen(true)}
                disabled={selected.size === 0}
                testid="customers-toolbar-portal-invite-btn"
                title={
                  selected.size === 0
                    ? "Select one or more customers to invite"
                    : `Send portal invite to ${selected.size} selected customer${selected.size === 1 ? "" : "s"}`
                }
              >
                <Mail size={16} /> Portal Invite
                {selected.size > 0 ? ` (${selected.size})` : ""}
              </Button>
            ) : null}
            {/* Feb-2026 · Phase — Customer geocoding on save +
                one-time backfill. Admin+/super_admin-only trigger
                for POST /api/admin/customers/backfill-geocoding.
                Small button — reuses the shared ghost variant, no
                new modal. Toast copy branches on the response
                envelope (inline counts vs. enqueued). */}
            {isAdmin ? (
              <BackfillGeocodingButton />
            ) : null}
          </>
        }
      />

      {/* Feb-2026 · Portal onboarding health tile — admin-only.
          ``externalRefetchToken={h1Result}`` — Feb-2026
          Bulk-Portal-Invite-from-CustomersList ship: whenever the
          Phase H1 bulk-invite modal resolves, its ``h1Result``
          object identity changes → tile useEffect fires → cohort
          counts refresh (subject to the 60s server cache). */}
      {isAdmin ? (
        <PortalOnboardingHealthTile externalRefetchToken={h1Result} />
      ) : null}

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

      {/* Phase I2 · Feb-2026 — "Send portal invite to entire
          Waitlist" cohort action. Only visible on the Waitlist
          tab, admin+ only. Reuses the H1 bulk-invite endpoint;
          fetches the full waitlisted-cohort id list at click-time
          so stale-tab counts can't corrupt the payload. */}
      {tab === "waitlist" && isAdmin && counts.waitlist > 0 ? (
        <div className="mb-3 flex justify-end">
          <Button
            variant="secondary"
            data-testid="waitlist-bulk-invite-btn"
            onClick={async () => {
              try {
                // Re-fetch waitlist ids at click time (no stale
                // state; page_size cap = 500 matches H1 batch cap).
                const listRes = await api.get(
                  "/customers?waitlisted=true&page=1&page_size=500",
                );
                const ids = (listRes?.items || [])
                  .map((c) => c.id).filter(Boolean);
                if (!ids.length) {
                  sonnerToast.info?.("No waitlisted customers to invite.");
                  return;
                }
                const confirmMsg = ids.length > 20
                  ? `Send portal invite to ${ids.length} waitlisted customers? Type WAITLIST to confirm.`
                  : `Send portal invite to ${ids.length} waitlisted customer(s)?`;
                if (ids.length > 20) {
                  // eslint-disable-next-line no-alert
                  const typed = window.prompt(confirmMsg);
                  if (typed !== "WAITLIST") return;
                } else if (!window.confirm(confirmMsg)) {
                  return;
                }
                const res = await api.post(
                  "/admin/customers/portal-invite/bulk",
                  { customer_ids: ids },
                );
                const invited = res?.sent ?? res?.invited_count ?? 0;
                const skipped = (res?.skipped_already_activated ?? 0)
                  + (res?.skipped_no_contact ?? 0)
                  + (res?.skipped_wrong_tenant ?? 0);
                sonnerToast.success(
                  `Invited ${invited}, skipped ${skipped} (already active or no email).`,
                );
              } catch (e) {
                sonnerToast.error(
                  e?.message
                  || "Bulk invite failed — hourly cap may be reached.",
                );
              }
            }}
          >
            Send portal invite to entire Waitlist ({counts.waitlist})
          </Button>
        </div>
      ) : null}

      {/* Filter row — Phase K52.1 · Feb-2026: navy chrome strip. */}
      <div
        className="rounded-2xl p-4 mb-4 flex flex-wrap gap-3 items-center"
        style={{ backgroundColor: colors.nav.bg, border: `1px solid ${colors.nav.border}` }}
        data-testid="customers-filters"
        data-k52-navy-strip="true"
      >
        <div className="relative flex-1 min-w-[220px]">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2"
            style={{ color: colors.nav.fgMuted }}
          />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name, email, phone, address…"
            className="w-full pl-9 pr-3 py-2.5 rounded-lg outline-none text-sm focus:ring-2 placeholder:text-white/70"
            style={{
              backgroundColor: "rgba(255,255,255,0.10)",
              border: `1px solid ${colors.nav.border}`,
              color: colors.nav.fg,
            }}
            data-testid="customers-search"
          />
        </div>
        <div className="flex items-center gap-1">
          <Filter size={14} style={{ color: colors.nav.fgMuted }} />
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
                // Phase K52.1 · Feb-2026 — scope is a filter-state
                // chip → active = K52 gradient, idle = transparent
                // w/ white outline (matches K52 Slice A pattern).
                background: scope === s.k ? colors.gradient.css : "transparent",
                color: colors.nav.fg,
                border: `1px solid ${scope === s.k ? "transparent" : colors.nav.fgMuted}`,
                textShadow: scope === s.k ? colors.gradient.textShadow : undefined,
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
            backgroundColor: colors.nav.bg,
            color: colors.nav.fg,
            border: `1px solid ${colors.nav.border}`,
          }}
          data-testid="customers-filter-tag"
        >
          <option value="">All tags</option>
          {TAG_PRESETS.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
        {/* Feb 2026 · Sort dropdown — Newest→Oldest default, persisted
            to localStorage. Change triggers a re-fetch via the load()
            effect (sortBy in dep-array) and resets to page 1. */}
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="text-xs font-semibold px-3 py-1.5 rounded-lg"
          style={{
            backgroundColor: colors.nav.bg,
            color: colors.nav.fg,
            border: `1px solid ${colors.nav.border}`,
          }}
          aria-label="Sort customers by"
          data-testid="customers-filter-sort"
        >
          {_SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        {/* Phase G4a · Feb-2026 — Portal-activation filter dropdown.
            Stacks with the segmented cohort tabs (Active | Inactive |
            Muted | All). Persists via ``customerListFilter.portalStatus``
            in localStorage. Selecting a non-default value resets to
            page 1 via the ``portalStatus`` effect above. */}
        <select
          value={portalStatus}
          onChange={(e) => setPortalStatus(e.target.value)}
          className="text-xs font-semibold px-3 py-1.5 rounded-lg"
          style={{
            backgroundColor: colors.nav.bg,
            color: colors.nav.fg,
            border: `1px solid ${colors.nav.border}`,
          }}
          aria-label="Filter customers by portal activation status"
          data-testid="customers-filter-portal-status"
        >
          {_PORTAL_STATUS_OPTIONS.map((o) => (
            <option
              key={o.value}
              value={o.value}
              data-testid={`portal-status-option-${o.value}`}
            >
              {o.label}
            </option>
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
        {/* Feb-2026 · P45 — "More filters" dropdown. Replaces the
             chip strip with a single trigger that opens a grouped,
             always-mounted panel. Every child control preserves its
             pre-existing ``data-testid`` so existing filter tests
             (P43b / P43c / P44 / merge / include-deleted) keep
             passing without modification. Panel is portaled by
             hidden-attribute toggle so RTL testid queries resolve
             even when the panel is closed.

             Kept OUT of the dropdown per spec:
               • "Missing card"  → primary filter, stays on this row.
             Grouping inside the dropdown:
               • Contact info missing → email / phone / address
               • Payment → No payment on file
               • Portal status (radio, tri-state)
               • Administrative → deleted / merged / merge candidates
        */}
        <div className="relative">
          {(() => {
            const active = (
              (missingEmail ? 1 : 0) +
              (missingPhone ? 1 : 0) +
              (missingAddress ? 1 : 0) +
              (noPaymentFilter ? 1 : 0) +
              (portalStatusFilter ? 1 : 0) +
              (neverLoggedIn ? 1 : 0) +
              (portalInvitedFilter ? 1 : 0) +
              (signedInFilter ? 1 : 0) +
              (includeDeleted ? 1 : 0) +
              (includeMerged ? 1 : 0) +
              (candidateFilterActive ? 1 : 0)
            );
            const summaryBits = [];
            if (missingEmail) summaryBits.push("No email");
            if (missingPhone) summaryBits.push("No phone");
            if (missingAddress) summaryBits.push("Missing address");
            if (noPaymentFilter) summaryBits.push("No payment");
            if (portalStatusFilter === "activated") summaryBits.push("Signed in");
            else if (portalStatusFilter === "not_activated") summaryBits.push("Never signed in");
            if (neverLoggedIn) summaryBits.push("Never logged in");
            if (portalInvitedFilter) summaryBits.push("Invited");
            if (signedInFilter) summaryBits.push("Signed in");
            if (includeDeleted) summaryBits.push("Show deleted");
            if (includeMerged) summaryBits.push("Show merged");
            if (candidateFilterActive) summaryBits.push("Merge candidates");
            let summary = "All";
            if (active === 1) summary = summaryBits[0];
            else if (active > 1) summary = `${summaryBits[0]} +${active - 1}`;
            return (
              <button
                type="button"
                onClick={() => setMoreFiltersOpen((v) => !v)}
                data-testid="customers-more-filters-dropdown"
                aria-haspopup="dialog"
                aria-expanded={moreFiltersOpen ? "true" : "false"}
                aria-controls="customers-more-filters-panel"
                className="text-xs font-semibold px-3 py-1.5 rounded-lg inline-flex items-center gap-1.5"
                style={{
                  backgroundColor: active > 0 ? "#DBEAFE" : colors.surfaceSecondary,
                  color: active > 0 ? "#1E3A8A" : colors.onSurfaceSecondary,
                  border: `1px solid ${active > 0 ? "#93C5FD" : colors.border}`,
                }}
                title="More filters"
              >
                <Filter size={12} />
                <span>More filters:</span>
                <span
                  data-testid="customers-more-filters-summary"
                  className="tabular-nums"
                  style={{ fontWeight: 700 }}
                >
                  {summary}
                </span>
                {active > 0 ? (
                  <span
                    className="ml-1 rounded-full px-1.5 py-0.5 text-[10px] tabular-nums"
                    style={{ backgroundColor: "#1E40AF", color: "#fff" }}
                    data-testid="customers-more-filters-active-count"
                  >
                    {active}
                  </span>
                ) : null}
              </button>
            );
          })()}
          {/* Backdrop — click-outside close. Always mounted so children
              stay in the DOM for test queries. */}
          <div
            hidden={!moreFiltersOpen}
            onClick={() => setMoreFiltersOpen(false)}
            className="fixed inset-0 z-40"
            aria-hidden="true"
          />
          <div
            id="customers-more-filters-panel"
            role="dialog"
            aria-label="More filters"
            hidden={!moreFiltersOpen}
            className="absolute z-50 mt-2 w-80 rounded-xl shadow-lg p-3"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") setMoreFiltersOpen(false);
            }}
          >
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs font-bold uppercase tracking-wide"
                   style={{ color: colors.onSurfaceSecondary }}>
                Filter by attribute
              </div>
              <button
                type="button"
                onClick={() => {
                  setMissingEmail(false);
                  setMissingPhone(false);
                  setMissingAddress(false);
                  setNoPaymentFilter(false);
                  setPortalStatusFilter("");
                  if (canManageDeleted) setIncludeDeleted(false);
                  setIncludeMerged(false);
                  setCandidateFilterActive(false);
                }}
                data-testid="customers-more-filters-clear"
                className="text-xs font-semibold underline"
                style={{ color: "#1E40AF" }}
              >
                Clear
              </button>
            </div>

            {/* Group: Contact info missing */}
            <div className="mb-3">
              <div className="text-[10px] font-bold uppercase mb-1.5"
                   style={{ color: colors.muted }}>
                Contact info missing
              </div>
              <button
                onClick={() => setMissingEmail((v) => !v)}
                data-testid="filter-chip-missing-email"
                aria-pressed={missingEmail ? "true" : "false"}
                className="w-full text-left text-xs font-semibold px-2 py-1.5 rounded inline-flex items-center gap-2"
                style={{
                  backgroundColor: missingEmail ? "#DBEAFE" : "transparent",
                  color: missingEmail ? "#1E3A8A" : colors.onSurface,
                }}
              >
                <span
                  className="inline-block w-3 h-3 rounded border"
                  style={{
                    backgroundColor: missingEmail ? "#1E40AF" : "transparent",
                    borderColor: missingEmail ? "#1E40AF" : colors.border,
                  }}
                  aria-hidden="true"
                />
                No email
              </button>
              <button
                onClick={() => setMissingPhone((v) => !v)}
                data-testid="filter-chip-missing-phone"
                aria-pressed={missingPhone ? "true" : "false"}
                className="w-full text-left text-xs font-semibold px-2 py-1.5 rounded inline-flex items-center gap-2"
                style={{
                  backgroundColor: missingPhone ? "#DBEAFE" : "transparent",
                  color: missingPhone ? "#1E3A8A" : colors.onSurface,
                }}
              >
                <span
                  className="inline-block w-3 h-3 rounded border"
                  style={{
                    backgroundColor: missingPhone ? "#1E40AF" : "transparent",
                    borderColor: missingPhone ? "#1E40AF" : colors.border,
                  }}
                  aria-hidden="true"
                />
                No phone number
              </button>
              <button
                onClick={() => setMissingAddress((v) => !v)}
                data-testid="customers-missing-address-filter"
                aria-pressed={missingAddress ? "true" : "false"}
                className="w-full text-left text-xs font-semibold px-2 py-1.5 rounded inline-flex items-center gap-2"
                style={{
                  backgroundColor: missingAddress ? "#DBEAFE" : "transparent",
                  color: missingAddress ? "#1E3A8A" : colors.onSurface,
                }}
              >
                <span
                  className="inline-block w-3 h-3 rounded border"
                  style={{
                    backgroundColor: missingAddress ? "#1E40AF" : "transparent",
                    borderColor: missingAddress ? "#1E40AF" : colors.border,
                  }}
                  aria-hidden="true"
                />
                <span className="flex-1">Missing address</span>
                {missingAddressCount != null ? (
                  <span
                    className="tabular-nums text-[11px]"
                    data-testid="customers-missing-address-count"
                    style={{
                      color: missingAddress ? "#1E3A8A" : colors.muted,
                      fontWeight: 600,
                    }}
                  >
                    ({missingAddressCount})
                  </span>
                ) : null}
              </button>
            </div>

            {/* Group: Payment */}
            <div className="mb-3">
              <div className="text-[10px] font-bold uppercase mb-1.5"
                   style={{ color: colors.muted }}>
                Payment
              </div>
              <button
                onClick={() => setNoPaymentFilter((v) => !v)}
                data-testid="customers-no-payment-filter"
                aria-pressed={noPaymentFilter ? "true" : "false"}
                title="Customers with no card AND no ACH bank account on file. Matches the same 'Card on file required — none saved' banner shown on customer detail."
                className="w-full text-left text-xs font-semibold px-2 py-1.5 rounded inline-flex items-center gap-2"
                style={{
                  backgroundColor: noPaymentFilter ? "#DBEAFE" : "transparent",
                  color: noPaymentFilter ? "#1E3A8A" : colors.onSurface,
                }}
              >
                <span
                  className="inline-block w-3 h-3 rounded border"
                  style={{
                    backgroundColor: noPaymentFilter ? "#1E40AF" : "transparent",
                    borderColor: noPaymentFilter ? "#1E40AF" : colors.border,
                  }}
                  aria-hidden="true"
                />
                <span className="flex-1">No payment on file</span>
                {noPaymentCount != null ? (
                  <span
                    className="tabular-nums text-[11px]"
                    data-testid="customers-no-payment-count"
                    style={{
                      color: noPaymentFilter ? "#1E3A8A" : colors.muted,
                      fontWeight: 600,
                    }}
                  >
                    ({noPaymentCount})
                  </span>
                ) : null}
              </button>
            </div>

            {/* Group: Portal status — tri-state radio */}
            <div className="mb-3">
              <div className="text-[10px] font-bold uppercase mb-1.5"
                   style={{ color: colors.muted }}>
                Portal status
              </div>
              <div
                data-testid="customers-portal-status-filter"
                data-value={portalStatusFilter || "any"}
                role="radiogroup"
                aria-label="Portal status"
              >
                {[
                  { value: "", label: "Any",
                    testid: "customers-portal-status-any" },
                  { value: "activated", label: "Signed in",
                    count: portalActivatedCount,
                    testid: "customers-portal-status-activated" },
                  { value: "not_activated", label: "Never signed in",
                    count: portalNotActivatedCount,
                    testid: "customers-portal-status-not-activated" },
                ].map((opt) => {
                  const active = portalStatusFilter === opt.value;
                  return (
                    <button
                      key={opt.value || "any"}
                      type="button"
                      role="radio"
                      onClick={() => setPortalStatusFilter(opt.value)}
                      data-testid={opt.testid}
                      aria-pressed={active ? "true" : "false"}
                      aria-checked={active ? "true" : "false"}
                      className="w-full text-left text-xs font-semibold px-2 py-1.5 rounded inline-flex items-center gap-2"
                      style={{
                        backgroundColor: active ? "#DBEAFE" : "transparent",
                        color: active ? "#1E3A8A" : colors.onSurface,
                      }}
                    >
                      <span
                        className="inline-block w-3 h-3 rounded-full border"
                        style={{
                          backgroundColor: active ? "#1E40AF" : "transparent",
                          borderColor: active ? "#1E40AF" : colors.border,
                        }}
                        aria-hidden="true"
                      />
                      <span className="flex-1">{opt.label}</span>
                      {opt.count != null ? (
                        <span
                          className="tabular-nums text-[11px]"
                          data-testid={`${opt.testid}-count`}
                          style={{
                            color: active ? "#1E3A8A" : colors.muted,
                            fontWeight: 600,
                          }}
                        >
                          ({opt.count})
                        </span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Group: First-time sign-in (Feb-2026 · Customer temp password) */}
            <div className="mb-3">
              <div className="text-[10px] font-bold uppercase mb-1.5"
                   style={{ color: colors.muted }}>
                First-time sign-in
              </div>
              {/* Feb-2026 · Onboarding-tile clickable ship — Invited chip.
                  Sibling of the Never Logged In chip, mirrors the same
                  toggle-→ ``?portal_invited=any`` URL persistence
                  pattern. Predicate matches the onboarding-health
                  ``invited`` cohort (``has_login`` truthy). */}
              <button
                onClick={() => setPortalInvitedFilter((v) => !v)}
                data-testid="filter-chip-portal-invited"
                aria-pressed={portalInvitedFilter ? "true" : "false"}
                title="Customers with an admin-issued portal invite (has_login=true)."
                className="w-full text-left text-xs font-semibold px-2 py-1.5 rounded inline-flex items-center gap-2 mb-1"
                style={{
                  backgroundColor: portalInvitedFilter ? "#FEF3C7" : "transparent",
                  color: portalInvitedFilter ? "#78350F" : colors.onSurface,
                }}
              >
                <span
                  className="inline-block w-3 h-3 rounded border"
                  style={{
                    backgroundColor: portalInvitedFilter ? "#D97706" : "transparent",
                    borderColor: portalInvitedFilter ? "#D97706" : colors.border,
                  }}
                  aria-hidden="true"
                />
                <span className="flex-1">Invited</span>
                {portalInvitedCount != null ? (
                  <span
                    className="tabular-nums text-[11px]"
                    data-testid="filter-chip-portal-invited-count"
                    style={{
                      color: portalInvitedFilter ? "#78350F" : colors.muted,
                      fontWeight: 600,
                    }}
                  >
                    ({portalInvitedCount})
                  </span>
                ) : null}
              </button>
              {/* Signed-in chip (Feb-2026 · Onboarding-tile clickable
                  ship). Mutually exclusive with "Never logged in" on
                  the shared ``first_access`` param — toggling one
                  turns the other off. */}
              <button
                onClick={() => {
                  setSignedInFilter((v) => {
                    const next = !v;
                    if (next) setNeverLoggedIn(false);
                    return next;
                  });
                }}
                data-testid="filter-chip-signed-in"
                aria-pressed={signedInFilter ? "true" : "false"}
                title="Customers who have completed a portal sign-in at least once."
                className="w-full text-left text-xs font-semibold px-2 py-1.5 rounded inline-flex items-center gap-2 mb-1"
                style={{
                  backgroundColor: signedInFilter ? "#FEF3C7" : "transparent",
                  color: signedInFilter ? "#78350F" : colors.onSurface,
                }}
              >
                <span
                  className="inline-block w-3 h-3 rounded border"
                  style={{
                    backgroundColor: signedInFilter ? "#D97706" : "transparent",
                    borderColor: signedInFilter ? "#D97706" : colors.border,
                  }}
                  aria-hidden="true"
                />
                <span className="flex-1">Signed in</span>
                {signedInCount != null ? (
                  <span
                    className="tabular-nums text-[11px]"
                    data-testid="filter-chip-signed-in-count"
                    style={{
                      color: signedInFilter ? "#78350F" : colors.muted,
                      fontWeight: 600,
                    }}
                  >
                    ({signedInCount})
                  </span>
                ) : null}
              </button>
              <button
                onClick={() => {
                  setNeverLoggedIn((v) => {
                    const next = !v;
                    if (next) setSignedInFilter(false);
                    return next;
                  });
                }}
                data-testid="customers-never-logged-in-filter"
                aria-pressed={neverLoggedIn ? "true" : "false"}
                title="Customers who have never completed a portal sign-in. A customer may have chosen their own password via a reset link but still not signed in — this filter surfaces the ones the front-office should chase."
                className="w-full text-left text-xs font-semibold px-2 py-1.5 rounded inline-flex items-center gap-2"
                style={{
                  backgroundColor: neverLoggedIn ? "#FEF3C7" : "transparent",
                  color: neverLoggedIn ? "#78350F" : colors.onSurface,
                }}
              >
                <span
                  className="inline-block w-3 h-3 rounded border"
                  style={{
                    backgroundColor: neverLoggedIn ? "#D97706" : "transparent",
                    borderColor: neverLoggedIn ? "#D97706" : colors.border,
                  }}
                  aria-hidden="true"
                />
                <span className="flex-1">Never logged in</span>
                {neverLoggedInCount != null ? (
                  <span
                    className="tabular-nums text-[11px]"
                    data-testid="customers-never-logged-in-count"
                    style={{
                      color: neverLoggedIn ? "#78350F" : colors.muted,
                      fontWeight: 600,
                    }}
                  >
                    ({neverLoggedInCount})
                  </span>
                ) : null}
              </button>
            </div>

            {/* Group: Administrative */}
            {(canManageDeleted || isAdmin) ? (
              <div className="mb-1">
                <div className="text-[10px] font-bold uppercase mb-1.5"
                     style={{ color: colors.muted }}>
                  Administrative
                </div>
                {canManageDeleted ? (
                  <button
                    onClick={() => setIncludeDeleted((v) => !v)}
                    data-testid="customers-filter-include-deleted"
                    aria-pressed={includeDeleted ? "true" : "false"}
                    title="Admin: include soft-deleted customers in the list"
                    className="w-full text-left text-xs font-semibold px-2 py-1.5 rounded inline-flex items-center gap-2"
                    style={{
                      backgroundColor: includeDeleted ? "#FEE2E2" : "transparent",
                      color: includeDeleted ? "#991B1B" : colors.onSurface,
                    }}
                  >
                    <span
                      className="inline-block w-3 h-3 rounded border"
                      style={{
                        backgroundColor: includeDeleted ? "#B91C1C" : "transparent",
                        borderColor: includeDeleted ? "#B91C1C" : colors.border,
                      }}
                      aria-hidden="true"
                    />
                    Show deleted
                  </button>
                ) : null}
                {isAdmin ? (
                  <button
                    onClick={() => setIncludeMerged((v) => !v)}
                    data-testid="customers-filter-include-merged"
                    aria-pressed={includeMerged ? "true" : "false"}
                    title="Include records that were merged into another customer"
                    className="w-full text-left text-xs font-semibold px-2 py-1.5 rounded inline-flex items-center gap-2"
                    style={{
                      backgroundColor: includeMerged ? "#F3E8FF" : "transparent",
                      color: includeMerged
                        ? (colors.accent?.violet?.[700] || "#6D28D9")
                        : colors.onSurface,
                    }}
                  >
                    <span
                      className="inline-block w-3 h-3 rounded border"
                      style={{
                        backgroundColor: includeMerged
                          ? (colors.accent?.violet?.[500] || "#8B5CF6")
                          : "transparent",
                        borderColor: includeMerged
                          ? (colors.accent?.violet?.[500] || "#8B5CF6")
                          : colors.border,
                      }}
                      aria-hidden="true"
                    />
                    Show merged
                  </button>
                ) : null}
                {isAdmin && candidateGroupsCount > 0 ? (
                  <button
                    onClick={() => setCandidateFilterActive((v) => !v)}
                    data-testid="customers-filter-pending-merge-candidates"
                    aria-pressed={candidateFilterActive ? "true" : "false"}
                    title="Filter list to duplicate candidates awaiting manual merge review"
                    className="w-full text-left text-xs font-semibold px-2 py-1.5 rounded inline-flex items-center gap-2"
                    style={{
                      backgroundColor: candidateFilterActive
                        ? (colors.accent?.amber?.[100] || "#FEF3C7")
                        : "transparent",
                      color: candidateFilterActive
                        ? (colors.accent?.amber?.[700] || "#B45309")
                        : colors.onSurface,
                    }}
                  >
                    <span
                      className="inline-block w-3 h-3 rounded border"
                      style={{
                        backgroundColor: candidateFilterActive
                          ? (colors.accent?.amber?.[500] || "#F59E0B")
                          : "transparent",
                        borderColor: candidateFilterActive
                          ? (colors.accent?.amber?.[500] || "#F59E0B")
                          : colors.border,
                      }}
                      aria-hidden="true"
                    />
                    <span className="flex-1">
                      Pending merge candidates
                    </span>
                    <span
                      className="tabular-nums text-[11px]"
                      style={{
                        color: candidateFilterActive
                          ? (colors.accent?.amber?.[700] || "#B45309")
                          : colors.muted,
                        fontWeight: 600,
                      }}
                    >
                      ({candidateGroupsCount})
                    </span>
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
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
          {/* Phase H1 · Feb-2026 — Bulk portal invite (admin+ only).
              Opens a confirm modal that surfaces current filter
              state + a warning about any pre-activated rows in the
              selection so ops don't accidentally re-invite a
              customer that already has portal access. */}
          {isAdmin ? (
            <Button
              variant="ghost"
              onClick={() => setH1ConfirmOpen(true)}
              testid="bulk-portal-invite"
            >
              Send portal invite ({selected.size})
            </Button>
          ) : null}
        </div>
      ) : null}

      {/* Feb-2026 · P43b — contextual banner shown ONLY when the
          missing-address chip is active. Sits ABOVE the data-table
          card so it renders whether the filtered list is empty or
          populated. Skipped when the chip is off so the list is
          uncluttered. */}
      {missingAddress ? (
        <div
          className="rounded-md border p-3 mb-3 text-sm inline-flex items-start gap-2"
          style={{
            background: "#EFF6FF",
            borderColor: "#BFDBFE",
            color: "#1E3A8A",
          }}
          data-testid="customers-missing-address-banner"
          role="note"
        >
          <span aria-hidden="true">&#9432;</span>
          <span>
            These customers can&rsquo;t appear on maps or route
            optimization until an address is added. Click any
            customer to add one.
          </span>
        </div>
      ) : null}

      {/* Feb-2026 · P44 — contextual banner shown ONLY when the
          "No payment on file" chip is active. Explains WHY the
          operator is looking at these rows and points at the row
          action button. */}
      {noPaymentFilter ? (
        <div
          className="rounded-md border p-3 mb-3 text-sm inline-flex items-start gap-2"
          style={{
            background: "#EFF6FF",
            borderColor: "#BFDBFE",
            color: "#1E3A8A",
          }}
          data-testid="customers-no-payment-banner"
          role="note"
        >
          <span aria-hidden="true">&#9432;</span>
          <span>
            These customers can&rsquo;t be auto-charged for invoices
            until they add a card. Use &ldquo;Add card&rdquo; on any
            row to email + SMS a secure link.
          </span>
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
            page_size={pageSize}
            onPageChange={setPage}
            pageSizeOptions={_K62_PAGE_SIZE_OPTIONS}
            onPageSizeChange={setPageSize}
            testidPrefix="customers-pager-top"
          />
          <table className="w-full text-sm" data-testid="customers-table">
            <thead>
              <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                <th className="text-left px-3 py-2 w-8"
                     data-testid="customer-select-all">
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
                  <td className="px-3 py-3"
                        onClick={(e) => e.stopPropagation()}
                        data-testid={`customer-select-${c.id}`}>
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
                      {/* Feb-2026 · P26 — Restore pill for admin-tier
                           (widened from super_admin by the Customer
                           Delete UX overhaul). */}
                      {c.deleted_at && canManageDeleted ? (
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
                      {/* Feb 2026 · Customer Merge Phase 2 — MERGED
                          badge. Only visible when the operator has
                          "Show merged" on (otherwise the row is
                          hidden by the backend). Clicking navigates
                          to the primary customer's detail page. */}
                      {c.merged_into ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/customers/${c.merged_into}`);
                          }}
                          className="text-[10px] font-semibold px-1.5 py-0.5 rounded inline-flex items-center gap-1 hover:brightness-110"
                          style={{
                            backgroundColor: colors.accent.violet[500],
                            color: "#fff",
                          }}
                          data-testid={`merged-badge-${c.id}`}
                          title={`Merged into ${c.merged_into} on ${c.merged_at || "unknown date"} — click to open the primary`}
                        >
                          MERGED
                        </button>
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
                            // Feb-2026 · P40 — mute/unmute changes
                            // the muted cohort but not any load()
                            // dep, so counts wouldn't otherwise
                            // refresh via the useEffect.
                            load();
                            loadCounts();
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
                      {/* Feb-2026 · P44 iteration r2 — "Add card"
                          row action. Relocated to the right-edge
                          action cluster and re-skinned navy-on-white
                          so it reads as a primary action, not a
                          warning. Placed BEFORE Reactivate /
                          Mark inactive so the natural left-to-right
                          reading order in the actions column is
                          [Add card] → [Reactivate|Mark inactive] →
                          [Mute] → [⋮]. Testid + legacy alias +
                          endpoint + rate limit are unchanged. */}
                      {isAdmin && !c.has_card_on_file ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleSendPaymentLink(c);
                          }}
                          disabled={sendingPaymentLink.has(c.id)}
                          data-testid={`add-card-btn-${c.id}`}
                          data-testid-legacy={`customer-row-send-payment-link-btn-${c.id}`}
                          className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded transition hover:brightness-110"
                          style={{
                            backgroundColor: "#1E293B",
                            color: "#FFFFFF",
                            border: "1px solid #0F172A",
                            opacity: sendingPaymentLink.has(c.id) ? 0.6 : 1,
                            cursor: sendingPaymentLink.has(c.id)
                              ? "not-allowed" : "pointer",
                          }}
                          title="Email + SMS the customer a secure link to add a card for auto-pay"
                        >
                          <Send size={12} />
                          {sendingPaymentLink.has(c.id)
                            ? "Sending…" : "Add card"}
                        </button>
                      ) : null}
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
                            // Feb-2026 · P40 — refresh tab counts
                            // alongside the list; see the identical
                            // handler above for rationale.
                            load();
                            loadCounts();
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
            page_size={pageSize}
            onPageChange={setPage}
            pageSizeOptions={_K62_PAGE_SIZE_OPTIONS}
            onPageSizeChange={setPageSize}
            testidPrefix="customers-pager-bottom"
          />
          </>
        )}
      </div>

      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} onDone={() => { setImportOpen(false); load(); loadCounts(); }} setToast={setToast} />
      <ImportCsvModalP41
        open={importCsvOpen}
        onClose={() => setImportCsvOpen(false)}
        onDone={() => { load(); loadCounts(); }}
        setToast={setToast}
      />

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

      {/* Feb 2026 · Customer Merge Phase 2 — merge modal. Hydrated
          with the full customer rows for the currently-selected
          ids so the side-by-side cards can render without extra
          fetches. */}
      <MergeCustomersModal
        open={mergeOpen}
        onClose={() => setMergeOpen(false)}
        customers={(rows || []).filter((r) => selected.has(r.id))}
        onDone={(res) => {
          setMergeOpen(false);
          setSelected(new Set());
          const N = res?.merged_count || 0;
          const totalRewired = Object.values(
            res?.related_records_rewired || {},
          ).reduce((a, b) => a + (Number(b) || 0), 0);
          sonnerToast.success(
            `Merged ${N} customer${N === 1 ? "" : "s"} into ${res?.primary_name || "primary"}.`,
            { description: `${totalRewired.toLocaleString()} related record${totalRewired === 1 ? "" : "s"} reassigned.` },
          );
          load();
          loadCounts();
          loadCandidates();
        }}
        onError={(msg) => sonnerToast.error(msg)}
      />

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
          // Feb 2026 · Customer Merge Phase 2 — surface the merge
          // flow from the same bulk-action bar. Gated to admin only
          // (matches the backend RBAC). Requires ≥2 selected and no
          // "select all matching" — the merge modal needs every
          // candidate's full doc, so unbounded selects can't be
          // hydrated in the browser.
          ...(isAdmin && !selectAllMatching && selected.size >= 2 ? [{
            key: "merge", label: "Merge selected",
            onClick: () => setMergeOpen(true),
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
      {/* Feb-2026 · Unlimited bulk delete — small deletes keep the
          shared single-click ``BulkConfirmModal``; large deletes
          (>=500 rows, catastrophic) render the shared
          ``<ArmToDelete>`` primitive inside a bespoke modal so the
          state machine + cooldown live in one place. */}
      {confirmDeleteOpen && _pendingDeleteCount < _CATASTROPHIC_THRESHOLD ? (
        <BulkConfirmModal
          open={confirmDeleteOpen}
          onClose={() => setConfirmDeleteOpen(false)}
          onConfirm={doBulkDelete}
          title={`Delete ${_pendingDeleteCount} customer${_pendingDeleteCount === 1 ? "" : "s"}?`}
          description="Customers with active invoices will show as locked and be skipped."
          confirmLabel={bulkBusy ? "Deleting…" : `Delete ${_pendingDeleteCount}`}
          busy={bulkBusy}
        />
      ) : null}
      {confirmDeleteOpen && _pendingDeleteCount >= _CATASTROPHIC_THRESHOLD ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !bulkBusy) {
              setConfirmDeleteOpen(false);
            }
          }}
          data-testid="customers-bulk-delete-catastrophic-modal"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold"
                style={{ color: "#DC2626" }}
                data-testid="customers-bulk-delete-catastrophic-title">
              Delete {_pendingDeleteCount} customer{_pendingDeleteCount === 1 ? "" : "s"}?
            </h2>
            <p className="text-sm mt-2"
                style={{ color: colors.onSurfaceSecondary || colors.muted }}>
              This is a large delete. Customers with active invoices
              will be locked and skipped. Deleted customers are
              soft-deleted (recoverable via backend restore) — but
              from the UI they're gone.
            </p>
            <p className="text-xs mt-3 font-semibold uppercase tracking-wider"
                style={{ color: colors.onSurfaceSecondary }}
                data-testid="customers-bulk-delete-catastrophic-help">
              This action is irreversible. Click Arm delete to arm,
              then click Delete again to execute.
            </p>
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
                onClick={() => setConfirmDeleteOpen(false)}
                disabled={bulkBusy}
                className="px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-60"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurface }}
                data-testid="customers-bulk-delete-catastrophic-cancel"
              >
                Cancel
              </button>
              <ArmToDelete
                count={_pendingDeleteCount}
                catastrophicThreshold={_CATASTROPHIC_THRESHOLD}
                cooldownMs={3000}
                onConfirm={doBulkDelete}
                label="Delete"
                armLabel="Arm delete"
                disabled={bulkBusy}
                size="md"
                testIdPrefix="customers-bulk-delete-catastrophic"
              />
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

      {/* ─── Phase H1 · Feb-2026 — Bulk portal invite confirm modal ────
          Surfaces the current filter state and any pre-activated
          rows in the selection so admins don't accidentally chase
          the wrong cohort or re-invite already-activated customers. */}
      {h1ConfirmOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) closeH1ConfirmModal();
          }}
          data-testid="h1-bulk-portal-invite-modal"
        >
          <div
            className="w-full max-w-md rounded-2xl p-6 shadow-2xl"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold"
                style={{ color: colors.onSurface }}
                data-testid="h1-modal-title">
              Send portal invite to {selected.size} customer
              {selected.size === 1 ? "" : "s"}?
            </h2>
            <div
              className="text-xs mt-2 rounded-lg px-3 py-2"
              style={{ backgroundColor: colors.surfaceSecondary,
                        color: colors.onSurfaceSecondary || colors.muted }}
              data-testid="h1-modal-filter-state"
            >
              Currently filtered: Portal =
              {" "}
              <span className="font-semibold">
                {portalStatus === "all" ? "All"
                  : portalStatus === "activated" ? "Activated"
                  : "Not activated"}
              </span>
              {" · "}Cohort =
              {" "}
              <span className="font-semibold">
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </span>
              {" · "}
              <span className="font-semibold">
                {selected.size} customer{selected.size === 1 ? "" : "s"} selected
              </span>
            </div>

            {_h1AlreadyActivatedCount() > 0 ? (
              <div
                className="mt-3 text-sm rounded-lg px-3 py-2"
                style={{ backgroundColor: "#FEF3C7", color: "#78350F" }}
                data-testid="h1-modal-already-warning"
              >
                {_h1AlreadyActivatedCount()} of your selected customers already
                have portal access — they'll be skipped.
              </div>
            ) : null}

            <p className="text-sm mt-3"
               style={{ color: colors.onSurfaceSecondary || colors.muted }}>
              Each recipient will receive an invite via email (if
              present) or SMS. Customers with no email AND no phone
              will be skipped. This action is throttled at 500
              invites per hour per tenant.
            </p>

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={closeH1ConfirmModal}
                className="px-4 py-2 rounded-xl text-sm font-semibold"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurface }}
                data-testid="h1-modal-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={h1Busy}
                onClick={doBulkPortalInvite}
                className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-40"
                style={{ backgroundColor: colors.brandPrimary || "#2563EB" }}
                data-testid="h1-modal-confirm"
              >
                {h1Busy ? "Sending…" :
                  `Send ${selected.size} invite${selected.size === 1 ? "" : "s"}`}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Phase H1 · Feb-2026 — Failure details side-panel. Rendered
          in-place off the summary toast so ops can see per-row
          reasons + error strings for any bulk-invite send that
          didn't succeed. */}
      {h1Result && (h1Result.failures || []).length > 0 ? (
        <div
          className="fixed bottom-6 right-6 z-40 rounded-2xl p-4 shadow-2xl w-full max-w-sm"
          style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid="h1-failure-details"
        >
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-bold"
                style={{ color: colors.onSurface }}>
              Bulk invite details
              ({(h1Result.failures || []).length})
            </h3>
            <button
              type="button"
              onClick={() => setH1Result(null)}
              className="text-xs px-2 py-0.5 rounded"
              style={{ backgroundColor: colors.surfaceSecondary,
                        color: colors.onSurface }}
              data-testid="h1-failure-close"
            >
              Close
            </button>
          </div>
          <ul className="text-xs space-y-1 max-h-64 overflow-auto"
              style={{ color: colors.onSurfaceSecondary || colors.muted }}>
            {(h1Result.failures || []).slice(0, 25).map((f, i) => (
              <li key={i} className="truncate">
                · <span className="font-mono">{(f.customer_id || "").slice(0, 8)}</span>
                {" · "}{f.reason}
                {f.error ? ` — ${f.error}` : ""}
              </li>
            ))}
            {(h1Result.failures || []).length > 25 ? (
              <li className="italic">
                … and {(h1Result.failures || []).length - 25} more.
              </li>
            ) : null}
          </ul>
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
