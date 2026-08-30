import React, { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { ArrowLeft, Edit3, Trash2, Mail, Phone, MapPin, BellRing, Beaker, KeyRound, Briefcase, FileText, StickyNote, Droplets, Star, ListChecks, Home, DollarSign } from "lucide-react";
import { api } from "@/api";
import { colors } from '@/theme';
import ClickToCallButton from "@/components/telephony/ClickToCallButton";
import { Button, Modal, TextInput, Skeleton, Chip, StatusPill, EmptyState, Toast } from "@/components/ui-kit";
import { ActivationControl } from "@/components/customers/ActivationControl";
import CustomerEquipmentLibrary from "@/components/customers/CustomerEquipmentLibrary";
import CustomerActionDropdowns from "@/components/customers/CustomerActionDropdowns";
import CustomerTagPicker from "@/components/customers/CustomerTagPicker";
import CustomerTagsCard from "@/components/customers/CustomerTagsCard";
import DemoAccountToggle from "@/components/comms/DemoAccountToggle";
import CustomerCommunicationsTimeline from "@/components/customers/CustomerCommunicationsTimeline";
import CustomerTasksPanel from "@/components/customers/CustomerTasksPanel";
import CustomerContactsPanel from "@/components/customers/CustomerContactsPanel";
import CustomerServiceNotesCards from "@/components/customers/CustomerServiceNotesCards";
import PropertiesTab from "./PropertiesTab";
import MasterBillingCard from "./MasterBillingCard";
import { CustomerCreditsPanel } from "./CustomerCreditsPage";


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
function PortalInviteQuickAction({ customer, onToast }) {
  const [busy, setBusy] = React.useState(false);
  const [payload, setPayload] = React.useState(null);
  const email = (
    (customer.emails || []).find((e) => e && e.address)?.address
    || customer.email
    || ""
  );
  const hasEmail = !!email.trim();

  const send = async () => {
    setBusy(true);
    setPayload(null);
    try {
      const r = await api.post(`/customers/${customer.id}/portal-invite`);
      if (r?.emailed) {
        onToast?.({ tone: "success",
                     message: `Portal invite email sent to ${r.email}` });
      } else if (r?.password) {
        setPayload({ link: r.login_url, email: r.email, password: r.password });
        onToast?.({ tone: "info",
                     message: "Portal invite link ready — share it manually" });
      } else {
        onToast?.({ tone: "success", message: "Portal invite sent" });
      }
    } catch (e) {
      onToast?.({ tone: "error", message: e.message || "Portal invite failed" });
    } finally {
      setBusy(false);
    }
  };

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
    </div>
  );
}
import CardOnFileControl from "@/components/customers/CardOnFileControl";
import CardOnFileWarningBanner from "@/components/customers/CardOnFileWarningBanner";
import CustomerDeleteModal from "@/components/customers/CustomerDeleteModal";
import CustomerReviewsTab from "@/components/customers/CustomerReviewsTab";
import AdminCardCapturePanel from "@/components/customers/AdminCardCapturePanel";
// Phase B4 · Feb-2026 — Stripe subscription CRUD panel.
import SubscriptionsPanel from "./SubscriptionsPanel";
import ResponsiveTabs from "@/components/ui/responsive-tabs";

