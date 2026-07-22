import React from "react";
import { api } from "@/api";
import { toast } from "sonner";
import { Phone, RefreshCw, PlugZap, ShieldCheck, RadioTower } from "lucide-react";
import ClickToCallButton from "@/components/telephony/ClickToCallButton";

/**
 * Phase 6B · Feb 2026 — Telephony admin page (RingCentral).
 *
 * • Ping card — POST /api/dev/ringcentral-ping (round-trips RC).
 * • Verify echo card — POST /api/dev/rc-verify-echo (env / JWT sanity).
 * • Subscriptions table — GET /api/rc/subscriptions.
 * • Recent calls — GET /api/rc/logs?limit=25.
 * • Test call — ClickToCallButton wired to POST /api/rc/call.
 *
 * Admin-only. Route (App.js) applies AdminOnly guard.
 */
export default function TelephonyPage() {
  const [ping, setPing] = React.useState(null);
  const [pingBusy, setPingBusy] = React.useState(false);
  const [echo, setEcho] = React.useState(null);
  const [echoBusy, setEchoBusy] = React.useState(false);
  const [subs, setSubs] = React.useState([]);
  const [logs, setLogs] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [testNumber, setTestNumber] = React.useState("");

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [s, l] = await Promise.all([
        api.get("/rc/subscriptions").catch(() => ({ subscriptions: [] })),
        api.get("/rc/logs?limit=25").catch(() => ({ calls: [] })),
      ]);
      setSubs(s?.subscriptions || []);
      setLogs(l?.calls || []);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const runPing = async () => {
    setPingBusy(true);
    try {
      const res = await api.post("/dev/ringcentral-ping", {});
      setPing(res);
      if (res?.ok) toast.success("RingCentral ping OK");
      else toast.error("RingCentral ping failed", { description: res?.error_status ? `HTTP ${res.error_status}` : "See details" });
    } catch (e) {
      toast.error("Ping failed", { description: e?.message || "" });
      setPing({ ok: false, error_body: e?.message });
    } finally {
      setPingBusy(false);
    }
  };

  const runEcho = async () => {
    setEchoBusy(true);
    try {
      const res = await api.post("/dev/rc-verify-echo", { ping: "hello" });
      setEcho(res);
      toast.success("Token echo OK");
    } catch (e) {
      toast.error("Echo failed", { description: e?.message || "" });
      setEcho({ ok: false });
    } finally {
      setEchoBusy(false);
    }
  };

  const setupWebhooks = async () => {
    try {
      const res = await api.post("/rc/setup-webhooks", {});
      if (res?.created) toast.success("Webhook subscription created");
      else toast(`Subscription already exists`, { description: res?.subscription_id });
      load();
    } catch (e) {
      toast.error("Webhook setup failed", { description: e?.message || "" });
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto" data-testid="telephony-admin-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <RadioTower size={22} /> Telephony (RingCentral)
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Ping RingCentral, inspect webhook subscriptions, and review inbound + outbound calls.
          </p>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-300 hover:bg-slate-50 text-sm"
          data-testid="telephony-refresh-btn"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        {/* Ping card */}
        <div className="rounded-xl border border-slate-200 p-4 bg-white" data-testid="telephony-ping-card">
          <div className="flex items-center gap-2 mb-2 text-sm font-semibold">
            <PlugZap size={16} /> Ping
          </div>
          <p className="text-xs text-slate-500 mb-3">
            Round-trip to <code>/restapi/v1.0/account/~/extension/~</code>.
          </p>
          <button
            onClick={runPing}
            disabled={pingBusy}
            className="px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 text-white text-sm disabled:opacity-60"
            data-testid="telephony-ping-btn"
          >
            {pingBusy ? "Pinging…" : "Ping RingCentral"}
          </button>
          {ping && (
            <div className="mt-3 text-xs font-mono bg-slate-50 rounded p-2 overflow-x-auto" data-testid="telephony-ping-result">
              <div className={ping.ok ? "text-emerald-700" : "text-rose-700"}>
                {ping.ok ? "✓ ok" : `✗ ${ping.error_status || "err"}`}
              </div>
              {ping.extension_id && (
                <div>ext: {ping.extension_number} · #{ping.extension_id}</div>
              )}
              <div>mode: {ping.mode}</div>
            </div>
          )}
        </div>

        {/* Echo card */}
        <div className="rounded-xl border border-slate-200 p-4 bg-white" data-testid="telephony-echo-card">
          <div className="flex items-center gap-2 mb-2 text-sm font-semibold">
            <ShieldCheck size={16} /> Token echo
          </div>
          <p className="text-xs text-slate-500 mb-3">
            Verifies env vars + JWT claims (never echoes secrets).
          </p>
          <button
            onClick={runEcho}
            disabled={echoBusy}
            className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm disabled:opacity-60"
            data-testid="telephony-echo-btn"
          >
            {echoBusy ? "Checking…" : "Run token echo"}
          </button>
          {echo && (
            <div className="mt-3 text-xs font-mono bg-slate-50 rounded p-2" data-testid="telephony-echo-result">
              <div>mode: {echo.mode}</div>
              <div>server: {echo.server || "—"}</div>
              <div>sub …{echo.jwt_sub_last4 || "----"}</div>
              <div>client id: {echo.client_id_set ? "set" : "unset"}</div>
              <div>webhook: {echo.webhook_url_set ? "set" : "unset"}</div>
              <div>verification token: {echo.webhook_verification_token_set ? "set" : "unset"}</div>
            </div>
          )}
        </div>

        {/* Test call card */}
        <div className="rounded-xl border border-slate-200 p-4 bg-white" data-testid="telephony-test-call-card">
          <div className="flex items-center gap-2 mb-2 text-sm font-semibold">
            <Phone size={16} /> Test call
          </div>
          <p className="text-xs text-slate-500 mb-3">
            Trigger a RingOut against a phone you control. Rate-limited to 20/min per user.
          </p>
          <input
            type="tel"
            placeholder="+15005550006"
            value={testNumber}
            onChange={(e) => setTestNumber(e.target.value)}
            className="w-full px-2 py-1.5 rounded border border-slate-300 text-sm mb-2"
            data-testid="telephony-test-call-input"
          />
          {testNumber && (
            <ClickToCallButton
              phoneNumber={testNumber}
              label="Ring out"
              testIdPrefix="telephony-test-call"
              showFallback={false}
            />
          )}
        </div>
      </div>

      {/* Subscriptions */}
      <div className="rounded-xl border border-slate-200 bg-white mb-4" data-testid="telephony-subs-card">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
          <div className="text-sm font-semibold">Webhook subscriptions</div>
          <button
            onClick={setupWebhooks}
            className="text-xs px-2 py-1 rounded bg-slate-800 hover:bg-slate-900 text-white"
            data-testid="telephony-setup-webhooks-btn"
          >
            Setup / refresh webhook
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-slate-500 uppercase">
              <tr>
                <th className="text-left px-3 py-2">Subscription ID</th>
                <th className="text-left px-3 py-2">Address</th>
                <th className="text-left px-3 py-2">Filters</th>
                <th className="text-left px-3 py-2">Created</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={4} className="px-3 py-6 text-center text-slate-400">Loading…</td></tr>
              )}
              {!loading && subs.length === 0 && (
                <tr><td colSpan={4} className="px-3 py-6 text-center text-slate-400">No subscriptions yet.</td></tr>
              )}
              {subs.map((s) => (
                <tr key={s.subscription_id} className="border-t border-slate-100" data-testid={`sub-row-${s.subscription_id}`}>
                  <td className="px-3 py-2 font-mono">{s.subscription_id}</td>
                  <td className="px-3 py-2 truncate max-w-[240px]">{s.address}</td>
                  <td className="px-3 py-2 text-slate-500">{(s.event_filters || []).length} filter(s)</td>
                  <td className="px-3 py-2 text-slate-500">{s.created_at?.slice(0, 19).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recent calls */}
      <div className="rounded-xl border border-slate-200 bg-white" data-testid="telephony-recent-calls-card">
        <div className="px-4 py-3 border-b border-slate-100 text-sm font-semibold">
          Recent calls
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-slate-500 uppercase">
              <tr>
                <th className="text-left px-3 py-2">When</th>
                <th className="text-left px-3 py-2">Direction</th>
                <th className="text-left px-3 py-2">From</th>
                <th className="text-left px-3 py-2">To</th>
                <th className="text-left px-3 py-2">Customer / Lead</th>
                <th className="text-left px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-slate-400">Loading…</td></tr>
              )}
              {!loading && logs.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-slate-400">No calls yet.</td></tr>
              )}
              {logs.map((c) => (
                <tr key={c.id} className="border-t border-slate-100" data-testid={`call-row-${c.id}`}>
                  <td className="px-3 py-2 text-slate-500">{(c.started_at || "").slice(0, 19).replace("T", " ")}</td>
                  <td className="px-3 py-2">{c.direction || "—"}</td>
                  <td className="px-3 py-2 font-mono">{c.from_number || "—"}</td>
                  <td className="px-3 py-2 font-mono">{c.to_number || "—"}</td>
                  <td className="px-3 py-2">{c.customer_name || c.matched_entity || "—"}</td>
                  <td className="px-3 py-2 text-slate-500">{c.status || c.direction || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
