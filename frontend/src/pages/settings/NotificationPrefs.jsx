/**
 * Phase 55 · Per-user notification preferences.
 *
 * Matrix of kind × channel toggles. Bell is authoritative — turning it
 * off silences a kind entirely. Email respects RESEND_API_KEY (mocks
 * to email_delivery_log when missing). SMS respects RC_OUTBOUND_ENABLED
 * (queues a mocked row when disabled).
 */
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Bell, Mail, MessageSquare, Save, Smartphone, Undo2, Sparkles, ChevronRight } from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";
import CommsWhitelistBanner from "@/components/comms/CommsWhitelistBanner";

const CHANNELS = [
  { key: "bell",  label: "Bell",  Icon: Bell,           hint: "In-app inbox + realtime toast" },
  { key: "push",  label: "Push",  Icon: Smartphone,     hint: "Mobile push via Expo (respects quiet hours)" },
  { key: "email", label: "Email", Icon: Mail,           hint: "Delivered via Resend when configured" },
  { key: "sms",   label: "SMS",   Icon: MessageSquare,  hint: "Delivered via RingCentral when outbound is enabled" },
];

export default function NotificationPrefs() {
  const nav = useNavigate();
  const { user } = useAuth() || {};
  const isAdmin = ["admin", "super_admin"].includes(user?.role);
  const [kinds, setKinds] = useState([]);
  const [channels, setChannels] = useState({});
  const [initial, setInitial] = useState({});
  const [quietHours, setQuietHours] = useState({ enabled: false, start_time: "22:00", end_time: "07:00", timezone: "UTC" });
  const [initialQuiet, setInitialQuiet] = useState({ enabled: false, start_time: "22:00", end_time: "07:00", timezone: "UTC" });
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.get("/settings/notifications");
      setKinds(r?.kinds || []);
      setChannels(r?.channels || {});
      setInitial(JSON.parse(JSON.stringify(r?.channels || {})));
      const qh = r?.quiet_hours || { enabled: false, start_time: "22:00", end_time: "07:00", timezone: "UTC" };
      setQuietHours(qh);
      setInitialQuiet(JSON.parse(JSON.stringify(qh)));
    } catch { /* silent */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  const flip = (kind, chan) => {
    setChannels((prev) => ({
      ...prev,
      [kind]: { ...(prev[kind] || {}), [chan]: !prev?.[kind]?.[chan] },
    }));
  };

  const dirty = JSON.stringify(channels) !== JSON.stringify(initial)
             || JSON.stringify(quietHours) !== JSON.stringify(initialQuiet);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put("/settings/notifications", { channels, quiet_hours: quietHours });
      setChannels(r?.channels || channels);
      setInitial(JSON.parse(JSON.stringify(r?.channels || channels)));
      const qh = r?.quiet_hours || quietHours;
      setQuietHours(qh);
      setInitialQuiet(JSON.parse(JSON.stringify(qh)));
      setToast("Preferences saved");
      setTimeout(() => setToast(""), 2000);
    } catch (e) {
      setToast(e?.message || "Save failed");
      setTimeout(() => setToast(""), 3000);
    }
    setSaving(false);
  };

  const reset = () => {
    setChannels(JSON.parse(JSON.stringify(initial)));
    setQuietHours(JSON.parse(JSON.stringify(initialQuiet)));
  };

  const setAll = (chan, value) => {
    setChannels((prev) => {
      const next = { ...prev };
      for (const k of kinds) {
        next[k.key] = { ...(next[k.key] || {}), [chan]: value };
      }
      return next;
    });
  };

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="notif-prefs-page">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <button onClick={() => nav(-1)} className="p-2 rounded-lg hover:brightness-95"
                  style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                  data-testid="notif-prefs-back">
            <ArrowLeft size={16} />
          </button>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold flex items-center gap-2" style={{ color: colors.onSurface }}>
              <Bell size={22} /> Notification Preferences
            </h1>
            <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
              Choose how you receive each kind of alert. Bell is the in-app inbox counter.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {toast ? (
            <span className="text-xs font-semibold px-2 py-1 rounded"
                  style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
                  data-testid="notif-prefs-toast">
              {toast}
            </span>
          ) : null}
          <button onClick={reset} disabled={!dirty}
                  className="px-3 py-2 rounded-lg text-sm font-semibold inline-flex items-center gap-1.5"
                  style={{
                    backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}`,
                    color: dirty ? colors.onSurface : colors.muted,
                    opacity: dirty ? 1 : 0.5,
                  }}
                  data-testid="notif-prefs-reset">
            <Undo2 size={14} /> Undo
          </button>
          <button onClick={save} disabled={!dirty || saving}
                  className="px-3 py-2 rounded-lg text-sm font-semibold inline-flex items-center gap-1.5"
                  style={{ backgroundColor: colors.brand, color: "#fff", opacity: dirty ? 1 : 0.5 }}
                  data-testid="notif-prefs-save">
            <Save size={14} /> {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>

      {/* Queue Item 4 · Feb-2026 — outbound comms whitelist banner.
          Warns admins that comms are demo-only + shows live counts. */}
      <CommsWhitelistBanner />

      {/* Feb-2026 · Phase B — tenant-scoped decline-notification
          toggle. Admin-only. Independent from the per-user matrix
          below (this one gates the fanout at the tenant boundary
          so a customer decline can be silenced entirely regardless
          of individual admins' preferences). */}
      {isAdmin ? <TenantDeclineNotifyToggle /> : null}
      {/* WELCOME-EMAIL-ON-FIRST-ACCEPTED-QUOTE · Feb-2026 — admin
          kill switch for the first-accepted-quote welcome email. */}
      {isAdmin ? <TenantWelcomeOnFirstAcceptToggle /> : null}

      {/* Feb-2026 · Phase C — signature-before-approve tenant gate.
          Admin-only. When enabled, customers cannot approve a
          quote/estimate until they've captured a signature. */}
      {isAdmin ? <TenantRequireSignatureBeforeApproveToggle /> : null}

      {/* P2 #10e · Feb-2026 — tenant-wide automation kill switches.
          The 4 flags below correspond to the P2 #10d transactional-
          template automations (lead-conversion welcome,
          completion-follow-up SMS, invoice past-due, estimate
          reminder). Default True on unset. Pair with the
          "Customize templates →" link that routes to the
          per-slug body/subject editor. Admin-only. */}
      {isAdmin ? <TenantAutomationTogglesSection /> : null}

      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="grid grid-cols-[1fr_repeat(4,88px)] items-center px-4 py-3 border-b"
             style={{ borderColor: colors.border, backgroundColor: colors.surfaceSecondary }}>
          <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
            Notification kind
          </div>
          {CHANNELS.map(({ key, label, Icon }) => (
            <div key={key} className="flex flex-col items-center gap-1" data-testid={`notif-prefs-col-${key}`}>
              <div className="inline-flex items-center gap-1 text-xs font-bold" style={{ color: colors.onSurface }}>
                <Icon size={12} /> {label}
              </div>
              <div className="inline-flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setAll(key, true)}
                  className="text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded"
                  style={{ color: colors.brand, backgroundColor: colors.brandTertiary || "transparent" }}
                  data-testid={`notif-prefs-all-on-${key}`}
                >
                  all on
                </button>
                <span className="text-[9px]" style={{ color: colors.muted }}>·</span>
                <button
                  type="button"
                  onClick={() => setAll(key, false)}
                  className="text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded"
                  style={{ color: colors.muted }}
                  data-testid={`notif-prefs-all-off-${key}`}
                >
                  all off
                </button>
              </div>
            </div>
          ))}
        </div>

        {kinds.map((k) => {
          const row = channels[k.key] || { bell: true, push: false, email: false, sms: false };
          return (
            <div key={k.key}
                 className="grid grid-cols-[1fr_repeat(4,88px)] items-center px-4 py-3 border-b"
                 style={{ borderColor: colors.border }}
                 data-testid={`notif-prefs-row-${k.key}`}>
              <div className="text-sm font-semibold pr-3" style={{ color: colors.onSurface }}>
                {k.label}
              </div>
              {CHANNELS.map(({ key }) => {
                const on = Boolean(row[key]);
                return (
                  <div key={key} className="flex items-center justify-center">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={on}
                      onClick={() => flip(k.key, key)}
                      className="relative inline-flex items-center h-6 w-11 rounded-full transition-colors"
                      style={{ backgroundColor: on ? colors.brand : "#D1D5DB" }}
                      data-testid={`notif-prefs-toggle-${k.key}-${key}`}
                    >
                      <span
                        className="inline-block h-5 w-5 rounded-full bg-white shadow transform transition-transform"
                        style={{ transform: on ? "translateX(22px)" : "translateX(2px)" }}
                      />
                    </button>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>

      <div className="mt-6 rounded-2xl p-4"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="notif-quiet-hours-card">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
          <div>
            <div className="text-sm font-bold" style={{ color: colors.onSurface }}>Quiet hours</div>
            <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
              Push notifications are silenced during this window. In-app inbox rows still record.
            </div>
          </div>
          <label className="inline-flex items-center gap-2 text-xs font-semibold" style={{ color: colors.onSurface }}>
            <input
              type="checkbox"
              checked={Boolean(quietHours.enabled)}
              onChange={(e) => setQuietHours((q) => ({ ...q, enabled: e.target.checked }))}
              data-testid="notif-quiet-hours-toggle"
            />
            Enabled
          </label>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
          <label className="flex flex-col gap-1" style={{ color: colors.muted }}>
            <span>Start</span>
            <input
              type="time"
              value={quietHours.start_time || "22:00"}
              onChange={(e) => setQuietHours((q) => ({ ...q, start_time: e.target.value }))}
              disabled={!quietHours.enabled}
              className="px-2 py-1.5 rounded-lg text-sm"
              style={{
                backgroundColor: colors.surface,
                border: `1px solid ${colors.border}`,
                color: colors.onSurface,
                opacity: quietHours.enabled ? 1 : 0.5,
              }}
              data-testid="notif-quiet-hours-start"
            />
          </label>
          <label className="flex flex-col gap-1" style={{ color: colors.muted }}>
            <span>End</span>
            <input
              type="time"
              value={quietHours.end_time || "07:00"}
              onChange={(e) => setQuietHours((q) => ({ ...q, end_time: e.target.value }))}
              disabled={!quietHours.enabled}
              className="px-2 py-1.5 rounded-lg text-sm"
              style={{
                backgroundColor: colors.surface,
                border: `1px solid ${colors.border}`,
                color: colors.onSurface,
                opacity: quietHours.enabled ? 1 : 0.5,
              }}
              data-testid="notif-quiet-hours-end"
            />
          </label>
          <label className="flex flex-col gap-1" style={{ color: colors.muted }}>
            <span>Timezone</span>
            <select
              value={quietHours.timezone || "UTC"}
              onChange={(e) => setQuietHours((q) => ({ ...q, timezone: e.target.value }))}
              disabled={!quietHours.enabled}
              className="px-2 py-1.5 rounded-lg text-sm"
              style={{
                backgroundColor: colors.surface,
                border: `1px solid ${colors.border}`,
                color: colors.onSurface,
                opacity: quietHours.enabled ? 1 : 0.5,
              }}
              data-testid="notif-quiet-hours-tz"
            >
              <option value="UTC">UTC</option>
              <option value="America/Phoenix">America/Phoenix</option>
              <option value="America/Los_Angeles">America/Los_Angeles</option>
              <option value="America/Denver">America/Denver</option>
              <option value="America/Chicago">America/Chicago</option>
              <option value="America/New_York">America/New_York</option>
            </select>
          </label>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-2 text-xs" style={{ color: colors.muted }}>
        {CHANNELS.map(({ key, label, Icon, hint }) => (
          <div key={key} className="rounded-lg p-3 flex items-start gap-2"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
            <Icon size={14} style={{ color: colors.brand }} className="mt-0.5" />
            <div>
              <div className="font-bold text-sm" style={{ color: colors.onSurface }}>{label}</div>
              <div className="mt-0.5">{hint}</div>
            </div>
          </div>
        ))}
      </div>

      <PortalChatSmsBridgeCard />

      {/* K63 · Feb-2026 — link to the tenant-scoped Lead Alerts
          recipient CRUD page. Admin-only; keeps per-user matrix
          separate from the tenant-wide widget-form fan-out list. */}
      <div
        className="mt-6 rounded-2xl p-4 flex items-center justify-between"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        data-testid="k63-lead-alerts-link-card"
      >
        <div>
          <div className="text-sm font-bold flex items-center gap-2" style={{ color: colors.onSurface }}>
            <Bell size={14} style={{ color: colors.brand }} /> Lead Alerts (widget forms)
          </div>
          <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Manage the list of admins who receive an email + SMS ping
            when the public widget forms create a new lead.
          </div>
        </div>
        <button
          onClick={() => nav("/settings/notifications/lead-alerts")}
          className="px-3 py-2 rounded-lg text-sm font-semibold"
          style={{ backgroundColor: colors.brand, color: "#fff" }}
          data-testid="k63-lead-alerts-open"
        >
          Manage recipients
        </button>
      </div>
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────
// Phase K9 · Feb-2026 — Portal chat SMS notifications card.
//
// Binds ``tenant.admin_sms_notify_to`` (E.164 or null) to a
// PATCH /api/tenants/{tid} call.  Rendered as a self-contained
// subsection at the bottom of NotificationPrefs so it lives beside
// the existing per-user matrix + quiet-hours block.
// ─────────────────────────────────────────────────────────────────
function PortalChatSmsBridgeCard() {
  const [tenantId, setTenantId] = React.useState(null);
  const [phone, setPhone] = React.useState("");
  const [initial, setInitial] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [toast, setToast] = React.useState("");
  const [error, setError] = React.useState("");

  const E164 = /^\+\d{10,15}$/;

  React.useEffect(() => {
    (async () => {
      try {
        const t = await api.get("/tenants/current");
        setTenantId(t?.id || null);
        const v = t?.admin_sms_notify_to || "";
        setPhone(v);
        setInitial(v);
      } catch {
        /* silent */
      }
    })();
  }, []);

  const dirty = (phone || "") !== (initial || "");
  const valid = phone === "" || E164.test(phone.trim());

  const save = async () => {
    if (!tenantId || !valid) {
      setError("Enter a valid E.164 number (e.g. +16028874400) or leave empty to clear.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const body = { admin_sms_notify_to: phone.trim() ? phone.trim() : null };
      const r = await api.patch(`/tenants/${tenantId}`, body);
      const v = r?.admin_sms_notify_to || "";
      setPhone(v);
      setInitial(v);
      setToast("Saved");
      setTimeout(() => setToast(""), 2000);
    } catch (e) {
      setError(e?.message || "Save failed");
    }
    setSaving(false);
  };

  return (
    <div
      className="mt-6 rounded-2xl p-4"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="k9-portal-sms-card"
    >
      <div className="flex items-center gap-2 mb-2">
        <MessageSquare size={14} style={{ color: colors.brand }} />
        <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
          Portal chat SMS notifications
        </div>
      </div>
      <div className="text-xs mb-3" style={{ color: colors.muted }}>
        Admin phone to receive SMS pings when a customer posts on the portal.
        Admin can reply to the SMS and the response is posted back to the
        customer's portal chat as Support.
      </div>
      <div className="flex flex-col sm:flex-row sm:items-end gap-3">
        <label className="flex flex-col gap-1 flex-1" style={{ color: colors.muted }}>
          <span className="text-xs font-semibold uppercase tracking-wide">
            Admin phone (E.164)
          </span>
          <input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+16028874400"
            className="px-3 py-2 rounded-lg text-sm"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${valid ? colors.border : "#DC2626"}`,
              color: colors.onSurface,
            }}
            data-testid="k9-portal-sms-input"
          />
          {!valid && (
            <span className="text-xs" style={{ color: "#DC2626" }} data-testid="k9-portal-sms-invalid">
              Must be an E.164 number like +16028874400.
            </span>
          )}
        </label>
        <button
          onClick={save}
          disabled={!dirty || saving || !valid || !tenantId}
          className="px-3 py-2 rounded-lg text-sm font-semibold inline-flex items-center gap-1.5 self-start sm:self-end"
          style={{
            backgroundColor: colors.brand,
            color: "#fff",
            opacity: dirty && valid && tenantId ? 1 : 0.5,
          }}
          data-testid="k9-portal-sms-save"
        >
          <Save size={14} /> {saving ? "Saving…" : "Save"}
        </button>
        {toast && (
          <span
            className="text-xs font-semibold px-2 py-1 rounded"
            style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
            data-testid="k9-portal-sms-toast"
          >
            {toast}
          </span>
        )}
      </div>
      {error && (
        <div className="mt-2 text-xs" style={{ color: "#DC2626" }} data-testid="k9-portal-sms-error">
          {error}
        </div>
      )}
    </div>
  );
}



