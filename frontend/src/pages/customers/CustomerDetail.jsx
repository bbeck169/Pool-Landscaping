import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams, Link } from "react-router-dom";
import { ArrowLeft, Edit3, Trash2, Mail, Phone, MapPin, Beaker, KeyRound, Briefcase, FileText, StickyNote, Droplets, Star, ListChecks, Home, DollarSign, Clock, ShieldCheck, Paperclip, GitMerge, Ruler, FlaskConical, MoreHorizontal, X as XIcon, AlertCircle, Receipt, Wallet, MessageSquare } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { api } from "@/api";
import TemplatePickerPreview from "@/components/communications/TemplatePickerPreview";
import { CustomerMeasurementsTab, filterCustomerTabs } from "@/components/customer/CustomerMeasurementsTab";
import CustomerChemicalHistoryTab, { CHEMICAL_HISTORY_TAB_ROLES } from "@/components/customer/CustomerChemicalHistoryTab";
import { useAuth } from "@/auth";
import { colors, money, statusMeta } from '@/theme';
import ClickToCallButton from "@/components/telephony/ClickToCallButton";
import { Button, Modal, TextInput, Skeleton, Chip, StatusPill, EmptyState, Toast } from "@/components/ui-kit";
import { MediaLibraryPicker } from "@/components/marketing/MediaLibraryPicker";
import { ActivationControl } from "@/components/customers/ActivationControl";
import { ServiceCategoryControl } from "@/components/customers/ServiceCategoryControl";
import CustomerEquipmentLibrary from "@/components/customers/CustomerEquipmentLibrary";
import CustomerWarrantiesLibrary from "@/components/customers/CustomerWarrantiesLibrary";
import CustomerActionDropdowns from "@/components/customers/CustomerActionDropdowns";
import SendServiceRecordsLinkModal from "@/components/customers/SendServiceRecordsLinkModal";
import CustomerTagPicker from "@/components/customers/CustomerTagPicker";
import CustomerTagsCard from "@/components/customers/CustomerTagsCard";
import DemoAccountToggle from "@/components/comms/DemoAccountToggle";
import CustomerCommunicationsTimeline from "@/components/customers/CustomerCommunicationsTimeline";
import CustomerTasksPanel from "@/components/customers/CustomerTasksPanel";
// TD-79 · Feb-2026 — Overview-tab invoice list section.
import CustomerInvoiceList from "@/components/customers/CustomerInvoiceList";
import CustomerContactsPanel from "@/components/customers/CustomerContactsPanel";
import NotesHistoryList from "@/components/customers/NotesHistoryList";
// Phase P52 · Feb-2026 — Chemistry / Chem History consolidation.
// Two standalone action-row buttons collapse into a single brand-
// coloured dropdown that sits inline with Edit / Delete on
// ``cd-action-row``.  Testids from the removed buttons move onto
// the new items so the cd-chemistry / cd-chemistry-history
// selectors used by existing suites keep resolving.
// Feb-2026 · Customer Header Navy Strip — the standalone Chemistry
// dropdown that lived inline on the customer header row has been
// folded into the "+ Create" menu inside CustomerActionDropdowns
// (as a nested "Chemistry…" submenu). The inline ChevronDown +
// DropdownMenu* imports that powered the removed block are gone.
import { PhoneLink, AddressLink } from "@/components/customer";
import CustomerMultiContactEditor from "@/components/customers/CustomerMultiContactEditor";
import HardDeleteModal from "@/components/hard_delete/HardDeleteModal";
import ResolveDuplicateDialog
  from "@/components/customers/ResolveDuplicateDialog";
import PaymentMethodTiles from "@/components/customers/PaymentMethodTiles";
import { MergeHistoryPanel } from "@/components/customers/MergeHistoryPanel";
import CustomerFullTimeline from "@/components/customers/CustomerFullTimeline";
import CustomerServiceNotesCards from "@/components/customers/CustomerServiceNotesCards";
import CustomerGeocodeInfo from "@/components/customers/CustomerGeocodeInfo";
import { useSetDynamicCrumb }
  from "@/components/nav/dynamicCrumbContext";
import PropertiesTab from "./PropertiesTab";
import MasterBillingCard from "./MasterBillingCard";
import { CustomerCreditsPanel, AdjustDialog } from "./CustomerCreditsPage";
// Feb-2026 · Customer name relocation — the PageHeader import
// was removed alongside the JSX call site.  The customer name
// now lives INSIDE the identity card (see the inline
// customer-detail-inline-h1 render near the address line) so a
// separate page-chrome header is no longer needed.


/**
 * Feb-2026 · Send Portal Invite button — relocated from the Portal
 * Access tab to the main Contact card in the Overview tab.
 *
 * Reuses the exact same backend endpoint the old placement called
 * (``POST /api/customers/{cid}/portal-invite``) so behaviour is
 * byte-identical: same email template, same auto-generated password,
 * same admin/super_admin permission gate (enforced server-side).
 *
 * Disabled state — required per the relocation spec:
 *   * No email on file → button disabled with a helpful tooltip.
 *   * Send in flight   → button labelled "Sending…" and disabled.
 */
// Exported so the dedicated vitest spec for the 409 collision
// handler (``PortalInvite.collision.test.jsx``) can mount the
// button in isolation without the full CustomerDetail tree.
// Phase 1 resolve-duplicate · Feb-2026 — cap the auto-retry chain so
// a pathological N-customer email collision can't infinite-loop the
// admin. The dialog re-opens with the NEXT conflicting record on
// subsequent 409s up to this bound; after that we surface a plain
// error and hand control back to the admin.
const _RESOLVE_DUP_MAX_AUTO_RETRIES = 2;

export function PortalInviteQuickAction({ customer, onToast }) {
  const [busy, setBusy] = React.useState(false);
  const [payload, setPayload] = React.useState(null);
  // Phase 1 resolve-duplicate · Feb-2026 — enriched 409 state.
  // ``conflict`` holds the ``conflict`` object from the backend
  // 409 payload; when non-null the component renders the rich
  // error UI (two buttons) under the primary action instead of a
  // bare toast.  ``dialogOpen`` + ``retryCount`` back the auto-
  // retry flow seeded off the ResolveDuplicateDialog callback.
  const [conflict, setConflict] = React.useState(null);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const retryCountRef = React.useRef(0);
  const email = (
    (customer.emails || []).find((e) => e && e.address)?.address
    || customer.email
    || ""
  );
  const hasEmail = !!email.trim();

  const _sendInvite = React.useCallback(async () => {
    // Returns ``{ok: true}`` on success (toast + payload side-
    // effects handled here), or ``{ok: false, conflict}`` on 409
    // collision so callers (initial send + auto-retry) can decide
    // what to render.  Any other error throws.
    const r = await api.post(`/customers/${customer.id}/portal-invite`);
    if (r?.emailed) {
      onToast?.({ tone: "success",
                   message: `Portal invite email sent to ${r.email}` });
      setPayload(null);
    } else if (r?.password) {
      setPayload({ link: r.login_url, email: r.email, password: r.password });
      onToast?.({ tone: "info",
                   message: "Portal invite link ready — share it manually" });
    } else {
      onToast?.({ tone: "success", message: "Portal invite sent" });
      setPayload(null);
    }
    return { ok: true };
  }, [customer.id, onToast]);

  const send = async () => {
    setBusy(true);
    setPayload(null);
    setConflict(null);
    retryCountRef.current = 0;
    try {
      await _sendInvite();
    } catch (e) {
      // PORTAL-INVITE-EMAIL-COLLISION-FIX · Feb-2026 (P0 #1 + #2) +
      // Phase 1 resolve-duplicate · Feb-2026.
      // The backend ``_upsert_customer_user`` guard raises 409 with
      // the new canonical ``detail.error_code=email_bound_to_other
      // _customer`` AND the legacy ``detail.code=portal_user_email
      // _collision`` (kept for pre-FE-update consumers).  Either
      // marker triggers the rich conflict UI; the new ``conflict``
      // object (if present) powers the ResolveDuplicateDialog.
      const detail = e?.data?.detail;
      const isCollision =
        e?.status === 409
        && detail && (
          detail.error_code === "email_bound_to_other_customer"
          || detail.code === "portal_user_email_collision"
        );
      if (isCollision) {
        const existingCidPrefix =
          detail.existing_customer_id_prefix || "";
        setConflict(detail.conflict || null);
        onToast?.({
          tone: "error",
          message:
            "This email is already linked to another customer in this "
            + "tenant"
            + (existingCidPrefix ? ` (ID: ${existingCidPrefix}…)` : "")
            + ". Resolve the duplicate before re-inviting.",
          testid: "portal-invite-email-collision-toast",
        });
      } else {
        onToast?.({ tone: "error", message: e.message || "Portal invite failed" });
      }
    } finally {
      setBusy(false);
    }
  };

  const handleResolved = React.useCallback(async (releasedEmail) => {
    // The dialog has just unbound the conflicting customer's email.
    // Auto-retry the invite — if it lands in another collision
    // (a third customer in the chain) re-open the dialog with the
    // new conflict, up to _RESOLVE_DUP_MAX_AUTO_RETRIES times.
    setDialogOpen(false);
    retryCountRef.current += 1;
    setBusy(true);
    try {
      await _sendInvite();
      onToast?.({
        tone: "success",
        message: `Email released and invite sent to ${releasedEmail || email}.`,
        testid: "resolve-duplicate-auto-retry-success-toast",
      });
      setConflict(null);
    } catch (e) {
      const detail = e?.data?.detail;
      const isCollision =
        e?.status === 409
        && detail && (
          detail.error_code === "email_bound_to_other_customer"
          || detail.code === "portal_user_email_collision"
        );
      if (
        isCollision
        && retryCountRef.current < _RESOLVE_DUP_MAX_AUTO_RETRIES
      ) {
        // Chain: open dialog on the NEXT conflicting record.
        setConflict(detail.conflict || null);
        setDialogOpen(true);
      } else if (isCollision) {
        onToast?.({
          tone: "error",
          message:
            "Email released, but another customer still has it. "
            + "Click 'Resend invite' to retry manually.",
          testid: "resolve-duplicate-retry-cap-toast",
        });
        setConflict(detail.conflict || null);
      } else {
        onToast?.({
          tone: "error",
          message:
            "Email released. Click 'Resend invite' to retry — "
            + (e?.message || "the auto-retry failed."),
        });
      }
    } finally {
      setBusy(false);
    }
  }, [_sendInvite, email, onToast]);

  return (
    <div data-testid="cd-portal-invite-quick-action">
      <div className="flex items-center justify-between rounded-xl p-3"
           style={{ backgroundColor: colors.surfaceSecondary,
                    border: `1px solid ${colors.border}` }}>
        <div className="min-w-0">
          <div className="text-xs uppercase font-semibold"
               style={{ color: colors.muted }}>
            Portal Access
          </div>
          <div className="text-sm mt-0.5"
               style={{ color: colors.onSurfaceSecondary }}>
            {hasEmail
              ? "Send a one-click login link to this customer."
              : "Add a customer email to enable portal invites."}
          </div>
        </div>
        <Button
          onClick={send}
          disabled={busy || !hasEmail}
          title={!hasEmail
            ? "Add customer email to send portal invite"
            : undefined}
          testid="cd-portal-invite"
        >
          {busy ? "Sending…" : "Send Portal Invite"}
        </Button>
      </div>
      {conflict ? (
        <div
          className="mt-2 rounded-xl p-3 space-y-2"
          style={{
            backgroundColor: "#FEF2F2",
            color: "#7F1D1D",
            border: "1px solid #FECACA",
          }}
          data-testid="portal-invite-collision-panel"
        >
          <div className="text-sm font-semibold">
            This email is already linked to another customer:
            {" "}<span data-testid="portal-invite-collision-name">
              {conflict.customer_name || "(unknown)"}
            </span>.
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              to={`/customers/${conflict.customer_id}`}
              className="inline-flex items-center text-sm font-semibold px-3 py-1.5 rounded-lg"
              style={{
                backgroundColor: colors.brand,
                color: "#fff",
              }}
              data-testid="portal-invite-view-conflicting-btn"
            >
              View conflicting customer →
            </Link>
            <Button
              variant="ghost"
              onClick={() => setDialogOpen(true)}
              testid="portal-invite-resolve-duplicate-btn"
            >
              Resolve duplicate…
            </Button>
          </div>
          <div className="text-xs opacity-80">
            This invite is blocked until the duplicate is resolved.
          </div>
        </div>
      ) : null}
      {payload ? (
        <div className="mt-2 rounded-lg p-3 text-sm"
             style={{ backgroundColor: colors.brandTertiary,
                      color: colors.onBrandTertiary }}
             data-testid="portal-invite-payload">
          <div className="font-semibold mb-1">
            Share these credentials manually:
          </div>
          <div>
            Login: <a href={payload.link} className="underline"
                       target="_blank" rel="noreferrer">{payload.link}</a>
          </div>
          <div>Email: <code>{payload.email}</code></div>
          <div>Temp password: <code>{payload.password}</code></div>
        </div>
      ) : null}
      <ResolveDuplicateDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        currentCustomer={{
          id: customer.id,
          name: customer.name,
          email,
          phone:
            (customer.phones && customer.phones[0]?.number)
            || customer.phone
            || "",
          address: customer.address || "",
          created_at: customer.created_at || "",
        }}
        conflict={conflict}
        onResolved={handleResolved}
      />
    </div>
  );
}
import CardOnFileControl from "@/components/customers/CardOnFileControl";
import CardOnFileWarningBanner from "@/components/customers/CardOnFileWarningBanner";
import CustomerDeleteModal from "@/components/customers/CustomerDeleteModal";
// Phase M1 · Feb-2026 — Customer Merge Wizard (admin-only 3-step).
import CustomerMergeWizard from "@/pages/customers/CustomerMergeWizard";
import CustomerReviewsTab from "@/components/customers/CustomerReviewsTab";
import AdminCardCapturePanel from "@/components/customers/AdminCardCapturePanel";
// Phase B4 · Feb-2026 — Stripe subscription CRUD panel.
import SubscriptionsPanel from "./SubscriptionsPanel";
import ResponsiveTabs from "@/components/ui/responsive-tabs";
// Feb-2026 · Customer detail — unified "Sent documents" tab.
// Merges quotes + invoices + estimator estimates + legacy
// estimates for the current customer into one sortable/filterable
// list. Preserves the existing Quotes / Invoices tab placeholders
// (they stay in the tab bar for backwards-compat) and adds a new
// consolidated "Documents" tab as the primary surface.
import CustomerDocumentsTab from "@/components/customers/CustomerDocumentsTab";
import { List } from "react-window";


// Phase P37 · Feb-2026 — fixed row height for the virtualized jobs
// history list. Measured against the pre-P37 DOM (rounded up from
// the natural ~68px so the row content has breathing room + the
// action buttons don't overflow). Kept module-scope so tests can
// import it deterministically.
const _P37_JOB_ROW_HEIGHT = 72;


// Phase P37 · Feb-2026 — memoized row component for the virtualized
// jobs history. Rendered by ``react-window``'s ``<List>`` (which
// passes ``index``, ``style``, ``ariaAttributes`` and any keys from
// ``rowProps``). Only re-renders when THIS row's job id / status /
// updated_at flips — a search-input keystroke on the parent won't
// force every windowed row through reconciliation.
const JobHistoryRow = React.memo(
  function JobHistoryRow({ index, style, ariaAttributes, jobs, reopenJob }) {
    const j = jobs[index];
    if (!j) return <div style={style} {...ariaAttributes} />;
    return (
      <div
        style={{ ...style, padding: "6px 4px" }}
        {...ariaAttributes}
        data-testid={`cd-job-row-${j.id}`}
      >
        <div
          className="flex items-center gap-3 p-3 rounded-xl transition hover:brightness-95 h-full"
          style={{
            backgroundColor: colors.surfaceSecondary,
            border: `1px solid ${colors.border}`,
          }}
        >
          <Link
            to={`/jobs/${j.id}`}
            className="flex-1 min-w-0"
            data-testid={`cd-job-${j.id}`}
          >
            <div
              className="text-sm font-semibold truncate"
              style={{ color: colors.onSurface }}
            >
              {j.title}
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              {j.scheduled_date || "Unscheduled"} ·
              {" " + (j.technician_name || "Unassigned")}
            </div>
          </Link>
          <StatusPill status={j.status} />
          {j.status === "completed" ? (
            <button
              onClick={() => reopenJob(j.id)}
              className="text-xs font-semibold px-2 py-1 rounded"
              style={{
                color: colors.brand,
                border: `1px solid ${colors.brandTertiary}`,
              }}
              data-testid={`cd-reopen-${j.id}`}
            >
              Reopen
            </button>
          ) : null}
        </div>
      </div>
    );
  },
  (prev, next) => {
    // Skip re-render unless THIS row's key data actually changed.
    // ``jobs`` array reference AND handler references are stable
    // via useCallback/useMemo at the parent — we can rely on
    // index+id+status+updated_at for the equality check.
    if (prev.index !== next.index) return false;
    const pj = prev.jobs[prev.index];
    const nj = next.jobs[next.index];
    if (pj === nj) return true;
    if (!pj || !nj) return false;
    return (
      pj.id === nj.id
      && pj.status === nj.status
      && pj.updated_at === nj.updated_at
      && pj.title === nj.title
      && pj.technician_name === nj.technician_name
      && pj.scheduled_date === nj.scheduled_date
      && prev.reopenJob === next.reopenJob
    );
  },
);


// Phase 27 · Feb-2026 — admin customer-profile dark-navy chassis
// constants, mirrored verbatim from PortalHome Phase 23/24 tile
// chassis so the two surfaces read as one visual family.  Chassis
// bg = ``#03002e`` (deep navy), border = ``#1E293B`` (Tailwind
// slate-800).  Red/green dynamic bg thresholds + hex values are
// locked in Phase 24's companion test file
// (``portal-home-tiles-hover-glow-dynamic-colors.test.jsx``) —
// do NOT invent new values here.
const CD_DARK_CARD_BG      = "#03002e";
const CD_DARK_CARD_BORDER  = "#1E293B";
const CD_DANGER_BG         = "#7F1D1D";          // red-900, Past-Due + Overdue>0
const CD_SUCCESS_BG        = "#064E3B";          // emerald-900, Credit>0
// Phase 38 · Feb-2026 — admin customer profile visual grouping.
// All constants layer ON TOP of the Phase 27 chassis palette; the
// pre-Phase-38 constants above remain the source of truth for the
// identity-header card + page shell + skeleton + dynamic Past-Due /
// Credit / Overdue flips, so Phase 24 / 27 / 28 regression locks
// stay intact. New constants only drive (a) the KPI tile neutral
// bg, (b) the action-row Edit/Merge/Credit/Correction button bg +
// border, (c) the Quick-Action nav-tile base bg, and (d) the
// Quick-Action icon-tint rotation.
//
// Contrast verified against WCAG 2.1 — see Phase 38 test file
// (``_FINANCIAL_NEUTRAL_WHITE_CONTRAST``, etc.).
const CD_FINANCIAL_NEUTRAL_BG   = "#115E59";     // teal-800, KPI neutral bg (7.9:1 vs white)
const CD_FINANCIAL_NEUTRAL_LABEL = "#CBD5E1";    // slate-300, KPI muted label on teal neutral (5.1:1 — up from the pre-P38 slate-400 which drops to 2.4:1 on teal)
const CD_ACTION_BTN_BG          = "#334155";     // slate-700, Edit/Merge/Credit/Correction medium steel (9.8:1 vs white)
const CD_ACTION_BTN_BORDER      = "#64748B";     // slate-500, action button outline on steel
const CD_NAV_TILE_BG            = "#0F172A";     // slate-900, QA nav tile base — slightly lighter than CD_DARK_CARD_BG for grouping separation (17.4:1 vs white)
const CD_ICON_ACCENT_TEAL       = "#2DD4BF";     // teal-400, every 3rd QA tile (i % 3 == 0)
const CD_ICON_ACCENT_INDIGO     = "#818CF8";     // indigo-400, every 3rd QA tile (i % 3 == 1)
const CD_ICON_ACCENT_SLATE      = "#94A3B8";     // slate-400, every 3rd QA tile (i % 3 == 2) — matches the pre-P38 single icon tint for a 1/3 coverage overlap
const CD_ICON_ACCENTS           = [
  CD_ICON_ACCENT_TEAL,
  CD_ICON_ACCENT_INDIGO,
  CD_ICON_ACCENT_SLATE,
];
const CD_TILE_CLASSES      = "text-left rounded-2xl p-3 transition hover:brightness-95";
const CD_ACTION_TILE_CLASSES =
  "rounded-xl p-3 text-left transition hover:brightness-95 "
  + "hover:shadow-[0_0_20px_rgba(255,255,255,0.6)] "
  + "transition-shadow duration-200 relative";


