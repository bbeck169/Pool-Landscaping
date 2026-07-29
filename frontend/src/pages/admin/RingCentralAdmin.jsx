/**
 * Phase 54 · Admin RingCentral settings + test screen.
 *
 * Combined page (settings on top, test tools below) so admins can flip
 * outbound and immediately validate on the same screen.
 */
import React, { useEffect, useState } from "react";
import { Phone, MessageSquare, PhoneCall, RefreshCw, ShieldAlert, Waves, Activity, Zap } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { mustConfirm } from "@/components/ui/confirm-dialog";

const evt = (r) => (r?.event_type || "unknown");

export default function RingCentralAdmin() {
  const [health, setHealth] = useState(null);
  const [events, setEvents] = useState([]);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  // Test tools state
  const [smsPhone, setSmsPhone] = useState("");
  const [smsMsg, setSmsMsg] = useState("");
  const [callPhone, setCallPhone] = useState("");
  const [simType, setSimType] = useState("telephony.session");
  const [simFrom, setSimFrom] = useState("+14805551234");
  const [simMsg, setSimMsg] = useState("");

  const load = async () => {
    try {
      const [h, e] = await Promise.all([
        api.get("/ringcentral/health"),
        api.get("/ringcentral/events?limit=20").catch(() => ({ items: [] })),
      ]);
      setHealth(h); setEvents(e?.items || []);
    } catch (er) { setError(er?.message || "load failed"); }
  };
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, []);

  const doAction = async (label, fn) => {
    setBusy(label); setError(null); setResult(null);
    try {
      const r = await fn();
      setResult({ label, ok: true, data: r });
      await load();
    } catch (e) { setResult({ label, ok: false, error: e?.message || "failed" }); }
    finally { setBusy(null); }
  };

  const registerSub = () =>
    doAction("register-subscription", () => api.post("/ringcentral/subscription/register", {}));

  const syncContacts = () =>
    doAction("sync-contacts", () => api.post("/ringcentral/contacts/sync", {}));

  const flipOutbound = async () => {
    const enabling = !health?.outbound_enabled;
    if (enabling) {
      const ok = await mustConfirm({
        title: "Enable live outbound?",
        description: "Toggling outbound ON means SMS + RingOut buttons will bill your real RingCentral account. Confirm you want to go live.",
        confirmText: "Enable live outbound",
        cancelText: "Cancel",
        tone: "destructive",
      });
      if (!ok) return;
    }
    doAction("flip-outbound", () =>
      api.post("/ringcentral/settings/outbound", { enabled: enabling }));
  };

  // Feb-2026 · Console-noise cleanup — Live inbound-events SSE toggle.
  // Default OFF so tenants without RC configured never open the
  // EventSource. Enable once RC is wired to receive live call toasts.
  const flipLiveEvents = () =>
    doAction("flip-live-events", () =>
      api.post("/ringcentral/settings/live-events",
                { enabled: !health?.live_events_enabled }));

  const testSms = async () => {
    if (!smsPhone || !smsMsg) { setResult({ label: "test-sms", ok: false, error: "phone + message required" }); return; }
    const ok = await mustConfirm({
      title: `Send test SMS to ${smsPhone}?`,
      description: "This is a live SMS from your RingCentral account (only if outbound is enabled — otherwise it's mocked).",
      confirmText: "Send", cancelText: "Cancel",
    });
    if (!ok) return;
    doAction("test-sms", () => api.post("/ringcentral/sms/send", { phone_number: smsPhone, message: smsMsg }));
  };
  const testCall = async () => {
    if (!callPhone) { setResult({ label: "test-call", ok: false, error: "phone required" }); return; }
    const ok = await mustConfirm({
      title: `RingOut to ${callPhone}?`,
      description: "This is a live call from your RingCentral account (only if outbound is enabled — otherwise it's mocked).",
      confirmText: "Call", cancelText: "Cancel",
    });
    if (!ok) return;
    doAction("test-call", () => api.post("/ringcentral/ringout", { phone_number: callPhone }));
  };
  const simulate = () => doAction("simulate", () =>
    api.post("/ringcentral/simulate-inbound",
              { event_type: simType, from_number: simFrom, message: simMsg }));

  const Row = ({ label, val, testid }) => (
    <div className="flex items-center justify-between py-1.5 text-sm" data-testid={testid}>
      <span style={{ color: colors.muted }}>{label}</span>
      <span className="font-bold" style={{ color: val ? "#166534" : "#B91C1C" }}>
        {typeof val === "boolean" ? (val ? "✓ configured" : "— missing") : (val || "—")}
      </span>
    </div>
  );

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto" data-testid="rc-admin-page">
      <div className="flex items-center gap-3 mb-6">
        <div className="w-11 h-11 rounded-xl flex items-center justify-center"
             style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
          <Phone size={20} />
        </div>
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            RingCentral
          </h1>
          <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
            Health · subscription · outbound toggle · test screen · live event log.
          </p>
        </div>
      </div>

      {/* Outbound safety banner */}
      {health?.outbound_enabled ? (
        <div className="rounded-2xl p-3 mb-4 text-sm flex items-center gap-2"
             style={{ background: "#FEE2E2", border: "1px solid #FECACA", color: "#991B1B" }}
             data-testid="rc-outbound-live-banner">
          <ShieldAlert size={16} /> Live outbound is <b>ENABLED</b>. Every RingOut + SMS bills your RingCentral account.
        </div>
      ) : (
        <div className="rounded-2xl p-3 mb-4 text-sm flex items-center gap-2"
             style={{ background: "#DCFCE7", border: "1px solid #86EFAC", color: "#166534" }}
             data-testid="rc-outbound-safe-banner">
          <ShieldAlert size={16} /> Outbound is <b>DISABLED</b> — all SMS / RingOut calls are mocked.
        </div>
      )}

      {error ? (
        <div className="rounded-2xl p-3 mb-4 text-sm"
             style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}>{error}</div>
      ) : null}

      <div className="grid md:grid-cols-2 gap-4 mb-6">
        <div className="rounded-2xl overflow-hidden"
             style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="rc-health-card">
          <div className="px-4 py-3 text-xs font-bold uppercase tracking-wider"
               style={{ background: colors.surfaceSecondary, color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
            Credentials + status
          </div>
          <div className="p-4">
            <Row testid="rc-health-client-id"     label="Client ID"      val={!!health?.client_id_configured} />
            <Row testid="rc-health-client-secret" label="Client secret"  val={!!health?.client_secret_configured} />
            <Row testid="rc-health-jwt"           label="JWT"            val={!!health?.jwt_configured} />
            <Row testid="rc-health-server"        label="Server URL"     val={!!health?.server_url_configured} />
            <Row testid="rc-health-from"          label="From number"    val={!!health?.from_number_configured} />
            <Row testid="rc-health-webhook-tok"   label="Webhook token"  val={!!health?.webhook_token_configured} />
            <Row testid="rc-health-subscription"  label="Subscription"   val={health?.active_subscription_id || null} />
            <div className="mt-3 text-[11px] break-all" style={{ color: colors.muted }}>
              Webhook URL: {health?.webhook_url}
            </div>
          </div>
        </div>
        <div className="rounded-2xl overflow-hidden"
             style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
          <div className="px-4 py-3 text-xs font-bold uppercase tracking-wider"
               style={{ background: colors.surfaceSecondary, color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
            Actions
          </div>
          <div className="p-4 space-y-2">
            <button type="button" onClick={registerSub} disabled={busy === "register-subscription"}
                    className="w-full inline-flex items-center gap-2 text-sm font-bold px-3 py-2 rounded-md"
                    style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface,
                              cursor: busy === "register-subscription" ? "wait" : "pointer" }}
                    data-testid="rc-action-register-subscription">
              <RefreshCw size={14} /> Register / Refresh webhook subscription
            </button>
            <button type="button" onClick={syncContacts} disabled={busy === "sync-contacts"}
                    className="w-full inline-flex items-center gap-2 text-sm font-bold px-3 py-2 rounded-md"
                    style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                    data-testid="rc-action-sync-contacts">
              <RefreshCw size={14} /> Sync contacts now
            </button>
            <button type="button" onClick={flipOutbound} disabled={busy === "flip-outbound"}
                    className="w-full inline-flex items-center gap-2 text-sm font-bold px-3 py-2 rounded-md"
                    style={{ background: health?.outbound_enabled ? "#DC2626" : colors.brand, color: "#fff", border: 0 }}
                    data-testid="rc-action-toggle-outbound">
              <Zap size={14} />
              {health?.outbound_enabled ? "Disable live outbound" : "Enable live outbound"}
            </button>
            <button type="button" onClick={flipLiveEvents} disabled={busy === "flip-live-events"}
                    className="w-full inline-flex items-center gap-2 text-sm font-bold px-3 py-2 rounded-md"
                    style={{
                      background: colors.surface,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}`,
                    }}
                    data-testid="rc-action-toggle-live-events"
                    title="When ON, admin + manager browsers open an SSE stream to receive inbound-call toasts. Leave OFF if RingCentral isn't fully configured yet.">
              <Zap size={14} />
              {health?.live_events_enabled
                ? "Disable inbound-call toasts (SSE)"
                : "Enable inbound-call toasts (SSE)"}
            </button>
          </div>
        </div>
      </div>

      {/* Test screen */}
      <div className="rounded-2xl overflow-hidden mb-6"
           style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="rc-test-screen">
        <div className="px-4 py-3 text-xs font-bold uppercase tracking-wider"
             style={{ background: colors.surfaceSecondary, color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
          Admin test tools
        </div>
        <div className="p-4 grid md:grid-cols-3 gap-4">
          <div>
            <div className="text-xs font-bold uppercase tracking-wider mb-2 inline-flex items-center gap-1"
                 style={{ color: colors.muted }}>
              <MessageSquare size={12} /> Test SMS
            </div>
            <input type="tel" placeholder="+14805551234" value={smsPhone} onChange={(e) => setSmsPhone(e.target.value)}
                   className="w-full px-2 py-1.5 rounded text-sm mb-1"
                   style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                   data-testid="rc-test-sms-phone" />
            <textarea placeholder="Hi from Pool & Landscaping…" value={smsMsg} onChange={(e) => setSmsMsg(e.target.value)}
                       className="w-full px-2 py-1.5 rounded text-sm mb-2 h-16"
                       style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                       data-testid="rc-test-sms-msg" />
            <button type="button" onClick={testSms} disabled={busy === "test-sms"}
                    className="w-full text-sm font-bold px-3 py-2 rounded-md"
                    style={{ background: colors.brand, color: "#fff", border: 0 }}
                    data-testid="rc-test-sms-send">
              Send test SMS
            </button>
          </div>
          <div>
            <div className="text-xs font-bold uppercase tracking-wider mb-2 inline-flex items-center gap-1"
                 style={{ color: colors.muted }}>
              <PhoneCall size={12} /> Test RingOut
            </div>
            <input type="tel" placeholder="+14805551234" value={callPhone} onChange={(e) => setCallPhone(e.target.value)}
                   className="w-full px-2 py-1.5 rounded text-sm mb-2"
                   style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                   data-testid="rc-test-call-phone" />
            <button type="button" onClick={testCall} disabled={busy === "test-call"}
                    className="w-full text-sm font-bold px-3 py-2 rounded-md"
                    style={{ background: colors.brand, color: "#fff", border: 0 }}
                    data-testid="rc-test-call-send">
              Test RingOut
            </button>
          </div>
          <div>
            <div className="text-xs font-bold uppercase tracking-wider mb-2 inline-flex items-center gap-1"
                 style={{ color: colors.muted }}>
              <Waves size={12} /> Simulate inbound
            </div>
            <select value={simType} onChange={(e) => setSimType(e.target.value)}
                    className="w-full px-2 py-1.5 rounded text-sm mb-1"
                    style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                    data-testid="rc-test-sim-type">
              <option value="telephony.session">Telephony session</option>
              <option value="instant-message-SMS">SMS</option>
              <option value="instant-message-Fax">Fax</option>
              <option value="instant-message-VoiceMail">Voicemail</option>
            </select>
            <input type="tel" placeholder="From +14805551234" value={simFrom} onChange={(e) => setSimFrom(e.target.value)}
                   className="w-full px-2 py-1.5 rounded text-sm mb-1"
                   style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                   data-testid="rc-test-sim-from" />
            <input type="text" placeholder="Message (optional)" value={simMsg} onChange={(e) => setSimMsg(e.target.value)}
                   className="w-full px-2 py-1.5 rounded text-sm mb-2"
                   style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                   data-testid="rc-test-sim-msg" />
            <button type="button" onClick={simulate} disabled={busy === "simulate"}
                    className="w-full text-sm font-bold px-3 py-2 rounded-md"
                    style={{ background: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                    data-testid="rc-test-sim-run">
              Trigger simulated inbound
            </button>
          </div>
        </div>
        {result ? (
          <div className="px-4 py-3 text-xs" style={{ borderTop: `1px solid ${colors.border}`, background: colors.surfaceSecondary }}
               data-testid="rc-test-result">
            <b style={{ color: result.ok ? "#166534" : "#B91C1C" }}>
              {result.ok ? "OK" : "FAILED"} · {result.label}
            </b>
            <pre className="mt-1 overflow-x-auto font-mono text-[11px]" style={{ color: colors.muted, whiteSpace: "pre-wrap" }}>
              {JSON.stringify(result.ok ? result.data : result.error, null, 2)}
            </pre>
          </div>
        ) : null}
      </div>

      {/* Live event feed */}
      <div className="rounded-2xl overflow-hidden"
           style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="rc-event-feed">
        <div className="px-4 py-3 flex items-center justify-between"
             style={{ background: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
          <span className="text-xs font-bold uppercase tracking-wider inline-flex items-center gap-1"
                style={{ color: colors.muted }}>
            <Activity size={12} /> Recent webhook events (last 20)
          </span>
          <button type="button" onClick={load}
                  className="text-xs font-semibold px-2 py-1 rounded"
                  style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                  data-testid="rc-event-feed-refresh">
            <RefreshCw size={11} /> Refresh
          </button>
        </div>
        {events.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm" style={{ color: colors.muted }}
               data-testid="rc-event-feed-empty">
            No events yet — trigger a simulated inbound above or wait for a real call.
          </div>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {events.map((r) => (
                <tr key={r.id} data-testid={`rc-event-row-${r.id}`}
                    style={{ borderBottom: `1px solid ${colors.border}` }}>
                  <td className="px-4 py-2 text-xs" style={{ color: colors.muted }}>
                    {r.received_at ? new Date(r.received_at).toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-2 font-semibold" style={{ color: colors.onSurface }}>{evt(r)}</td>
                  <td className="px-4 py-2 text-right text-[11px]" style={{ color: colors.muted }}>
                    {r.raw_payload_size_bytes || 0} b
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