/**
 * Feb-2026 · Phase B — tenant-scoped decline-notification toggle.
 *
 * Reads / writes ``notify_admin_on_decline`` on the tenant settings
 * doc via the existing ``/api/tenants/mine/settings`` GET+PATCH.
 * Admin-only (parent gates the mount).
 *
 * Gating semantics (matches ``services/quote_notifications``):
 *   * ``true``  → email + SMS admin fanout fires on top-level decline.
 *   * ``false`` → bell fanout still fires; email + SMS suppressed.
 *   * unset    → treated as ``true`` by the backend.
 */
export function TenantDeclineNotifyToggle() {
  const [value, setValue] = useState(null);   // null while loading
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/tenants/mine/settings");
        setValue(Boolean(r?.notify_admin_on_decline ?? true));
      } catch { setValue(true); }
    })();
  }, []);

  const flip = async () => {
    if (value === null || saving) return;
    const next = !value;
    setSaving(true);
    setValue(next);                            // optimistic
    try {
      const r = await api.patch(
        "/tenants/mine/settings",
        { notify_admin_on_decline: next },
      );
      setValue(Boolean(r?.notify_admin_on_decline ?? next));
      setToast("Saved");
    } catch (e) {
      setValue(!next);                          // rollback
      setToast(e?.message || "Save failed");
    } finally {
      setSaving(false);
      setTimeout(() => setToast(""), 2000);
    }
  };

  const on = Boolean(value);
  const loading = value === null;

  return (
    <div
      className="rounded-2xl px-4 py-3 mb-4 flex items-center justify-between gap-3"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="tenant-decline-notify-row"
    >
      <div className="min-w-0">
        <div
          className="text-sm font-semibold"
          style={{ color: colors.onSurface }}
        >
          Notify admins when a customer declines a quote/estimate
        </div>
        <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
          Sends email + SMS to the tenant's notification recipients
          (falls back to workforce admins). Bell alerts stay on
          regardless of this setting.
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {toast ? (
          <span
            className="text-[10px] font-semibold px-2 py-1 rounded"
            style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
            data-testid="tenant-decline-notify-toast"
          >
            {toast}
          </span>
        ) : null}
        <button
          type="button"
          role="switch"
          aria-checked={on}
          onClick={flip}
          disabled={loading || saving}
          className="relative inline-flex items-center h-6 w-11 rounded-full transition-colors"
          style={{
            backgroundColor: on ? colors.brand : "#D1D5DB",
            opacity: loading ? 0.5 : 1,
            cursor: loading ? "wait" : "pointer",
          }}
          data-testid="tenant-decline-notify-toggle"
        >
          <span
            className="inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform"
            style={{
              transform: `translateX(${on ? 22 : 2}px)`,
            }}
          />
        </button>
      </div>
    </div>
  );
}


