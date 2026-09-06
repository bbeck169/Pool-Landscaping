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
import { ArrowLeft, Bell, Mail, MessageSquare, Save, Smartphone, Undo2 } from "lucide-react";
import { api } from "@/api";
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
