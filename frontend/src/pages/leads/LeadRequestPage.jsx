import React, { useEffect, useState } from "react";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { api } from "@/api";
import { colors, gradients } from "@/theme";
import { Link2, MessageSquare, Mail, Copy, RefreshCw, X } from 'lucide-react';

const Card = ({ children, className = "", testId }) => (
  <div className={"rounded-2xl " + className}
       style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
       data-testid={testId}>{children}</div>
);
const H = ({ title, sub, right }) => (
  <div className="flex items-start justify-between mb-6">
    <div>
      <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>{title}</h1>
      {sub && <p className="text-sm mt-1" style={{ color: colors.muted }}>{sub}</p>}
    </div>
    {right}
  </div>
);

const DEFAULT_MSG = "Please complete the following information & we will get back with you shortly.";

function expiryLabel(exp) {
  if (!exp) return { label: "No expiry", tone: "muted" };
  const ms = new Date(exp).getTime() - Date.now();
  if (ms <= 0) return { label: "Expired", tone: "danger" };
  const hrs = Math.round(ms / 3600000);
  if (hrs >= 24) return { label: `${hrs}h left`, tone: "success" };
  return { label: `${hrs}h left`, tone: "warning" };
}
const TONE_BG = { success: "#DCFCE7", warning: "#FEF3C7", danger: "#FEE2E2", muted: "#E5E7EB" };
const TONE_FG = { success: "#166534", warning: "#92400E", danger: "#991B1B", muted: "#6B7280" };

