/**
 * Phase 7 · Feb-2026 — Weekly Scorecard Digest admin page.
 *
 * Admin / Super Admin / Manager only. Three sections:
 *   1. Settings — Slack webhook (masked after save), recipients,
 *      day-of-week + hour, enabled toggle, "Send test digest" btn.
 *   2. Preview — pick period_end, GET /preview, render top/bottom
 *      tables per department.
 *   3. History — recent digests with per-channel delivery status.
 */
import React from "react";
import { toast } from "sonner";
import { Send, PlayCircle, Save } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const DEPT_LABEL = { field: "Field Techs", dispatch: "Dispatchers", sales: "Sales" };
const DOW = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MEDAL = ["🥇", "🥈", "🥉"];

function _delta(pct) {
  if (pct === null || pct === undefined) return { txt: "—", color: colors.muted };
  if (pct >= 0) return { txt: `↑ ${pct}%`, color: "#16A34A" };
  return { txt: `↓ ${Math.abs(pct)}%`, color: "#DC2626" };
}

export default function WeeklyDigestPage() {
  const [settings, setSettings] = React.useState(null);
  const [form, setForm] = React.useState({ slack_webhook_url: "", slack_channel: "",
                                              recipient_emails: "", enabled: false,
                                              day_of_week: 1, hour_utc: 14 });
  const [preview, setPreview] = React.useState(null);
  const [periodEnd, setPeriodEnd] = React.useState("");
  const [history, setHistory] = React.useState([]);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const [s, h] = await Promise.all([
        api.get("/scorecard/digest/settings"),
        api.get("/scorecard/digest/history?limit=10"),
      ]);
      setSettings(s);
      setForm((f) => ({
        ...f,
        slack_channel: s.slack_channel || "",
        recipient_emails: (s.recipient_emails || []).join(", "),
        enabled: !!s.enabled,
        day_of_week: s.day_of_week ?? 1,
        hour_utc: s.hour_utc ?? 14,
      }));
      setHistory(h.items || []);
    } catch (e) { toast.error(e?.message || "Failed to load"); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const save = async () => {
    setBusy(true);
    try {
      const body = {
        slack_channel: form.slack_channel || "",
        recipient_emails: form.recipient_emails.split(",").map((s) => s.trim()).filter(Boolean),
        enabled: !!form.enabled,
        day_of_week: parseInt(form.day_of_week, 10),
        hour_utc: parseInt(form.hour_utc, 10),
      };
      if (form.slack_webhook_url && form.slack_webhook_url.trim())
        body.slack_webhook_url = form.slack_webhook_url.trim();
      const r = await api.post("/scorecard/digest/settings", body);
      setSettings(r);
      setForm((f) => ({ ...f, slack_webhook_url: "" }));
      toast.success("Settings saved");
    } catch (e) { toast.error(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  const runPreview = async () => {
    try {
      const q = periodEnd ? `?period_end=${periodEnd}` : "";
      const r = await api.get(`/scorecard/digest/preview${q}`);
      setPreview(r);
    } catch (e) { toast.error(e?.message || "Preview failed"); }
  };

  const sendTest = async () => {
    setBusy(true);
    try {
      const r = await api.post("/scorecard/digest/run-now",
                                  { deliver: true });
      const parts = [];
      if (r.delivery?.slack?.sent) parts.push("Slack ✓");
      else if (r.delivery?.slack?.error) parts.push(`Slack ✗ (${r.delivery.slack.error})`);
      if (r.delivery?.email?.sent) parts.push("Email ✓");
      else if (r.delivery?.email?.error) parts.push(`Email ✗ (${r.delivery.email.error})`);
      toast.success(`Digest fired · ${parts.join(" · ") || "no channels"}`);
      load();
    } catch (e) { toast.error(e?.message || "Failed"); }
    finally { setBusy(false); }
  };

  return (
    <div className="px-4 md:px-8 pt-4 space-y-4 pb-24"
          data-testid="weekly-digest-page">
      <div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight"
            style={{ color: colors.onSurface }}>Weekly Scorecard Digest</h1>
        <p className="text-sm" style={{ color: colors.muted }}>
          Top-3 and bottom-3 performers per department, delivered to Slack
          and email every Monday at your configured hour.
        </p>
      </div>

      {/* Settings card */}
      <div className="rounded-xl p-4 space-y-3"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="weekly-digest-settings">
        <div className="text-xs uppercase tracking-wide font-semibold"
              style={{ color: colors.muted }}>Settings</div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <div>
            <label className="text-[11px] font-semibold" style={{ color: colors.muted }}>
              Slack webhook URL {settings?.slack_webhook_url_masked ? `(current: ${settings.slack_webhook_url_masked})` : ""}
            </label>
            <input value={form.slack_webhook_url}
                    onChange={(e) => setForm({ ...form, slack_webhook_url: e.target.value })}
                    placeholder="https://hooks.slack.com/services/…"
                    className="w-full rounded-lg px-3 py-1.5 text-sm"
                    style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                    data-testid="weekly-digest-slack-url" />
          </div>
          <div>
            <label className="text-[11px] font-semibold" style={{ color: colors.muted }}>Slack channel</label>
            <input value={form.slack_channel}
                    onChange={(e) => setForm({ ...form, slack_channel: e.target.value })}
                    placeholder="#leadership"
                    className="w-full rounded-lg px-3 py-1.5 text-sm"
                    style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                    data-testid="weekly-digest-slack-channel" />
          </div>
        </div>

        <div>
          <label className="text-[11px] font-semibold" style={{ color: colors.muted }}>Recipient emails (comma-separated)</label>
          <input value={form.recipient_emails}
                  onChange={(e) => setForm({ ...form, recipient_emails: e.target.value })}
                  placeholder="owner@example.com, ops@example.com"
                  className="w-full rounded-lg px-3 py-1.5 text-sm"
                  style={{ backgroundColor: colors.surfaceSecondary,
                            color: colors.onSurface,
                            border: `1px solid ${colors.border}` }}
                  data-testid="weekly-digest-recipients" />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-2 items-end">
          <div>
            <label className="text-[11px] font-semibold" style={{ color: colors.muted }}>Day of week</label>
            <select value={form.day_of_week}
                    onChange={(e) => setForm({ ...form, day_of_week: parseInt(e.target.value, 10) })}
                    className="w-full rounded-lg px-2 py-1.5 text-sm"
                    style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                    data-testid="weekly-digest-dow">
              {DOW.map((d, i) => <option key={i} value={i}>{d}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[11px] font-semibold" style={{ color: colors.muted }}>Hour (UTC)</label>
            <input type="number" min={0} max={23} value={form.hour_utc}
                    onChange={(e) => setForm({ ...form, hour_utc: parseInt(e.target.value || 0, 10) })}
                    className="w-full rounded-lg px-2 py-1.5 text-sm"
                    style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                    data-testid="weekly-digest-hour" />
          </div>
          <label className="flex items-center gap-2 text-sm"
                  style={{ color: colors.onSurface }}>
            <input type="checkbox" checked={form.enabled}
                    onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                    data-testid="weekly-digest-enabled" />
            Enabled
          </label>
          <button type="button" onClick={save} disabled={busy}
                   className="flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50"
                   style={{ backgroundColor: colors.brand, color: "#fff" }}
                   data-testid="weekly-digest-save">
            <Save size={14} /> Save
          </button>
        </div>

        <button type="button" onClick={sendTest} disabled={busy}
                 className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50"
                 style={{ backgroundColor: colors.surfaceSecondary,
                           color: colors.onSurface,
                           border: `1px solid ${colors.border}` }}
                 data-testid="weekly-digest-send-test">
          <Send size={14} /> Send test digest to me now
        </button>
      </div>

      {/* Preview card */}
      <div className="rounded-xl p-4 space-y-3"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="weekly-digest-preview">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="text-xs uppercase tracking-wide font-semibold"
                style={{ color: colors.muted }}>Preview</div>
          <input type="date" value={periodEnd}
                  onChange={(e) => setPeriodEnd(e.target.value)}
                  className="rounded-lg px-2 py-1.5 text-xs"
                  style={{ backgroundColor: colors.surfaceSecondary,
                            color: colors.onSurface,
                            border: `1px solid ${colors.border}` }}
                  data-testid="weekly-digest-period-end" />
          <button type="button" onClick={runPreview}
                   className="ml-auto flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold"
                   style={{ backgroundColor: colors.brand, color: "#fff" }}
                   data-testid="weekly-digest-preview-run">
            <PlayCircle size={12} /> Preview
          </button>
        </div>
        {preview ? (
          <div data-testid="weekly-digest-preview-result">
            <div className="text-sm font-semibold mb-2"
                  style={{ color: colors.onSurface }}>
              Week {preview.period_start} – {preview.period_end}
            </div>
            {Object.keys(preview.departments || {}).length === 0 ? (
              <div className="text-xs" style={{ color: colors.muted }}>
                No activity this week. Nothing would be sent.
              </div>
            ) : (
              Object.entries(preview.departments).map(([dept, data]) => (
                <div key={dept} className="mt-3">
                  <div className="text-xs uppercase tracking-wide font-semibold"
                        style={{ color: colors.brand }}>
                    {DEPT_LABEL[dept] || dept}
                  </div>
                  {["top", "bottom"].map((k) => (data[k] || []).length ? (
                    <div key={k} className="mt-1">
                      <div className="text-[11px] font-semibold"
                            style={{ color: colors.muted }}>{k.toUpperCase()}</div>
                      <ul className="text-xs space-y-0.5"
                           style={{ color: colors.onSurface }}>
                        {data[k].map((r, i) => {
                          const dl = _delta(r.delta_pct);
                          return (
                            <li key={r.user_id}>
                              {k === "top" && i < 3 ? MEDAL[i] : "•"}{" "}
                              <b>{r.name}</b> — {r.composite}{" "}
                              <span style={{ color: dl.color }}>({dl.txt})</span>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ) : null)}
                </div>
              ))
            )}
          </div>
        ) : (
          <div className="text-xs" style={{ color: colors.muted }}>
            Pick a period end (Sunday) and click Preview.
          </div>
        )}
      </div>

      {/* History card */}
      <div className="rounded-xl p-4"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="weekly-digest-history">
        <div className="text-xs uppercase tracking-wide font-semibold mb-2"
              style={{ color: colors.muted }}>History</div>
        {history.length === 0 ? (
          <div className="text-xs" style={{ color: colors.muted }}>No digests yet.</div>
        ) : (
          <ul className="text-xs space-y-1" data-testid="weekly-digest-history-list">
            {history.map((h) => (
              <li key={h.digest_id} className="flex items-center justify-between gap-2 p-2 rounded-md"
                   style={{ backgroundColor: colors.surfaceSecondary,
                             border: `1px solid ${colors.border}` }}>
                <span style={{ color: colors.onSurface }}>
                  <b>{h.period_start}</b> – {h.period_end}
                </span>
                <span style={{ color: colors.muted }}>
                  Slack {h.delivery?.slack?.sent ? "✓" : "✗"} · Email {h.delivery?.email?.sent ? "✓" : "✗"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