/**
 * Feb-2026 · Phase C — signature-before-approve tenant gate.
 *
 * Reads / writes ``require_signature_before_approve`` on the tenant
 * settings doc via the existing ``/api/tenants/mine/settings``
 * GET+PATCH. Admin-only (parent gates the mount).
 *
 * Gating semantics (matches ``routers/estimate_viewer.py``):
 *   * ``true``  → customers cannot approve a quote/estimate until
 *                 ``signature_status === "signed"``. Portal Approve
 *                 button is disabled with a "Sign to enable" hint.
 *   * ``false`` → legacy behaviour, Approve is always available.
 *   * unset    → treated as ``false`` by the backend.
 */
export function TenantRequireSignatureBeforeApproveToggle() {
  const [value, setValue] = useState(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/tenants/mine/settings");
        setValue(Boolean(r?.require_signature_before_approve ?? false));
      } catch { setValue(false); }
    })();
  }, []);

  const flip = async () => {
    if (value === null || saving) return;
    const next = !value;
    setSaving(true);
    setValue(next);
    try {
      const r = await api.patch(
        "/tenants/mine/settings",
        { require_signature_before_approve: next },
      );
      setValue(Boolean(r?.require_signature_before_approve ?? next));
      setToast("Saved");
    } catch (e) {
      setValue(!next);
      setToast(e?.message || "Save failed");
    } finally {
      setSaving(false);
      setTimeout(() => setToast(""), 2000);
    }
  };

  const on = Boolean(value);
  const loading = value === null;

  return (
    <div
      className="rounded-2xl px-4 py-3 mb-4 flex items-center justify-between gap-3"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="tenant-require-signature-row"
    >
      <div className="min-w-0">
        <div
          className="text-sm font-semibold"
          style={{ color: colors.onSurface }}
        >
          Require customer signature before Approve
        </div>
        <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
          When enabled, customers cannot approve a quote/estimate
          until they've signed. The Approve button will be disabled
          with a "Sign to enable" hint until signature is captured.
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {toast ? (
          <span
            className="text-[10px] font-semibold px-2 py-1 rounded"
            style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
            data-testid="tenant-require-signature-toast"
          >
            {toast}
          </span>
        ) : null}
        <button
          type="button"
          role="switch"
          aria-checked={on}
          onClick={flip}
          disabled={loading || saving}
          className="relative inline-flex items-center h-6 w-11 rounded-full transition-colors"
          style={{
            backgroundColor: on ? colors.brand : "#D1D5DB",
            opacity: loading ? 0.5 : 1,
            cursor: loading ? "wait" : "pointer",
          }}
          data-testid="tenant-require-signature-toggle"
        >
          <span
            className="inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform"
            style={{
              transform: `translateX(${on ? 22 : 2}px)`,
            }}
          />
        </button>
      </div>
    </div>
  );
}


