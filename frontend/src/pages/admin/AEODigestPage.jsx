/** Phase 8 · Feb-2026 — Weekly AEO PDF Digest admin page. */
import React from "react";
import { toast } from "sonner";
import { FileDown, Send, PlayCircle, Save } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const DOW = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];

export default function AEODigestPage() {
  const [_settings, setSettings] = React.useState(null);
  const [form, setForm] = React.useState({ enabled: false, recipient_emails: "",
    day_of_week: 1, hour_utc: 15, include_negative_snippets: true });
  const [preview, setPreview] = React.useState(null);
  const [history, setHistory] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const backendBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");

  const load = React.useCallback(async () => {
    try {
      const [s, h] = await Promise.all([
        api.get("/aeo/digest/settings"),
        api.get("/aeo/digest/history?limit=10"),
      ]);
      setSettings(s);
      setForm({ enabled: !!s.enabled,
                 recipient_emails: (s.recipient_emails || []).join(", "),
                 day_of_week: s.day_of_week ?? 1,
                 hour_utc: s.hour_utc ?? 15,
                 include_negative_snippets: s.include_negative_snippets !== false });
      setHistory(h.items || []);
    } catch (e) { toast.error(e?.message || "Failed to load"); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const save = async () => {
    setBusy(true);
    try {
      const r = await api.post("/aeo/digest/settings", {
        enabled: !!form.enabled,
        recipient_emails: form.recipient_emails.split(",").map((s) => s.trim()).filter(Boolean),
        day_of_week: parseInt(form.day_of_week, 10),
        hour_utc: parseInt(form.hour_utc, 10),
        include_negative_snippets: !!form.include_negative_snippets,
      });
      setSettings(r);
      toast.success("Settings saved");
    } catch (e) { toast.error(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  const runPreview = async () => {
    setBusy(true);
    try {
      const r = await api.post("/aeo/digest/preview", {});
      setPreview(r);
    } catch (e) { toast.error(e?.message || "Preview failed"); }
    finally { setBusy(false); }
  };

  const sendTest = async () => {
    setBusy(true);
    try {
      const r = await api.post("/aeo/digest/run-now", { deliver: true });
      const em = r.delivery?.email;
      if (em?.sent) toast.success(`Sent to ${em.recipients?.length || 0} recipients`);
      else toast.error(`Delivery failed: ${em?.error || "unknown"}`);
      load();
    } catch (e) { toast.error(e?.message || "Failed"); }
    finally { setBusy(false); }
  };

  return (
    <div className="px-4 md:px-8 pt-4 space-y-4 pb-24"
          data-testid="aeo-digest-page">
      <div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight"
            style={{ color: colors.onSurface }}>Weekly AEO PDF Digest</h1>
        <p className="text-sm" style={{ color: colors.muted }}>
          1-2 page PDF snapshot of AEO score, AI visibility, brand mentions
          and action items — emailed via Resend every Monday.
        </p>
      </div>

      <div className="rounded-xl p-4 space-y-3"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="aeo-digest-settings">
        <div className="text-xs uppercase tracking-wide font-semibold"
              style={{ color: colors.muted }}>Settings</div>
        <input value={form.recipient_emails}
                onChange={(e) => setForm({ ...form, recipient_emails: e.target.value })}
                placeholder="owner@example.com, marketing@example.com"
                className="w-full rounded-lg px-3 py-1.5 text-sm"
                style={{ backgroundColor: colors.surfaceSecondary,
                          color: colors.onSurface,
                          border: `1px solid ${colors.border}` }}
                data-testid="aeo-digest-recipients" />
        <div className="grid grid-cols-1 md:grid-cols-4 gap-2 items-end">
          <div>
            <label className="text-[11px] font-semibold" style={{ color: colors.muted }}>Day of week</label>
            <select value={form.day_of_week}
                     onChange={(e) => setForm({ ...form, day_of_week: parseInt(e.target.value, 10) })}
                     className="w-full rounded-lg px-2 py-1.5 text-sm"
                     style={{ backgroundColor: colors.surfaceSecondary,
                               color: colors.onSurface,
                               border: `1px solid ${colors.border}` }}
                     data-testid="aeo-digest-dow">
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
                    data-testid="aeo-digest-hour" />
          </div>
          <label className="flex items-center gap-2 text-sm"
                  style={{ color: colors.onSurface }}>
            <input type="checkbox" checked={form.enabled}
                    onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                    data-testid="aeo-digest-enabled" />
            Enabled
          </label>
          <label className="flex items-center gap-2 text-sm"
                  style={{ color: colors.onSurface }}>
            <input type="checkbox" checked={form.include_negative_snippets}
                    onChange={(e) => setForm({ ...form, include_negative_snippets: e.target.checked })}
                    data-testid="aeo-digest-neg-snippets" />
            Include negative snippets
          </label>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={save} disabled={busy}
                   className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50"
                   style={{ backgroundColor: colors.brand, color: "#fff" }}
                   data-testid="aeo-digest-save">
            <Save size={14} /> Save
          </button>
          <button onClick={sendTest} disabled={busy}
                   className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50"
                   style={{ backgroundColor: colors.surfaceSecondary,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="aeo-digest-send-test">
            <Send size={14} /> Send test digest to me now
          </button>
          <button onClick={runPreview} disabled={busy}
                   className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50"
                   style={{ backgroundColor: colors.surfaceSecondary,
                             color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                   data-testid="aeo-digest-preview-run">
            <PlayCircle size={14} /> Generate preview
          </button>
        </div>
      </div>

      {preview ? (
        <div className="rounded-xl p-4 space-y-2"
              style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
              data-testid="aeo-digest-preview-result">
          <div className="text-xs uppercase tracking-wide font-semibold"
                style={{ color: colors.muted }}>
            Preview · {preview.pdf_size_bytes} bytes
          </div>
          <iframe title="AEO Digest PDF preview"
                   src={backendBase + preview.pdf_url}
                   style={{ width: "100%", height: 640,
                             border: `1px solid ${colors.border}`, borderRadius: 8 }}
                   data-testid="aeo-digest-pdf-frame" />
          <a href={backendBase + preview.pdf_url} target="_blank" rel="noopener noreferrer"
              className="text-xs font-semibold inline-flex items-center gap-1"
              style={{ color: colors.brand }}>
            <FileDown size={12} /> Open PDF
          </a>
        </div>
      ) : null}

      <div className="rounded-xl p-4"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="aeo-digest-history">
        <div className="text-xs uppercase tracking-wide font-semibold mb-2"
              style={{ color: colors.muted }}>History</div>
        {history.length === 0 ? (
          <div className="text-xs" style={{ color: colors.muted }}>No digests yet.</div>
        ) : (
          <ul className="text-xs space-y-1">
            {history.map((h) => (
              <li key={h.digest_id} className="flex items-center justify-between gap-2 p-2 rounded-md"
                   style={{ backgroundColor: colors.surfaceSecondary,
                             border: `1px solid ${colors.border}` }}>
                <span style={{ color: colors.onSurface }}>
                  <b>{h.period_start}</b> – {h.period_end} · {h.pdf_size_bytes}B
                </span>
                <span>
                  <a href={backendBase + h.pdf_url} target="_blank" rel="noopener noreferrer"
                      className="mr-2" style={{ color: colors.brand }}>Download</a>
                  <span style={{ color: colors.muted }}>
                    Email {h.delivery?.email?.sent ? "✓" : "✗"}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
