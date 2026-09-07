/**
 * Phase I1.7.a · Feb-2026 — Tenant BYO Integrations card.
 *
 * Renders on ``/settings/integrations`` above the legacy env-based
 * integrations grid. Powers the Stripe Connect Standard OAuth flow
 * so tenants can plug in their OWN Stripe account. Placeholders
 * for SMS / Email / AI / Maps / Calendars / Storage are wired but
 * disabled — real providers land in I1.7.b–d.
 *
 * Guarantees:
 *   • Plaintext access tokens NEVER touch this component. The list
 *     endpoint returns masked ``last_4`` + ``connected_account_id_masked``
 *     only.
 *   • Every button has a stable ``data-testid``.
 *   • Read-only for ``manager`` (test/connect/delete buttons hidden
 *     unless ``role ∈ {admin, super_admin}``).
 *   • Absorbs the ``?connect=success|error`` query-string bounce
 *     from the Stripe OAuth callback and shows a toast.
 */
import React, { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";


const PROVIDER_CARDS = [
  { key: "stripe",    label: "Stripe",           kind: "payments",   status: "available", desc: "Card + ACH payments via your own Stripe account (Connect Standard OAuth)." },
  { key: "sms",       label: "SMS provider",     kind: "messaging",  status: "coming",    desc: "Twilio · RingCentral · Bandwidth." },
  { key: "email",     label: "Email provider",   kind: "messaging",  status: "coming",    desc: "Resend · SendGrid · Postmark." },
  { key: "ai",        label: "AI provider",      kind: "ai",         status: "coming",    desc: "OpenAI · Claude · Gemini. BYO API key or Emergent-managed." },
  { key: "maps",      label: "Maps provider",    kind: "geo",        status: "coming",    desc: "Google Maps · Mapbox · OpenStreetMap." },
  { key: "calendars", label: "Calendar sync",    kind: "productivity", status: "coming",  desc: "Google Calendar · Outlook · iCloud." },
  { key: "storage",   label: "Object storage",   kind: "storage",    status: "coming",    desc: "S3 · GCS · Emergent-managed default." },
];


function StatusPill({ tone = "neutral", children, testid }) {
  const palette = {
    connected: { bg: "#DCFCE7", fg: "#166534" },
    disconnected: { bg: "#FEE2E2", fg: "#991B1B" },
    coming: { bg: "#F1F5F9", fg: "#475569" },
    warn: { bg: "#FEF3C7", fg: "#854D0E" },
    neutral: { bg: "#F1F5F9", fg: "#475569" },
  }[tone] || { bg: "#F1F5F9", fg: "#475569" };
  return (
    <span
      className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full tracking-wide"
      style={{ backgroundColor: palette.bg, color: palette.fg }}
      data-testid={testid}
    >
      {children}
    </span>
  );
}


export default function TenantIntegrationsCard() {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState({}); // per-provider spinner
  const [role, setRole] = useState("manager");

  useEffect(() => {
    try {
      const u = JSON.parse(localStorage.getItem("user") || "null");
      if (u?.role) setRole(u.role);
    } catch { /* localStorage may be unavailable in tests */ }
  }, []);

  const canWrite = role === "admin" || role === "super_admin";

  const load = useCallback(async () => {
    try {
      const r = await api.get("/tenants/me/integrations");
      const map = {};
      (r?.integrations || []).forEach((row) => { map[row.provider_key] = row; });
      setRows(map);
    } catch (e) {
      setRows({});
      toast.error(e?.message || "Failed to load integrations");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Absorb the ?connect=success|error bounce from the OAuth callback.
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const flag = params.get("connect");
      if (flag === "success") {
        toast.success("Stripe connected successfully.");
      } else if (flag === "error") {
        const reason = params.get("reason") || "unknown";
        toast.error(`Stripe connection failed: ${reason}`);
      }
      if (flag) {
        // Strip the query so a refresh doesn't re-toast.
        const clean = window.location.pathname + window.location.hash;
        window.history.replaceState({}, "", clean);
      }
    } catch { /* window unavailable in SSR/test — no-op */ }
  }, []);

  const setBusyFor = (k, val) => setBusy((b) => ({ ...b, [k]: val }));

  const connectStripe = async () => {
    setBusyFor("stripe", "connect");
    try {
      const r = await api.get("/integrations/stripe/connect-link");
      if (r?.url) {
        // Full-page redirect — Stripe's OAuth UI + our callback flow.
        window.location.assign(r.url);
        return;
      }
      toast.error("No connect URL returned by server.");
    } catch (e) {
      toast.error(e?.message || "Could not start Stripe connect.");
    } finally {
      setBusyFor("stripe", null);
    }
  };

  const testConnection = async (k) => {
    setBusyFor(k, "test");
    try {
      const r = await api.post(`/tenants/me/integrations/${k}/test`);
      if (r?.ok) toast.success(`${k} · ${r.message || "connected"}`);
      else toast.error(`${k} · ${r?.message || "connection failed"}`);
      await load();
    } catch (e) {
      toast.error(e?.message || `${k} test failed`);
    } finally {
      setBusyFor(k, null);
    }
  };

  const disconnect = async (k) => {
    if (typeof window !== "undefined" && window.confirm) {
      if (!window.confirm(`Disconnect ${k}? Your saved credentials will be permanently removed.`)) return;
    }
    setBusyFor(k, "delete");
    try {
      const r = await api.delete(`/tenants/me/integrations/${k}`);
      if (r?.removed) toast.success(`${k} disconnected.`);
      else toast(`${k} was not connected.`);
      await load();
    } catch (e) {
      toast.error(e?.message || `${k} disconnect failed`);
    } finally {
      setBusyFor(k, null);
    }
  };

  return (
    <div
      className="rounded-2xl bg-white p-5"
      style={{ border: `1px solid ${colors.border}` }}
      data-testid="tenant-integrations-card"
    >
      <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
        <div>
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Bring your own providers
          </h2>
          <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
            Connect your OWN accounts so charges, messages and jobs run
            under your brand — not the platform's. Credentials are
            encrypted at rest with AES-256-GCM; only the last 4
            characters are ever shown back to you.
          </p>
        </div>
        {rows === null && (
          <span className="text-xs" style={{ color: colors.onSurfaceSecondary }} data-testid="tenant-integrations-loading">
            Loading…
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {PROVIDER_CARDS.map((p) => {
          const row = (rows && rows[p.key]) || null;
          const isConnected = !!row?.connected;
          const state = p.status === "coming" ? "coming" : isConnected ? "connected" : "disconnected";
          const tone = state;
          const stateLabel = state === "coming" ? "Coming soon"
            : state === "connected" ? "Connected"
            : "Not connected";

          return (
            <div
              key={p.key}
              className="rounded-xl p-4 flex flex-col gap-3"
              style={{ border: `1px solid ${colors.border}`, opacity: p.status === "coming" ? 0.72 : 1 }}
              data-testid={`tenant-integration-${p.key}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <div className="font-semibold text-sm" style={{ color: colors.onSurface }}>{p.label}</div>
                    <StatusPill tone={tone} testid={`tenant-integration-${p.key}-status`}>{stateLabel}</StatusPill>
                  </div>
                  <div className="text-xs mt-0.5" style={{ color: colors.onSurfaceSecondary }}>
                    {p.desc}
                  </div>
                </div>
              </div>

              {isConnected && (
                <div
                  className="rounded-lg px-3 py-2 text-xs space-y-1"
                  style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                  data-testid={`tenant-integration-${p.key}-summary`}
                >
                  {row.connected_account_id_masked && (
                    <div><span className="font-semibold">Account:</span>{" "}
                      <span className="font-mono" data-testid={`tenant-integration-${p.key}-account`}>
                        {row.connected_account_id_masked}
                      </span>
                    </div>
                  )}
                  {row.last_4 && (
                    <div><span className="font-semibold">Token · last 4:</span>{" "}
                      <span className="font-mono" data-testid={`tenant-integration-${p.key}-last4`}>••••{row.last_4}</span>
                    </div>
                  )}
                  {row.last_used_at && (
                    <div><span className="font-semibold">Last used:</span>{" "}
                      <span data-testid={`tenant-integration-${p.key}-last-used`}>{new Date(row.last_used_at).toLocaleString()}</span>
                    </div>
                  )}
                  {row.last_error && row.error_log_count > 0 && (
                    <div style={{ color: "#991B1B" }} data-testid={`tenant-integration-${p.key}-last-error`}>
                      <span className="font-semibold">Last error:</span>{" "}
                      {row.last_error.code} · {row.last_error.message}
                    </div>
                  )}
                </div>
              )}

              <div className="flex items-center gap-2 flex-wrap">
                {p.key === "stripe" && p.status === "available" && !isConnected && canWrite && (
                  <button
                    onClick={connectStripe}
                    disabled={!!busy.stripe}
                    className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
                    style={{ backgroundColor: colors.brand, opacity: busy.stripe ? 0.6 : 1 }}
                    data-testid="tenant-integration-stripe-connect"
                  >
                    {busy.stripe === "connect" ? "Redirecting…" : "Connect Stripe"}
                  </button>
                )}
                {p.status === "available" && isConnected && canWrite && (
                  <>
                    <button
                      onClick={() => testConnection(p.key)}
                      disabled={!!busy[p.key]}
                      className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                      style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, opacity: busy[p.key] ? 0.6 : 1 }}
                      data-testid={`tenant-integration-${p.key}-test`}
                    >
                      {busy[p.key] === "test" ? "Testing…" : "Test connection"}
                    </button>
                    <button
                      onClick={() => disconnect(p.key)}
                      disabled={!!busy[p.key]}
                      className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                      style={{ backgroundColor: "#FEE2E2", color: "#991B1B", opacity: busy[p.key] ? 0.6 : 1 }}
                      data-testid={`tenant-integration-${p.key}-disconnect`}
                    >
                      {busy[p.key] === "delete" ? "Removing…" : "Disconnect"}
                    </button>
                  </>
                )}
                {p.status === "coming" && (
                  <span className="text-xs italic" style={{ color: colors.onSurfaceSecondary }}>
                    Ships in a follow-up phase (I1.7.b–d).
                  </span>
                )}
                {p.status === "available" && !canWrite && (
                  <span className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
                    Ask an admin to connect this provider.
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