/**
 * WELCOME-EMAIL-ON-FIRST-ACCEPTED-QUOTE · Feb-2026 — tenant-scoped
 * kill switch for the one-off welcome email that fires when a
 * customer accepts their first-ever quote.
 *
 * Reads / writes ``welcome_email_on_first_accepted_quote_enabled``
 * on the tenant settings doc via the existing
 * ``/api/tenants/mine/settings`` GET+PATCH.  Admin-only (parent
 * gates the mount).  Mirrors ``<TenantDeclineNotifyToggle>`` + the
 * sibling signature-required toggle in this file.
 *
 * Gating semantics:
 *   * ``true``  → welcome email fires on the customer's first
 *                 accepted quote.
 *   * ``false`` → welcome email is suppressed.  Admin "mark
 *                 accepted on behalf" was never a trigger.
 *   * unset    → treated as ``true`` by the backend.
 */
export function TenantWelcomeOnFirstAcceptToggle() {
  const [value, setValue] = useState(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/tenants/mine/settings");
        setValue(Boolean(
          r?.welcome_email_on_first_accepted_quote_enabled ?? true,
        ));
      } catch { setValue(true); }
    })();
  }, []);

  const flip = async () => {
    if (value === null || saving) return;
    const next = !value;
    setSaving(true);
    setValue(next);
    try {
      const r = await api.patch(
        "/tenants/mine/settings",
        { welcome_email_on_first_accepted_quote_enabled: next },
      );
      setValue(Boolean(
        r?.welcome_email_on_first_accepted_quote_enabled ?? next,
      ));
      setToast("Saved");
    } catch (e) {
      setValue(!next);
      setToast(e?.message || "Save failed");
    } finally {
      setSaving(false);
      setTimeout(() => setToast(""), 2000);
    }
  };

  const on = Boolean(value);
  const loading = value === null;

  return (
    <div
      className="rounded-2xl px-4 py-3 mb-4 flex items-center justify-between gap-3"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="tenant-welcome-first-accept-row"
    >
      <div className="min-w-0">
        <div
          className="text-sm font-semibold"
          style={{ color: colors.onSurface }}
        >
          Send welcome email on a customer's first accepted quote
        </div>
        <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
          Fires exactly once per customer, on the first ever
          customer-triggered accept.  Admin "mark accepted on
          behalf" never triggers this email.
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {toast ? (
          <span
            className="text-[10px] font-semibold px-2 py-1 rounded"
            style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
            data-testid="tenant-welcome-first-accept-toast"
          >
            {toast}
          </span>
        ) : null}
        <button
          type="button"
          role="switch"
          aria-checked={on}
          onClick={flip}
          disabled={loading || saving}
          className="relative inline-flex items-center h-6 w-11 rounded-full transition-colors"
          style={{
            backgroundColor: on ? colors.brand : "#D1D5DB",
            opacity: loading ? 0.5 : 1,
            cursor: loading ? "wait" : "pointer",
          }}
          data-testid="tenant-welcome-first-accept-toggle"
        >
          <span
            className="inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform"
            style={{
              transform: `translateX(${on ? 22 : 2}px)`,
            }}
          />
        </button>
      </div>
    </div>
  );
}



