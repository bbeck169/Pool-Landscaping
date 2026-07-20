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
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.get("/settings/notifications");
      setKinds(r?.kinds || []);
      setChannels(r?.channels || {});
      setInitial(JSON.parse(JSON.stringify(r?.channels || {})));
    } catch { /* silent */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  const flip = (kind, chan) => {
    setChannels((prev) => ({
      ...prev,
      [kind]: { ...(prev[kind] || {}), [chan]: !prev?.[kind]?.[chan] },
    }));
  };

  const dirty = JSON.stringify(channels) !== JSON.stringify(initial);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put("/settings/notifications", { channels });
      setChannels(r?.channels || channels);
      setInitial(JSON.parse(JSON.stringify(r?.channels || channels)));
      setToast("Preferences saved");
      setTimeout(() => setToast(""), 2000);
    } catch (e) {
      setToast(e?.message || "Save failed");
      setTimeout(() => setToast(""), 3000);
    }
    setSaving(false);
  };

  const reset = () => setChannels(JSON.parse(JSON.stringify(initial)));

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
    </div>
  );
}
