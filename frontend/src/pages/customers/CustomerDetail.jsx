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
} from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { usePermissions } from "@/hooks/usePermissions";
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

const TABS = [
  { k: "overview", label: "Overview", icon: MapPin },
  { k: "jobs", label: "Jobs", icon: Briefcase },
  { k: "quotes", label: "Quotes", icon: FileText },
  { k: "invoices", label: "Invoices", icon: FileText },
  { k: "equipment", label: "Equipment", icon: Beaker },
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
              {customer.is_vip ? (
                <span
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold uppercase tracking-wider"
                  style={{
                    backgroundColor: "#FEF3C7",
                    color: "#92400E",
                    border: "1px solid #F59E0B",
                  }}
                  data-testid="customer-vip-badge"
                  title="VIP customer"
                >
                  <Star size={12} fill="#F59E0B" color="#F59E0B" /> VIP
                </span>
              ) : null}
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
            <Button variant="danger" onClick={() => setConfirmDelete(true)} testid="cd-delete">
              <Trash2 size={14} /> Delete
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
          {[
            { icon: Phone, label: "Phone", value: customer.phone },
            { icon: Mail, label: "Email", value: customer.email },
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

          {tab === "notes" ? (
            <Info label="Notes" value={customer.notes} preserveNewlines />
          ) : null}

          {tab === "portal" ? (
            <PortalAccessPanel customer={customer} onDone={load} onToast={(t) => setToast(t)} openLogin={() => setLoginModal(true)} />
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

  const doAction = async (endpoint, label) => {
    setBusy(endpoint);
    setInviteLink(null);
    setTempPassword(null);
    try {
      const r = await api.post(`/customers/${customer.id}/${endpoint}`);
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

  return (
    <div className="space-y-4">
      {customer.has_login ? (
        <div className="text-sm" style={{ color: colors.onSurface }}>
          Portal login active for <strong>{customer.email}</strong>.
        </div>
      ) : (
        <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
          No portal login yet. Send an invite (auto-generated password) or create one manually.
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => doAction("portal-invite", "Portal invite")} disabled={busy === "portal-invite"} testid="cd-portal-invite">
          {busy === "portal-invite" ? "Sending…" : "Send portal invite"}
        </Button>
        {customer.has_login ? (
          <>
            <Button variant="ghost" onClick={() => doAction("portal-reset", "Portal reset")} disabled={busy === "portal-reset"} testid="cd-portal-reset">
              {busy === "portal-reset" ? "Resetting…" : "Reset password"}
            </Button>
            <Button variant="ghost" onClick={impersonate} disabled={busy === "impersonate"} testid="cd-impersonate">
              View as customer
            </Button>
            <Button variant="danger" onClick={() => doAction("portal-revoke", "Portal revoked")} disabled={busy === "portal-revoke"} testid="cd-portal-revoke">
              Revoke access
            </Button>
          </>
        ) : (
          <Button variant="ghost" onClick={openLogin}>Manual create…</Button>
        )}
      </div>
      {inviteLink && tempPassword ? (
        <div className="rounded-lg p-3 text-sm" style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }} data-testid="portal-invite-payload">
          <div className="font-semibold mb-1">Share these credentials manually:</div>
          <div>Login: <a href={inviteLink} className="underline" target="_blank" rel="noreferrer">{inviteLink}</a></div>
          <div>Email: <code>{customer.email}</code></div>
          <div>Temp password: <code>{tempPassword}</code></div>
        </div>
      ) : null}
    </div>
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
