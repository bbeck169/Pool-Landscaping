import React, { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import {
  ArrowLeft,
  Edit3,
  Trash2,
  Mail,
  Phone,
  MapPin,
  BellRing,
  Beaker,
  UserPlus,
  KeyRound,
  Briefcase,
  FileText,
  StickyNote,
  Droplets,
  Star,
  ListChecks,
  MessageSquare,
  Home,
} from "lucide-react";
import { api } from "@/api";
import { colors } from '@/theme';
import ClickToCallButton from "@/components/telephony/ClickToCallButton";
import {
  PageHeader,
  Button,
  Modal,
  TextInput,
  Skeleton,
  TagChip,
  Chip,
  StatusPill,
  EmptyState,
  Toast,
} from "@/components/ui-kit";
import { ActivationControl } from "@/components/customers/ActivationControl";
import CustomerEquipmentLibrary from "@/components/customers/CustomerEquipmentLibrary";
import CustomerActionDropdowns from "@/components/customers/CustomerActionDropdowns";
import CustomerTasksPanel from "@/components/customers/CustomerTasksPanel";
import CustomerContactsPanel from "@/components/customers/CustomerContactsPanel";
import CustomerServiceNotesCards from "@/components/customers/CustomerServiceNotesCards";
import PropertiesTab from "./PropertiesTab";
import MasterBillingCard from "./MasterBillingCard";

const TABS = [
  { k: "overview", label: "Overview", icon: MapPin },
  { k: "properties", label: "Properties", icon: Home },
  { k: "jobs", label: "Jobs", icon: Briefcase },
  { k: "quotes", label: "Quotes", icon: FileText },
  { k: "invoices", label: "Invoices", icon: FileText },
  { k: "equipment", label: "Equipment", icon: Beaker },
  { k: "tasks", label: "Tasks", icon: ListChecks },
  { k: "notes", label: "Notes", icon: StickyNote },
  { k: "portal", label: "Portal Access", icon: KeyRound },
];

export default function CustomerDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [customer, setCustomer] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [tab, setTab] = useState("overview");
  const [toast, setToast] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [loginModal, setLoginModal] = useState(false);
  const [vipModal, setVipModal] = useState(false);
  const [sendModal, setSendModal] = useState(null); // { channel, to }
  const [taskQuickAddOpener, setTaskQuickAddOpener] = useState(null);

  const load = async () => {
    try {
      const [c, allJobs] = await Promise.all([
        api.get(`/customers/${id}`),
        api.get("/jobs"),
      ]);
      setCustomer(c);
      setJobs((allJobs || []).filter((j) => j.customer_id === id));
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const doDelete = async () => {
    try {
      await api.del(`/customers/${id}`);
      setToast({ tone: "success", message: "Customer deleted" });
      setTimeout(() => navigate("/customers"), 500);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
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
            <div className="flex items-center gap-2 mt-2 flex-wrap">
              {(customer.tags || []).map((t) => (
                <TagChip tag={t} key={t} />
              ))}
              {customer.waitlisted ? <Chip label="Waitlist" tone="warning" /> : null}
              {customer.has_login ? <Chip label="Portal enabled" tone="success" /> : null}
            </div>
          </div>
          <div className="flex flex-col items-end gap-2">
            {/* Feb-2026 Customer Detail Additions — top-right Send + Create dropdowns */}
            <CustomerActionDropdowns
              customer={customer}
              onSend={openSendModal}
              onQuickTask={openQuickTaskFromDropdown}
            />
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => navigate(`/customers/${id}/edit`)} testid="cd-edit">
                <Edit3 size={14} /> Edit
              </Button>
              <Button
                variant="ghost"
                onClick={() => navigate(`/customers/${id}/chemistry`)}
                testid="cd-chemistry"
              >
                <Beaker size={14} /> Chemistry
              </Button>
              <Button
                variant="ghost"
                onClick={() => navigate(`/customers/${id}/chemistry-history`)}
                testid="cd-chemistry-history"
              >
                <Beaker size={14} /> Chem History
              </Button>
              <Button variant="danger" onClick={() => setConfirmDelete(true)} testid="cd-delete">
                <Trash2 size={14} /> Delete
              </Button>
            </div>
            {/* Phase 6B · Feb 2026 — one-click RingCentral call */}
            {(() => {
              const primary =
                (customer.mobiles && customer.mobiles[0]?.number_e164) ||
                customer.phone;
              if (!primary) return null;
              return (
                <div className="mt-1" data-testid="cd-click-to-call-wrapper">
                  <ClickToCallButton
                    phoneNumber={primary}
                    entityKind="customer"
                    entityId={customer.id}
                    label={`Call ${customer.name || "customer"}`}
                    testIdPrefix="cd-click-to-call"
                  />
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

      {/* Tabs */}
      <div
        className="rounded-2xl overflow-hidden mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <nav className="flex overflow-x-auto" style={{ borderBottom: `1px solid ${colors.border}` }}>
          {TABS.map((t) => (
            <button
              key={t.k}
              onClick={() => setTab(t.k)}
              className="flex items-center gap-2 px-4 py-3 text-sm font-semibold whitespace-nowrap transition"
              style={{
                color: tab === t.k ? colors.brand : colors.muted,
                borderBottom: `2px solid ${tab === t.k ? colors.brand : "transparent"}`,
              }}
              data-testid={`cd-tab-${t.k}`}
            >
              <t.icon size={14} />
              {t.label}
            </button>
          ))}
        </nav>
        <div className="p-5">
          {tab === "overview" ? (
            <div className="space-y-4">
              <MasterBillingCard
                customer={customer}
                onToast={(t) => setToast(t)}
                onRefreshCustomer={load}
              />
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
              <CustomerContactsPanel
                customer={customer}
                onSaved={(updated) => {
                  setCustomer((c) => ({ ...c, ...updated }));
                  setToast({ tone: "success", message: "Contacts saved" });
                }}
                onError={(msg) => setToast({ tone: "error", message: msg })}
              />
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
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Delete customer?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>Cancel</Button>
            <Button variant="danger" onClick={doDelete} testid="cd-confirm-delete">
              Delete permanently
            </Button>
          </>
        }
      >
        <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
          This will remove <strong>{customer.name}</strong> from the system. Their jobs, quotes and
          history remain, but references become read-only.
        </p>
      </Modal>

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
    } catch (e) {
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

      {/* Actions */}
      <div className="flex flex-wrap gap-2">
        <Button
          onClick={() => doAction("portal-invite", "Portal invite")}
          disabled={busy === "portal-invite"}
          testid="cd-portal-invite"
        >
          {busy === "portal-invite" ? "Sending…" : "Send portal invite"}
        </Button>
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
  useEffect(() => {
    if (payload) {
      setSubject("");
      setMessage("");
    }
  }, [payload]);
  if (!payload) return null;
  const isEmail = payload.channel === "email";
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
        await api.post("/sms/send", {
          phone_number: payload.to,
          message,
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
          <Button onClick={submit} disabled={busy} testid="cd-send-submit">
            {busy ? "Sending…" : "Send"}
          </Button>
        </>
      }
    >
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
          <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>
            MESSAGE
          </div>
          <textarea
            className="w-full min-h-[140px] px-3 py-2 rounded-lg text-sm"
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
      </div>
    </Modal>
  );
}