function _fmtMoney(cents) {
  const amount = Math.max(0, Number(cents || 0)) / 100;
  return `$${amount.toLocaleString(undefined,
    {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
}


// ═══════════════════════════════════════════════════════════════════
// CUSTOMER-DETAIL-NEXT-SERVICE · Feb-2026 — admin "Next Service" tile.
// ═══════════════════════════════════════════════════════════════════
// Standalone card between the Phase 27 KPI tile grid (above) and
// the Phase 27 Quick Actions tile grid (below).  Phase 27 locks
// preserved — this does NOT touch either adjacent grid.  Chassis
// matches the adjacent Phase 27 dark-navy chassis
// (``CD_TILE_CLASSES`` + ``CD_FINANCIAL_NEUTRAL_BG`` +
// ``CD_DARK_CARD_BORDER``) so the three-row stack reads as a
// single visual block — honouring the "same chassis as the
// adjacent grids" directive. (Spec parenthetical mentioned
// ``colors.surface`` / ``colors.border`` but those don't match
// what the adjacent grids actually render; chose adjacency match.)
//
// Fields rendered when a job is present:
//   • Formatted date + time (locale-formatted, e.g.
//     "Thu, Nov 7 · 10:00 AM").
//   • service_type (or ``title`` fallback).
//   • ``technician_name`` denorm (admin side has this baked in
//     per jobs.py read-time cascade — line 1684).
//   • ``<StatusPill status={job.status} />`` from
//     ``@/components/ui-kit`` — reuses JobDetail's convention
//     (JobDetail.jsx line 572).
//   • Entire card click → ``navigate(`/jobs/${job.id}`)`` — the
//     canonical schedule-row destination (TodaySchedule.jsx:786,
//     CalendarSchedule.jsx:14).
//
// Empty state ("No upcoming services"):
//   • "Schedule a job" CTA → ``/jobs/new?customer_id=${customerId}``
//     — the canonical new-job route (JobNew.jsx:50; CustomerDetail
//     itself already uses this at line ~1985).
// ═══════════════════════════════════════════════════════════════════
// Exported so the dedicated vitest spec
// (``__tests__/CustomerDetail.nextService.test.jsx``) can mount the
// tile in isolation without rendering the full CustomerDetail page.
// Named export only — the default export of this module is
// unchanged; the inline usage inside the page still references the
// in-scope function reference.
export function NextServiceTile({ customerId }) {
  const navigate = useNavigate();
  const [state, setState] = useState({ loading: true, job: null });

  useEffect(() => {
    let cancelled = false;
    setState({ loading: true, job: null });
    (async () => {
      try {
        const res = await api.get(
          `/customers/${customerId}/next-service`,
        );
        if (cancelled) return;
        setState({ loading: false, job: res?.next_service || null });
      } catch (_err) {
        // Tile is non-critical; swallow errors silently and show
        // the empty state so the operator can still schedule.
        if (cancelled) return;
        setState({ loading: false, job: null });
      }
    })();
    return () => { cancelled = true; };
  }, [customerId]);

  const { loading, job } = state;

  // Date-time formatting — mirrors Schedule row conventions
  // (locale-default; tenant tz is handled on the write side).
  const formatted = useMemo(() => {
    if (!job) return null;
    const raw = job.scheduled_start || job.scheduled_date;
    if (!raw) return null;
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return null;
    const datePart = d.toLocaleDateString(undefined, {
      weekday: "short", month: "short", day: "numeric",
    });
    const timePart = job.scheduled_start
      ? d.toLocaleTimeString(undefined, {
          hour: "numeric", minute: "2-digit",
        })
      : null;
    return timePart ? `${datePart} · ${timePart}` : datePart;
  }, [job]);

  const onCardClick = () => {
    if (job?.id) navigate(`/jobs/${job.id}`);
  };

  const onScheduleCta = (e) => {
    e.stopPropagation();
    navigate(`/jobs/new?customer_id=${customerId}`);
  };

  // Shared chassis — matches the adjacent Phase 27 grids so the
  // three-row stack reads as one block.
  const chassisStyle = {
    backgroundColor: CD_FINANCIAL_NEUTRAL_BG,
    border: `1px solid ${CD_DARK_CARD_BORDER}`,
  };

  if (loading) {
    return (
      <div
        className={`${CD_TILE_CLASSES} mb-4`}
        style={chassisStyle}
        data-testid="cd-next-service-tile"
        data-state="loading"
      >
        <div
          className="flex items-center gap-1.5"
          style={{ color: CD_FINANCIAL_NEUTRAL_LABEL }}
        >
          <Clock size={13} />
          <span className="text-xs font-semibold uppercase tracking-wide">
            Next Service
          </span>
        </div>
        <div className="text-sm mt-2" style={{ color: "#F1F5F9" }}>
          Loading…
        </div>
      </div>
    );
  }

  if (!job) {
    return (
      <div
        className={`${CD_TILE_CLASSES} mb-4`}
        style={chassisStyle}
        data-testid="cd-next-service-tile"
        data-state="empty"
      >
        <div
          className="flex items-center gap-1.5"
          style={{ color: CD_FINANCIAL_NEUTRAL_LABEL }}
        >
          <Clock size={13} />
          <span className="text-xs font-semibold uppercase tracking-wide">
            Next Service
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 mt-2">
          <div
            className="text-sm"
            style={{ color: "#F1F5F9" }}
            data-testid="cd-next-service-empty"
          >
            No upcoming services
          </div>
          <Button
            variant="ghost"
            onClick={onScheduleCta}
            testid="cd-next-service-schedule-cta"
          >
            Schedule a job
          </Button>
        </div>
      </div>
    );
  }

  const title = job.service_type || job.title || "Service visit";
  const techName = job.technician_name || null;

  return (
    <button
      type="button"
      onClick={onCardClick}
      className={`${CD_TILE_CLASSES} mb-4 w-full`}
      style={chassisStyle}
      data-testid="cd-next-service-tile"
      data-state="has-job"
    >
      <div
        className="flex items-center gap-1.5"
        style={{ color: CD_FINANCIAL_NEUTRAL_LABEL }}
      >
        <Clock size={13} />
        <span className="text-xs font-semibold uppercase tracking-wide">
          Next Service
        </span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 mt-2">
        <div className="flex-1 min-w-0">
          <div
            className="text-base md:text-lg font-semibold truncate"
            style={{ color: "#F1F5F9" }}
            data-testid="cd-next-service-date"
          >
            {formatted || "—"}
          </div>
          <div
            className="text-sm truncate"
            style={{ color: "#F1F5F9" }}
            data-testid="cd-next-service-service-type"
          >
            {title}
          </div>
          {techName ? (
            <div
              className="text-xs mt-0.5 truncate"
              style={{ color: CD_FINANCIAL_NEUTRAL_LABEL }}
              data-testid="cd-next-service-tech"
            >
              {techName}
            </div>
          ) : null}
        </div>
        <div
          className="shrink-0"
          data-testid="cd-next-service-status-pill"
        >
          <StatusPill status={job.status} />
        </div>
      </div>
    </button>
  );
}




// Phase 27 · Feb-2026 — six-tile KPI grid rendered immediately
// below the Phase-20 command-strip tabs row.  Fields consumed:
//   balance_due_cents | past_due_cents | credit_cents
//   overdue_count     | pending_estimates_count
//   unread_messages_count
// Null kpi (pre-load) renders tiles with "—" placeholders so the
// grid lays out stable while the fetch resolves.
function KPITileGrid({ kpi, testidPrefix = "cd" }) {
  const balanceDueCents = Number(kpi?.balance_due_cents || 0);
  const pastDueCents    = Number(kpi?.past_due_cents || 0);
  const creditCents     = Number(kpi?.credit_cents || 0);
  const overdueCount    = Number(kpi?.overdue_count || 0);
  const pendingEstCount = Number(kpi?.pending_estimates_count || 0);
  const unreadMsgCount  = Number(kpi?.unread_messages_count || 0);
  const loaded = kpi !== null && kpi !== undefined;

  const tiles = [
    {k: "balance-due",  label: "Balance Due",       icon: Receipt,
     value: loaded ? _fmtMoney(balanceDueCents) : "—",
     bgColor: undefined},
    {k: "past-due",     label: "Past Due",          icon: AlertCircle,
     value: loaded ? _fmtMoney(pastDueCents) : "—",
     bgColor: pastDueCents > 0 ? CD_DANGER_BG : undefined},
    {k: "credit",       label: "Credit",            icon: Wallet,
     value: loaded ? _fmtMoney(creditCents) : "—",
     bgColor: creditCents > 0 ? CD_SUCCESS_BG : undefined},
    {k: "overdue",      label: "Overdue",           icon: Clock,
     value: loaded ? String(overdueCount) : "—",
     bgColor: overdueCount > 0 ? CD_DANGER_BG : undefined},
    {k: "pending-est",  label: "Pending Estimates", icon: FileText,
     value: loaded ? String(pendingEstCount) : "—",
     bgColor: undefined},
    {k: "unread-msgs",  label: "Unread Messages",   icon: MessageSquare,
     value: loaded ? String(unreadMsgCount) : "—",
     bgColor: undefined},
  ];

  return (
    <div
      className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 mb-4"
      data-testid={`${testidPrefix}-kpi-tile-grid`}
    >
      {tiles.map((t) => {
        const Icon = t.icon;
        const hasDynamicBg = Boolean(t.bgColor);
        // Phase 38 · Feb-2026 — on the Phase-24 dynamic flip (red /
        // emerald), labels stay pure-white per the Phase-27 lock.
        // On the Phase-38 teal neutral bg, slate-300 holds the
        // ≥4.5:1 "muted secondary" contrast tier (the pre-P38
        // slate-400 drops to 2.4:1 on teal and would fail WCAG).
        const labelColor = hasDynamicBg
          ? "#FFFFFF"
          : CD_FINANCIAL_NEUTRAL_LABEL;
        const valueColor = hasDynamicBg ? "#FFFFFF" : "#F1F5F9";
        return (
          <div
            key={t.k}
            className={CD_TILE_CLASSES}
            style={{
              // Phase 38 · Feb-2026 — KPI neutral bg flips to the
              // teal grouping color; chassis border untouched so
              // the dynamic Past-Due / Credit / Overdue overrides
              // (via ``t.bgColor``) continue to layer on top.
              backgroundColor: CD_FINANCIAL_NEUTRAL_BG,
              border: `1px solid ${CD_DARK_CARD_BORDER}`,
              ...(t.bgColor ? {backgroundColor: t.bgColor} : {}),
            }}
            data-testid={`${testidPrefix}-kpi-tile-${t.k}`}
            data-auto-bg={hasDynamicBg ? "true" : undefined}
          >
            <div className="flex items-center gap-1.5" style={{color: labelColor}}>
              <Icon size={13} />
              <span className="text-xs font-semibold uppercase tracking-wide">{t.label}</span>
            </div>
            <div
              className="text-xl md:text-2xl font-bold mt-1 truncate"
              style={{color: valueColor}}
              data-testid={`${testidPrefix}-kpi-tile-${t.k}-value`}
            >
              {t.value}
            </div>
          </div>
        );
      })}
    </div>
  );
}


// Phase 27 · Feb-2026 — Quick Actions tile grid.  Each tile is a
// clickable button that calls ``setTab(k)`` to switch the admin
// profile's tab-body — the SAME code path the Phase-20 preserved
// ResponsiveTabs dropdown drives — so every destination +
// deep-link param is byte-for-byte preserved.  Hover glow mirrors
// Phase 24's ActionTile pattern exactly.
function QuickActionTileGrid({ tabs, active, onPick, testidPrefix = "cd-quick-action" }) {
  return (
    <div
      className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 mb-4"
      data-testid={`${testidPrefix}-grid`}
    >
      {tabs.map((t, i) => {
        const Icon = t.icon;
        const isActive = active === t.k;
        // Phase 38 · Feb-2026 — rotate the icon tint across the 17
        // tiles for visual grouping. Phase 27 pins the BORDER
        // expression (``isActive ? "#4F46E5" : CD_DARK_CARD_BORDER``)
        // byte-for-byte; the accent lives on the icon-only path per
        // the brief's "colored left border OR icon accent" clause.
        // Active tile keeps the full slate icon (same as pre-P38)
        // so the ``#4F46E5`` indigo border reads as the dominant
        // active-tile signal without a competing icon color.
        const iconColor = isActive
          ? "#94A3B8"
          : CD_ICON_ACCENTS[i % CD_ICON_ACCENTS.length];
        return (
          <button
            key={t.k}
            type="button"
            onClick={() => onPick(t.k)}
            className={CD_ACTION_TILE_CLASSES}
            style={{
              // Phase 38 · Feb-2026 — nav-tile bg flips to a slightly
              // lighter navy so the tile grid visually separates
              // from the page shell (CD_DARK_CARD_BG) while staying
              // high-contrast (17.4:1 vs white text).
              backgroundColor: isActive ? "#0a0940" : CD_NAV_TILE_BG,
              border: `1px solid ${isActive ? "#4F46E5" : CD_DARK_CARD_BORDER}`,
              color: "#F1F5F9",
            }}
            data-testid={`${testidPrefix}-${t.k}`}
            data-active={isActive ? "true" : undefined}
            aria-pressed={isActive ? "true" : "false"}
          >
            <div className="flex items-center gap-2">
              <Icon size={16} style={{color: iconColor}} />
              <span className="text-sm font-semibold">{t.label}</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}


const TABS = [
  { k: "overview", label: "Overview", icon: MapPin },
  { k: "properties", label: "Properties", icon: Home },
  { k: "jobs", label: "Jobs", icon: Briefcase },
  { k: "measurements", label: "Measurements", icon: Ruler, roles: ["admin", "super_admin", "manager"] },
  // Feb-2026 · C5 · Chemical History tab lives adjacent to Measurements
  // since both are field-service record surfaces gated to admin +
  // super_admin + manager. Techs record sprays from the mobile app;
  // customers never see the tab.
  { k: "chemical_history", label: "Chemical History", icon: FlaskConical, roles: CHEMICAL_HISTORY_TAB_ROLES },
  { k: "documents", label: "Documents", icon: FileText },
  { k: "quotes", label: "Quotes", icon: FileText },
  { k: "invoices", label: "Invoices", icon: FileText },
  { k: "equipment", label: "Equipment", icon: Beaker },
  { k: "warranties", label: "Warranties", icon: ShieldCheck },
  { k: "tasks", label: "Tasks", icon: ListChecks },
  { k: "notes", label: "Notes", icon: StickyNote },
  { k: "credits", label: "Credits", icon: DollarSign },
  { k: "payments", label: "Payments", icon: DollarSign },
  { k: "subscriptions", label: "Subscriptions", icon: DollarSign },
  { k: "reviews", label: "Reviews", icon: Star },
  { k: "portal", label: "Portal Access", icon: KeyRound },
];


// Feb-2026 · Customer profile — primary-property address line under
// the name. "Primary" = the property flagged ``is_primary`` on the
// property doc; if none flagged, fall back to the first property in
// the API-returned list (backend sorts by ``sort_order`` asc). The
// backend lazily backfills a single "Main" property from a legacy
// customer's address on first read, so this covers legacy rows too.
export function getPrimaryPropertyAddress(properties) {
  if (!Array.isArray(properties) || properties.length === 0) return null;
  const flagged = properties.find(
    (p) => p && (p.is_primary === true || p.primary === true),
  );
  const chosen = flagged || properties[0];
  const addr = (chosen && chosen.address) || {};
  const line1 = (addr.line1 || addr.address_line1 || "").trim();
  const city = (addr.city || "").trim();
  const state = (addr.state || "").trim();
  const postal = (addr.postal_code || addr.zip || "").trim();
  if (!line1 && !city && !state && !postal) return null;
  const cityStateZip = [
    city,
    [state, postal].filter(Boolean).join(" ").trim(),
  ].filter(Boolean).join(", ");
  const oneLine = [line1, cityStateZip].filter(Boolean).join(", ");
  return oneLine || null;
}


export default function CustomerDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user: authUser } = useAuth();
  const [customer, setCustomer] = useState(null);
  const [jobs, setJobs] = useState([]);
  // Phase P37 · Feb-2026 — CustomerDetail jobs history pagination +
  // virtualization. On profiles with 900+ jobs the browser was
  // jank-rendering every row on first paint AND transporting the
  // full array over the wire. New shape:
  //   • Fetch the first ``_P37_JOBS_PAGE`` (50) via
  //     ``GET /jobs?customer_id=&limit=50&offset=0&sort=scheduled_date_desc``.
  //   • ``Load more`` button appends the next 50 via a follow-up
  //     fetch (``offset = jobs.length``).
  //   • The rendered list itself is windowed via ``react-window``'s
  //     ``<List>`` so even 900 accumulated rows only paint the
  //     visible ~10 + overscan.
  //
  // Sort switched to DESC (most-recent first) — matches the P37
  // brief. The default endpoint sort (ASC) is preserved for every
  // other caller.
  const _P37_JOBS_PAGE = 50;
  const [jobsLoadingMore, setJobsLoadingMore] = useState(false);
  const [jobsHasMore, setJobsHasMore] = useState(false);
  // Phase 9d · Feb-2026 — lightweight counts snapshot fetched
  // alongside the slim profile load. Shape documented at
  // ``GET /api/customers/{cid}/summary``. Null until first load
  // resolves (and remains null if the fetch errors — tab badges
  // just render without a count in that case).
  const [summary, setSummary] = useState(null);
  // Feb-2026 · Customer profile — primary-property address line under
  // the name (see the header render). Fetched alongside customer +
  // jobs so the address can appear in the first paint.
  const [properties, setProperties] = useState([]);
  const [tab, _setTab] = useState("overview");
  // Phase J1 · Feb-2026 — URL round-trip on the tab dropdown so a
  // deep-link like ``/customers/:id?tab=jobs`` restores state on
  // mount and every selection updates the query string in place.
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const q = searchParams.get("tab");
    if (q && q !== tab) _setTab(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const setTab = (next) => {
    _setTab(next);
    const params = new URLSearchParams(searchParams);
    if (next && next !== "overview") params.set("tab", next);
    else params.delete("tab");
    setSearchParams(params, { replace: true });
  };
  // Feb-2026 · M2 · role-scoped tab visibility.  Every legacy tab
  // stays visible to every role (server-side gate on the page
  // owner does the real enforcement); tabs that declare a
  // ``roles: [...]`` array are gated to those roles only.
  // Currently that only affects the Measurements tab, which is
  // hidden for technician + customer per the M2 ruling.
  const visibleTabs = useMemo(
    () => filterCustomerTabs(TABS, authUser?.role),
    [authUser?.role],
  );
  const [toast, setToast] = useState(null);
  // Phase 27 · Feb-2026 — admin KPI tile grid state.  Lightweight
  // best-effort fetch from ``GET /customers/{id}/kpi-summary`` —
  // non-fatal when the call fails (grid still renders with zeros).
  const [kpi, setKpi] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // HARD-DELETE · HD-B · Feb-2026 — "Move to Trash" flow uses the
  // HD-A endpoints in a shared modal. Coexists with the legacy
  // ``confirmDelete`` mode-aware DELETE surface above.
  const [hardDeleteOpen, setHardDeleteOpen] = useState(false);
  // Phase M1 · Feb-2026 — Merge Wizard modal open/close.
  const [mergeOpen, setMergeOpen] = useState(false);
  // Feb-2026 · Customer Delete UX overhaul — which mode is currently
  // in flight from the modal. null = idle, "soft" | "hard" = busy.
  const [deleteBusyMode, setDeleteBusyMode] = useState(null);
  const [loginModal, setLoginModal] = useState(false);
  const [vipModal, setVipModal] = useState(false);
  const [sendModal, setSendModal] = useState(null); // { channel, to }
  // Task 6 · Feb 2026 — "Send service records link" modal state.
  const [srLinkOpen, setSrLinkOpen] = useState(false);
  const [taskQuickAddOpener, setTaskQuickAddOpener] = useState(null);
  // Phase 12 · Feb 2026 — role + tenant default fetched once for the
  // card-on-file admin controls. Techs never see the toggle at all.
  const [meRole, setMeRole] = useState("");
  const [tenantDefault, setTenantDefault] = useState(true);

  // Phase K2 · Feb-2026 — publish the customer's display name to
  // the breadcrumbs shell so the current-page crumb reads the
  // person's actual name instead of the generic "Customer".  The
  // hook returns nothing but registers/deregisters on mount +
  // unmount so navigating between customers doesn't leak names.
  const _crumbLabel = customer
    ? (customer.display_name
        || [customer.first_name, customer.last_name].filter(Boolean).join(" ")
        || customer.email
        || "Customer")
    : null;
  useSetDynamicCrumb("customer", _crumbLabel);

  useEffect(() => {
    (async () => {
      try {
        const [me, t] = await Promise.all([
          api.get("/auth/me"),
          api.get("/tenants/current"),
        ]);
        setMeRole(me?.role || "");
        setTenantDefault(
          t?.require_card_on_file_default !== false,
        );
      } catch { /* silent — falls back to hidden UI */ }
    })();
  }, []);
  const canSeeCardControls =
    meRole === "admin" || meRole === "manager" || meRole === "super_admin";

  // CUSTOMER-PROFILE-ACTION-BAR · Feb-2026 — Issue Credit shortcut
  // on the top navy action strip.  Visible to the four privileged
  // roles that the backend ``_require_credit_adjuster`` dep
  // accepts (admin / super_admin / manager / owner).  The modal
  // state + the balance it previews live on this component so the
  // existing ``AdjustDialog`` can be reused verbatim from
  // ``CustomerCreditsPage.jsx`` (no fork, no new positive-only
  // variant — see CUSTOMER-PROFILE-ACTION-BAR brief gate 4ii).
  const canIssueCredit = ["admin", "super_admin", "manager", "owner"]
    .includes((meRole || "").toLowerCase());
  const [issueCreditOpen, setIssueCreditOpen] = useState(false);
  const [issueCreditBalanceCents, setIssueCreditBalanceCents] = useState(0);
  // CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — Account
  // Correction toggle.  Same role gate as Issue Credit above
  // (``require_admin_or_manager`` on the backend).  The modal
  // collects an optional ``note`` on toggle-ON per G4.  State is
  // local — refetches ``customer`` on success so the inline chip
  // + badge reflect immediately.
  const canToggleAccountCorrection = canIssueCredit;
  const [accountCorrectionOpen, setAccountCorrectionOpen] = useState(false);
  const [accountCorrectionNote, setAccountCorrectionNote] = useState("");
  const [accountCorrectionBusy, setAccountCorrectionBusy] = useState(false);
  const openIssueCreditModal = async () => {
    // Fetch the current ledger balance so the modal's live-preview
    // ("will change the balance from X to Y") shows a correct
    // starting value.  Guarded with try/catch so a transient
    // credits-service error still opens the modal (preview will
    // show "$0.00 → delta" which the backend floor-check will
    // still reject if the real balance can't absorb it).
    try {
      const r = await api.get(`/customers/${id}/credits`);
      setIssueCreditBalanceCents(Number(r?.balance_cents) || 0);
    } catch {
      setIssueCreditBalanceCents(0);
    }
    setIssueCreditOpen(true);
  };

  const load = async () => {
    try {
      // Phase F3.5 · Feb-2026 — sub-3s customer profile.
      //   • Fetch only THIS customer's jobs via the new `customer_id`
      //     filter instead of the tenant-wide `/jobs` mega-fetch that
      //     used to force every profile open to transport the entire
      //     tenant's job list.
      //   • Cuts payload from "whole tenant" (MB in prod) to a single
      //     customer's history (KB) and eliminates the client-side
      //     `.filter(j.customer_id === id)` altogether.
      // Phase P37 · Feb-2026 — server-side jobs pagination (DESC).
      // Fetches ``_P37_JOBS_PAGE`` (50) rows at a time so a
      // customer with 900+ jobs no longer transports the full
      // history on first paint. See ``jobsHasMore`` + the
      // ``Load more`` button below.
      const [c, myJobs, props, summary, kpiSummary] = await Promise.all([
        api.get(`/customers/${id}?slim=1`),
        api.get(
          `/jobs?customer_id=${encodeURIComponent(id)}`
          + `&limit=${_P37_JOBS_PAGE}&offset=0`
          + `&sort=scheduled_date_desc`,
        ),
        // Feb-2026 · Customer profile — properties fetched for the
        // primary-address line under the customer name. Non-fatal:
        // if the call fails we still render the rest of the page and
        // just show "No address on file".
        api.get(`/customers/${id}/properties`).catch(() => []),
        // Phase 9d · Feb-2026 — lightweight counts snapshot for
        // tab-badges / overview summary panels. Non-fatal — if the
        // call fails we fall back to zero-badges (the lazy per-tab
        // fetch still populates its own count on open).
        api.get(`/customers/${id}/summary`).catch(() => null),
        // Phase 27 · Feb-2026 — six-field KPI tile grid data
        // (balance_due_cents / past_due_cents / credit_cents /
        // overdue_count / pending_estimates_count /
        // unread_messages_count).  Non-fatal — tiles render with
        // zeros on error.
        api.get(`/customers/${id}/kpi-summary`).catch(() => null),
      ]);
      setCustomer(c);
      const firstPage = Array.isArray(myJobs) ? myJobs : [];
      setJobs(firstPage);
      // If we got a full page back, there's likely more. This is a
      // truthy heuristic — the follow-up fetch handles the empty
      // case + flips ``jobsHasMore`` to false when we hit the tail.
      setJobsHasMore(firstPage.length >= _P37_JOBS_PAGE);
      setProperties(Array.isArray(props) ? props : []);
      setSummary(summary && typeof summary === "object" ? summary : null);
      setKpi(kpiSummary && typeof kpiSummary === "object" ? kpiSummary : null);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Phase P37 · Feb-2026 — Load-more handler. Fetches the next
  // ``_P37_JOBS_PAGE`` (50) jobs at ``offset = jobs.length`` and
  // appends. Guards against double-click via ``jobsLoadingMore``
  // and flips ``jobsHasMore`` to false when we get a partial page
  // (or empty) back, so the button hides at the tail.
  const loadMoreJobs = useCallback(async () => {
    if (jobsLoadingMore || !jobsHasMore) return;
    setJobsLoadingMore(true);
    try {
      const next = await api.get(
        `/jobs?customer_id=${encodeURIComponent(id)}`
        + `&limit=${_P37_JOBS_PAGE}&offset=${jobs.length}`
        + `&sort=scheduled_date_desc`,
      );
      const chunk = Array.isArray(next) ? next : [];
      if (chunk.length === 0) {
        setJobsHasMore(false);
      } else {
        setJobs((prev) => [...(prev || []), ...chunk]);
        setJobsHasMore(chunk.length >= _P37_JOBS_PAGE);
      }
    } catch (e) {
      setToast({ tone: "error",
                    message: `Load more failed: ${e.message}` });
    } finally {
      setJobsLoadingMore(false);
    }
  }, [id, jobs.length, jobsHasMore, jobsLoadingMore]);

  const doDelete = async (mode) => {
    // Feb-2026 · Customer Delete UX overhaul — mode-aware delete.
    // Backend defaults to "soft" if no ?mode is passed, but we
    // always pass the mode explicitly for observability + so the
    // audit-log ``event`` is unambiguous.
    if (deleteBusyMode) return;                    // guard double-click
    setDeleteBusyMode(mode);
    try {
      const res = await api.del(`/customers/${id}?mode=${mode}`);
      const verb = mode === "hard" ? "permanently deleted" : "soft-deleted";
      setToast({
        tone: "success",
        message: res?.already_deleted
          ? "Customer was already soft-deleted"
          : `Customer ${verb}`,
      });
      setConfirmDelete(false);
      setTimeout(() => navigate("/customers"), 500);
    } catch (e) {
      // 409 unpaid-invoice branch — surface a helpful description
      // with the count and (optionally) the first few invoice ids
      // so the toast is directly actionable.
      const detail = e?.data?.detail;
      const isDict = detail && typeof detail === "object";
      if (
        mode === "hard" &&
        e?.status === 409 &&
        isDict &&
        detail.detail === "customer_has_unpaid_invoices"
      ) {
        const n = detail.invoice_count ?? "some";
        setToast({
          tone: "error",
          message:
            `Cannot hard-delete: ${n} unpaid invoice(s). ` +
            "Resolve them or use Soft Delete instead.",
        });
      } else {
        setToast({ tone: "error", message: e.message });
      }
    } finally {
      setDeleteBusyMode(null);
    }
  };

  // Phase P37 · Feb-2026 — stable ``reopenJob`` reference so the
  // memoized ``<JobHistoryRow />`` doesn't invalidate its equality
  // check every time the parent re-renders (e.g. on tab switch or
  // toast dismiss). ``load`` is closed-over but is itself stable
  // enough for this use — it references ``id`` from ``useParams``.
  const reopenJob = useCallback(async (jid) => {
    try {
      await api.post(`/jobs/${jid}/reopen`);
      setToast({ tone: "success", message: "Job reopened" });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleVip = async (isVip, note) => {
    try {
      const doc = await api.patch(`/customers/${id}/vip`, {
        is_vip: isVip,
        vip_note: note ?? customer?.vip_note ?? null,
      });
      setCustomer((c) => ({ ...c, ...doc }));
      setToast({
        tone: "success",
        message: isVip ? "Flagged as VIP" : "Removed VIP flag",
      });
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const openSendModal = (payload) => setSendModal(payload);

  const openQuickTaskFromDropdown = () => {
    setTab("tasks");
    setTimeout(() => {
      if (typeof taskQuickAddOpener === "function") taskQuickAddOpener();
    }, 100);
  };

  if (!customer) {
    // ───────────────────────────────────────────────────────────
    // Phase 22 · Feb-2026 — Customer profile skeleton loader.
    //
    // Replaces the pre-Phase-22 single thin ``<Skeleton
    // height={160}>`` bar that read as a blank white page. The
    // new skeleton mirrors the final layout 1:1 so there is zero
    // layout shift when the slim fetch resolves and the real
    // tree takes over:
    //
    //   * Outer wrapper matches ``max-w-5xl mx-auto px-4
    //     sm:px-6 lg:px-8 py-6`` (same as the real tree).
    //   * Back-button row placeholder.
    //   * Portal access tile row placeholder (2 tiles).
    //   * Action row placeholder — matches Phase 20's
    //     ``cd-command-strip`` chrome + 7 button widths.
    //   * Tabs row placeholder — matches Phase 20's
    //     ``cd-command-strip-tabs`` chrome + 3 button widths.
    //   * Header card placeholder — avatar circle + name bar +
    //     address line + badge chips.
    //   * Content area — three stacked content tile placeholders.
    //
    // The skeleton swaps out as soon as the slim profile fetch
    // (``load()``) resolves — ``setCustomer(c)`` flips this
    // branch and the full tree renders. No minimum render time,
    // zero intentional flicker. Fast loads (<50ms) flip
    // instantly; slow loads keep the skeleton visible with no
    // fallback to a blank page.
    //
    // Nav chrome preserved for Phase 20 regression lock — the
    // skeleton still has an outer ``max-w-5xl`` wrapper and the
    // ``animate-pulse`` affordance makes the skeleton read as
    // "loading" rather than "broken".
    // ───────────────────────────────────────────────────────────
    const skelBar = (w, h = "h-4") => (
      <div
        className={`${h} ${w} rounded animate-pulse`}
        style={{ backgroundColor: colors.surfaceTertiary }}
      />
    );
    const skelButton = (w) => (
      <div
        className={`h-7 ${w} rounded-md animate-pulse`}
        style={{ backgroundColor: "rgba(255,255,255,0.12)" }}
      />
    );
    const skelStripChrome = {
      backgroundColor: colors.nav.bg,
      border: `1px solid ${colors.nav.border}`,
    };
    return (
      <div
        className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
        style={{
          // Phase 27 · Feb-2026 — skeleton loader shares the admin
          // customer-profile dark-navy page bg so the hand-off from
          // skeleton → real content is seamless.
          backgroundColor: CD_DARK_CARD_BG,
          minHeight: "100vh",
        }}
        data-testid="customer-detail-skeleton"
      >
        {/* Back-button row — matches the real "All customers"
            back button's visual rhythm. */}
        <div className="flex items-center gap-2 mb-4">
          {skelBar("w-32", "h-4")}
        </div>
        {/* Portal access tile row placeholder — same mb-4 as
            the real top-action-stack. */}
        <div
          className="space-y-2 mb-4"
          data-testid="cd-skeleton-portal-stack"
        >
          <div
            className="h-14 rounded-xl animate-pulse w-full"
            style={{ backgroundColor: colors.surfaceTertiary }}
          />
          <div
            className="h-14 rounded-xl animate-pulse w-full"
            style={{ backgroundColor: colors.surfaceTertiary }}
          />
        </div>
        {/* Phase 20 action row — placeholder matches navy chrome
            + 7 button widths in the same source order
            (Edit / Merge / Credit / Correction / Call / Delete /
            Trash). Carries the Phase-22 skeleton row testid so
            tests can assert the shell is in the first paint. */}
        <div
          className="rounded-2xl mb-4 px-3 py-3"
          style={skelStripChrome}
          data-testid="cd-skeleton-action-strip"
        >
          <div
            className="flex flex-row flex-nowrap items-center gap-2 overflow-x-auto"
            data-testid="cd-skeleton-action-row"
          >
            {skelButton("w-14")}
            {skelButton("w-16")}
            {skelButton("w-24")}
            {skelButton("w-28")}
            {skelButton("w-12")}
            {skelButton("w-16")}
            {skelButton("w-28")}
          </div>
        </div>
        {/* Phase 20 tabs row — placeholder matches navy chrome
            + Send / Create / Overview button widths. */}
        <div
          className="rounded-2xl mb-4 px-3 py-3"
          style={skelStripChrome}
          data-testid="cd-skeleton-tabs-strip"
        >
          <div
            className="flex flex-row flex-nowrap items-center gap-2 overflow-x-auto"
            data-testid="cd-skeleton-tabs-row"
          >
            {skelButton("w-20")}
            {skelButton("w-20")}
            {skelButton("w-56")}
          </div>
        </div>
        {/* Header card placeholder — avatar + name + address +
            badge chips. Mirrors the identity card's visual mass
            so the skeleton reads as "the customer header" even
            before any data arrives. */}
        <div
          className="rounded-2xl p-5 mb-4"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="cd-skeleton-header-card"
        >
          <div className="flex items-start gap-4">
            <div
              className="w-16 h-16 rounded-full animate-pulse flex-shrink-0"
              style={{ backgroundColor: colors.surfaceTertiary }}
              data-testid="cd-skeleton-avatar"
            />
            <div className="flex-1 min-w-0 space-y-3">
              <div className="flex items-center gap-2">
                {skelBar("w-20", "h-5")}
                {skelBar("w-16", "h-5")}
                {skelBar("w-16", "h-5")}
              </div>
              {skelBar("w-48", "h-7")}
              {skelBar("w-64", "h-4")}
              <div className="flex items-center gap-2">
                {skelBar("w-16", "h-5")}
                {skelBar("w-20", "h-5")}
                {skelBar("w-14", "h-5")}
              </div>
            </div>
          </div>
        </div>
        {/* Main content area — three stacked content tiles so the
            viewport is filled below the fold. */}
        <div className="space-y-4" data-testid="cd-skeleton-content">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-32 rounded-2xl animate-pulse"
              style={{
                backgroundColor: colors.surface,
                border: `1px solid ${colors.border}`,
              }}
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div
      className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="customer-detail"
      style={{
        // Phase 27 · Feb-2026 — admin customer-profile dark-navy
        // page bg, matching Portal Home's chassis (``#03002e``)
        // so the KPI tile grid + Quick Actions tile grid rendered
        // below the command strip visually anchor the page.
        backgroundColor: CD_DARK_CARD_BG,
        minHeight: "100vh",
      }}
    >
      {/* Feb-2026 · Customer profile name relocation — the
          PageHeader-rendered H1 used to sit here above the "All
          customers" back button.  Moved into the identity card
          (below the customer-since / VIP / ACTIVE row, above the
          address line) so the name reads as part of the card
          identity rather than the page chrome.  Semantic H1
          preserved on the new inline element; the sr-only stub
          that lived inside the pill row was removed in the same
          diff. */}

      <button
        onClick={() => navigate("/customers")}
        className="flex items-center gap-1 text-sm font-semibold mb-4"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> All customers
      </button>

      {/* Header card */}
      {/* Feb-2026 · Customer profile typography bump — identity +
          contact block reads at 14px (text-sm) across ALL nested
          text.  Wrapper carries a Tailwind arbitrary variant
          ([&_.text-xs]:!text-sm) so descendants that render their
          own text-xs class inside shared components
          (CustomerGeocodeInfo, ActivationControl, Chip, etc.)
          scale up here without leaking the bump to those
          components' other consumers.  ``!important`` guarantees
          override regardless of utility source order.

          Phase 28 · Feb-2026 — repositioned to render ABOVE the
          Phase-20 command strip + Phase-27 KPI tile grid so the
          customer's identity is the first thing visible after
          the breadcrumb.  Chassis recoloured to Phase-27 dark-
          navy tokens (``#03002e`` bg, ``#1E293B`` border, light
          text) for visual coherence with the rest of the admin
          customer profile.  Phase-27 regression contract on the
          command strip + KPI tiles unchanged. */}
      <div
        className="rounded-2xl p-6 mb-4 [&_.text-xs]:!text-sm"
        style={{ backgroundColor: "#03002e", border: "1px solid #1E293B", color: "#F1F5F9" }}
        data-testid="cd-identity-header"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              {customer.customer_since ? (
                <span
                  data-testid="customer-since-label"
                  title={customer.customer_since}
                  className="text-xs font-medium px-2 py-1 rounded"
                  style={{ background: "#0a0940",
                              color: "rgba(255,255,255,0.85)" }}
                >
                  {`Customer since ${new Date(customer.customer_since)
                      .toLocaleDateString(undefined, {
                          month: "long", year: "numeric" })}`}
                </span>
              ) : null}
              {/* Feb-2026 Customer Detail Additions — VIP toggle button
                  replaces the previous read-only badge. Left-clicking the
                  star flips is_vip; the small edit affordance opens the
                  note modal. */}
              <button
                onClick={() => toggleVip(!customer.is_vip)}
                onDoubleClick={() => setVipModal(true)}
                title={customer.is_vip ? "Remove VIP flag (double-click to edit note)" : "Flag as VIP"}
                data-testid="customer-vip-toggle"
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold uppercase tracking-wider transition"
                style={{
                  backgroundColor: customer.is_vip ? "#FEF3C7" : colors.surfaceSecondary,
                  color: customer.is_vip ? "#92400E" : colors.muted,
                  border: `1px solid ${customer.is_vip ? "#F59E0B" : colors.border}`,
                }}
              >
                <Star
                  size={12}
                  fill={customer.is_vip ? "#F59E0B" : "transparent"}
                  color={customer.is_vip ? "#F59E0B" : colors.muted}
                />{" "}
                {customer.is_vip ? "VIP" : "Flag as VIP"}
              </button>
              {customer.is_active === false ? (
                <span
                  className="hidden"
                  aria-hidden="true"
                  data-testid="customer-inactive-badge"
                >
                  Inactive
                </span>
              ) : null}
              {/* P2 #6 · Feb-2026 — Service Category dropdown. Admin-
                  only edit affordance; PATCH /customers/{cid}/service-
                  category.  Values "pool"/"landscaping"/"both" + the
                  "Not set" clear option.  Toast on success/error. */}
              <ServiceCategoryControl
                customer={customer}
                onOptimisticSet={(next) =>
                  setCustomer((c) => ({ ...c, service_category: next }))
                }
              />
              <ActivationControl
                customer={customer}
                onOptimisticFlip={(next) => setCustomer((c) => ({ ...c, is_active: next }))}
                onSuccess={(updated) => {
                  setCustomer(updated);
                  setToast({
                    tone: "success",
                    message: updated.is_active === false
                      ? `${updated.name} marked inactive`
                      : `${updated.name} reactivated`,
                  });
                }}
                onError={(msg) => setToast({ tone: "error", message: msg })}
              />
            </div>
            {/* Feb-2026 · Customer name relocated INTO the identity
                card (was rendered at page-chrome level via
                PageHeader).  Sits directly above the address line
                so the name + property + geocode read as one
                cohesive identity block.  H1 semantic preserved
                per accessibility (screen readers key off page
                landmarks); text-2xl matches the sibling
                cd-customer-name-secondary echo inside the
                Overview tab body for visual continuity. */}
            <h1
              className="text-2xl font-bold mt-3 mb-1"
              style={{ color: "#F1F5F9" }}
              data-testid="customer-detail-inline-h1"
            >
              {customer.name}
            </h1>
            {/* Feb-2026 · Customer profile — primary-property address
                line under the name. Clickable → Google Maps
                directions in a new tab. Falls back to a muted
                "No address on file" when the customer has no
                usable property address. Long addresses truncate
                with ellipsis; ``title`` reveals the full string
                on hover. */}
            {(() => {
              const oneLine = getPrimaryPropertyAddress(properties);
              if (!oneLine) {
                return (
                  <div
                    className="flex items-center gap-1.5 mt-2 text-sm truncate max-w-xl"
                    style={{ color: "rgba(255,255,255,0.85)" }}
                    data-testid="customer-primary-address"
                    title="No address on file"
                  >
                    <MapPin size={14} />
                    <span
                      className="truncate"
                      data-testid="customer-primary-address-empty"
                    >
                      No address on file
                    </span>
                  </div>
                );
              }
              const href = "https://www.google.com/maps/dir/?api=1&destination="
                + encodeURIComponent(oneLine);
              return (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Navigate to ${oneLine}`}
                  title={oneLine}
                  className="inline-flex items-center gap-1.5 mt-2 text-sm hover:underline truncate max-w-xl"
                  style={{ color: "rgba(255,255,255,0.85)" }}
                  data-testid="customer-primary-address"
                >
                  <MapPin size={14} />
                  <span
                    className="truncate"
                    data-testid="customer-primary-address-text"
                  >
                    {oneLine}
                  </span>
                </a>
              );
            })()}
            {/* Feb-2026 · Customer profile — geocode observability line.
                Reads customer.latitude / longitude / geocoded_at from
                the already-Phase-17-populated fields. Non-admin roles
                see the line but NOT the "Re-geocode" button. See
                /app/memory/FEATURE_CUSTOMER_MANUAL_REGEOCODE_UI.md. */}
            <CustomerGeocodeInfo
              customer={customer}
              role={meRole}
              onRefetch={load}
              onToast={setToast}
            />
            <div className="flex items-center gap-2 mt-2 flex-wrap">
              {/* Phase 15b · Feb-2026 — inline tag picker with a
                  "+ Add new tag" affordance in the dropdown. Server
                  RBAC allows admin + manager writes; other roles will
                  see the trigger but the PATCH will 403 (parent could
                  hide via readOnly, but leaving the discovery affordance
                  in place is intentional). */}
              <CustomerTagPicker
                customerId={customer.id}
                value={customer.tags || []}
                onChange={(nextTags) =>
                  setCustomer((c) => c ? { ...c, tags: nextTags } : c)
                }
              />
              {customer.waitlisted ? <Chip label="Waitlist" tone="warning" /> : null}
              {customer.has_login ? <Chip label="Portal enabled" tone="success" /> : null}
              {/* Queue Item 4 · Feb-2026 — outbound-comms whitelist
                  toggle. Flipping this changes whether Resend + RC
                  send outbound comms to this customer. Hard-confirm
                  modal is built into the component. */}
              <DemoAccountToggle
                recordType="customer"
                recordId={customer.id}
                isDemo={!!customer.is_demo_account}
                recordLabel={customer.name || "this customer"}
                size="sm"
                onChange={(nextVal) =>
                  setCustomer((c) => c ? { ...c, is_demo_account: nextVal } : c)
                }
              />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
          {[
            {
              icon: Phone,
              label: (customer.mobiles || []).length > 1 ? "Mobiles" : "Phone",
              value:
                (customer.mobiles || []).length > 0
                  ? (customer.mobiles || [])
                      .map((m) => `${m.number_e164}${m.label ? ` (${m.label})` : ""}`)
                      .join("  ·  ")
                  : (customer.phone
                      ? <PhoneLink phone={customer.phone} />
                      : null),
              testid: "customer-mobiles-display",
            },
            {
              icon: Mail,
              label: (customer.emails || []).length > 1 ? "Emails" : "Email",
              value:
                (customer.emails || []).length > 0
                  ? (customer.emails || [])
                      .map((e) => `${e.address}${e.label ? ` (${e.label})` : ""}`)
                      .join("  ·  ")
                  : customer.email,
              testid: "customer-emails-display",
            },
            {
              icon: Droplets,
              label: "Pool",
              value:
                customer.pool_gallons != null
                  ? `${Number(customer.pool_gallons).toLocaleString()} gal`
                  : "— (not set)",
              testid: "customer-pool-gallons-display",
            },
            /* APR-III · Feb-2026 — ``Alert phone`` + ``Alert email``
               stat tiles removed (fields dropped from CustomerIn in
               APR-II).  Primary phone + email tiles above remain
               the single contact channels. */
            /* CP-1-B · Feb-2026 (updated by GCR · Feb-2026) —
             * Gate code lives in the top stat-tile row and NOWHERE
             * else on the Overview tab.  The CP-1-B shim that kept
             * a duplicate ``<Info>`` inside ``cd-address-block``
             * was removed in the GCR atomic.  Unconditional render
             * for every role; the shared ``{c.value || "—"}``
             * fallback in the loop below surfaces an em-dash when
             * ``customer.gate_code`` is null / undefined / empty
             * string.  No role guard — gate codes are visible to
             * anyone with access to the customer profile. */
            {
              icon: KeyRound,
              label: "Gate code",
              value: customer.gate_code,
              testid: "cd-stat-gate-code",
            },
          ].map((c) => (
            <div
              key={c.label}
              className="rounded-xl p-3"
              style={{
                // Phase 28 · Feb-2026 — stat-tile inner-bg uses a
                // slightly lighter navy (``#0a0940``) for depth
                // against the ``#03002e`` identity-card chassis.
                backgroundColor: "#0a0940",
                border: "1px solid #1E293B",
              }}
              data-testid={c.testid}
            >
              <div className="flex items-center gap-1.5 text-xs mb-1" style={{ color: c.warn ? "#FCD34D" : "rgba(255,255,255,0.7)" }}>
                <c.icon size={12} />
                <span className="uppercase font-semibold">{c.label}</span>
              </div>
              <div className="text-sm font-semibold truncate" style={{ color: "#F1F5F9" }}>
                {c.value || "—"}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Feb-2026 · Top action stack — Card-on-file trigger (line 1)
          + Portal invite (line 2) sit together at the top of the
          admin customer detail so the two most-used contact actions
          share one visual rhythm. Both children still return
          ``null`` (Banner) or ``disabled`` (Invite) when the
          customer state doesn't warrant them; the wrapper collapses
          gracefully. Layout only — test-ids + click handlers
          unchanged. Admin/manager only (techs never see this). */}
      {canSeeCardControls && (
        <div
          className="space-y-2 mb-4"
          data-testid="customer-detail-top-action-stack"
        >
          <CardOnFileWarningBanner
            customer={customer}
            onSent={(msg) => setToast({ tone: "success", message: msg })}
            onError={(msg) => setToast({ tone: "error", message: msg })}
          />
          <PortalInviteQuickAction
            customer={customer}
            onToast={(t) => setToast(t)}
          />
        </div>
      )}

      {/* Feb-2026 · Unified navy command strip — Phase 2 (single row).
          Consolidates Send / Create / Overview / Edit / Merge /
          Issue Credit / Mark Correction / Call / Delete / Move to
          Trash into ONE horizontal navy row.  Below ``md:`` the
          Edit / Merge / Credit / Correction / Delete / Trash set
          collapses into a kebab (``cd-mobile-kebab-trigger``) so
          Send / Create / Overview / Call remain reachable without
          the strip overflowing.  All handlers, testids, role
          gates, and modals are preserved byte-for-byte — this is
          a layout + styling move only.  Role filtering on the
          kebab items mirrors the inline buttons' role gates so
          there is zero behavioural drift between surfaces.

          Shared className constants (``NAVY_*``) replace the
          repeated inline ``className="px-2.5 py-1 text-xs …"`` +
          ``style={{ ... }}`` blocks that caused the pre-fix
          inconsistency.  Each variant maps to a single color
          intention (outline / danger / warn) so a future palette
          tweak only touches ONE place. */}
      {(() => {
        const BTN_BASE =
          "px-2.5 py-1 text-xs whitespace-nowrap";
        const NAVY_OUTLINE =
          "hover:!bg-white/10 focus:!ring-2 focus:!ring-white/40";
        const NAVY_DANGER =
          "hover:!bg-red-400/25 focus:!ring-2 focus:!ring-red-300/60";
        const NAVY_WARN =
          "hover:!bg-orange-400/25 focus:!ring-2 focus:!ring-orange-300/60";
        const navyOutlineStyle = {
          // Phase 38 · Feb-2026 — Edit / Merge / Issue Credit /
          // Mark Correction buttons flip from a transparent-outline
          // treatment to a solid medium-steel-blue (slate-700)
          // with a slate-500 border, matching the user's "visual
          // grouping on dark navy" spec. Call / Delete / Hard-Delete
          // buttons sit outside this IIFE and keep their current
          // green / red / amber hues per the brief.
          background: CD_ACTION_BTN_BG,
          color: colors.nav.fg,
          border: `1px solid ${CD_ACTION_BTN_BORDER}`,
        };
        const navyDangerStyle = {
          background: "rgba(239,68,68,0.18)",
          color: "#FCA5A5",
          border: "1px solid rgba(252,165,165,0.40)",
        };
        const navyWarnStyle = {
          background: "rgba(251,146,60,0.18)",
          color: "#FED7AA",
          border: "1px solid rgba(254,215,170,0.40)",
        };
        const roleLower = (meRole || "").toLowerCase();
        const canHardDelete = ["admin", "super_admin"].includes(roleLower);
        const canMerge = ["admin", "super_admin", "owner"].includes(roleLower);
        const primaryMobile =
          (customer.mobiles && customer.mobiles[0]?.number_e164) ||
          customer.phone;
        const telHref = primaryMobile
          ? `tel:${String(primaryMobile).replace(/[^0-9+]/g, "")}`
          : null;
        return (
          <>
          {/* ─────────────────────────────────────────────────────
              Phase 20 · Feb-2026 — ACTION ROW (above the tabs row).
              The action-bar block (Edit / Merge / Issue Credit /
              Mark Correction / Call / Delete / Move to Trash +
              mobile kebab) was relocated OUT of the shared single-
              row strip into its own full-width dedicated row that
              renders ABOVE the Send / Create / Overview tabs row.
              Buttons remain left-aligned (natural flex-row order,
              no flex-1 spacer); every testid, handler, role gate,
              and mobile-kebab collapse behavior is preserved
              byte-for-byte from the pre-Phase-20 single row.
          ───────────────────────────────────────────────────── */}
          <div
            className="rounded-2xl mb-4 px-3 py-3"
            style={{
              backgroundColor: colors.nav.bg,
              border: `1px solid ${colors.nav.border}`,
            }}
            data-testid="cd-command-strip"
          >
            <div
              className="flex flex-row flex-nowrap items-center gap-2 overflow-x-auto"
              data-testid="cd-action-row"
            >
              {/* Right-primary group — Edit / Merge / Credit / Correction.
                  Collapses into the mobile kebab below ``md:``. */}
              <div
                className="hidden md:inline-flex items-center gap-2"
                data-testid="cd-action-row-right-primary"
              >
                <Button
                  variant="ghost"
                  className={`${BTN_BASE} ${NAVY_OUTLINE}`}
                  onClick={() => navigate(`/customers/${id}/edit`)}
                  testid="cd-edit"
                  style={navyOutlineStyle}
                >
                  <Edit3 size={14} /> Edit
                </Button>
                {canMerge ? (
                  <Button
                    variant="ghost"
                    className={`${BTN_BASE} ${NAVY_OUTLINE}`}
                    onClick={() => setMergeOpen(true)}
                    testid="cd-merge-btn"
                    style={navyOutlineStyle}
                  >
                    <GitMerge size={14} /> Merge
                  </Button>
                ) : null}
                {canIssueCredit ? (
                  <Button
                    variant="ghost"
                    className={`${BTN_BASE} ${NAVY_OUTLINE}`}
                    onClick={openIssueCreditModal}
                    testid="cd-issue-credit-btn"
                    style={navyOutlineStyle}
                  >
                    <DollarSign size={14} /> Issue Credit
                  </Button>
                ) : null}
                {canToggleAccountCorrection ? (
                  <Button
                    variant="ghost"
                    className={`${BTN_BASE} ${NAVY_OUTLINE}`}
                    onClick={() => {
                      setAccountCorrectionNote("");
                      setAccountCorrectionOpen(true);
                    }}
                    testid="cd-account-correction-btn"
                    style={{ ...navyOutlineStyle, opacity: 0.85 }}
                    title={
                      customer.account_correction
                        ? "Un-flag Account Correction (will be counted in retention tiles)"
                        : "Mark Account Correction (excluded from retention tiles)"
                    }
                  >
                    <ShieldCheck size={14} />
                    {customer.account_correction
                      ? "Un-flag Correction"
                      : "Mark Correction"}
                  </Button>
                ) : null}
              </div>
              {/* Call — always visible (mobile + desktop) between the
                  primary and destructive groups. */}
              {primaryMobile ? (
                <div
                  className="inline-flex items-center gap-1"
                  data-testid="cd-click-to-call-wrapper"
                >
                  <ClickToCallButton
                    phoneNumber={primaryMobile}
                    entityKind="customer"
                    entityId={customer.id}
                    label="Call"
                    testIdPrefix="cd-click-to-call"
                    size="sm"
                    showFallback={false}
                  />
                  <a
                    href={telHref}
                    className="inline-flex items-center justify-center w-7 h-7 rounded-md hover:bg-white/10"
                    style={{ color: colors.nav.fg }}
                    title="Dial from this device"
                    aria-label="Dial from this device"
                    data-testid="cd-click-to-call-tel-fallback"
                  >
                    <Phone size={12} />
                  </a>
                </div>
              ) : null}
              {/* Right-destructive group — Delete / Move to Trash.
                  Also collapses into the mobile kebab below ``md:``. */}
              <div
                className="hidden md:inline-flex items-center gap-2"
                data-testid="cd-action-row-right-destructive"
              >
                <Button
                  variant="danger"
                  className={`${BTN_BASE} ${NAVY_DANGER}`}
                  onClick={() => setConfirmDelete(true)}
                  testid="cd-delete"
                  style={navyDangerStyle}
                >
                  <Trash2 size={14} /> Delete
                </Button>
                {canHardDelete ? (
                  <Button
                    variant="danger"
                    className={`${BTN_BASE} ${NAVY_WARN}`}
                    onClick={() => setHardDeleteOpen(true)}
                    testid="cd-hard-delete-btn"
                    style={navyWarnStyle}
                  >
                    <Trash2 size={14} /> Move to Trash
                  </Button>
                ) : null}
              </div>
              {/* Mobile kebab — Edit / Merge / Credit / Correction /
                  Delete / Trash collapse here below ``md:``.  Each
                  item is filtered by the SAME role flag that gates
                  the inline button, so permissions are consistent
                  across the two surfaces. */}
              <div className="md:hidden" data-testid="cd-mobile-kebab-wrapper">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      className={`${BTN_BASE} ${NAVY_OUTLINE}`}
                      testid="cd-mobile-kebab-trigger"
                      style={navyOutlineStyle}
                      aria-label="More actions"
                    >
                      <MoreHorizontal size={16} />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem
                      onSelect={() => navigate(`/customers/${id}/edit`)}
                      data-testid="cd-mobile-kebab-edit"
                    >
                      <Edit3 size={14} className="mr-2" /> Edit
                    </DropdownMenuItem>
                    {canMerge ? (
                      <DropdownMenuItem
                        onSelect={() => setMergeOpen(true)}
                        data-testid="cd-mobile-kebab-merge"
                      >
                        <GitMerge size={14} className="mr-2" /> Merge
                      </DropdownMenuItem>
                    ) : null}
                    {canIssueCredit ? (
                      <DropdownMenuItem
                        onSelect={openIssueCreditModal}
                        data-testid="cd-mobile-kebab-issue-credit"
                      >
                        <DollarSign size={14} className="mr-2" /> Issue Credit
                      </DropdownMenuItem>
                    ) : null}
                    {canToggleAccountCorrection ? (
                      <DropdownMenuItem
                        onSelect={() => {
                          setAccountCorrectionNote("");
                          setAccountCorrectionOpen(true);
                        }}
                        data-testid="cd-mobile-kebab-correction"
                      >
                        <ShieldCheck size={14} className="mr-2" />
                        {customer.account_correction
                          ? "Un-flag Correction"
                          : "Mark Correction"}
                      </DropdownMenuItem>
                    ) : null}
                    <DropdownMenuItem
                      onSelect={() => setConfirmDelete(true)}
                      data-testid="cd-mobile-kebab-delete"
                    >
                      <Trash2 size={14} className="mr-2" /> Delete
                    </DropdownMenuItem>
                    {canHardDelete ? (
                      <DropdownMenuItem
                        onSelect={() => setHardDeleteOpen(true)}
                        data-testid="cd-mobile-kebab-trash"
                      >
                        <Trash2 size={14} className="mr-2" /> Move to Trash
                      </DropdownMenuItem>
                    ) : null}
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>
          </div>
          {/* ─────────────────────────────────────────────────────
              Phase 20 · Feb-2026 — TABS ROW (below the action row).
              Hosts the Send / Create dropdowns + the Overview tab
              selector (``cd-tabs-dropdown-shell`` keeps its testid
              + ``minWidth: 220`` compact shell). Shares the navy
              chrome with the action row so the two strips read as
              a coherent command cluster.
          ───────────────────────────────────────────────────── */}
          <div
            className="rounded-2xl mb-4 px-3 py-3"
            style={{
              backgroundColor: colors.nav.bg,
              border: `1px solid ${colors.nav.border}`,
            }}
            data-testid="cd-command-strip-tabs"
          >
            <div
              className="flex flex-row flex-nowrap items-center gap-2 overflow-x-auto"
              data-testid="cd-tabs-row"
            >
              {/* Left group — Send / Create / Overview. */}
              <CustomerActionDropdowns
                customer={customer}
                onSend={openSendModal}
                onQuickTask={openQuickTaskFromDropdown}
                onSendServiceRecordsLink={() => setSrLinkOpen(true)}
                navy
              />
              <div
                style={{ minWidth: 220 }}
                data-testid="cd-tabs-dropdown-shell"
              >
                <ResponsiveTabs
                  tabs={visibleTabs}
                  active={tab}
                  onChange={setTab}
                  testidPrefix="cd-tab"
                  ariaLabel="Customer sections"
                  forceDropdown
                  recentStorageKey={
                    customer?.id ? `cd-tabs-recent-3-${customer.id}` : null
                  }
                />
              </div>
            </div>
          </div>

          {/* Phase 27 · Feb-2026 — Dark-navy KPI tile grid.
              Six tiles with the same chassis Portal Home uses
              (``rounded-2xl p-3 transition hover:brightness-95``,
              ``#03002e`` chassis bg).  Past Due flips to
              ``#7F1D1D`` (red-900) when ``past_due_cents > 0``;
              Credit flips to ``#064E3B`` (emerald-900) when
              ``credit_cents > 0``; Overdue count flips red when
              ``> 0``.  Chassis styles inlined per Phase 27
              decision #3 — Phase 23/24 regression locks on
              PortalHome.jsx are byte-for-byte preserved. */}
          <KPITileGrid kpi={kpi} testidPrefix="cd" />

          {/* CUSTOMER-DETAIL-NEXT-SERVICE · Feb-2026 — admin "Next
              Service" tile.  Standalone card between the Phase 27
              KPI grid (above) and the Phase 27 Quick Actions grid
              (below).  Both adjacent grids are untouched — their
              Phase 27 regression locks remain byte-for-byte.  See
              the ``NextServiceTile`` component definition above
              for chassis + wire-contract notes. */}
          <NextServiceTile customerId={id} />

          {/* Phase 27 · Feb-2026 — Quick Actions tile grid.
              Primary nav surface replacing the role of the
              ``cd-tabs-dropdown-shell`` ResponsiveTabs dropdown
              above.  The dropdown stays in-DOM as a compact
              fallback (and to preserve Phase 20 regression locks)
              — the tile grid is the operator's primary nav.  Each
              tile calls ``setTab(k)`` which drives the same tab-
              body render path the dropdown drove, so every
              handler + deep-link param is preserved byte-for-byte.
              Hover glow pattern mirrors Phase 24
              (``hover:shadow-[0_0_20px_rgba(255,255,255,0.6)]
              transition-shadow duration-200``). */}
          <QuickActionTileGrid
            tabs={visibleTabs}
            active={tab}
            onPick={setTab}
            testidPrefix="cd-quick-action"
          />
          </>
        );
      })()}

      {/* CUSTOMER-PROFILE-ACTION-BAR · Feb-2026 — Issue Credit
          modal rendered at the page root so it layers above the
          navy strip + the rest of the profile.  Reused verbatim
          from ``CustomerCreditsPage.jsx``'s ``AdjustDialog`` — no
          fork.  ``onSaved`` re-fetches the full customer summary
          (``load()``) so any surface displaying the balance
          refreshes without a page reload. */}
      {issueCreditOpen && canIssueCredit ? (
        <AdjustDialog
          customerId={id}
          currentBalanceCents={issueCreditBalanceCents}
          onClose={() => setIssueCreditOpen(false)}
          onSaved={() => {
            setIssueCreditOpen(false);
            load();
          }}
        />
      ) : null}

      {/* CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — toggle
          confirmation modal.  Simple shape (title / note textarea /
          2-button footer) because the action is reversible + fully
          audited.  The note field stays optional per G4 — no
          validation, blank POSTs through as ``null``. */}
      {accountCorrectionOpen && canToggleAccountCorrection ? (
        <Modal
          open={accountCorrectionOpen}
          onClose={() =>
            accountCorrectionBusy ? null : setAccountCorrectionOpen(false)
          }
          title={
            customer.account_correction
              ? "Un-flag Account Correction"
              : "Mark Account Correction"
          }
          testid="account-correction-modal"
        >
          <div className="space-y-3 p-1" data-testid="account-correction-form">
            <p className="text-sm" style={{ color: colors.onSurface }}>
              {customer.account_correction ? (
                <>
                  This customer is currently <strong>excluded</strong> from
                  retention / churn tile counts.  Un-flagging will
                  re-include them on the next page refresh.
                </>
              ) : (
                <>
                  Flagged customers are <strong>excluded</strong> from
                  retention / churn tile counts — past, present, and
                  future.  Use this for test accounts, bookkeeping
                  duplicates, or rows the office doesn't want to count
                  against their numbers.
                </>
              )}
            </p>
            <label className="block text-xs" style={{ color: colors.onMuted }}>
              Note (optional)
              <textarea
                value={accountCorrectionNote}
                onChange={(e) => setAccountCorrectionNote(e.target.value)}
                data-testid="account-correction-note-input"
                className="mt-1 w-full rounded-lg border p-2 text-sm"
                rows={3}
                placeholder="Why is this account being flagged? (optional)"
                style={{
                  background: colors.surface,
                  color: colors.onSurface,
                  borderColor: colors.border,
                }}
              />
            </label>
            <div className="flex gap-2 justify-end pt-2">
              <Button
                variant="ghost"
                onClick={() => setAccountCorrectionOpen(false)}
                disabled={accountCorrectionBusy}
                testid="account-correction-cancel-btn"
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={async () => {
                  setAccountCorrectionBusy(true);
                  try {
                    await api.post(
                      `/customers/${id}/account-correction`,
                      {
                        active: !customer.account_correction,
                        note: accountCorrectionNote || null,
                      },
                    );
                    setAccountCorrectionOpen(false);
                    setAccountCorrectionNote("");
                    load();
                  } catch (err) {
                    // Fall through — Toast primitive consumed by load()
                    // path; keep the modal open so the admin can retry.
                  } finally {
                    setAccountCorrectionBusy(false);
                  }
                }}
                disabled={accountCorrectionBusy}
                testid="account-correction-confirm-btn"
              >
                {customer.account_correction ? "Un-flag" : "Mark Correction"}
              </Button>
            </div>
          </div>
        </Modal>
      ) : null}

      {/* Feb-2026 · Tabs — the standalone ``ResponsiveTabs`` block
          that lived here has been relocated into the unified
          navy command strip immediately below the Portal Access
          panel (see ``cd-command-strip`` above). Kept a
          placeholder comment so the diff for future readers
          shows where the dropdown used to live. */}
      <div
        className="rounded-2xl overflow-hidden mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="p-5">
          {tab === "overview" ? (
            <div className="space-y-4">
              {/* Phase 48 · Feb-2026 — removed the compact company
                  business card from the customer profile header per
                  user redesign. Component stays in-tree for other
                  surfaces (tech ToolsHub, marketing card slot). */}
              {/* Phase 48.1 · Feb-2026 — customer name is echoed under
                  the header row, followed immediately by the contact
                  section, then addresses. Reorder matches user's
                  layout mockup. */}
              <div
                className="text-2xl font-bold"
                style={{ color: colors.onSurface }}
                data-testid="cd-customer-name-secondary"
              >
                {customer.name}
              </div>
              {/* TD-79 · Feb-2026 — Invoice list section between the
                  tab-nav red divider and the Payment Method Tiles,
                  per operator placement spec. Caps at 10 most-recent
                  rows (newest first); when the customer has >10 we
                  render a "View all" link to the main InvoicesList
                  prefiltered by ``?customer_id=``. */}
              <CustomerInvoiceList customerId={customer.id} />
              {/* Phase I5 · Feb-2026 — Payment Method Tiles between
                  the customer name heading and the Contact panel,
                  per the human's mockup with the red underline. */}
              <PaymentMethodTiles
                customerId={customer.id}
                variant="admin"
              />
              <CustomerContactsPanel
                customer={customer}
                onSaved={(updated) => {
                  setCustomer((c) => ({ ...c, ...updated }));
                  setToast({ tone: "success", message: "Contacts saved" });
                }}
                onError={(msg) => setToast({ tone: "error", message: msg })}
              />
              {/* Feb-2026 · Multi-Contact Phase 1 · editor + mute toggle.
                  Renders the up-to-4-emails / up-to-4-mobiles multi-row
                  editor AND the automations-mute admin toggle. Distinct
                  from the ``is_muted`` control (that one suppresses
                  auto-scheduling — see CustomerActionDropdowns). */}
              <CustomerMultiContactEditor
                customer={customer}
                isAdmin={authUser?.role === "admin"
                          || authUser?.role === "super_admin"}
                onRefresh={load}
              />
              {/* Feb-2026 · Send Portal Invite promoted to the
                  top action stack (rendered near the top of this
                  page alongside the Card-on-file action).  This
                  Overview slot is intentionally empty — the button
                  no longer duplicates. See the top-action-stack
                  block above for the live instance. */}
              {/* Queue Item 3 · Feb-2026 — dedicated Tags section on
                  the customer detail page. Chip render + combobox +
                  inline "Create new: <query>" all live inside
                  CustomerTagPicker; this card just gives it a
                  labelled home in the Overview stack. */}
              <CustomerTagsCard
                customer={customer}
                onChange={(nextTags) =>
                  setCustomer((c) => c ? { ...c, tags: nextTags } : c)
                }
              />
              <div data-testid="cd-address-block" className="space-y-2">
                <Info
                  label="Primary address"
                  value={customer.address
                          ? <AddressLink address={customer.address} />
                          : null}
                />
                <Info
                  label="Billing address"
                  value={customer.billing_address
                          ? <AddressLink address={customer.billing_address} />
                          : null}
                />
                {/* GCR · Feb-2026 — the lower duplicate <Info>
                     render was removed from this block.  The
                     value is now surfaced ONLY by the top stat-
                     tile grid (testid ``cd-stat-gate-code``,
                     line ~1012).  Primary address / Billing
                     address / Secondary addresses siblings
                     untouched. */}
                {(customer.secondary_addresses || []).length ? (
                  <div>
                    <div className="text-xs uppercase font-semibold mb-1" style={{ color: colors.muted }}>
                      Secondary addresses
                    </div>
                    <ul className="space-y-1 text-sm" style={{ color: colors.onSurface }}>
                      {customer.secondary_addresses.map((a, i) => (
                        <li key={i}>· <AddressLink address={a} /></li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
              <MasterBillingCard
                customer={customer}
                onToast={(t) => setToast(t)}
                onRefreshCustomer={load}
              />
              {/* Phase 12 · Feb 2026 — Card-on-file toggle. Admin +
                  manager only. Tri-state override with a "Reset to
                  tenant default" ghost button. */}
              {canSeeCardControls && (
                <CardOnFileControl
                  customer={customer}
                  tenantDefault={tenantDefault}
                  onSaved={(doc) => {
                    setCustomer((c) => ({ ...c, ...doc }));
                    setToast({ tone: "success",
                                message: "Card requirement updated" });
                  }}
                  onError={(msg) => setToast({ tone: "error", message: msg })}
                />
              )}
              {/* Feb-2026 service-notes ship — Pool + Landscape long-form
                  notes. Admin-editable; techs see only the note matching
                  their service_type via /jobs?* enrichment. */}
              <CustomerServiceNotesCards
                customer={customer}
                onSaved={(updated) => {
                  setCustomer((c) => ({ ...c, ...updated }));
                  setToast({ tone: "success", message: "Service notes saved" });
                }}
                onError={(msg) => setToast({ tone: "error", message: msg })}
              />
              {/* Task N Round 2 · Feb-2026 — Notes History replaces the
                  legacy static ``<Info label="Notes" value={customer.notes}
                  />`` display.  Compact 3-row preview here; full paginated
                  list lives on the "Notes" tab.  ``customer.notes`` (the
                  persisted, edited-via-CustomerForm free-text field) is
                  intentionally NOT rendered in this About section — it
                  shows above the SR history on the Notes tab so the two
                  distinct "note" concepts (customer-level free-text vs
                  per-visit SR notes) don't blur together. */}
              <div
                className="mt-2"
                data-testid="cd-notes-history-preview-about"
              >
                <div
                  className="text-xs font-semibold uppercase tracking-wide mb-1"
                  style={{ color: colors.onSurfaceSecondary }}
                >
                  Recent notes
                </div>
                <NotesHistoryList
                  customerId={id}
                  compact
                  onSeeAll={() => setTab("notes")}
                />
              </div>
              {/* CP-2 · Feb-2026 — Recent Invoices + Recent Estimates
                   sections, appended at the end of the Overview
                   stack per the brief (``do NOT refactor the existing
                   Overview layout; just append''). */}
              <RecentDocsSection customerId={id} />
            </div>
          ) : null}

          {tab === "jobs" ? (
            jobs.length === 0 ? (
              <EmptyState
                title="No jobs yet"
                hint="Create a job for this customer to see it here."
                action={
                  <Button onClick={() => navigate(`/jobs/new?customer_id=${id}`)}>
                    New job
                  </Button>
                }
              />
            ) : (
              /* Phase P37 · Feb-2026 — virtualized jobs history.
                 The container caps at 60vh so react-window's ``List``
                 has a bounded viewport to window against. Overscan
                 8 rows. Each row is a memoized ``<JobHistoryRow />``
                 (see the component at the bottom of this file) that
                 skips re-renders unless its own job's ``id`` /
                 ``updated_at`` / ``status`` change. */
              <div data-testid="cd-jobs-list">
                <List
                  className="rounded-xl"
                  rowComponent={JobHistoryRow}
                  rowCount={jobs.length}
                  rowHeight={_P37_JOB_ROW_HEIGHT}
                  rowKey={(index) => jobs[index]?.id ?? `p37-idx-${index}`}
                  rowProps={{ jobs, reopenJob }}
                  overscanCount={8}
                  defaultHeight={Math.min(600, jobs.length * _P37_JOB_ROW_HEIGHT + 4)}
                  style={{
                    maxHeight: "60vh",
                    border: `1px solid ${colors.border}`,
                    backgroundColor: colors.surface,
                  }}
                />
                {/* Phase P37 · Feb-2026 — server-side ``Load more``.
                    Fetches the next 50 rows via
                    ``GET /jobs?offset=<jobs.length>``. Hidden at
                    the tail. */}
                {jobsHasMore ? (
                  <button
                    type="button"
                    onClick={loadMoreJobs}
                    disabled={jobsLoadingMore}
                    className="w-full text-sm font-semibold py-2 mt-2 rounded"
                    style={{
                      backgroundColor: colors.surfaceSecondary,
                      color: colors.brand,
                      border: `1px solid ${colors.border}`,
                      opacity: jobsLoadingMore ? 0.6 : 1,
                      cursor: jobsLoadingMore ? "not-allowed" : "pointer",
                    }}
                    data-testid="cd-jobs-load-more"
                  >
                    {jobsLoadingMore ? "Loading…" : `Load more (${_P37_JOBS_PAGE} at a time)`}
                  </button>
                ) : null}
              </div>
            )
          ) : null}

          {tab === "measurements" ? (
            // Feb-2026 · M2 · role-gated at TABS filter (visibleTabs)
            // + defensive guard here so a stale deep-link like
            // ``?tab=measurements`` on a technician session never
            // renders the tab body even if the URL param bypassed
            // the sidebar dropdown.
            (["admin", "super_admin", "manager"].includes(authUser?.role)) ? (
              <CustomerMeasurementsTab customer={customer} />
            ) : null
          ) : null}

          {tab === "chemical_history" ? (
            // Feb-2026 · C5 · same defensive shape as measurements —
            // filter gate + hard role check so a stale deep-link on a
            // technician / customer session can't render the tab body.
            (CHEMICAL_HISTORY_TAB_ROLES.includes(authUser?.role)) ? (
              <CustomerChemicalHistoryTab customer={customer} />
            ) : null
          ) : null}

          {tab === "documents" ? (
            <CustomerDocumentsTab customerId={id} />
          ) : null}

          {tab === "quotes" ? (
            <EmptyState title="Quotes come in Phase 3" hint="Stripe checkout + card-on-file ship next." />
          ) : null}
          {tab === "invoices" ? (
            <EmptyState title="Invoices come in Phase 3" hint="Master invoice + combine ship there." />
          ) : null}

          {tab === "equipment" ? (
            <CustomerEquipmentLibrary
              customerId={id}
              currentUser={(() => {
                try { return JSON.parse(localStorage.getItem("user") || "null"); } catch { return null; }
              })()}
            />
          ) : null}

          {tab === "warranties" ? (
            <CustomerWarrantiesLibrary
              customerId={id}
              currentUser={(() => {
                try { return JSON.parse(localStorage.getItem("user") || "null"); } catch { return null; }
              })()}
            />
          ) : null}

          {tab === "tasks" ? (
            <CustomerTasksPanel
              customerId={id}
              registerOpener={(fn) => setTaskQuickAddOpener(() => fn)}
            />
          ) : null}

          {tab === "notes" ? (
            <div
              className="space-y-3"
              data-testid="cd-notes-history-tab"
            >
              {/* Task N Round 2 · Phase N.5 §E halt option — preserve
                  at-a-glance visibility of the persisted customer-level
                  free-text ``customer.notes`` field.  Render as a
                  read-only block above the SR history list; hidden when
                  empty so the tab stays focused on visit notes.  The
                  write path remains ``CustomerForm.jsx`` (Edit Customer
                  page) → ``PUT /customers/{cid}`` — unchanged. */}
              {customer.notes && customer.notes.trim() ? (
                <div
                  className="p-3 rounded-lg"
                  data-testid="cd-notes-tab-customer-profile-note"
                  style={{
                    backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}`,
                  }}
                >
                  <div
                    className="text-xs font-semibold uppercase tracking-wide mb-1"
                    style={{ color: colors.onSurfaceSecondary }}
                  >
                    Customer profile note
                  </div>
                  <div
                    className="text-sm whitespace-pre-line"
                    style={{ color: colors.onSurface }}
                  >
                    {customer.notes}
                  </div>
                </div>
              ) : null}
              <NotesHistoryList customerId={id} />
            </div>
          ) : null}

          {/* Phase I7 · Wave A · Feb-2026 — Communication Timeline
              tab. Merges SMS + email dispatch rows and portal-invite
              audit events into a single per-customer stream. */}
          {null}

          {tab === "credits" ? (
            <CustomerCreditsPanel customerId={id} />
          ) : null}

          {tab === "payments" ? (
            <AdminCardCapturePanel customerId={id} onChange={load} />
          ) : null}

          {tab === "subscriptions" ? (
            <SubscriptionsPanel
              customerId={id}
              canWrite={["owner", "admin", "super_admin"].includes(meRole)}
            />
          ) : null}

          {tab === "reviews" ? (
            <CustomerReviewsTab customerId={id} jobs={jobs} />
          ) : null}

          {tab === "portal" ? (
            <PortalAccessPanel customer={customer} onDone={load} onToast={(t) => setToast(t)} openLogin={() => setLoginModal(true)} />
          ) : null}

          {tab === "properties" ? (
            <PropertiesTab
              customer={customer}
              onToast={(t) => setToast(t)}
              onRefreshCustomer={load}
            />
          ) : null}
        </div>

        {/* Phase I7 · Wave A · Feb-2026 (revised) — Communication
            Timeline mounted OUTSIDE the tab-panel switch so it stays
            visible regardless of which tab is active. Sits at the
            bottom of the page above modal region. */}
        <section
          className="mt-6"
          data-testid="customer-detail-comm-timeline-section"
        >
          <h2
            className="text-base font-bold mb-3 flex items-center gap-2"
            style={{ color: colors.onSurface }}
          >
            <Clock size={16} /> Communication Timeline
          </h2>
          {/* Feb-2026 · Full-history timeline — merges marketing
              deliveries + invoices + estimates on top of the legacy
              SMS/email dispatch feed. Old ``CommunicationTimeline``
              stays available (backwards-compat + other consumers)
              but is no longer mounted here. */}
          <CustomerFullTimeline scope="admin" customerId={id} />
        </section>

        {/* Feb-2026 · duplicate-management feature — merge
            history + rollback panel.  BE SHA d8dd7eb49.
            Visible to all admin+manager roles (same gate as
            the Duplicates tab); Rollback button renders only
            for admin and only while the audit row's
            ``remaining_rollback_days > 0 AND rolled_back_at
            === null``. */}
        <MergeHistoryPanel
          customerId={id}
          canRollback={authUser?.role === "admin"}
        />
      </div>

      <PortalLoginModal
        open={loginModal}
        onClose={() => setLoginModal(false)}
        customer={customer}
        onDone={async (msg) => {
          setLoginModal(false);
          setToast({ tone: "success", message: msg });
          await load();
        }}
        onError={(e) => setToast({ tone: "error", message: e })}
      />

      <Modal
        open={false}
        onClose={() => setConfirmDelete(false)}
        title="Delete customer? (legacy modal — retained until Phase 20 removes it)"
        footer={null}
      >
        <span />
      </Modal>

      {/* Feb-2026 · Customer Delete UX overhaul — dedicated 3-button
          modal (Cancel / Soft Delete / Hard Delete). Replaces the
          previous ``ConfirmDeleteDialog`` which silently HARD-
          deleted while its copy claimed to "archive" — a real
          safety hole this modal closes. */}
      <CustomerDeleteModal
        open={confirmDelete}
        customer={customer}
        busyMode={deleteBusyMode}
        onCancel={() => setConfirmDelete(false)}
        onSoftDelete={() => doDelete("soft")}
        onHardDelete={() => doDelete("hard")}
      />

      {/* HARD-DELETE · HD-B · Feb-2026 — "Move to Trash" modal. */}
      <HardDeleteModal
        open={hardDeleteOpen}
        entityType="customer"
        entityId={id}
        entityLabel={customer?.name}
        testidPrefix="cd-hard-delete"
        onClose={() => setHardDeleteOpen(false)}
        onSuccess={() => {
          setHardDeleteOpen(false);
          setTimeout(() => navigate("/customers"), 400);
        }}
        onBlocked={() => setHardDeleteOpen(false)}
      />

      {/* Phase M1 · Feb-2026 — Customer Merge Wizard. Admin-only —
           the trigger button is already role-gated. This modal renders
           unconditionally when open; server enforces the role a second
           time on POST. */}
      <CustomerMergeWizard
        open={mergeOpen}
        primary={customer}
        onClose={() => setMergeOpen(false)}
        onMerged={() => { setMergeOpen(false); load(); }}
      />

      {/* Feb-2026 Customer Detail Additions — VIP note modal (double-click star). */}
      <VipNoteModal
        open={vipModal}
        onClose={() => setVipModal(false)}
        customer={customer}
        onSave={async (note) => {
          try {
            const doc = await api.patch(`/customers/${id}/vip`, {
              is_vip: !!customer.is_vip,
              vip_note: note || null,
            });
            setCustomer((c) => ({ ...c, ...doc }));
            setToast({ tone: "success", message: "VIP note saved" });
            setVipModal(false);
          } catch (e) {
            setToast({ tone: "error", message: e.message });
          }
        }}
      />

      {/* Feb-2026 Customer Detail Additions — Send Email/SMS modal. */}
      <SendComposeModal
        payload={sendModal}
        customer={customer}
        onClose={() => setSendModal(null)}
        onSent={() => {
          setSendModal(null);
          setToast({ tone: "success", message: "Message sent" });
        }}
        onError={(msg) => setToast({ tone: "error", message: msg })}
      />

      {/* Task 6 · Feb 2026 — Send service records link modal. */}
      <SendServiceRecordsLinkModal
        open={srLinkOpen}
        customer={customer}
        onClose={() => setSrLinkOpen(false)}
        onSent={() => {
          setToast({ tone: "success", message: "Service records link sent" });
        }}
        onError={(msg) => setToast({ tone: "error", message: msg })}
      />

      {/* Phase 16 · Item 4 · Feb-2026 — Communications timeline at
          the bottom of the customer detail. Admin / super_admin only
          — technician and customer roles never render this section.
          Server also enforces the guard on GET /communications-log. */}
      {(meRole === "admin" || meRole === "super_admin") && customer?.id ? (
        <CustomerCommunicationsTimeline customerId={customer.id} />
      ) : null}

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

function Info({ label, value, preserveNewlines }) {
  return (
    <div>
      <div className="text-xs uppercase font-semibold mb-1" style={{ color: colors.muted }}>
        {label}
      </div>
      <div
        className="text-sm"
        style={{ color: colors.onSurface, whiteSpace: preserveNewlines ? "pre-wrap" : undefined }}
      >
        {value || "—"}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   CP-2 · Feb-2026 — Recent Invoices + Recent Estimates sections.

   Appended at the end of the Overview stack (NOT refactoring the
   surrounding layout).  Reuses the existing
   ``GET /api/quotes?doc_type={invoice|quote}&customer_id={id}``
   endpoint (``backend/routers/quotes.py:252``) — no backend
   changes.  Both lists fetch in parallel via ``Promise.allSettled``
   so one failure never blanks the other (criterion e. in the vitest).

   Named export (``RecentDocsSection``) so the CP-2 vitest can mount
   this sub-tree in isolation; CustomerDetail itself is ~3000 lines
   and would need a mountain of mocks to render.  The ``api`` prop
   is an injection point for the test — defaults to the real client.
   ═══════════════════════════════════════════════════════════════ */
export function RecentDocsSection({ customerId, api: apiProp }) {
  const client = apiProp || api;
  const [invoices, setInvoices] = useState([]);
  const [estimates, setEstimates] = useState([]);
  const [invoicesLoading, setInvoicesLoading] = useState(true);
  const [estimatesLoading, setEstimatesLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setInvoicesLoading(true);
    setEstimatesLoading(true);
    // P1 PERF-HOTFIX · Feb-2026 — opt-in Shape-A pagination +
    // slim projection on ``GET /quotes``. Pre-hotfix we fetched
    // the FULL customer history (up to 1000 docs including
    // ``line_items`` / ``pdf_cache``) and sliced to 5 client-
    // side.  On preview with 263 quotes that's 118KB per call;
    // on prod with 500-2000 quotes/customer that's 2.5-20 MB
    // per call × two parallel calls — the suspected root cause
    // of the >60s customer-profile regression.
    //
    // The new call pattern passes ``limit=5&slim=1`` so:
    //   * server returns the Shape-A envelope
    //     ``{rows, limit, offset, has_more, total_count}``
    //     with exactly the 5 rows we render.
    //   * ``line_items`` / ``pdf_cache`` / ``pdf_url_cache`` /
    //     ``legacy_payload`` are dropped from the projection —
    //     payload drops ~30x (preview: 118KB → 3.2KB).
    // Response is destructured on ``.rows`` with a defensive
    // fallback to a bare array (keeps the client working if an
    // upstream proxy somehow strips the envelope).
    Promise.allSettled([
      client.get(
        `/quotes?doc_type=invoice&customer_id=${customerId}`
        + `&limit=5&slim=1`,
      ),
      client.get(
        `/quotes?doc_type=quote&customer_id=${customerId}`
        + `&limit=5&slim=1`,
      ),
    ]).then(([inv, est]) => {
      if (cancelled) return;
      const _extract = (payload) => {
        if (Array.isArray(payload)) return payload;         // legacy bare array
        if (payload && Array.isArray(payload.rows)) {
          return payload.rows;                              // Shape-A envelope
        }
        return [];
      };
      if (inv.status === "fulfilled") {
        setInvoices(_extract(inv.value));
      } else {
        // eslint-disable-next-line no-console
        console.warn("[cp-2] recent invoices fetch failed", inv.reason);
        setInvoices([]);
      }
      if (est.status === "fulfilled") {
        setEstimates(_extract(est.value));
      } else {
        // eslint-disable-next-line no-console
        console.warn("[cp-2] recent estimates fetch failed", est.reason);
        setEstimates([]);
      }
      setInvoicesLoading(false);
      setEstimatesLoading(false);
    });
    return () => { cancelled = true; };
  }, [customerId, client]);

  return (
    <div
      className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4"
      data-testid="cd-recent-docs-section"
    >
      <RecentDocsList
        title="Recent invoices"
        testidPrefix="cd-recent-invoices"
        docs={invoices}
        loading={invoicesLoading}
        emptyLabel="No recent invoices"
        hrefPrefix="/invoices"
        numberKey="invoice_number"
      />
      <RecentDocsList
        title="Recent estimates"
        testidPrefix="cd-recent-estimates"
        docs={estimates}
        loading={estimatesLoading}
        emptyLabel="No recent estimates"
        hrefPrefix="/quotes"
        numberKey="quote_number"
      />
    </div>
  );
}

function RecentDocsList({
  title, testidPrefix, docs, loading, emptyLabel, hrefPrefix, numberKey,
}) {
  return (
    <div
      className="rounded-xl p-3"
      style={{
        backgroundColor: colors.surfaceSecondary,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={`${testidPrefix}-section`}
    >
      <div
        className="text-xs font-semibold uppercase tracking-wide mb-2"
        style={{ color: colors.onSurfaceSecondary }}
      >
        {title}
      </div>
      {loading ? (
        <div className="space-y-1" data-testid={`${testidPrefix}-loading`}>
          <Skeleton className="h-6" />
          <Skeleton className="h-6" />
          <Skeleton className="h-6" />
        </div>
      ) : docs.length === 0 ? (
        <div
          className="text-sm"
          style={{ color: colors.muted }}
          data-testid={`${testidPrefix}-empty`}
        >
          {emptyLabel}
        </div>
      ) : (
        <ul className="space-y-1" data-testid={`${testidPrefix}-list`}>
          {docs.map((d) => (
            <li key={d.id} data-testid={`${testidPrefix}-row-${d.id}`}>
              <Link
                to={`${hrefPrefix}/${d.id}`}
                className="flex items-center justify-between gap-2 text-sm rounded-lg px-2 py-1 hover:underline"
                style={{ color: colors.onSurface }}
                data-testid={`${testidPrefix}-link-${d.id}`}
              >
                <span className="truncate" style={{ minWidth: 0 }}>
                  <span style={{ color: colors.muted }}>
                    {(d.created_at || "").slice(0, 10)}
                  </span>
                  <span className="mx-2">·</span>
                  <span>{d[numberKey] || (d.id || "").slice(0, 8)}</span>
                </span>
                <span className="flex items-center gap-2 flex-shrink-0">
                  <span style={{ fontFamily: "monospace" }}>
                    {money(d.total || 0)}
                  </span>
                  <RecentDocStatusPill status={d.status} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RecentDocStatusPill({ status }) {
  const meta =
    statusMeta[status] || {
      label: status || "—",
      bg: colors.surfaceTertiary,
      fg: colors.muted,
    };
  return (
    <span
      className="text-xs font-semibold px-2 py-0.5 rounded-full whitespace-nowrap"
      style={{ backgroundColor: meta.bg, color: meta.fg }}
      data-testid={`recent-doc-status-pill-${status || "none"}`}
    >
      {meta.label}
    </span>
  );
}



function PortalAccessPanel({ customer, onDone, onToast, openLogin }) {
  const { user: authUser } = useAuth();
  const canImpersonate = authUser?.role === "super_admin" || authUser?.role === "admin";
  const showCopyResetLink = canCopyResetLink(authUser?.role);
  const [busy, setBusy] = React.useState("");
  const [inviteLink, setInviteLink] = React.useState(null);
  const [tempPassword, setTempPassword] = React.useState(null);
  const [status, setStatus] = React.useState(null);
  const [history, setHistory] = React.useState([]);
  const [resetModalOpen, setResetModalOpen] = React.useState(false);
  const [resetLinkModalOpen, setResetLinkModalOpen] = React.useState(false);
  const [resetLinkStatus, setResetLinkStatus] = React.useState(null);
  // K30.copy-admin-link · Feb-2026 — separate confirm modal +
  // clipboard-fallback modal state.
  const [copyLinkModalOpen, setCopyLinkModalOpen] = React.useState(false);
  const [copyFallback, setCopyFallback] = React.useState(null);

  const loadStatus = React.useCallback(async () => {
    try {
      const [s, h, rl] = await Promise.all([
        api.get(`/customers/${customer.id}/portal-status`),
        api.get(`/customers/${customer.id}/portal-history?limit=25`),
        api.get(`/customers/${customer.id}/portal-reset-link-status`)
          .catch(() => null),
      ]);
      setStatus(s || null);
      setHistory((h && h.events) || []);
      setResetLinkStatus(rl || null);
    } catch (_e) {
      // Non-fatal — panel still renders with the legacy customer.has_login flag.
    }
  }, [customer.id]);

  React.useEffect(() => { loadStatus(); }, [loadStatus]);

  const doAction = async (endpoint, label, body) => {
    setBusy(endpoint);
    setInviteLink(null);
    setTempPassword(null);
    try {
      const r = await api.post(`/customers/${customer.id}/${endpoint}`, body || undefined);
      if (r?.emailed) {
        onToast({ tone: "success", message: `${label} email sent to ${r.email}` });
      } else if (r?.password) {
        setInviteLink(r.login_url);
        setTempPassword(r.password);
        onToast({ tone: "info", message: `${label} link ready — share it manually` });
      } else {
        onToast({ tone: "success", message: `${label} done` });
      }
      await onDone();
      await loadStatus();
    } catch (e) {
      onToast({ tone: "error", message: e.message });
    } finally { setBusy(""); }
  };

  const impersonate = async () => {
    // Feb-2026 · Popup-blocker fix. Browsers (Chrome/Safari/Firefox)
    // only allow ``window.open()`` when it fires *directly* from a
    // user gesture. Any ``await`` BEFORE the open call detaches it
    // from the click and the browser silently blocks it — the
    // previous version called ``window.open`` after ``await
    // api.post(...)`` returned, so the tab never opened while the
    // success toast still fired. Open a blank stub tab
    // synchronously first, then navigate it once the token comes
    // back. If the pre-open itself is blocked (``win === null``)
    // we surface a real error with a clipboard fallback.
    const win = typeof window !== "undefined"
      ? window.open("about:blank", "_blank")
      : null;
    setBusy("impersonate");
    try {
      const r = await api.post(`/admin/impersonate/${customer.id}`);
      const token = r?.access_token;
      if (!token) {
        if (win) { try { win.close(); } catch { /* ignore */ } }
        onToast({ tone: "error",
                   message: r?.detail || r?.message
                     || "Impersonation failed — the server did not return a token." });
        return;
      }
      // Phase K13 · Feb-2026 — open the portal in a new tab with the
      // impersonation token in the query string.  The bootstrap on
      // the portal side pins it to sessionStorage + strips the URL.
      // Admin tab is NOT re-tokened, so the admin's session survives.
      const portalUrl = `/portal/home?impersonation_token=${encodeURIComponent(token)}`;
      if (!win) {
        // Popup blocker bit through even the synchronous pre-open
        // (some hardened browser configs). Surface a real error
        // with a clipboard fallback — NO success toast.
        onToast({ tone: "error",
                   message: "Enable popups to impersonate. URL copied to clipboard.",
                   action: { label: "Copy portal URL",
                             onClick: () => navigator?.clipboard?.writeText(
                               window.location.origin + portalUrl) } });
        try {
          await navigator?.clipboard?.writeText(window.location.origin + portalUrl);
        } catch { /* clipboard may fail in test env */ }
        return;
      }
      // Success path — navigate the pre-opened stub tab, THEN toast.
      // ``replace`` (not ``assign``) so back-navigation from the
      // portal doesn't return to about:blank.
      try {
        win.location.replace(portalUrl);
      } catch {
        // Defensive fallback for exotic cross-origin edge cases.
        win.location.href = portalUrl;
      }
      onToast({ tone: "success",
                 message: `Opened portal as ${customer.name || "customer"} in a new tab.` });
    } catch (e) {
      // Every failure path surfaces a toast — no more silent "nothing
      // happened" on missing portal-user rows (400) or 5xx errors.
      if (win) { try { win.close(); } catch { /* ignore */ } }
      const detail = e?.detail || e?.message
        || (typeof e === "string" ? e : "Impersonation failed.");
      onToast({ tone: "error", message: detail });
    } finally { setBusy(""); }
  };

  const hasLogin = (status && status.has_login) ?? customer.has_login;
  const active = (status && status.active) ?? true;

  return (
    <div className="space-y-5" data-testid="portal-access-panel">
      {/* Feb-2026 · Bug 1 fix — Send Portal Invite CTA mirrored from
          the Overview tab so both surfaces render identically for
          the same customer state. Reuses the same
          ``PortalInviteQuickAction`` component (no fork) → identical
          gating (email-required disable), identical endpoint
          (``POST /customers/{id}/portal-invite``), identical toast
          copy. Renders for both hasLogin=true (rotates password) and
          hasLogin=false (issues new credentials) — matching Overview.
          The advanced Reset / Impersonate / Revoke / Manual-create
          actions below are unaffected. */}
      <PortalInviteQuickAction customer={customer} onToast={onToast} />

      {/* Status row */}
      <div
        className="rounded-lg p-3 text-sm"
        style={{ backgroundColor: colors.surfaceMuted, color: colors.onSurface }}
        data-testid="portal-status-row"
      >
        {hasLogin ? (
          <>
            <div className="font-semibold" data-testid="portal-status-email">
              Portal login: {status?.email || customer.email}
              {" "}
              {active ? (
                <Chip label="Active" tone="success" testid="portal-status-active" />
              ) : (
                <Chip label="Revoked" tone="danger" testid="portal-status-revoked" />
              )}
              {" "}
              <PortalResetLinkChip data={resetLinkStatus} />
            </div>
            <div className="mt-1" style={{ color: colors.onSurfaceSecondary }}>
              {status?.last_portal_login_at ? (
                <span data-testid="portal-last-login">
                  Last portal login: {new Date(status.last_portal_login_at).toLocaleString()}
                  {status.last_portal_login_ip ? ` · IP ${status.last_portal_login_ip}` : ""}
                </span>
              ) : (
                <span>No portal login recorded yet.</span>
              )}
            </div>
          </>
        ) : (
          <div style={{ color: colors.onSurfaceSecondary }}>
            No portal login yet. Send an invite (auto-generated password) or create one manually.
            {" "}
            <PortalResetLinkChip data={resetLinkStatus} />
          </div>
        )}
      </div>

      {/* Actions.  Feb-2026 · the customer-facing invite CTA MOVED
          to the main Contact card in the Overview tab
          (``PortalInviteQuickAction``); this panel keeps only the
          advanced portal-access actions. */}
      <div className="flex flex-wrap gap-2">
        {/* K30 · Feb-2026 — admin-triggered tokenized reset-link.
            Always visible (independent of hasLogin) because the
            endpoint auto-provisions the portal user row if missing.
            Disabled only when the customer has no email on file. */}
        <Button
          variant="ghost"
          onClick={() => setResetLinkModalOpen(true)}
          disabled={busy === "portal-reset-link" || !(customer.email || status?.email)}
          testid="cd-portal-reset-link"
        >
          Send reset link
        </Button>
        {/* K30.copy-admin-link · Feb-2026 — super-admin-only
            clipboard-copy action for cases where email delivery is
            too slow (customer on the phone). Hidden entirely for
            non-super-admins so it can't be mis-clicked. */}
        {showCopyResetLink ? (
          <Button
            variant="ghost"
            onClick={() => setCopyLinkModalOpen(true)}
            disabled={busy === "portal-reset-link-copy"
              || !(customer.email || status?.email)}
            testid="cd-portal-reset-link-copy"
          >
            Copy reset link
          </Button>
        ) : null}
        {hasLogin ? (
          <>
            <Button
              variant="ghost"
              onClick={() => setResetModalOpen(true)}
              testid="cd-portal-reset"
            >
              Reset password…
            </Button>
            <Button
              variant="ghost"
              onClick={impersonate}
              disabled={busy === "impersonate" || !active || !canImpersonate}
              testid="cd-impersonate"
              style={{ display: canImpersonate ? undefined : "none" }}
            >
              View as customer
            </Button>
            <Button
              variant="danger"
              onClick={() => doAction("portal-revoke", "Portal revoked")}
              disabled={busy === "portal-revoke" || !active}
              testid="cd-portal-revoke"
            >
              Revoke access
            </Button>
          </>
        ) : (
          <Button variant="ghost" onClick={openLogin} testid="cd-portal-manual-create">Manual create…</Button>
        )}
      </div>

      {inviteLink && tempPassword ? (
        <div
          className="rounded-lg p-3 text-sm"
          style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}
          data-testid="portal-invite-payload"
        >
          <div className="font-semibold mb-1">Share these credentials manually:</div>
          <div>Login: <a href={inviteLink} className="underline" target="_blank" rel="noreferrer">{inviteLink}</a></div>
          <div>Email: <code>{status?.email || customer.email}</code></div>
          <div>Temp password: <code>{tempPassword}</code></div>
        </div>
      ) : null}

      {/* Activity feed */}
      <div data-testid="portal-history-section">
        <div
          className="text-xs uppercase font-semibold mb-2"
          style={{ color: colors.muted }}
        >
          Recent portal activity
        </div>
        {history.length === 0 ? (
          <div className="text-sm" style={{ color: colors.onSurfaceSecondary }} data-testid="portal-history-empty">
            No recent activity.
          </div>
        ) : (
          <ul className="space-y-1 text-sm" data-testid="portal-history-list">
            {history.slice(0, 10).map((row) => (
              <li key={row.id} className="flex justify-between gap-2">
                <span style={{ color: colors.onSurface }}>
                  {PORTAL_EVENT_LABELS[row.event] || row.event}
                  {row.actor_email ? ` — ${row.actor_email}` : ""}
                  {row.ip_address ? ` (${row.ip_address})` : ""}
                </span>
                <span style={{ color: colors.onSurfaceSecondary }}>
                  {row.created_at ? new Date(row.created_at).toLocaleString() : "—"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <PortalResetModal
        open={resetModalOpen}
        onClose={() => setResetModalOpen(false)}
        onSubmit={async (explicitPassword) => {
          setResetModalOpen(false);
          await doAction(
            "portal-reset",
            "Portal reset",
            explicitPassword ? { password: explicitPassword } : {},
          );
        }}
      />

      {/* K30 · Feb-2026 — Confirm modal for the admin-triggered
          tokenized reset-link. Deliberately separate from
          PortalResetModal (which sends a raw temp password) so
          each action is discoverable independently. */}
      <PortalResetLinkConfirmModal
        open={resetLinkModalOpen}
        customer={customer}
        email={status?.email || customer.email}
        onClose={() => setResetLinkModalOpen(false)}
        onConfirm={async () => {
          setResetLinkModalOpen(false);
          setBusy("portal-reset-link");
          try {
            const r = await api.post(`/customers/${customer.id}/portal-reset-link`);
            onToast({
              tone: "success",
              message: r?.sent_to
                ? `Reset link sent to ${r.sent_to} (expires in ${r.token_ttl_minutes || 30}m)`
                : "Reset link sent",
            });
            await onDone();
            await loadStatus();
          } catch (e) {
            onToast({ tone: "error", message: e?.message || "Reset link send failed" });
          } finally {
            setBusy("");
          }
        }}
      />

      {/* K30.copy-admin-link · Feb-2026 — confirm modal for the
          super-admin clipboard-copy path. Deliberately shouts about
          the security posture ("do not share by insecure channels")
          because the operator is about to hold a bearer credential
          in the browser clipboard for ~30 minutes. */}
      <PortalResetLinkCopyConfirmModal
        open={copyLinkModalOpen}
        customer={customer}
        email={status?.email || customer.email}
        onClose={() => setCopyLinkModalOpen(false)}
        onConfirm={async () => {
          setCopyLinkModalOpen(false);
          setBusy("portal-reset-link-copy");
          try {
            const r = await api.post(`/customers/${customer.id}/portal-reset-link-copy`);
            const url = r?.reset_url || "";
            let clipboardOk = false;
            try {
              if (navigator?.clipboard?.writeText && url) {
                await navigator.clipboard.writeText(url);
                clipboardOk = true;
              }
            } catch { /* fall through to fallback modal */ }
            if (clipboardOk) {
              onToast({
                tone: "success",
                message: `Link copied — expires in ${r?.token_ttl_minutes || 30} min`,
              });
            } else {
              // Fall back to a modal that shows the URL so the
              // operator can manually copy. This path is common in
              // insecure contexts (http://) and Playwright.
              setCopyFallback({ url, expires_at: r?.expires_at });
            }
            await onDone();
            await loadStatus();
          } catch (e) {
            onToast({ tone: "error", message: e?.message || "Reset link copy failed" });
          } finally {
            setBusy("");
          }
        }}
      />

      <PortalResetLinkCopyFallbackModal
        open={!!copyFallback}
        url={copyFallback?.url || ""}
        expiresAt={copyFallback?.expires_at || null}
        onClose={() => setCopyFallback(null)}
        onCopied={() => onToast({ tone: "success", message: "Link copied to clipboard" })}
      />
    </div>
  );
}

const PORTAL_EVENT_LABELS = {
  portal_login: "Customer signed in",
  portal_reset: "Admin reset password",
  portal_revoke: "Admin revoked access",
  impersonation_started: "Admin viewed as customer",
  impersonation_ended: "Admin ended impersonation",
  admin_password_reset_triggered: "Admin sent reset link",
  admin_password_reset_copied: "Admin copied reset link",
};

/**
 * K30.status-chip · Feb-2026 — chip that reflects the latest row in
 * ``password_reset_tokens`` for this customer. Tone map:
 *   issued  → info    (fresh link out, awaiting click)
 *   used    → success (customer completed the reset)
 *   expired → warning (link went cold without being clicked)
 *   none    → chip is hidden entirely
 */
function _k30RelativeTime(iso) {
  if (!iso) return null;
  try {
    const then = new Date(iso).getTime();
    const now = Date.now();
    const diff = Math.max(0, now - then);
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins} min ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  } catch {
    return null;
  }
}

function PortalResetLinkChip({ data }) {
  if (!data || !data.status || data.status === "none") return null;
  const status = data.status;
  const tone =
    status === "issued" ? "brand"
      : status === "used" ? "success"
      : status === "expired" ? "warning"
      : "neutral";
  const ts = status === "used" ? data.used_at : data.issued_at;
  const rel = _k30RelativeTime(ts);
  const labelBase =
    status === "issued" ? "Reset link issued"
      : status === "used" ? "Reset link used"
      : status === "expired" ? "Reset link expired"
      : `Reset link ${status}`;
  const label = rel ? `${labelBase} · ${rel}` : labelBase;
  return (
    <Chip
      label={label}
      tone={tone}
      testid={`portal-reset-link-chip-${status}`}
    />
  );
}

/**
 * K30 · Feb-2026 — Admin confirmation modal for the tokenized
 * password reset LINK (distinct from PortalResetModal which sends a
 * raw temp password). Shows a masked-email preview so the operator
 * can double-check the recipient before firing the send.
 */
function _k30MaskEmail(email) {
  if (!email || typeof email !== "string" || !email.includes("@")) return email || "";
  const [local, domain] = email.split("@");
  if (!local) return `***@${domain}`;
  return `${local[0]}***@${domain}`;
}

/**
 * K30.copy-admin-link · Feb-2026 — Role gate for the clipboard-copy
 * button. Exported so unit tests can assert the visibility contract
 * without mounting the full CustomerDetail tree.
 */
export function canCopyResetLink(role) {
  return role === "super_admin";
}

function PortalResetLinkConfirmModal({ open, customer, email, onClose, onConfirm }) {
  const masked = _k30MaskEmail(email);
  const name = (customer?.name || "this customer").trim();
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Send password reset link"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} testid="portal-reset-link-cancel">
            Cancel
          </Button>
          <Button
            onClick={onConfirm}
            disabled={!email}
            testid="portal-reset-link-confirm"
          >
            Send reset link
          </Button>
        </>
      }
    >
      <div className="space-y-3" data-testid="portal-reset-link-modal-body">
        <p className="text-sm" style={{ color: colors.onSurface }}>
          Send <strong>{name}</strong> a password reset email at{" "}
          <code data-testid="portal-reset-link-masked-email">{masked || "no email on file"}</code>?
        </p>
        <p className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
          The link expires in 30 minutes and is single-use. If the portal
          account doesn't exist yet, it will be created automatically.
          The customer sets their own password via the link — no temporary
          password is ever emailed.
        </p>
      </div>
    </Modal>
  );
}


/**
 * K30.copy-admin-link · Feb-2026 — Super-admin-only confirm modal
 * for minting a fresh reset URL and copying it to the clipboard.
 * Deliberately louder than the send-reset confirm modal — the
 * operator is about to hold a bearer credential in their clipboard.
 */
export function PortalResetLinkCopyConfirmModal({ open, customer, email, onClose, onConfirm }) {
  const name = (customer?.name || "this customer").trim();
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Copy password reset link"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}
                    testid="portal-reset-link-copy-cancel">
            Cancel
          </Button>
          <Button
            onClick={onConfirm}
            disabled={!email}
            testid="portal-reset-link-copy-confirm"
          >
            Generate and copy
          </Button>
        </>
      }
    >
      <div className="space-y-3" data-testid="portal-reset-link-copy-modal-body">
        <p className="text-sm" style={{ color: colors.onSurface }}>
          Generate and copy a one-time reset link for <strong>{name}</strong>?
        </p>
        <p className="text-xs" style={{ color: colors.warning || colors.onSurfaceSecondary }}>
          This link works for 30 minutes and gives portal access —
          do <strong>not</strong> share by insecure channels
          (public chat, unencrypted email, etc.). The link is
          single-use and no email will be sent from this action.
        </p>
      </div>
    </Modal>
  );
}


/**
 * K30.copy-admin-link · Feb-2026 — Clipboard-permission fallback.
 * Renders the raw reset URL in a readonly input with a "Copy"
 * button so the operator can copy it manually when
 * ``navigator.clipboard.writeText`` fails (insecure context,
 * denied permission, headless browser).
 */
export function PortalResetLinkCopyFallbackModal({ open, url, expiresAt, onClose, onCopied }) {
  const inputRef = React.useRef(null);
  const copy = React.useCallback(async () => {
    try {
      await navigator.clipboard.writeText(url);
      onCopied && onCopied();
    } catch {
      // Last-resort — use the legacy document.execCommand path.
      try {
        if (inputRef.current) {
          inputRef.current.select();
          document.execCommand("copy");
          onCopied && onCopied();
        }
      } catch { /* really cannot copy — user must select manually */ }
    }
  }, [url, onCopied]);
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Copy reset link"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}
                    testid="portal-reset-link-copy-fallback-close">
            Close
          </Button>
          <Button onClick={copy}
                    testid="portal-reset-link-copy-fallback-copy">
            Copy to clipboard
          </Button>
        </>
      }
    >
      <div className="space-y-3" data-testid="portal-reset-link-copy-fallback-body">
        <p className="text-sm" style={{ color: colors.onSurface }}>
          Your browser blocked clipboard access. Select the link
          below and copy it manually, or click <strong>Copy to
          clipboard</strong> to retry.
        </p>
        <input
          ref={inputRef}
          type="text"
          value={url}
          readOnly
          onFocus={(e) => e.target.select()}
          data-testid="portal-reset-link-copy-fallback-input"
          className="w-full px-2 py-1 rounded text-xs font-mono"
          style={{
            backgroundColor: colors.surfaceSecondary,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
        />
        {expiresAt ? (
          <p className="text-xs" style={{ color: colors.onSurfaceSecondary }}
              data-testid="portal-reset-link-copy-fallback-expiry">
            Expires at {new Date(expiresAt).toLocaleString()}.
          </p>
        ) : null}
      </div>
    </Modal>
  );
}

function PortalResetModal({ open, onClose, onSubmit }) {  const [mode, setMode] = React.useState("auto");
  const [password, setPassword] = React.useState("");
  React.useEffect(() => {
    if (open) { setMode("auto"); setPassword(""); }
  }, [open]);
  const canSubmit = mode === "auto" || (mode === "explicit" && password.length >= 8);
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Reset portal password"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} testid="portal-reset-cancel">Cancel</Button>
          <Button
            onClick={() => onSubmit(mode === "explicit" ? password : null)}
            disabled={!canSubmit}
            testid="portal-reset-submit"
          >
            {mode === "auto" ? "Generate & send" : "Set password"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <label className="flex items-start gap-2 text-sm" style={{ color: colors.onSurface }}>
          <input
            type="radio"
            name="reset-mode"
            checked={mode === "auto"}
            onChange={() => setMode("auto")}
            data-testid="portal-reset-mode-auto"
          />
          <div>
            <div className="font-medium">Generate + email to customer</div>
            <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
              A one-time password is generated and emailed via Resend. If Resend is
              not configured, the password is returned here so you can share it manually.
            </div>
          </div>
        </label>
        <label className="flex items-start gap-2 text-sm" style={{ color: colors.onSurface }}>
          <input
            type="radio"
            name="reset-mode"
            checked={mode === "explicit"}
            onChange={() => setMode("explicit")}
            data-testid="portal-reset-mode-explicit"
          />
          <div className="flex-1">
            <div className="font-medium">Set a specific password</div>
            <div className="text-xs mb-2" style={{ color: colors.onSurfaceSecondary }}>
              Minimum 8 characters, at least one uppercase, one lowercase, one digit.
            </div>
            {mode === "explicit" ? (
              <TextInput
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="New password"
                type="password"
                autoFocus
                testid="portal-reset-password-input"
              />
            ) : null}
          </div>
        </label>
      </div>
    </Modal>
  );
}

function PortalLoginModal({ open, onClose, customer, onDone, onError }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setEmail(customer?.email || "");
      setPassword("");
    }
  }, [open, customer]);
  const submit = async () => {
    setBusy(true);
    try {
      await api.post(`/customers/${customer.id}/create-login`, { email, password });
      onDone("Portal login created");
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create portal login"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={busy || !email || !password} testid="cd-login-submit">
            {busy ? "Creating…" : "Create login"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <TextInput label="EMAIL" value={email} onChange={(e) => setEmail(e.target.value)} testid="cd-login-email" />
        <TextInput
          label="PASSWORD (≥8 chars, upper + lower + digit)"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          testid="cd-login-password"
        />
      </div>
    </Modal>
  );
}

// ─── Feb-2026 Customer Detail Additions helper modals ────────────────

function VipNoteModal({ open, onClose, customer, onSave }) {
  const [note, setNote] = useState("");
  useEffect(() => {
    if (open) setNote(customer?.vip_note || "");
  }, [open, customer]);
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="VIP note"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={() => onSave(note.trim())} testid="cd-vip-note-save">
            Save note
          </Button>
        </>
      }
    >
      <div className="space-y-2">
        <p className="text-xs" style={{ color: colors.muted }}>
          Add context for teammates — service preferences, escalation contacts, do-not-disturb hours.
        </p>
        <textarea
          className="w-full min-h-[120px] px-3 py-2 rounded-lg text-sm"
          style={{
            backgroundColor: colors.surface,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="e.g. Big HOA — always call before visiting. Escalate to Maria on 555-…"
          data-testid="cd-vip-note-textarea"
        />
      </div>
    </Modal>
  );
}


// ═══════════════════════════════════════════════════════════════════
// Phase P7 · Feb-2026 — Send-email inline "Upload from computer".
// ═══════════════════════════════════════════════════════════════════
// Constants shared between the modal and the vitest suite.
//
// * ``P7_EMAIL_ATTACH_ACCEPT`` — mirrors the backend whitelist. Used
//   directly on the hidden ``<input type="file" accept=…>`` so the
//   OS-native picker filters non-whitelisted types before they even
//   reach client-side validation. A duplicate JS-side whitelist runs
//   below because ``accept`` is a hint, not a hard gate.
// * ``P7_EMAIL_ATTACH_TYPES`` — the JS-side hard whitelist.
// * ``P7_EMAIL_ATTACH_MAX_BYTES`` — 10 MB per file (matches backend).
// * ``P7_EMAIL_ATTACH_MAX_COUNT`` — 5 attachments per send (matches
//   backend).
const P7_EMAIL_ATTACH_TYPES = new Set([
  "image/jpeg", "image/png", "image/webp",
  "image/heic", "image/heif",
  "application/pdf",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "text/csv",
]);
const P7_EMAIL_ATTACH_ACCEPT = Array.from(P7_EMAIL_ATTACH_TYPES).join(",");
const P7_EMAIL_ATTACH_MAX_BYTES = 10 * 1024 * 1024;   // 10 MB
const P7_EMAIL_ATTACH_MAX_COUNT = 5;                   // per-send cap


function SendComposeModal({ payload, customer, onClose, onSent, onError }) {
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  // TD-100-sub-template · Feb-2026 — template-list fetch + picker JSX
  // extracted to ``components/communications/TemplatePickerPreview``.
  // Parent still owns ``pickedId`` (controlled) + preview state because
  // operator edits subject/message after pick, and the Preview pane
  // mounts in this editor column, not the picker aside.
  const [pickedId, setPickedId] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState(null);
  // Feb-2026 · Customer-Attachments (Option D) — media picker state.
  // ``attachments`` is an array of ``{id, file_name, mime_type, ...}``
  // objects gathered by the multi-select MediaLibraryPicker. When the
  // user hits Send we ship the ids in the request body; the backend
  // resolves them to inbox-visible attachments (email) or
  // signed-URL-suffixed body (SMS).
  const [attachOpen, setAttachOpen] = useState(false);
  const [attachments, setAttachments] = useState([]);
  // ── Phase P7 · Feb-2026 — "Upload from computer" inline picker
  //    (email only). Reuses ``POST /api/marketing/media/upload`` so
  //    the resulting rows land in the same Option D pipeline as any
  //    media-library pick. State shapes:
  //      * ``uploading``   — Map<tempId, {name, size, progress, xhr}>
  //      * ``uploadError`` — inline error string when client-side
  //                         validation (size/type/count) rejects a
  //                         selection BEFORE any upload fires.
  //      * ``waitingUploads`` — flash notice shown when the operator
  //                         clicks Send while any upload is still in
  //                         flight. Cleared as soon as they interact
  //                         again or all uploads complete.
  const [uploading, setUploading] = useState(() => new Map());
  const [uploadError, setUploadError] = useState("");
  const [waitingUploads, setWaitingUploads] = useState(false);
  const uploadInputRef = React.useRef(null);
  const isEmail = payload?.channel === "email";
  useEffect(() => {
    if (payload) {
      setSubject("");
      setMessage("");
      setPickedId("");
      setPreview(null);
      setAttachments([]);   // reset per-open
      // ── P7 · reset uploads too so a re-open doesn't leak
      //    an in-flight XHR from a prior compose session.
      setUploading((prev) => {
        prev.forEach((r) => { try { r.xhr && r.xhr.abort(); } catch { /* noop */ } });
        return new Map();
      });
      setUploadError("");
      setWaitingUploads(false);
      // TD-100-sub-template · Feb-2026 — template fetch moved into
      // ``<TemplatePickerPreview>``. Modal-open resets still live here
      // because they coordinate with attachment + upload state that
      // the sub-primitive does not own.
    }
  }, [payload, isEmail]);
  // ── Phase P7 · Feb-2026 — auto-clear the waiting-uploads flash
  //    notice once every upload has settled (success OR abort). The
  //    operator can now click Send without re-mounting the modal.
  useEffect(() => {
    if (waitingUploads && uploading.size === 0) {
      setWaitingUploads(false);
    }
  }, [uploading, waitingUploads]);
  const pickTemplate = (t) => {
    setPickedId(t?.id || "");
    if (!t) {
      // Reset to "Custom message" — blank fields.
      setSubject("");
      setMessage("");
      return;
    }
    setSubject(t.subject || "");
    setMessage(t.body || "");
  };
  const runPreview = async () => {
    if (!message.trim()) {
      onError("Nothing to preview");
      return;
    }
    setPreviewing(true);
    try {
      const r = await api.post(`/customers/${customer.id}/preview-message`, {
        channel: isEmail ? "email" : "sms",
        subject: subject || "",
        body: message || "",
      });
      setPreview(r);
    } catch (e) {
      onError(e?.message || "Preview failed");
    } finally { setPreviewing(false); }
  };
  if (!payload) return null;

  // ── Phase P7 · Feb-2026 — inline uploader helpers ────────────
  // Kick a hidden ``<input type=file>``. The button reuses the same
  // accept whitelist the backend enforces, so the native picker
  // hides most non-whitelisted types up-front; the JS whitelist
  // below is the actual gate.
  const _openNativePicker = () => {
    setUploadError("");
    setWaitingUploads(false);
    uploadInputRef.current?.click();
  };

  // XHR upload against the existing ``POST /api/marketing/media/upload``
  // endpoint (multipart). Progress tracking + cancel are baked in so
  // the modal can drop an in-flight upload cleanly.
  const _uploadOne = (file, tempId) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("alt_text", "");
    const base = process.env.REACT_APP_BACKEND_URL || "";
    const url = `${base}/api/marketing/media/upload`;
    const token = (typeof window !== "undefined")
      ? window.localStorage.getItem("token") : "";
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const pct = (e.loaded / e.total) * 100;
      setUploading((prev) => {
        const next = new Map(prev);
        const row = next.get(tempId);
        if (row) { next.set(tempId, { ...row, progress: pct }); }
        return next;
      });
    };
    xhr.onload = () => {
      // Drop the row from ``uploading`` regardless of outcome — a
      // failure just leaves nothing attached; success promotes the
      // upload into ``attachments``.
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const created = JSON.parse(xhr.responseText);
          setAttachments((prev) => {
            const byId = new Map(prev.map((a) => [a.id, a]));
            byId.set(created.id, {
              id:         created.id,
              file_name:  created.file_name || file.name,
              mime_type:  created.mime_type || file.type,
              size_bytes: created.size_bytes || file.size,
            });
            return Array.from(byId.values());
          });
        } catch {
          onError && onError("Upload response was malformed");
        }
      } else {
        try {
          const body = JSON.parse(xhr.responseText);
          onError && onError(
            body?.detail?.message || body?.detail || `Upload failed (${xhr.status})`,
          );
        } catch {
          onError && onError(`Upload failed (${xhr.status})`);
        }
      }
      setUploading((prev) => {
        const next = new Map(prev);
        next.delete(tempId);
        return next;
      });
    };
    xhr.onerror = () => {
      onError && onError("Network error uploading file");
      setUploading((prev) => {
        const next = new Map(prev);
        next.delete(tempId);
        return next;
      });
    };
    xhr.send(fd);
    return xhr;
  };

  const _handleFilesSelected = (files) => {
    setUploadError("");
    setWaitingUploads(false);
    if (!files || files.length === 0) return;
    const picked = Array.from(files);
    // 1. Type gate. ``accept=`` isn't authoritative — a user can
    //    change the OS picker's filter to "All files" so we re-check.
    const badType = picked.find((f) => !P7_EMAIL_ATTACH_TYPES.has(f.type));
    if (badType) {
      setUploadError(
        `File type not allowed for email attachments: ${badType.name}. ` +
        `Images, PDFs, and Office/CSV docs only.`,
      );
      return;
    }
    // 2. Size gate — client-side, BEFORE upload. Matches server 10 MB.
    const tooBig = picked.find((f) => f.size > P7_EMAIL_ATTACH_MAX_BYTES);
    if (tooBig) {
      setUploadError(
        `File too large — 10 MB max for email attachments (${tooBig.name}).`,
      );
      return;
    }
    // 3. Per-send cap (already-uploaded + in-flight + new picks).
    const inFlight = uploading.size;
    const existing = attachments.length;
    if (existing + inFlight + picked.length > P7_EMAIL_ATTACH_MAX_COUNT) {
      setUploadError(
        `Maximum ${P7_EMAIL_ATTACH_MAX_COUNT} attachments per email.`,
      );
      return;
    }
    // Stamp a client-side tempId + kick each upload in parallel.
    setUploading((prev) => {
      const next = new Map(prev);
      picked.forEach((f) => {
        const tempId = `up-${Math.random().toString(36).slice(2, 10)}`;
        const xhr = _uploadOne(f, tempId);
        next.set(tempId, {
          name: f.name, size: f.size, progress: 0, xhr,
        });
      });
      return next;
    });
  };

  const _cancelUpload = (tempId) => {
    setUploading((prev) => {
      const next = new Map(prev);
      const row = next.get(tempId);
      if (row?.xhr) {
        try { row.xhr.abort(); } catch { /* noop */ }
      }
      next.delete(tempId);
      return next;
    });
  };

  const submit = async () => {
    if (!message.trim()) {
      onError("Message body required");
      return;
    }
    // ── Phase P7 · Feb-2026 — block send while uploads are in-flight.
    //    Better UX than a disabled button because the operator can
    //    see a plain-language explanation ("Wait for uploads to
    //    finish…") next to the Send control. The click is a no-op
    //    so we don't lose the composed subject/body/attachments.
    if (isEmail && uploading.size > 0) {
      setWaitingUploads(true);
      return;
    }
    setBusy(true);
    try {
      // Feb-2026 · Customer-Attachments (Option D) — include attachment
      // file IDs when the operator picked any. Omit the field entirely
      // (don't send an empty array) so the backend's default branch
      // stays quiet.
      const attachmentIds = attachments.map((a) => a.id).filter(Boolean);
      if (isEmail) {
        const body = {
          to: payload.to,
          subject: subject || `Message from ${customer?.name || "your service"}`,
          body: message,
          customer_id: customer?.id,
        };
        if (attachmentIds.length > 0) body.attachments = attachmentIds;
        await api.post(`/customers/${customer.id}/send-email`, body);
      } else {
        // BUG F · Feb 2026 — POST to the customer-scoped SMS endpoint
        // (was hitting the non-existent ``/sms/send`` which 404'd with
        // "not found"). New wrapper mirrors ``send-email`` — validates
        // the recipient against the customer's mirrored phones and
        // persists a ``customer_direct_message`` comms_log row.
        const body = {
          to: payload.to,
          body: message,
          customer_id: customer?.id,
        };
        if (attachmentIds.length > 0) body.attachments = attachmentIds;
        await api.post(`/customers/${customer.id}/send-sms`, body);
      }
      onSent();
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={!!payload}
      onClose={onClose}
      title={isEmail ? `Email ${payload.to}` : `Text ${payload.to}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="ghost" onClick={runPreview} disabled={busy || previewing}
                  testid="cd-send-preview">
            {previewing ? "Previewing…" : "Preview"}
          </Button>
          <Button onClick={submit} disabled={busy} testid="cd-send-submit">
            {busy ? "Sending…" : "Send"}
          </Button>
        </>
      }
    >
      <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 16 }}>
        {/* TD-100-sub-template · Feb-2026 — template picker aside
            extracted to a shared sub-primitive. Parent owns
            ``pickedId`` (controlled) + the pickTemplate side-effects
            on ``subject`` / ``message``. */}
        <TemplatePickerPreview
          channel={isEmail ? "email" : "sms"}
          recipientId={customer?.id}
          pickedId={pickedId}
          onPick={pickTemplate}
        />
        {/* Editor */}
        <div className="space-y-3">
          {isEmail ? (
            <TextInput
              label="SUBJECT"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              testid="cd-send-subject"
            />
          ) : null}
          <div>
            <div className="text-xs font-semibold mb-1 flex items-center justify-between"
                  style={{ color: colors.muted }}>
              <span>MESSAGE</span>
              {!isEmail ? (
                <span data-testid="cd-send-char-count">
                  {message.length} chars
                </span>
              ) : null}
            </div>
            <textarea
              className="w-full min-h-[220px] px-3 py-2 rounded-lg text-sm"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              data-testid="cd-send-message"
            />
          </div>
          {/* Feb-2026 · Customer-Attachments (Option D) — attach files
              row.  Paperclip trigger opens the multi-select media
              library picker; selected files render as removable chips.
              For SMS, we surface a hint that files are appended as
              download links (not carried in-band). */}
          <div data-testid="cd-send-attachments-row">
            <div
              className="text-xs font-semibold mb-1"
              style={{ color: colors.muted }}
            >
              ATTACHMENTS
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                onClick={() => setAttachOpen(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border"
                style={{
                  borderColor: colors.border,
                  color: colors.onSurface,
                  background: colors.surface,
                }}
                data-testid="cd-send-attach-btn"
                aria-label="Attach files from media library"
              >
                <Paperclip className="w-3.5 h-3.5" />
                Attach files
              </button>
              {/* Phase P7 · Feb-2026 — inline "Upload from computer"
                  button + hidden native file input. Email only —
                  ``!isEmail`` short-circuits so the SMS branch renders
                  exactly like it did pre-P7. */}
              {isEmail ? (
                <>
                  <button
                    type="button"
                    onClick={_openNativePicker}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border"
                    style={{
                      borderColor: colors.border,
                      color: colors.onSurface,
                      background: colors.surface,
                    }}
                    data-testid="cd-send-attach-upload-btn"
                    aria-label="Upload files from your computer"
                  >
                    <Paperclip className="w-3.5 h-3.5" />
                    Upload from computer
                  </button>
                  <input
                    ref={uploadInputRef}
                    type="file"
                    multiple
                    accept={P7_EMAIL_ATTACH_ACCEPT}
                    onChange={(e) => {
                      _handleFilesSelected(e.target.files);
                      // Reset so re-picking the same filename fires
                      // ``onChange`` a second time.
                      e.target.value = "";
                    }}
                    style={{ display: "none" }}
                    data-testid="cd-send-attach-upload-input"
                  />
                </>
              ) : null}
              {attachments.length === 0 ? (
                <span
                  className="text-xs"
                  style={{ color: colors.muted }}
                  data-testid="cd-send-attach-empty"
                >
                  No files attached
                </span>
              ) : null}
              {/* Phase P7 · Feb-2026 — in-flight upload progress rows.
                  Each row shows the filename + a small progress % and
                  an X to cancel the underlying XHR. Rendered inline
                  with the completed chips so the user sees them as
                  part of the attachment list. */}
              {Array.from(uploading.entries()).map(([tempId, row]) => (
                <span
                  key={tempId}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs"
                  style={{
                    background: colors.surface,
                    color: colors.onSurface,
                    border: `1px dashed ${colors.border}`,
                  }}
                  data-testid={`cd-send-attach-uploading-${tempId}`}
                  title={row.name}
                >
                  <FileText className="w-3 h-3" />
                  <span className="max-w-[160px] truncate">
                    {row.name}
                  </span>
                  <span
                    className="text-[10px]"
                    style={{ color: colors.muted }}
                    data-testid={`cd-send-attach-uploading-progress-${tempId}`}
                  >
                    {Math.round(row.progress || 0)}%
                  </span>
                  <button
                    type="button"
                    onClick={() => _cancelUpload(tempId)}
                    className="ml-0.5 text-zinc-400 hover:text-zinc-900"
                    aria-label={`Cancel upload of ${row.name}`}
                    data-testid={`cd-send-attach-upload-cancel-${tempId}`}
                  >
                    <XIcon className="w-3 h-3" />
                  </button>
                </span>
              ))}
              {attachments.map((a) => (
                <span
                  key={a.id}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs"
                  style={{
                    background: colors.surfaceSecondary,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid={`cd-send-attach-chip-${a.id}`}
                  title={a.file_name || a.id}
                >
                  <FileText className="w-3 h-3" />
                  <span className="max-w-[160px] truncate">
                    {a.file_name || a.id}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setAttachments((prev) =>
                        prev.filter((x) => x.id !== a.id),
                      )
                    }
                    className="ml-0.5 text-zinc-400 hover:text-zinc-900"
                    aria-label={`Remove ${a.file_name || a.id}`}
                    data-testid={`cd-send-attach-remove-${a.id}`}
                  >
                    <XIcon className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
            {!isEmail && attachments.length > 0 ? (
              <div
                className="text-[11px] mt-1.5"
                style={{ color: colors.muted }}
                data-testid="cd-send-attach-sms-hint"
              >
                SMS can't carry files — download links will be appended
                to the message body.
              </div>
            ) : null}
            {/* Phase P7 · Feb-2026 — inline error surfaces when the
                client-side gate rejects a selection (type / size /
                count). Doesn't block subsequent uploads; picking a
                valid file clears it. */}
            {isEmail && uploadError ? (
              <div
                className="text-[11px] mt-1.5"
                style={{ color: "#B91C1C" }}
                data-testid="cd-send-attach-error"
                role="alert"
              >
                {uploadError}
              </div>
            ) : null}
            {/* Phase P7 · Feb-2026 — waiting-uploads flash notice.
                Fires only when the operator clicks Send while any
                upload is still in flight. Auto-cleared once uploads
                complete (see the ``uploading.size === 0`` effect). */}
            {isEmail && waitingUploads ? (
              <div
                className="text-[11px] mt-1.5"
                style={{ color: "#B45309" }}
                data-testid="cd-send-attach-waiting-uploads"
                role="status"
              >
                Wait for attachments to finish uploading…
              </div>
            ) : null}
          </div>
          {preview ? (
            <div className="rounded-lg p-3 text-sm"
                 style={{ background: colors.surfaceSecondary,
                            border: `1px solid ${colors.border}` }}
                 data-testid="cd-send-preview-panel">
              <div className="text-xs font-semibold mb-1"
                    style={{ color: colors.muted }}>
                PREVIEW — merge tags resolved for {customer?.name || "this customer"}
              </div>
              {preview.subject_rendered ? (
                <div className="text-sm font-semibold mb-1"
                      data-testid="cd-send-preview-subject">
                  {preview.subject_rendered}
                </div>
              ) : null}
              {isEmail ? (
                <div dangerouslySetInnerHTML={{ __html: preview.body_rendered || "" }}
                     data-testid="cd-send-preview-body-html"
                     style={{ color: colors.onSurface }} />
              ) : (
                <pre style={{ whiteSpace: "pre-wrap", color: colors.onSurface,
                               fontFamily: "inherit", margin: 0 }}
                      data-testid="cd-send-preview-body-text">
                  {preview.body_rendered}
                </pre>
              )}
              {preview.unresolved_tokens && preview.unresolved_tokens.length > 0 ? (
                <div className="text-xs mt-2" style={{ color: "#B45309" }}
                      data-testid="cd-send-preview-unresolved">
                  Unresolved: {preview.unresolved_tokens.join(", ")}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      {/* Feb-2026 · Customer-Attachments (Option D) — multi-select
          media library picker.  Rendered as a sibling <Dialog> so it
          layers on top of the compose modal.  ``kind={null}`` shows
          both images and documents; the user filters inside the
          picker. */}
      <MediaLibraryPicker
        open={attachOpen}
        onOpenChange={setAttachOpen}
        multiSelect
        onSelectMultiple={(items) => {
          // De-dupe by id when the user re-opens the picker after an
          // initial pick.
          setAttachments((prev) => {
            const byId = new Map(prev.map((a) => [a.id, a]));
            items.forEach((it) => { byId.set(it.id, it); });
            return Array.from(byId.values());
          });
        }}
      />
    </Modal>
  );
}

// Feb-2026 · Customer-Attachments (Option D) — test-only re-export.
// The Vitest suite (``customer-attach-files.test.jsx``) mounts the
// modal in isolation to exercise the attach + submit flow without
// spinning up the full CustomerDetail page.  Kept separate from
// the default export so runtime consumers still just render the
// page component.
export const CustomerDetailModule = { SendComposeModal };



