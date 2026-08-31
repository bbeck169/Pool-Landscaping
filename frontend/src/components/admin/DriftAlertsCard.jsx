/**
 * Phase D · Feb-2026 — Drift Alerts settings card.
 *
 * Mounted directly under the DataIntegrityTile on /admin/migrations.
 * Reads GET /admin/settings/drift-alerts (masked webhook), PUTs on
 * save, POSTs to /test-fire for a manual dispatch that bypasses
 * both the 08:00 gate and the same-day dedupe.
 *
 * data-testids:
 *   drift-alerts-card
 *   drift-alerts-enabled-toggle
 *   drift-alerts-emails-input
 *   drift-alerts-webhook-input
 *   drift-alerts-save-btn
 *   drift-alerts-test-fire-btn
 *   drift-alerts-last-dispatch
 *   drift-alerts-timezone-input
 */
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { api } from "@/api";
import { colors } from "@/theme";
import { Bell, PlayCircle, Save as SaveIcon } from "lucide-react";


export default function DriftAlertsCard({ userRole }) {
  const [loaded, setLoaded] = useState(false);
  const [settings, setSettings] = useState({
    enabled: true,
    email_recipients: [],
    slack_webhook_url_masked: "",
    timezone: "America/Phoenix",
  });
  const [webhookDraft, setWebhookDraft] = useState("");
  const [emailDraft, setEmailDraft] = useState("");
  const [tzDraft, setTzDraft] = useState("America/Phoenix");
  const [enabledDraft, setEnabledDraft] = useState(true);
  const [saving, setSaving] = useState(false);
  const [firing, setFiring] = useState(false);
  const [last, setLast] = useState(null);

  const load = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([
        api.get("/admin/settings/drift-alerts"),
        api.get("/admin/settings/drift-alerts/last-dispatch"),
      ]);
      setSettings(s);
      setEmailDraft((s.email_recipients || []).join(", "));
      setTzDraft(s.timezone || "America/Phoenix");
      setEnabledDraft(!!s.enabled);
      setWebhookDraft("");  // never populate from masked value
      setLast(l?.present ? l : null);
    } catch (e) {
      toast.error(e?.message || "Failed to load drift alert settings");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const emails = emailDraft
        .split(",").map((s) => s.trim()).filter(Boolean);
      const body = {
        enabled: enabledDraft,
        email_recipients: emails,
        timezone: tzDraft || "America/Phoenix",
      };
      if (webhookDraft) body.slack_webhook_url = webhookDraft;
      const updated = await api.put(
        "/admin/settings/drift-alerts", body,
      );
      setSettings(updated);
      setWebhookDraft("");
      toast.success("Drift alerts saved");
    } catch (e) {
      toast.error(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const testFire = async () => {
    setFiring(true);
    try {
      const r = await api.post(
        "/admin/settings/drift-alerts/test-fire", {},
      );
      const total = r?.dangling_refs_total ?? 0;
      const reason = r?.reason || "unknown";
      if (r?.dispatched) {
        toast.success(
          `Test dispatch sent · ${total} drift ref${total !== 1 ? "s" : ""} · ` +
          `channels: ${(r.channels_notified || []).join(", ") || "none"}`,
          { duration: 6000 },
        );
      } else {
        toast(
          reason === "clean"
            ? "F3 is clean — nothing to alert. Audit heartbeat written."
            : `Test fire: ${reason}`,
          { duration: 5000 },
        );
      }
      await load();
    } catch (e) {
      toast.error(e?.message || "Test fire failed");
    } finally {
      setFiring(false);
    }
  };

  const canTestFire = userRole === "super_admin";

  return (
    <div
      className="rounded-2xl p-5 mb-4"
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="drift-alerts-card"
    >
      <div className="flex items-start gap-3 mb-3">
        <Bell size={20} color="#0284C7" />
        <div>
          <div
            className="text-lg font-semibold"
            style={{ color: colors.onSurface }}
          >
            Drift Alerts
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Daily 08:00 tenant-local digest when the F3 boot check
            detects dangling refs. Slack + email, idempotent per day.
          </div>
        </div>
      </div>

      {!loaded ? (
        <div className="text-sm" style={{ color: colors.muted }}>
          Loading…
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabledDraft}
              onChange={(e) => setEnabledDraft(e.target.checked)}
              data-testid="drift-alerts-enabled-toggle"
            />
            <span style={{ color: colors.onSurface }}>
              Enabled
            </span>
          </label>

          <div>
            <div
              className="text-xs font-semibold mb-1"
              style={{ color: colors.muted }}
            >
              Email recipients (comma-separated)
            </div>
            <input
              type="text"
              value={emailDraft}
              onChange={(e) => setEmailDraft(e.target.value)}
              placeholder="ops@example.com, alerts@example.com"
              className="w-full rounded-lg px-3 py-2 text-sm"
              style={{
                border: `1px solid ${colors.border}`,
                background: colors.surfaceSecondary,
                color: colors.onSurface,
              }}
              data-testid="drift-alerts-emails-input"
            />
          </div>

          <div>
            <div
              className="text-xs font-semibold mb-1"
              style={{ color: colors.muted }}
            >
              Slack webhook URL{" "}
              {settings.slack_webhook_url_masked ? (
                <span style={{ color: colors.onSurface }}>
                  (current: <code>{settings.slack_webhook_url_masked}</code>)
                </span>
              ) : null}
            </div>
            <input
              type="password"
              value={webhookDraft}
              onChange={(e) => setWebhookDraft(e.target.value)}
              placeholder={
                settings.slack_webhook_url_masked
                  ? "Enter new URL to replace"
                  : "https://hooks.slack.com/services/…"
              }
              className="w-full rounded-lg px-3 py-2 text-sm"
              style={{
                border: `1px solid ${colors.border}`,
                background: colors.surfaceSecondary,
                color: colors.onSurface,
              }}
              data-testid="drift-alerts-webhook-input"
            />
          </div>

          <div>
            <div
              className="text-xs font-semibold mb-1"
              style={{ color: colors.muted }}
            >
              Timezone (IANA)
            </div>
            <input
              type="text"
              value={tzDraft}
              onChange={(e) => setTzDraft(e.target.value)}
              placeholder="America/Phoenix"
              className="w-full rounded-lg px-3 py-2 text-sm"
              style={{
                border: `1px solid ${colors.border}`,
                background: colors.surfaceSecondary,
                color: colors.onSurface,
              }}
              data-testid="drift-alerts-timezone-input"
            />
          </div>

          {last ? (
            <div
              className="text-xs rounded-lg px-3 py-2"
              style={{
                background: colors.surfaceSecondary,
                color: colors.onSurfaceSecondary,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="drift-alerts-last-dispatch"
            >
              <span style={{ color: colors.muted }}>Last dispatch:</span>{" "}
              <b>{last.dispatched ? "sent" : (last.reason || "—")}</b>{" "}
              · {last.date || (last.timestamp || "").slice(0, 10)}{" "}
              {last.channels_notified?.length ? (
                <> · via {last.channels_notified.join(", ")}</>
              ) : null}
              {last.dangling_refs_total ? (
                <> · <b>{last.dangling_refs_total}</b> refs</>
              ) : null}
            </div>
          ) : (
            <div
              className="text-xs"
              style={{ color: colors.muted }}
              data-testid="drift-alerts-last-dispatch"
            >
              No dispatch history yet.
            </div>
          )}

          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-bold"
              style={{
                background: "#0284C7", color: "#fff",
                opacity: saving ? 0.55 : 1,
              }}
              data-testid="drift-alerts-save-btn"
            >
              <SaveIcon size={14} />
              {saving ? "Saving…" : "Save"}
            </button>
            {canTestFire ? (
              <button
                type="button"
                onClick={testFire}
                disabled={firing || !enabledDraft}
                className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-semibold"
                style={{
                  background: colors.surfaceSecondary,
                  color: colors.onSurfaceSecondary,
                  border: `1px solid ${colors.border}`,
                  opacity: firing || !enabledDraft ? 0.5 : 1,
                }}
                data-testid="drift-alerts-test-fire-btn"
              >
                <PlayCircle size={14} />
                {firing ? "Firing…" : "Send test digest"}
              </button>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