/**
 * P2 #10e · Feb-2026 — tenant-wide automation kill switches section.
 *
 * Reads / writes the 4 P2 #10d automation flags on the tenant
 * settings doc via the existing ``/api/tenants/mine/settings``
 * GET+PATCH:
 *   * ``lead_conversion_welcome_enabled``
 *   * ``completion_followup_sms_enabled``
 *   * ``invoice_past_due_enabled``
 *   * ``estimate_reminder_enabled``
 *
 * All default True on unset (opt-out posture). Pairs with the
 * "Customize templates →" link that routes to the per-slug
 * body/subject editor at ``/settings/notifications/templates``.
 */
const _P2_10E_FLAGS = [
  {
    key: "lead_conversion_welcome_enabled",
    testidSuffix: "lead-conversion-welcome-enabled",
    label: "Send welcome email + SMS when a lead is converted",
    description:
      "Fires on admin-initiated lead conversion. Email + SMS go " +
      "to the new customer. Default on; flip off to silence both " +
      "channels at the tenant boundary.",
  },
  {
    key: "completion_followup_sms_enabled",
    testidSuffix: "completion-followup-sms-enabled",
    label: "Send completion follow-up SMS after a service report submits",
    description:
      "Short text with a portal link to the full report + photos. " +
      "Email summary is sent separately and not affected by this " +
      "toggle. Default on.",
  },
  {
    key: "invoice_past_due_enabled",
    testidSuffix: "invoice-past-due-enabled",
    label: "Send past-due reminder email on outstanding invoices",
    description:
      "Fires from the invoice reminder flow. Pay-link + outstanding " +
      "balance. Does not affect estimate reminders (see below). " +
      "Default on.",
  },
  {
    key: "estimate_reminder_enabled",
    testidSuffix: "estimate-reminder-enabled",
    label: "Send review reminder email on pending estimates / quotes",
    description:
      "Fires from the estimate reminder flow with a review CTA. " +
      "Never mentions balance or Pay Now. Default on.",
  },
];

