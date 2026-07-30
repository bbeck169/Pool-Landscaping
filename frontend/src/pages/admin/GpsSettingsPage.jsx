/**
 * G0 · Feb-2026 — GPS Driver Activity admin settings.
 *
 * Foundational admin surface. No data collection happens yet — G1
 * hooks the mobile ``expo-location`` wire once these settings are
 * signed off.
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, ShieldAlert, MapPin, Save, Loader2,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";
import AttributionSettingsPanel from "@/pages/admin/AttributionSettingsPanel";

const HELPER_FG =
  "How often the app sends a location ping while the technician has the "
  + "tech app in the foreground (screen on). Range 15–600 seconds.";
const HELPER_BG =
  "Ping interval while the app is running in the background. Range "
  + "60–3600 seconds. Battery-friendly defaults sit around 5 minutes.";
const HELPER_RETENTION =
  "How many days of raw location pings are retained before the daily "
  + "purge cron drops them. Range 7–365 days.";

export default function GpsSettingsPage() {
  const nav = useNavigate();
  const { user } = useAuth() || {};
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";

  const [form, setForm] = useState(null);
  const [initial, setInitial] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");

  useEffect(() => {
    if (!isAdmin) return;
    (async () => {
      try {
        const r = await api.get("/admin/gps/settings");
        setForm(r); setInitial(r);
      } catch (e) {
        setErr(e?.message || "Failed to load settings.");
      }
    })();
  }, [isAdmin]);

  const bump = (patch) => {
    setOk("");
    setForm((cur) => ({ ...(cur || {}), ...patch }));
  };

  const save = async () => {
    setBusy(true); setErr(""); setOk("");
    // Diff → only send changed fields (cleaner audit trail).
    const payload = {};
    ["enabled", "hr_agreement_ack",
      "ping_interval_foreground_s", "ping_interval_background_s",
      "retention_days", "geocoder"].forEach((k) => {
      if (form[k] !== initial[k]) payload[k] = form[k];
    });
    if (Object.keys(payload).length === 0) {
      setOk("No changes to save.");
      setBusy(false);
      return;
    }
    try {
      const r = await api.put("/admin/gps/settings", payload);
      setForm(r); setInitial(r);
      setOk("Settings saved.");
    } catch (e) {
      // Inline hr_agreement_required guidance.
      const msg = String(e?.message || "");
      if (/hr_agreement_required/.test(msg)) {
        setErr("Tick the HR agreement box before enabling tracking.");
      } else {
        setErr(msg || "Save failed.");
      }
    } finally {
      setBusy(false);
    }
  };

  if (!isAdmin) {
    return (
      <div className="p-8 max-w-2xl mx-auto"
             data-testid="gps-settings-forbidden">
        <div className="rounded-xl p-4 text-sm"
              style={{ background: "#FEE2E2", color: "#7F1D1D",
                        border: "1px solid #FCA5A5" }}>
          <b>Admin only.</b> This page controls tenant-wide operational
          settings.
        </div>
      </div>
    );
  }

  if (!form) {
    return (
      <div className="p-8 max-w-2xl mx-auto"
             data-testid="gps-settings-loading">
        <Loader2 size={16} className="animate-spin" /> Loading…
      </div>
    );
  }

  const enableDisabled = !form.hr_agreement_ack;

  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto space-y-5"
           data-testid="gps-settings-page">
      <button onClick={() => nav(-1)}
                className="flex items-center gap-1 text-sm font-semibold"
                style={{ color: colors.muted }}>
        <ArrowLeft size={14} /> Back
      </button>

      <div className="flex items-center gap-2">
        <MapPin size={22} color="#0891B2" />
        <h1 className="text-2xl font-bold"
             style={{ color: colors.onSurface }}>
          GPS Driver Activity
        </h1>
      </div>

      <div className="rounded-xl p-4 flex items-start gap-2"
            style={{ background: "#FEF3C7", color: "#78350F",
                      border: "1px solid #FCD34D" }}
            data-testid="gps-settings-hr-warning">
        <ShieldAlert size={16} style={{ marginTop: 2 }} />
        <div className="text-sm">
          This feature will begin tracking technician location while they
          are clocked in. Ensure written HR agreements are on file before
          enabling.
        </div>
      </div>

      <section className="rounded-2xl p-5 space-y-4"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}>
        <label className="flex items-center gap-2 text-sm font-semibold"
                style={{ color: colors.onSurface }}>
          <input
            type="checkbox"
            checked={!!form.hr_agreement_ack}
            onChange={(e) => bump({ hr_agreement_ack: e.target.checked })}
            data-testid="gps-settings-hr-ack"
          />
          HR agreement on file
        </label>

        <label className="flex items-center gap-2 text-sm font-semibold"
                style={{ color: colors.onSurface,
                          opacity: enableDisabled ? 0.5 : 1 }}>
          <input
            type="checkbox"
            checked={!!form.enabled}
            disabled={enableDisabled}
            onChange={(e) => bump({ enabled: e.target.checked })}
            data-testid="gps-settings-enable"
          />
          Enable tracking (while clocked in)
        </label>

        <div className="grid md:grid-cols-2 gap-4 pt-2 border-t"
              style={{ borderColor: colors.border }}>
          <div>
            <label className="text-xs uppercase font-bold mb-1 block"
                    style={{ color: colors.muted }}>
              Foreground ping (s)
            </label>
            <input
              type="number" min={15} max={600}
              value={form.ping_interval_foreground_s}
              onChange={(e) => bump({ ping_interval_foreground_s:
                                          parseInt(e.target.value, 10) || 0 })}
              className="w-full px-3 py-1.5 rounded-md text-sm"
              style={{ border: `1px solid ${colors.border}` }}
              data-testid="gps-settings-fg-interval"
            />
            <p className="text-[11px] mt-1"
                style={{ color: colors.muted }}>{HELPER_FG}</p>
          </div>
          <div>
            <label className="text-xs uppercase font-bold mb-1 block"
                    style={{ color: colors.muted }}>
              Background ping (s)
            </label>
            <input
              type="number" min={60} max={3600}
              value={form.ping_interval_background_s}
              onChange={(e) => bump({ ping_interval_background_s:
                                          parseInt(e.target.value, 10) || 0 })}
              className="w-full px-3 py-1.5 rounded-md text-sm"
              style={{ border: `1px solid ${colors.border}` }}
              data-testid="gps-settings-bg-interval"
            />
            <p className="text-[11px] mt-1"
                style={{ color: colors.muted }}>{HELPER_BG}</p>
          </div>
          <div>
            <label className="text-xs uppercase font-bold mb-1 block"
                    style={{ color: colors.muted }}>
              Retention (days)
            </label>
            <input
              type="number" min={7} max={365}
              value={form.retention_days}
              onChange={(e) => bump({ retention_days:
                                          parseInt(e.target.value, 10) || 0 })}
              className="w-full px-3 py-1.5 rounded-md text-sm"
              style={{ border: `1px solid ${colors.border}` }}
              data-testid="gps-settings-retention"
            />
            <p className="text-[11px] mt-1"
                style={{ color: colors.muted }}>{HELPER_RETENTION}</p>
          </div>
          <div>
            <label className="text-xs uppercase font-bold mb-1 block"
                    style={{ color: colors.muted }}>
              Geocoder
            </label>
            <select
              value={form.geocoder}
              onChange={(e) => bump({ geocoder: e.target.value })}
              className="w-full px-3 py-1.5 rounded-md text-sm"
              style={{ border: `1px solid ${colors.border}` }}
              data-testid="gps-settings-geocoder"
            >
              <option value="mapbox">Mapbox</option>
            </select>
            <p className="text-[11px] mt-1"
                style={{ color: colors.muted }}>
              Additional providers land in a later phase.
            </p>
          </div>
        </div>

        {err ? (
          <div className="text-sm rounded-md p-2"
                style={{ background: "#FEE2E2", color: "#7F1D1D" }}
                data-testid="gps-settings-error">
            {err}
          </div>
        ) : null}
        {ok ? (
          <div className="text-sm rounded-md p-2"
                style={{ background: "#DCFCE7", color: "#166534" }}
                data-testid="gps-settings-ok">
            {ok}
          </div>
        ) : null}

        <div className="flex justify-end">
          <button
            type="button"
            onClick={save}
            disabled={busy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-bold text-white"
            style={{ background: "#0891B2", opacity: busy ? 0.6 : 1 }}
            data-testid="gps-settings-save"
          >
            <Save size={12} /> {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </section>
      {/* G5b · Feb-2026 — Stop → Job attribution knobs. */}
      <AttributionSettingsPanel />
    </div>
  );
}