const TABS = [
  { k: "overview", label: "Overview", icon: MapPin },
  { k: "properties", label: "Properties", icon: Home },
  { k: "jobs", label: "Jobs", icon: Briefcase },
  { k: "quotes", label: "Quotes", icon: FileText },
  { k: "invoices", label: "Invoices", icon: FileText },
  { k: "equipment", label: "Equipment", icon: Beaker },
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
  const [customer, setCustomer] = useState(null);
  const [jobs, setJobs] = useState([]);
  // Feb-2026 · Customer profile — primary-property address line under
  // the name (see the header render). Fetched alongside customer +
  // jobs so the address can appear in the first paint.
  const [properties, setProperties] = useState([]);
  const [tab, setTab] = useState("overview");
  const [toast, setToast] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Feb-2026 · Customer Delete UX overhaul — which mode is currently
  // in flight from the modal. null = idle, "soft" | "hard" = busy.
  const [deleteBusyMode, setDeleteBusyMode] = useState(null);
  const [loginModal, setLoginModal] = useState(false);
  const [vipModal, setVipModal] = useState(false);
  const [sendModal, setSendModal] = useState(null); // { channel, to }
  const [taskQuickAddOpener, setTaskQuickAddOpener] = useState(null);
  // Phase 12 · Feb 2026 — role + tenant default fetched once for the
  // card-on-file admin controls. Techs never see the toggle at all.
  const [meRole, setMeRole] = useState("");
  const [tenantDefault, setTenantDefault] = useState(true);

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

  const load = async () => {
    try {
      const [c, allJobs, props] = await Promise.all([
        api.get(`/customers/${id}`),
        api.get("/jobs"),
        // Feb-2026 · Customer profile — properties fetched for the
        // primary-address line under the customer name. Non-fatal:
        // if the call fails we still render the rest of the page and
        // just show "No address on file".
        api.get(`/customers/${id}/properties`).catch(() => []),
      ]);
      setCustomer(c);
      setJobs((allJobs || []).filter((j) => j.customer_id === id));
      setProperties(Array.isArray(props) ? props : []);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

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

  const reopenJob = async (jid) => {
    try {
      await api.post(`/jobs/${jid}/reopen`);
      setToast({ tone: "success", message: "Job reopened" });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

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
    return (
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <Skeleton style={{ height: 160 }} />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="customer-detail">
      <button
        onClick={() => navigate("/customers")}
        className="flex items-center gap-1 text-sm font-semibold mb-4"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> All customers
      </button>

      {/* Phase 12 · Feb 2026 — Card-on-file requirement banner. Only
          shows when effective_require_card_on_file && !has_card_on_file.
          Admin + manager only (techs never see this). */}
      {canSeeCardControls && (
        <CardOnFileWarningBanner
          customer={customer}
          onSent={(msg) => setToast({ tone: "success", message: msg })}
          onError={(msg) => setToast({ tone: "error", message: msg })}
        />
      )}

      {/* Header card */}
      <div
        className="rounded-2xl p-6 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
                {customer.name}
              </h1>
              {customer.customer_since ? (
                <span
                  data-testid="customer-since-label"
                  title={customer.customer_since}
                  className="text-xs font-medium px-2 py-1 rounded"
                  style={{ background: colors.surfaceSecondary,
                              color: colors.onSurfaceSecondary }}
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
                    style={{ color: colors.muted }}
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
                  style={{ color: colors.onSurfaceSecondary }}
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
          <div
            className="flex flex-row flex-nowrap items-center gap-2 overflow-x-auto"
            data-testid="cd-action-row"
          >
            {/* Feb-2026 Customer Detail Additions — top-right Send + Create dropdowns */}
            <CustomerActionDropdowns
              customer={customer}
              onSend={openSendModal}
              onQuickTask={openQuickTaskFromDropdown}
            />
            <Button variant="ghost" className="px-2.5 py-1 text-xs" onClick={() => navigate(`/customers/${id}/edit`)} testid="cd-edit">
              <Edit3 size={14} /> Edit
            </Button>
            <Button
              variant="ghost"
              className="px-2.5 py-1 text-xs"
              onClick={() => navigate(`/customers/${id}/chemistry`)}
              testid="cd-chemistry"
            >
              <Beaker size={14} /> Chemistry
            </Button>
            <Button
              variant="ghost"
              className="px-2.5 py-1 text-xs"
              onClick={() => navigate(`/customers/${id}/chemistry-history`)}
              testid="cd-chemistry-history"
            >
              <Beaker size={14} /> Chem History
            </Button>
            <Button variant="danger" className="px-2.5 py-1 text-xs" onClick={() => setConfirmDelete(true)} testid="cd-delete">
              <Trash2 size={14} /> Delete
            </Button>
            {/* Phase 6B · Feb 2026 — one-click RingCentral call. Feb-2026 UX
                cleanup — action bar consolidated to a single row, so we
                suppress the ClickToCallButton's stacked ``Dial from this
                device`` fallback and render it here as a compact icon-
                only sibling with a tooltip. All click handlers, phone
                normalization, and RingCentral wiring stay identical. */}
            {(() => {
              const primary =
                (customer.mobiles && customer.mobiles[0]?.number_e164) ||
                customer.phone;
              if (!primary) return null;
              const telHref = `tel:${String(primary).replace(/[^0-9+]/g, "")}`;
              return (
                <div
                  className="inline-flex items-center gap-1"
                  data-testid="cd-click-to-call-wrapper"
                >
                  <ClickToCallButton
                    phoneNumber={primary}
                    entityKind="customer"
                    entityId={customer.id}
                    label={`Call ${customer.name || "customer"}`}
                    testIdPrefix="cd-click-to-call"
                    size="sm"
                    showFallback={false}
                  />
                  <a
                    href={telHref}
                    className="inline-flex items-center justify-center w-7 h-7 rounded-md text-slate-500 hover:text-slate-800 hover:bg-slate-100"
                    title="Dial from this device"
                    aria-label="Dial from this device"
                    data-testid="cd-click-to-call-tel-fallback"
                  >
                    <Phone size={12} />
                  </a>
                </div>
              );
            })()}
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
                  : customer.phone,
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
            { icon: BellRing, label: "Alert phone", value: customer.alert_phone, warn: true },
            { icon: BellRing, label: "Alert email", value: customer.alert_email, warn: true },
          ].map((c) => (
            <div
              key={c.label}
              className="rounded-xl p-3"
              style={{
                backgroundColor: colors.surfaceSecondary,
                border: `1px solid ${colors.border}`,
              }}
              data-testid={c.testid}
            >
              <div className="flex items-center gap-1.5 text-xs mb-1" style={{ color: c.warn ? "#A16207" : colors.muted }}>
                <c.icon size={12} />
                <span className="uppercase font-semibold">{c.label}</span>
              </div>
              <div className="text-sm font-semibold truncate" style={{ color: colors.onSurface }}>
                {c.value || "—"}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Tabs — Feb-2026 · migrated to <ResponsiveTabs>. Desktop
          keeps the identical horizontal strip; <md renders a
          full-width dropdown so the 12-tab list stops requiring a
          horizontal scroll. Parent still owns ``tab`` state, so
          deep-linking (see the initial ``tab`` from URL query in
          the ``useCustomerTabParam`` block above) is preserved. */}
      <div
        className="rounded-2xl overflow-hidden mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <ResponsiveTabs
          tabs={TABS}
          active={tab}
          onChange={setTab}
          testidPrefix="cd-tab"
          ariaLabel="Customer sections"
        />
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
              <CustomerContactsPanel
                customer={customer}
                onSaved={(updated) => {
                  setCustomer((c) => ({ ...c, ...updated }));
                  setToast({ tone: "success", message: "Contacts saved" });
                }}
                onError={(msg) => setToast({ tone: "error", message: msg })}
              />
              {/* Feb-2026 · Send Portal Invite relocated from the
                  Portal Access tab to the main Contact card.  Same
                  handler + API + toast shape as the old Portal
                  Access panel button; disabled when the customer
                  has no email on file.  See the PRD queue entry
                  #1 for the relocation spec. */}
              <PortalInviteQuickAction
                customer={customer}
                onToast={(t) => setToast(t)}
              />
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
                <Info label="Primary address" value={customer.address} />
                <Info label="Billing address" value={customer.billing_address} />
                <Info label="Gate code" value={customer.gate_code} />
                {(customer.secondary_addresses || []).length ? (
                  <div>
                    <div className="text-xs uppercase font-semibold mb-1" style={{ color: colors.muted }}>
                      Secondary addresses
                    </div>
                    <ul className="space-y-1 text-sm" style={{ color: colors.onSurface }}>
                      {customer.secondary_addresses.map((a, i) => (
                        <li key={i}>· {a}</li>
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
              <Info label="Notes" value={customer.notes} preserveNewlines />
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
              <ul className="space-y-2" data-testid="cd-jobs-list">
                {jobs.map((j) => (
                  <li
                    key={j.id}
                    className="flex items-center gap-3 p-3 rounded-xl transition hover:brightness-95"
                    style={{
                      backgroundColor: colors.surfaceSecondary,
                      border: `1px solid ${colors.border}`,
                    }}
                  >
                    <Link to={`/jobs/${j.id}`} className="flex-1 min-w-0" data-testid={`cd-job-${j.id}`}>
                      <div className="text-sm font-semibold truncate" style={{ color: colors.onSurface }}>
                        {j.title}
                      </div>
                      <div className="text-xs" style={{ color: colors.muted }}>
                        {j.scheduled_date || "Unscheduled"} · {j.technician_name || "Unassigned"}
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
                  </li>
                ))}
              </ul>
            )
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

          {tab === "tasks" ? (
            <CustomerTasksPanel
              customerId={id}
              registerOpener={(fn) => setTaskQuickAddOpener(() => fn)}
            />
          ) : null}

          {tab === "notes" ? (
            <Info label="Notes" value={customer.notes} preserveNewlines />
          ) : null}

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


function PortalAccessPanel({ customer, onDone, onToast, openLogin }) {
  const [busy, setBusy] = React.useState("");
  const [inviteLink, setInviteLink] = React.useState(null);
  const [tempPassword, setTempPassword] = React.useState(null);
  const [status, setStatus] = React.useState(null);
  const [history, setHistory] = React.useState([]);
  const [resetModalOpen, setResetModalOpen] = React.useState(false);

  const loadStatus = React.useCallback(async () => {
    try {
      const [s, h] = await Promise.all([
        api.get(`/customers/${customer.id}/portal-status`),
        api.get(`/customers/${customer.id}/portal-history?limit=25`),
      ]);
      setStatus(s || null);
      setHistory((h && h.events) || []);
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
    setBusy("impersonate");
    try {
      const r = await api.post(`/admin/impersonate/${customer.id}`);
      if (r?.access_token) {
        localStorage.setItem("token", r.access_token);
        if (r.user) localStorage.setItem("user", JSON.stringify(r.user));
        window.location.href = "/portal/home";
      }
    } catch (e) { onToast({ tone: "error", message: e.message }); }
    finally { setBusy(""); }
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
          </div>
        )}
      </div>

      {/* Actions.  Feb-2026 · the customer-facing invite CTA MOVED
          to the main Contact card in the Overview tab
          (``PortalInviteQuickAction``); this panel keeps only the
          advanced portal-access actions. */}
      <div className="flex flex-wrap gap-2">
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
              disabled={busy === "impersonate" || !active}
              testid="cd-impersonate"
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
    </div>
  );
}

const PORTAL_EVENT_LABELS = {
  portal_login: "Customer signed in",
  portal_reset: "Admin reset password",
  portal_revoke: "Admin revoked access",
  impersonation_started: "Admin viewed as customer",
  impersonation_ended: "Admin ended impersonation",
};

function PortalResetModal({ open, onClose, onSubmit }) {
  const [mode, setMode] = React.useState("auto");
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


function SendComposeModal({ payload, customer, onClose, onSent, onError }) {
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  // Phase 29 · Feb 2026 — template picker + preview state. Template list
  // is fetched once when the modal opens; ``pickedId`` = "" ("Custom
  // message") by default so operators can compose from scratch without
  // a template. Selecting a template populates ``subject`` + ``message``
  // and the operator can edit before sending.
  const [templates, setTemplates] = useState([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [pickedId, setPickedId] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState(null);
  const isEmail = payload?.channel === "email";
  useEffect(() => {
    if (payload) {
      setSubject("");
      setMessage("");
      setPickedId("");
      setPreview(null);
      setTemplatesLoading(true);
      api.get(`/marketing/templates?channel=${isEmail ? "email" : "sms"}&active=true`)
        .then((r) => setTemplates(r?.templates || []))
        .catch(() => setTemplates([]))
        .finally(() => setTemplatesLoading(false));
    }
  }, [payload, isEmail]);
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
  const submit = async () => {
    if (!message.trim()) {
      onError("Message body required");
      return;
    }
    setBusy(true);
    try {
      if (isEmail) {
        await api.post(`/customers/${customer.id}/send-email`, {
          to: payload.to,
          subject: subject || `Message from ${customer?.name || "your service"}`,
          body: message,
          customer_id: customer?.id,
        });
      } else {
        // BUG F · Feb 2026 — POST to the customer-scoped SMS endpoint
        // (was hitting the non-existent ``/sms/send`` which 404'd with
        // "not found"). New wrapper mirrors ``send-email`` — validates
        // the recipient against the customer's mirrored phones and
        // persists a ``customer_direct_message`` comms_log row.
        await api.post(`/customers/${customer.id}/send-sms`, {
          to: payload.to,
          body: message,
          customer_id: customer?.id,
        });
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
        {/* Template picker */}
        <aside data-testid="cd-send-templates"
                style={{ borderRight: `1px solid ${colors.border}`,
                            paddingRight: 12, maxHeight: 380, overflowY: "auto" }}>
          <div className="text-xs font-semibold mb-2" style={{ color: colors.muted }}>
            TEMPLATE
          </div>
          <button type="button"
                   onClick={() => pickTemplate(null)}
                   className="w-full text-left rounded-md px-2 py-1.5 mb-1 text-sm"
                   style={{
                     background: pickedId === "" ? colors.surfaceSecondary : "transparent",
                     border: pickedId === "" ? `1px solid ${colors.border}` : "1px solid transparent",
                     color: colors.onSurface,
                   }}
                   data-testid="cd-send-template-custom">
            <div className="font-semibold">Custom message</div>
            <div className="text-xs" style={{ color: colors.muted }}>
              Write from scratch
            </div>
          </button>
          {templatesLoading ? (
            <div className="text-xs" style={{ color: colors.muted }}
                 data-testid="cd-send-templates-loading">Loading…</div>
          ) : templates.length === 0 ? (
            <div className="text-xs" style={{ color: colors.muted }}
                 data-testid="cd-send-templates-empty">
              No saved {isEmail ? "email" : "SMS"} templates.
            </div>
          ) : templates.map((t) => (
            <button key={t.id}
                     type="button"
                     onClick={() => pickTemplate(t)}
                     className="w-full text-left rounded-md px-2 py-1.5 mb-1 text-sm"
                     style={{
                       background: pickedId === t.id ? colors.surfaceSecondary : "transparent",
                       border: pickedId === t.id ? `1px solid ${colors.border}` : "1px solid transparent",
                       color: colors.onSurface,
                     }}
                     data-testid={`cd-send-template-${t.id}`}>
              <div className="font-semibold">{t.name}</div>
              {t.category ? (
                <div className="text-xs" style={{ color: colors.muted }}>{t.category}</div>
              ) : null}
            </button>
          ))}
        </aside>
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
    </Modal>
  );
}