export function TenantAutomationTogglesSection() {
  const nav = useNavigate();
  // Single shared GET for all 4 flags — one round-trip on mount.
  const [values, setValues] = useState(null);  // null while loading
  const [saving, setSaving] = useState({});
  const [toasts, setToasts] = useState({});

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/tenants/mine/settings");
        const v = {};
        for (const f of _P2_10E_FLAGS) {
          v[f.key] = Boolean(r?.[f.key] ?? true);
        }
        setValues(v);
      } catch {
        const v = {};
        for (const f of _P2_10E_FLAGS) v[f.key] = true;
        setValues(v);
      }
    })();
  }, []);

  const flip = async (flagKey) => {
    if (!values || saving[flagKey]) return;
    const next = !values[flagKey];
    setSaving((s) => ({ ...s, [flagKey]: true }));
    setValues((v) => ({ ...v, [flagKey]: next }));  // optimistic
    try {
      const r = await api.patch(
        "/tenants/mine/settings",
        { [flagKey]: next },
      );
      setValues((v) => ({
        ...v, [flagKey]: Boolean(r?.[flagKey] ?? next),
      }));
      setToasts((t) => ({ ...t, [flagKey]: "Saved" }));
    } catch (e) {
      // Rollback.
      setValues((v) => ({ ...v, [flagKey]: !next }));
      setToasts((t) => ({ ...t, [flagKey]: e?.message || "Save failed" }));
    } finally {
      setSaving((s) => ({ ...s, [flagKey]: false }));
      setTimeout(
        () => setToasts((t) => ({ ...t, [flagKey]: "" })),
        2000,
      );
    }
  };

  const loading = values === null;

  return (
    <div
      className="rounded-2xl mb-4 overflow-hidden"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="tenant-automation-toggles-section"
    >
      <div
        className="px-4 py-3 border-b flex items-center justify-between gap-3 flex-wrap"
        style={{
          borderColor: colors.border,
          backgroundColor: colors.surfaceSecondary,
        }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <Sparkles size={14} style={{ color: colors.brand }} />
          <div
            className="text-sm font-bold"
            style={{ color: colors.onSurface }}
          >
            Automated customer notifications
          </div>
        </div>
        <button
          type="button"
          onClick={() => nav("/settings/notifications/templates")}
          className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1.5 rounded-lg"
          style={{
            color: colors.brand,
            backgroundColor: colors.brandTertiary || "transparent",
            border: `1px solid ${colors.border}`,
          }}
          data-testid="tenant-automation-customize-templates-link"
        >
          Customize templates <ChevronRight size={12} />
        </button>
      </div>
      {_P2_10E_FLAGS.map((f) => {
        const on = Boolean(values?.[f.key]);
        const isSaving = Boolean(saving[f.key]);
        const toast = toasts[f.key] || "";
        return (
          <div
            key={f.key}
            className="px-4 py-3 border-b flex items-center justify-between gap-3"
            style={{ borderColor: colors.border }}
            data-testid={`tenant-toggle-${f.testidSuffix}-row`}
          >
            <div className="min-w-0">
              <div
                className="text-sm font-semibold"
                style={{ color: colors.onSurface }}
              >
                {f.label}
              </div>
              <p
                className="text-xs mt-0.5"
                style={{ color: colors.muted }}
              >
                {f.description}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {toast ? (
                <span
                  className="text-[10px] font-semibold px-2 py-1 rounded"
                  style={{
                    backgroundColor:
                      toast === "Saved" ? "#DCFCE7" : "#FEE2E2",
                    color:
                      toast === "Saved" ? "#166534" : "#991B1B",
                  }}
                  data-testid={`tenant-toggle-${f.testidSuffix}-toast`}
                >
                  {toast}
                </span>
              ) : null}
              <button
                type="button"
                role="switch"
                aria-checked={on}
                onClick={() => flip(f.key)}
                disabled={loading || isSaving}
                className="relative inline-flex items-center h-6 w-11 rounded-full transition-colors"
                style={{
                  backgroundColor: on ? colors.brand : "#D1D5DB",
                  opacity: loading ? 0.5 : 1,
                  cursor: loading ? "wait" : "pointer",
                }}
                data-testid={`tenant-toggle-${f.testidSuffix}`}
              >
                <span
                  className="inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform"
                  style={{
                    transform: `translateX(${on ? 22 : 2}px)`,
                  }}
                />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
