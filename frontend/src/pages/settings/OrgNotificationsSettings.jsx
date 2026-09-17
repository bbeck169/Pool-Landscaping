/**
 * Feb-2026 · Ticket #3 · Organization Notifications settings tab.
 *
 * Admin-only sidebar tab in SettingsHub. Four ON/OFF toggles that
 * each gate a real send path on the backend:
 *   1. Lead Confirmation Alerts     → lead_confirmation
 *   2. Technician On My Way         → tech_on_my_way
 *   3. Job Completion Summary       → job_completion_summary
 *   4. Warranty Expiration          → warranty_expiration
 *
 * Auto-save on toggle change (single-field PATCH) + toast feedback.
 * Backend: GET/PATCH /api/tenants/mine/settings/notifications.
 */
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Bell, Truck, ClipboardCheck, ShieldCheck } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";

const ROWS = [
  {
    key: "lead_confirmation",
    label: "Lead Confirmation Alerts",
    hint: "Notify recipients when a new lead is captured. Default channel: email + SMS.",
    Icon: Bell,
  },
  {
    key: "tech_on_my_way",
    label: "Technician On My Way",
    hint: "SMS the customer when a tech taps \"On my way\" or the route auto-arrival fires.",
    Icon: Truck,
  },
  {
    key: "job_completion_summary",
    label: "Job Completion Summary",
    hint: "Email a completion summary + photos to the customer after a job is closed.",
    Icon: ClipboardCheck,
  },
  {
    key: "warranty_expiration",
    label: "Warranty Expiration",
    hint: "Email the customer before an active warranty contract expires.",
    Icon: ShieldCheck,
  },
];

export default function OrgNotificationsSettings() {
  const { user } = useAuth() || {};
  const isAdmin = ["admin", "super_admin"].includes(
    (user?.role || "").toLowerCase(),
  );
  const [flags, setFlags] = useState(null);
  const [busy, setBusy] = useState(null);
  const [loadErr, setLoadErr] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.get("/tenants/mine/settings/notifications");
      setFlags(r || {});
      setLoadErr("");
    } catch (e) {
      setLoadErr(e?.message || "Failed to load notification settings");
    }
  }, []);

  useEffect(() => { if (isAdmin) load(); }, [load, isAdmin]);

  const flip = async (key) => {
    if (!flags || busy) return;
    const next = !flags[key];
    setBusy(key);
    // Optimistic update — revert on failure.
    setFlags((prev) => ({ ...prev, [key]: next }));
    try {
      const r = await api.patch(
        "/tenants/mine/settings/notifications",
        { [key]: next },
      );
      setFlags(r || {});
      toast.success(`${labelFor(key)} — ${next ? "ON" : "OFF"}`);
    } catch (e) {
      setFlags((prev) => ({ ...prev, [key]: !next }));
      toast.error(e?.message || `Failed to update ${labelFor(key)}`);
    } finally {
      setBusy(null);
    }
  };

  if (!isAdmin) {
    return (
      <div className="rounded-2xl p-6"
            style={{ background: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="org-notifications-forbidden">
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
          Admin access required
        </div>
        <div className="text-xs mt-1" style={{ color: colors.muted }}>
          Only admins can view or change organization-level notification settings.
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl p-5 space-y-4"
          style={{ background: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid="org-notifications-card">
      <div>
        <h2 className="text-lg font-semibold"
             style={{ color: colors.onSurface }}
             data-testid="org-notifications-title">
          Notifications
        </h2>
        <p className="text-sm mt-1" style={{ color: colors.muted }}>
          Master switches for the four org-wide send paths. When OFF, the
          corresponding email + SMS pipeline short-circuits before sending.
        </p>
      </div>

      {loadErr ? (
        <div className="rounded-lg px-3 py-2 text-sm"
              style={{ background: "#FEF2F2", color: "#991B1B",
                        border: "1px solid #FECACA" }}
              data-testid="org-notifications-error">
          {loadErr}
        </div>
      ) : null}

      {!flags && !loadErr ? (
        <div className="text-sm" style={{ color: colors.muted }}
              data-testid="org-notifications-loading">
          Loading…
        </div>
      ) : null}

      {flags ? (
        <div className="divide-y" style={{ borderColor: colors.border }}>
          {ROWS.map(({ key, label, hint, Icon }) => {
            const isOn = !!flags[key];
            return (
              <div key={key}
                    className="flex items-start justify-between gap-4 py-3"
                    data-testid={`notif-row-${key}`}>
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  <Icon size={18} style={{ color: colors.brand,
                                              marginTop: 2 }} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold"
                          style={{ color: colors.onSurface }}>
                      {label}
                    </div>
                    <div className="text-xs mt-0.5"
                          style={{ color: colors.muted }}>
                      {hint}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => flip(key)}
                  disabled={busy === key}
                  aria-pressed={isOn}
                  className="inline-flex items-center justify-center w-11 h-6 rounded-full transition-colors"
                  style={{
                    background: isOn ? "#10B981" : "#D1D5DB",
                    cursor: busy === key ? "wait" : "pointer",
                    opacity: busy === key ? 0.6 : 1,
                  }}
                  data-testid={`notif-toggle-${key}`}
                >
                  <span
                    className="block w-5 h-5 rounded-full bg-white transition-transform"
                    style={{
                      transform: isOn ? "translateX(10px)" : "translateX(-10px)",
                    }}
                  />
                </button>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function labelFor(key) {
  const row = ROWS.find((r) => r.key === key);
  return row?.label || key;
}