export default function LeadRequestPage() {
  const [message, setMessage] = useState(DEFAULT_MSG);
  const [smsPhone, setSmsPhone] = useState("");
  const [emailTo, setEmailTo] = useState("");
  const [expiryHours, setExpiryHours] = useState(48);
  const [dispatches, setDispatches] = useState([]);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");

  const showToast = (t) => { setToast(t); setTimeout(() => setToast(""), 3000); };
  const load = () => api.get("/lead-requests").then(setDispatches).catch(() => {});
  useEffect(() => { load(); }, []);

  const generate = async (method) => {
    if (method === "sms" && !smsPhone.trim()) return showToast("Enter a phone number");
    if (method === "email" && !emailTo.trim()) return showToast("Enter an email address");
    setBusy(true);
    try {
      const body = {
        method,
        custom_message: message,
        expiry_hours: expiryHours,
        to: method === "sms" ? smsPhone : method === "email" ? emailTo : null,
      };
      const r = await api.post("/lead-requests/generate", body);
      if (method === "link") {
        try { await navigator.clipboard.writeText(r.url); showToast("Link copied to clipboard"); }
        catch { showToast(`Link: ${r.url}`); }
      } else if (method === "sms") {
        if (r.sent) showToast("SMS sent");
        else if (r.reason === "sms-not-configured" || r.reason === "twilio-not-configured") {
          try { await navigator.clipboard.writeText(r.url); showToast("SMS delivery not configured — link copied to clipboard"); }
          catch { showToast(`SMS delivery not configured. Copy link manually: ${r.url}`); }
        } else showToast(`Send failed: ${r.reason || "unknown"}`);
      } else if (method === "email") {
        if (r.sent) showToast("Email sent");
        else {
          try { await navigator.clipboard.writeText(r.url); showToast("Email send failed — link copied instead"); }
          catch { showToast(`Copy link manually: ${r.url}`); }
        }
      }
      await load();
    } catch (e) { showToast(e.message || "Failed"); }
    finally { setBusy(false); }
  };

  const revoke = async (did) => {
    if (!(await mustConfirm({ title: "Revoke this link?", description: "The prospect will no longer be able to submit.", tone: "danger" }))) return;
    await api.post(`/lead-requests/${did}/revoke`, {});
    showToast("Link revoked");
    load();
  };
  const resend = async (did) => {
    setBusy(true);
    try {
      const r = await api.post(`/lead-requests/${did}/resend`, {});
      showToast(r.sent ? "Re-sent" : `Re-send failed: ${r.reason || "unknown"}`);
      load();
    } finally { setBusy(false); }
  };
  const copyLink = async (url) => {
    try { await navigator.clipboard.writeText(url); showToast("Link copied"); } catch {}
  };

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="lead-request-page">
      <H title="Request info from a prospect"
         sub="Generate a single-use link and send it via link, SMS, or email. The prospect fills a short form; a new lead is created automatically."
      />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <Card className="p-5" testId="lr-message-card">
          <label className="text-xs font-bold uppercase tracking-wide mb-2 block" style={{ color: colors.muted }}>
            Personal message (shown to the prospect)
          </label>
          <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={3}
                    className="w-full px-3 py-2 rounded-lg text-sm outline-none mb-3"
                    style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface, color: colors.onSurface }}
                    data-testid="lr-message" />
          <label className="text-xs font-bold uppercase tracking-wide mb-1 block" style={{ color: colors.muted }}>
            Link expires in
          </label>
          <select value={expiryHours} onChange={(e) => setExpiryHours(parseInt(e.target.value, 10))}
                  className="px-3 py-2 rounded-lg text-sm outline-none"
                  style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface, color: colors.onSurface }}
                  data-testid="lr-expiry">
            <option value={24}>24 hours</option>
            <option value={48}>48 hours (default)</option>
            <option value={72}>72 hours</option>
            <option value={168}>7 days</option>
          </select>
        </Card>

        <Card className="p-5 space-y-4" testId="lr-options">
          {/* Copy Link */}
          <div className="pb-3" style={{ borderBottom: `1px solid ${colors.border}` }}>
            <div className="text-xs font-bold uppercase tracking-wide mb-2" style={{ color: colors.brand }}>
              Option 1 — Copy Link
            </div>
            <button onClick={() => generate("link")} disabled={busy}
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-bold text-white"
                    style={{ background: gradients.navyToGreen.css, opacity: busy ? 0.6 : 1 }}
                    data-testid="lr-generate-link">
              <Link2 size={14} /> Make Link to Copy
            </button>
          </div>

          {/* SMS */}
          <div className="pb-3" style={{ borderBottom: `1px solid ${colors.border}` }}>
            <div className="text-xs font-bold uppercase tracking-wide mb-2" style={{ color: colors.brand }}>
              Option 2 — Text Message
            </div>
            <input value={smsPhone} onChange={(e) => setSmsPhone(e.target.value)}
                   placeholder="+1 555 123 4567"
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none mb-2"
                   style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface, color: colors.onSurface }}
                   data-testid="lr-sms-to" />
            <button onClick={() => generate("sms")} disabled={busy}
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-bold text-white"
                    style={{ background: gradients.navyToGreen.css, opacity: busy ? 0.6 : 1 }}
                    data-testid="lr-generate-sms">
              <MessageSquare size={14} /> Request Via Text Message
            </button>
          </div>

          {/* Email */}
          <div>
            <div className="text-xs font-bold uppercase tracking-wide mb-2" style={{ color: colors.brand }}>
              Option 3 — Email
            </div>
            <input value={emailTo} onChange={(e) => setEmailTo(e.target.value)}
                   placeholder="prospect@example.com"
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none mb-2"
                   style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface, color: colors.onSurface }}
                   data-testid="lr-email-to" />
            <button onClick={() => generate("email")} disabled={busy}
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-bold text-white"
                    style={{ background: gradients.navyToGreen.css, opacity: busy ? 0.6 : 1 }}
                    data-testid="lr-generate-email">
              <Mail size={14} /> Request Via Email
            </button>
          </div>
        </Card>
      </div>

      <Card className="overflow-hidden" testId="lr-dispatches">
        <div className="grid grid-cols-12 gap-2 px-4 py-2 text-xs font-bold uppercase tracking-wide"
             style={{ color: colors.muted, backgroundColor: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
          <div className="col-span-2">Method</div>
          <div className="col-span-3">Recipient</div>
          <div className="col-span-2">Sent</div>
          <div className="col-span-2">Expiry</div>
          <div className="col-span-2">Status</div>
          <div className="col-span-1 text-right">Actions</div>
        </div>
        {dispatches.slice(0, 10).map((d) => {
          const exp = expiryLabel(d.expires_at);
          const status = d.revoked ? { label: "Revoked", tone: "danger" }
                       : d.submitted_at ? { label: "Submitted", tone: "success" }
                       : d.opened_at ? { label: "Opened", tone: "warning" }
                       : { label: "Sent", tone: "muted" };
          return (
            <div key={d.id} className="grid grid-cols-12 gap-2 px-4 py-3 text-sm items-center"
                 style={{ borderBottom: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid={`lr-row-${d.id}`}>
              <div className="col-span-2 uppercase text-xs font-semibold">{d.method}</div>
              <div className="col-span-3 truncate text-xs" style={{ color: colors.muted }}>{d.to || "—"}</div>
              <div className="col-span-2 text-xs" style={{ color: colors.muted }}>{(d.sent_at || "").slice(0, 16).replace("T", " ")}</div>
              <div className="col-span-2">
                <span className="text-[10px] font-bold px-2 py-1 rounded"
                      style={{ backgroundColor: TONE_BG[exp.tone], color: TONE_FG[exp.tone] }}>{exp.label}</span>
              </div>
              <div className="col-span-2">
                <span className="text-[10px] font-bold px-2 py-1 rounded"
                      style={{ backgroundColor: TONE_BG[status.tone], color: TONE_FG[status.tone] }}
                      data-testid={`lr-status-${d.id}`}>{status.label}</span>
              </div>
              <div className="col-span-1 flex justify-end gap-1">
                <button onClick={() => copyLink(d.url)} title="Copy link"
                        className="p-1.5 rounded"
                        style={{ backgroundColor: colors.surfaceSecondary }}
                        data-testid={`lr-copy-${d.id}`}><Copy size={12} /></button>
                {!d.submitted_at && !d.revoked && (
                  <button onClick={() => resend(d.id)} title="Re-send"
                          className="p-1.5 rounded"
                          style={{ backgroundColor: colors.surfaceSecondary }}
                          data-testid={`lr-resend-${d.id}`}><RefreshCw size={12} /></button>
                )}
                {!d.revoked && !d.submitted_at && (
                  <button onClick={() => revoke(d.id)} title="Revoke"
                          className="p-1.5 rounded"
                          style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
                          data-testid={`lr-revoke-${d.id}`}><X size={12} /></button>
                )}
              </div>
            </div>
          );
        })}
        {dispatches.length === 0 && <div className="p-6 text-center text-sm" style={{ color: colors.muted }}>No dispatches yet.</div>}
      </Card>

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl text-sm text-white shadow-lg"
             style={{ backgroundColor: colors.onSurface }}
             data-testid="lr-toast">{toast}</div>
      )}
    </div>
  );
}
