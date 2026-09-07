/**
 * Phase I1.7.a · Feb-2026 — Tenant BYO Integrations card.
 * Phase I1.7.b · Feb-2026 — SMS + Email BYO provider cards.
 *
 * Renders on ``/settings/integrations`` above the legacy env-based
 * integrations grid.
 *
 * Sections:
 *   • Stripe (Connect Standard OAuth) — from I1.7.a.
 *   • SMS provider (Twilio / TextMagic / RingCentral) — new in I1.7.b.
 *   • Email provider (Resend / SendGrid / Postmark / Mailgun / SMTP)
 *     — new in I1.7.b.
 *   • "Coming soon" placeholders: AI / Maps / Calendars / Storage.
 *
 * Guarantees:
 *   • Plaintext credentials NEVER touch the API responses this
 *     component consumes. The list endpoint returns masked
 *     ``last_4`` + ``connected_account_id_masked`` only.
 *   • Every button has a stable ``data-testid``.
 *   • Read-only for ``manager`` (test/connect/delete buttons hidden
 *     unless ``role ∈ {admin, super_admin}``).
 *   • Stale badge appears when ``last_used_at`` is > 30 days old.
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { mustConfirm } from "@/components/ui/confirm-dialog";


// Phase I1.7.c.2.followup · Feb-2026 — Shared in-app disconnect
// confirmation. Replaces the 4 legacy ``window.confirm(...)`` calls
// on the Stripe / SMS / Email / AI / Maps disconnect flows so
// browser-use automation isn't blocked by native dialogs.
async function _confirmDisconnect(label) {
  return await mustConfirm({
    title: `Disconnect ${label}?`,
    description: "Your stored API key will be removed. You can reconnect at any time.",
    confirmText: "Disconnect",
    cancelText: "Cancel",
    tone: "danger",
    confirmTestId: "integrations-disconnect-confirm",
    cancelTestId: "integrations-disconnect-cancel",
  });
}


const STALE_DAYS = 30;
const COMING_SOON = [
  { key: "storage",   label: "Object storage",   desc: "S3 · GCS · Emergent-managed default." },
];

// Phase I1.7.c.1 — AI provider display metadata (short_name → label).
const AI_PROVIDER_LABELS = {
  ai_openai:    { short: "openai",    label: "OpenAI",    desc: "Bring your own OpenAI API key (GPT-4o etc)." },
  ai_anthropic: { short: "anthropic", label: "Anthropic", desc: "Bring your own Anthropic API key (Claude family)." },
  ai_gemini:    { short: "gemini",    label: "Gemini",    desc: "Bring your own Google Gemini API key." },
};

// Phase I1.7.c.2 — Maps provider display metadata (short_name → label).
const MAPS_PROVIDER_LABELS = {
  maps_google: { short: "google", label: "Google Maps",
                  desc: "Bring your own Google Maps API key (Geocoding + Routes + Static Maps)." },
  maps_mapbox: { short: "mapbox", label: "Mapbox",
                  desc: "Bring your own Mapbox access token (Geocoding + Directions + Static Maps)." },
};


// Phase I1.7.c.3 — Calendars provider display metadata (short_name → label).
const CALENDARS_PROVIDER_LABELS = {
  calendars_google:  { short: "google",  label: "Google Calendar",
                        desc: "Per-technician Google Calendar OAuth · push jobs / pull availability." },
  calendars_outlook: { short: "outlook", label: "Microsoft Outlook",
                        desc: "Per-technician Microsoft 365 / Outlook OAuth · push jobs / pull availability." },
};


function StatusPill({ tone = "neutral", children, testid }) {
  const palette = {
    connected: { bg: "#DCFCE7", fg: "#166534" },
    disconnected: { bg: "#FEE2E2", fg: "#991B1B" },
    coming: { bg: "#F1F5F9", fg: "#475569" },
    stale: { bg: "#FEF3C7", fg: "#854D0E" },
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


// Approved I1.7.a-follow-up: yellow stale badge when last_used_at is
// older than STALE_DAYS. Nudges tenants to click Test connection
// before their next batch and surfaces revoked tokens early.
function StaleBadge({ lastUsedAt, providerKey }) {
  if (!lastUsedAt) return null;
  const then = new Date(lastUsedAt).getTime();
  if (!Number.isFinite(then)) return null;
  const days = (Date.now() - then) / (1000 * 60 * 60 * 24);
  if (days < STALE_DAYS) return null;
  return (
    <StatusPill tone="stale" testid={`tenant-integration-${providerKey}-stale`}>
      Stale · {Math.floor(days)}d
    </StatusPill>
  );
}


/** ————————————————————————————————————————————————————————————
 *  Section: Stripe card (from I1.7.a).
 *  ———————————————————————————————————————————————————————————— */
function StripeCard({ row, canWrite, busy, setBusyFor, reload }) {
  const isConnected = !!row?.connected;
  const state = isConnected ? "connected" : "disconnected";
  const stateLabel = isConnected ? "Connected" : "Not connected";

  const connect = async () => {
    setBusyFor("stripe", "connect");
    try {
      const r = await api.get("/integrations/stripe/connect-link");
      if (r?.url) { window.location.assign(r.url); return; }
      toast.error("No connect URL returned by server.");
    } catch (e) {
      toast.error(e?.message || "Could not start Stripe connect.");
    } finally { setBusyFor("stripe", null); }
  };

  const testConn = async () => {
    setBusyFor("stripe", "test");
    try {
      const r = await api.post("/tenants/me/integrations/stripe/test");
      if (r?.ok) toast.success(`Stripe · ${r.message || "connected"}`);
      else toast.error(`Stripe · ${r?.message || "connection failed"}`);
      await reload();
    } catch (e) { toast.error(e?.message || "Stripe test failed"); }
    finally { setBusyFor("stripe", null); }
  };

  const remove = async () => {
    if (!(await _confirmDisconnect("Stripe"))) return;
    setBusyFor("stripe", "delete");
    try {
      const r = await api.delete("/tenants/me/integrations/stripe");
      if (r?.removed) toast.success("Stripe disconnected.");
      else toast("Stripe was not connected.");
      await reload();
    } catch (e) { toast.error(e?.message || "Stripe disconnect failed"); }
    finally { setBusyFor("stripe", null); }
  };

  return (
    <div
      className="rounded-xl p-4 flex flex-col gap-3"
      style={{ border: `1px solid ${colors.border}` }}
      data-testid="tenant-integration-stripe"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="font-semibold text-sm" style={{ color: colors.onSurface }}>Stripe</div>
            <StatusPill tone={state} testid="tenant-integration-stripe-status">{stateLabel}</StatusPill>
            {isConnected && <StaleBadge lastUsedAt={row.last_used_at} providerKey="stripe" />}
          </div>
          <div className="text-xs mt-0.5" style={{ color: colors.onSurfaceSecondary }}>
            Card + ACH payments via your own Stripe account (Connect Standard OAuth).
          </div>
        </div>
      </div>

      {isConnected && (
        <div
          className="rounded-lg px-3 py-2 text-xs space-y-1"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
          data-testid="tenant-integration-stripe-summary"
        >
          {row.connected_account_id_masked && (
            <div><span className="font-semibold">Account:</span>{" "}
              <span className="font-mono" data-testid="tenant-integration-stripe-account">{row.connected_account_id_masked}</span></div>
          )}
          {row.last_4 && (
            <div><span className="font-semibold">Token · last 4:</span>{" "}
              <span className="font-mono" data-testid="tenant-integration-stripe-last4">••••{row.last_4}</span></div>
          )}
          {row.last_used_at && (
            <div><span className="font-semibold">Last used:</span>{" "}
              <span data-testid="tenant-integration-stripe-last-used">{new Date(row.last_used_at).toLocaleString()}</span></div>
          )}
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        {!isConnected && canWrite && (
          <button onClick={connect} disabled={!!busy.stripe}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
            style={{ backgroundColor: colors.brand, opacity: busy.stripe ? 0.6 : 1 }}
            data-testid="tenant-integration-stripe-connect">
            {busy.stripe === "connect" ? "Redirecting…" : "Connect Stripe"}
          </button>
        )}
        {isConnected && canWrite && (
          <>
            <button onClick={testConn} disabled={!!busy.stripe}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold"
              style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, opacity: busy.stripe ? 0.6 : 1 }}
              data-testid="tenant-integration-stripe-test">
              {busy.stripe === "test" ? "Testing…" : "Test connection"}
            </button>
            <button onClick={remove} disabled={!!busy.stripe}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold"
              style={{ backgroundColor: "#FEE2E2", color: "#991B1B", opacity: busy.stripe ? 0.6 : 1 }}
              data-testid="tenant-integration-stripe-disconnect">
              {busy.stripe === "delete" ? "Removing…" : "Disconnect"}
            </button>
          </>
        )}
        {!canWrite && (
          <span className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
            Ask an admin to connect this provider.
          </span>
        )}
      </div>
    </div>
  );
}


/** ————————————————————————————————————————————————————————————
 *  Section: Messaging card (SMS or Email) with provider dropdown +
 *  schema-driven form. New in Phase I1.7.b.
 *  ———————————————————————————————————————————————————————————— */
function MessagingCard({
  kind,           // "sms" | "email"
  label,          // "SMS provider"
  desc,           // human blurb
  schemas,        // array of {provider_key, kind, fields[]}
  connectedRow,   // whichever row from list_connections is currently connected in this kind, or null
  canWrite, busy, setBusyFor, reload,
}) {
  const [selected, setSelected] = useState("");
  const [form, setForm] = useState({});

  // Default the dropdown to the connected provider (if any) or the
  // first schema. This effect intentionally excludes ``selected``
  // from its deps so a user's manual selection doesn't trigger a
  // form wipe on subsequent parent re-renders.
  useEffect(() => {
    setSelected((prev) => {
      if (prev) return prev;
      if (connectedRow?.provider_key) return connectedRow.provider_key;
      if (schemas.length) return schemas[0].provider_key;
      return "";
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectedRow?.provider_key, schemas]);

  const onProviderChange = (value) => {
    setSelected(value);
    setForm({});   // reset transient form ONLY on explicit dropdown change
  };

  useEffect(() => {
    if (connectedRow?.provider_key) setSelected(connectedRow.provider_key);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectedRow?.provider_key]);

  const activeSchema = useMemo(
    () => schemas.find((s) => s.provider_key === selected) || schemas[0],
    [schemas, selected],
  );

  if (!activeSchema) {
    return null;
  }

  const isConnected = !!connectedRow?.connected;
  const state = isConnected ? "connected" : "disconnected";
  const stateLabel = isConnected ? "Connected" : "Not connected";
  const busyKey = connectedRow?.provider_key || selected;

  const save = async () => {
    setBusyFor(kind, "save");
    try {
      const r = await api.put(`/tenants/me/integrations/${selected}`, { config: form });
      if (r?.saved) toast.success(`${activeSchema.provider_key} saved.`);
      setForm({});
      await reload();
    } catch (e) {
      toast.error(e?.message || `${selected} save failed`);
    } finally { setBusyFor(kind, null); }
  };

  const testConn = async () => {
    if (!connectedRow?.provider_key) return;
    setBusyFor(kind, "test");
    try {
      const r = await api.post(`/tenants/me/integrations/${connectedRow.provider_key}/test`);
      if (r?.ok) toast.success(`${connectedRow.provider_key} · ${r.message || "connected"}`);
      else toast.error(`${connectedRow.provider_key} · ${r?.message || "connection failed"}`);
      await reload();
    } catch (e) {
      toast.error(e?.message || "test failed");
    } finally { setBusyFor(kind, null); }
  };

  const remove = async () => {
    if (!connectedRow?.provider_key) return;
    if (!(await _confirmDisconnect(connectedRow.provider_key))) return;
    setBusyFor(kind, "delete");
    try {
      const r = await api.delete(`/tenants/me/integrations/${connectedRow.provider_key}`);
      if (r?.removed) toast.success(`${connectedRow.provider_key} disconnected.`);
      else toast(`${connectedRow.provider_key} was not connected.`);
      await reload();
    } catch (e) { toast.error(e?.message || "disconnect failed"); }
    finally { setBusyFor(kind, null); }
  };

  return (
    <div
      className="rounded-xl p-4 flex flex-col gap-3"
      style={{ border: `1px solid ${colors.border}` }}
      data-testid={`tenant-integration-${kind}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="font-semibold text-sm" style={{ color: colors.onSurface }}>{label}</div>
            <StatusPill tone={state} testid={`tenant-integration-${kind}-status`}>{stateLabel}</StatusPill>
            {isConnected && <StaleBadge lastUsedAt={connectedRow.last_used_at} providerKey={kind} />}
          </div>
          <div className="text-xs mt-0.5" style={{ color: colors.onSurfaceSecondary }}>{desc}</div>
        </div>
      </div>

      {isConnected && (
        <div
          className="rounded-lg px-3 py-2 text-xs space-y-1"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
          data-testid={`tenant-integration-${kind}-summary`}
        >
          <div><span className="font-semibold">Provider:</span>{" "}
            <span className="font-mono" data-testid={`tenant-integration-${kind}-provider-key`}>{connectedRow.provider_key}</span></div>
          {connectedRow.connected_account_id_masked && (
            <div><span className="font-semibold">Account:</span>{" "}
              <span className="font-mono" data-testid={`tenant-integration-${kind}-account`}>{connectedRow.connected_account_id_masked}</span></div>
          )}
          {connectedRow.last_used_at && (
            <div><span className="font-semibold">Last used:</span>{" "}
              <span data-testid={`tenant-integration-${kind}-last-used`}>{new Date(connectedRow.last_used_at).toLocaleString()}</span></div>
          )}
        </div>
      )}

      {canWrite && (
        <div className="flex flex-col gap-2">
          <label className="text-xs font-semibold" style={{ color: colors.onSurface }}>
            Provider
          </label>
          <select
            value={selected}
            onChange={(e) => onProviderChange(e.target.value)}
            disabled={!!busy[kind]}
            className="w-full rounded-lg px-2 py-1.5 text-sm"
            style={{ border: `1px solid ${colors.border}`, backgroundColor: "white", color: colors.onSurface }}
            data-testid={`tenant-integration-${kind}-provider-select`}
          >
            {schemas.map((s) => (
              <option key={s.provider_key} value={s.provider_key}>{s.provider_key}</option>
            ))}
          </select>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-1">
            {activeSchema.fields.map((f) => (
              <label key={f.name} className="text-xs flex flex-col gap-1"
                style={{ color: colors.onSurfaceSecondary }}>
                <span>
                  {f.label}
                  {f.required ? <span style={{ color: "#991B1B" }}> *</span> : null}
                </span>
                <input
                  type={f.secret ? "password" : "text"}
                  value={form[f.name] ?? ""}
                  onChange={(e) => setForm((prev) => ({ ...prev, [f.name]: e.target.value }))}
                  autoComplete="off"
                  placeholder={f.secret ? "•••" : ""}
                  data-testid={`tenant-integration-${kind}-field-${f.name}`}
                  className="rounded-lg px-2 py-1 text-sm"
                  style={{ border: `1px solid ${colors.border}`, backgroundColor: "white", color: colors.onSurface }}
                />
              </label>
            ))}
          </div>

          <div className="flex items-center gap-2 flex-wrap mt-1">
            <button
              onClick={save}
              disabled={!!busy[kind]}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
              style={{ backgroundColor: colors.brand, opacity: busy[kind] ? 0.6 : 1 }}
              data-testid={`tenant-integration-${kind}-save`}
            >
              {busy[kind] === "save" ? "Saving…" : (isConnected ? "Save (rotate)" : "Save")}
            </button>
            {isConnected && (
              <>
                <button
                  onClick={testConn}
                  disabled={!!busy[kind]}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                  style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, opacity: busy[kind] ? 0.6 : 1 }}
                  data-testid={`tenant-integration-${kind}-test`}
                >
                  {busy[kind] === "test" ? "Testing…" : "Test connection"}
                </button>
                <button
                  onClick={remove}
                  disabled={!!busy[kind]}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                  style={{ backgroundColor: "#FEE2E2", color: "#991B1B", opacity: busy[kind] ? 0.6 : 1 }}
                  data-testid={`tenant-integration-${kind}-disconnect`}
                >
                  {busy[kind] === "delete" ? "Removing…" : "Disconnect"}
                </button>
              </>
            )}
          </div>
        </div>
      )}
      {!canWrite && (
        <span className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
          Ask an admin to connect this provider.
        </span>
      )}
    </div>
  );
}


/** ————————————————————————————————————————————————————————————
 *  Section: AI provider card (OpenAI / Anthropic / Gemini) — new
 *  in Phase I1.7.c.1. One card per provider with:
 *    - api_key (secret) input
 *    - default_model dropdown (schema.models[])
 *    - monthly_token_cap input (empty = unlimited, 0 = block all)
 *    - usage progress bar (green < 80% · amber 80–99% · red ≥ 100%)
 *  ———————————————————————————————————————————————————————————— */
function AICard({ schema, row, usage, canWrite, busy, setBusyFor, reload }) {
  const providerKey = schema.provider_key;      // e.g. "ai_openai"
  const shortName = (AI_PROVIDER_LABELS[providerKey] || {}).short || providerKey;
  const label = (AI_PROVIDER_LABELS[providerKey] || {}).label || providerKey;
  const desc = (AI_PROVIDER_LABELS[providerKey] || {}).desc || "";

  const isConnected = !!row?.connected;
  const state = isConnected ? "connected" : "disconnected";
  const stateLabel = isConnected ? "Connected" : "Not connected";
  const busyKey = providerKey;

  const [form, setForm] = useState({ default_model: schema.models?.[0] || "" });
  const [capInput, setCapInput] = useState(
    usage?.monthly_token_cap == null ? "" : String(usage.monthly_token_cap),
  );

  useEffect(() => {
    if (usage?.default_model) {
      setForm((prev) => ({ ...prev, default_model: usage.default_model }));
    }
    if (usage?.monthly_token_cap != null) {
      setCapInput(String(usage.monthly_token_cap));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usage?.default_model, usage?.monthly_token_cap]);

  const save = async () => {
    setBusyFor(busyKey, "save");
    try {
      const body = {
        config: {
          api_key: form.api_key || "",
          default_model: form.default_model || schema.models?.[0] || "",
        },
        monthly_token_cap: capInput === "" ? null : Number(capInput),
      };
      const r = await api.put(`/tenants/me/integrations/${providerKey}`, body);
      if (r?.saved) toast.success(`${label} saved.`);
      setForm((prev) => ({ ...prev, api_key: "" }));
      await reload();
    } catch (e) {
      toast.error(e?.message || `${label} save failed`);
    } finally { setBusyFor(busyKey, null); }
  };

  const remove = async () => {
    if (!(await _confirmDisconnect(label))) return;
    setBusyFor(busyKey, "delete");
    try {
      const r = await api.delete(`/tenants/me/integrations/${providerKey}`);
      if (r?.removed) toast.success(`${label} disconnected.`);
      else toast(`${label} was not connected.`);
      await reload();
    } catch (e) { toast.error(e?.message || `${label} disconnect failed`); }
    finally { setBusyFor(busyKey, null); }
  };

  // Usage progress bar colour: green < 80% · amber 80–99% · red ≥ 100%.
  const pct = usage?.pct_used ?? 0;
  const pctDisplay = usage?.monthly_token_cap == null
    ? null
    : Math.min(100, Math.round((pct || 0) * 100));
  const barColor = usage?.status === "blocked" ? "#DC2626"
    : usage?.status === "warn" ? "#F59E0B"
    : "#16A34A";
  const capLabel = usage?.monthly_token_cap == null
    ? "Unlimited"
    : usage.monthly_token_cap === 0
    ? "Blocked (cap = 0)"
    : `${(usage.tokens_total || 0).toLocaleString()} / ${usage.monthly_token_cap.toLocaleString()}`;

  return (
    <div
      className="rounded-xl p-4 flex flex-col gap-3"
      style={{ border: `1px solid ${colors.border}` }}
      data-testid={`tenant-integration-${providerKey}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="font-semibold text-sm" style={{ color: colors.onSurface }}>{label}</div>
            <StatusPill tone={state} testid={`tenant-integration-${providerKey}-status`}>{stateLabel}</StatusPill>
            {isConnected && <StaleBadge lastUsedAt={row.last_used_at} providerKey={providerKey} />}
          </div>
          <div className="text-xs mt-0.5" style={{ color: colors.onSurfaceSecondary }}>{desc}</div>
        </div>
      </div>

      {isConnected && (
        <div
          className="rounded-lg px-3 py-2 text-xs space-y-1"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
          data-testid={`tenant-integration-${providerKey}-summary`}
        >
          {row.last_4 && (
            <div><span className="font-semibold">API key · last 4:</span>{" "}
              <span className="font-mono" data-testid={`tenant-integration-${providerKey}-last4`}>••••{row.last_4}</span></div>
          )}
          {usage?.default_model && (
            <div><span className="font-semibold">Default model:</span>{" "}
              <span className="font-mono" data-testid={`tenant-integration-${providerKey}-model`}>{usage.default_model}</span></div>
          )}
        </div>
      )}

      {/* Usage progress bar */}
      <div className="flex flex-col gap-1" data-testid={`tenant-integration-${providerKey}-usage`}>
        <div className="flex items-center justify-between text-xs" style={{ color: colors.onSurfaceSecondary }}>
          <span>Usage this month</span>
          <span data-testid={`tenant-integration-${providerKey}-usage-label`}>{capLabel}</span>
        </div>
        <div className="w-full h-2 rounded-full overflow-hidden" style={{ backgroundColor: "#E5E7EB" }}>
          {pctDisplay != null && (
            <div
              className="h-full transition-all"
              style={{ width: `${pctDisplay}%`, backgroundColor: barColor }}
              data-testid={`tenant-integration-${providerKey}-usage-bar`}
            />
          )}
        </div>
        {usage?.status === "warn" && (
          <div className="text-[11px]" style={{ color: "#854D0E" }}
               data-testid={`tenant-integration-${providerKey}-usage-warn`}>
            ⚠︎ Soft warning · ≥ 80% of monthly cap consumed.
          </div>
        )}
        {usage?.status === "blocked" && (
          <div className="text-[11px]" style={{ color: "#991B1B" }}
               data-testid={`tenant-integration-${providerKey}-usage-blocked`}>
            ✕ Monthly cap reached · requests will return 429 until next month or you raise the cap.
          </div>
        )}
      </div>

      {canWrite && (
        <div className="flex flex-col gap-2">
          <label className="text-xs flex flex-col gap-1" style={{ color: colors.onSurfaceSecondary }}>
            <span>API key<span style={{ color: "#991B1B" }}> *</span></span>
            <input
              type="password"
              value={form.api_key ?? ""}
              onChange={(e) => setForm((prev) => ({ ...prev, api_key: e.target.value }))}
              autoComplete="off"
              placeholder={isConnected ? "•••• (leave blank to keep current)" : "sk-…"}
              className="rounded-lg px-2 py-1 text-sm"
              style={{ border: `1px solid ${colors.border}`, backgroundColor: "white", color: colors.onSurface }}
              data-testid={`tenant-integration-${providerKey}-field-api_key`}
            />
          </label>

          <label className="text-xs flex flex-col gap-1" style={{ color: colors.onSurfaceSecondary }}>
            <span>Default model</span>
            <select
              value={form.default_model || ""}
              onChange={(e) => setForm((prev) => ({ ...prev, default_model: e.target.value }))}
              className="rounded-lg px-2 py-1 text-sm"
              style={{ border: `1px solid ${colors.border}`, backgroundColor: "white", color: colors.onSurface }}
              data-testid={`tenant-integration-${providerKey}-model-select`}
            >
              {(schema.models || []).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>

          <label className="text-xs flex flex-col gap-1" style={{ color: colors.onSurfaceSecondary }}>
            <span>
              Monthly token cap
              <span className="italic" style={{ color: colors.onSurfaceSecondary }}> · empty = unlimited · 0 = block all</span>
            </span>
            <input
              type="number"
              min="0"
              step="1"
              value={capInput}
              onChange={(e) => setCapInput(e.target.value)}
              placeholder="Unlimited"
              className="rounded-lg px-2 py-1 text-sm"
              style={{ border: `1px solid ${colors.border}`, backgroundColor: "white", color: colors.onSurface }}
              data-testid={`tenant-integration-${providerKey}-cap-input`}
            />
          </label>

          <div className="flex items-center gap-2 flex-wrap mt-1">
            <button
              onClick={save}
              disabled={!!busy[busyKey]}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
              style={{ backgroundColor: colors.brand, opacity: busy[busyKey] ? 0.6 : 1 }}
              data-testid={`tenant-integration-${providerKey}-save`}
            >
              {busy[busyKey] === "save" ? "Saving…" : (isConnected ? "Save (rotate)" : "Save")}
            </button>
            {isConnected && (
              <button
                onClick={remove}
                disabled={!!busy[busyKey]}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                style={{ backgroundColor: "#FEE2E2", color: "#991B1B", opacity: busy[busyKey] ? 0.6 : 1 }}
                data-testid={`tenant-integration-${providerKey}-disconnect`}
              >
                {busy[busyKey] === "delete" ? "Removing…" : "Disconnect"}
              </button>
            )}
          </div>
        </div>
      )}
      {!canWrite && (
        <span className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
          Ask an admin to connect this provider.
        </span>
      )}
    </div>
  );
}


/** ————————————————————————————————————————————————————————————
 *  Section: Maps provider card (Google Maps / Mapbox) — new in
 *  Phase I1.7.c.2. Same shape as ``AICard`` — the differences are:
 *    - Non-secret config fields (``region_bias`` / ``style``) come
 *      from the ``schema.fields[]`` payload, not a fixed dropdown.
 *    - Cap uses ``monthly_request_cap`` (request counter) instead
 *      of the AI ``monthly_token_cap`` (token counter). Same
 *      null / 0 / positive semantics.
 *    - Usage row surfaces per-operation counters (geocode / route /
 *      static_map) plus the rolled-up ``total`` — the progress bar
 *      is against ``total``.
 *  ———————————————————————————————————————————————————————————— */
function MapsCard({ schema, row, usage, canWrite, busy, setBusyFor, reload }) {
  const providerKey = schema.provider_key;
  const shortName = (MAPS_PROVIDER_LABELS[providerKey] || {}).short || providerKey;
  const label = (MAPS_PROVIDER_LABELS[providerKey] || {}).label || providerKey;
  const desc = (MAPS_PROVIDER_LABELS[providerKey] || {}).desc || "";

  const isConnected = !!row?.connected;
  const state = isConnected ? "connected" : "disconnected";
  const stateLabel = isConnected ? "Connected" : "Not connected";
  const busyKey = providerKey;

  const nonSecretFields = (schema.fields || []).filter((f) => !f.secret);

  const [form, setForm] = useState(() => {
    const seed = {};
    nonSecretFields.forEach((f) => { seed[f.name] = usage?.[f.name] ?? ""; });
    return seed;
  });
  const [capInput, setCapInput] = useState(
    usage?.monthly_request_cap == null ? "" : String(usage.monthly_request_cap),
  );

  useEffect(() => {
    if (usage?.monthly_request_cap != null) {
      setCapInput(String(usage.monthly_request_cap));
    }
    // Populate any non-secret fields from the usage sidecar (echoes
    // the stored value the server sent back).
    setForm((prev) => {
      let changed = false;
      const next = { ...prev };
      nonSecretFields.forEach((f) => {
        if (usage && usage[f.name] != null && !next[f.name]) {
          next[f.name] = usage[f.name];
          changed = true;
        }
      });
      return changed ? next : prev;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usage?.monthly_request_cap]);

  const save = async () => {
    setBusyFor(busyKey, "save");
    try {
      const config = { api_key: form.api_key || "" };
      nonSecretFields.forEach((f) => { config[f.name] = form[f.name] ?? ""; });
      const body = {
        config,
        monthly_request_cap: capInput === "" ? null : Number(capInput),
      };
      const r = await api.put(`/tenants/me/integrations/${providerKey}`, body);
      if (r?.saved) toast.success(`${label} saved.`);
      setForm((prev) => ({ ...prev, api_key: "" }));
      await reload();
    } catch (e) {
      toast.error(e?.message || `${label} save failed`);
    } finally { setBusyFor(busyKey, null); }
  };

  const remove = async () => {
    if (!(await _confirmDisconnect(label))) return;
    setBusyFor(busyKey, "delete");
    try {
      const r = await api.delete(`/tenants/me/integrations/${providerKey}`);
      if (r?.removed) toast.success(`${label} disconnected.`);
      else toast(`${label} was not connected.`);
      await reload();
    } catch (e) { toast.error(e?.message || `${label} disconnect failed`); }
    finally { setBusyFor(busyKey, null); }
  };

  const pct = usage?.pct_used ?? 0;
  const pctDisplay = usage?.monthly_request_cap == null
    ? null
    : Math.min(100, Math.round((pct || 0) * 100));
  const barColor = usage?.status === "blocked" ? "#DC2626"
    : usage?.status === "warn" ? "#F59E0B"
    : "#16A34A";
  const capLabel = usage?.monthly_request_cap == null
    ? "Unlimited"
    : usage.monthly_request_cap === 0
    ? "Blocked (cap = 0)"
    : `${(usage.total || 0).toLocaleString()} / ${usage.monthly_request_cap.toLocaleString()}`;

  return (
    <div
      className="rounded-xl p-4 flex flex-col gap-3"
      style={{ border: `1px solid ${colors.border}` }}
      data-testid={`tenant-integration-${providerKey}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="font-semibold text-sm" style={{ color: colors.onSurface }}>{label}</div>
            <StatusPill tone={state} testid={`tenant-integration-${providerKey}-status`}>{stateLabel}</StatusPill>
            {isConnected && <StaleBadge lastUsedAt={row.last_used_at} providerKey={providerKey} />}
          </div>
          <div className="text-xs mt-0.5" style={{ color: colors.onSurfaceSecondary }}>{desc}</div>
        </div>
      </div>

      {isConnected && (
        <div
          className="rounded-lg px-3 py-2 text-xs space-y-1"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
          data-testid={`tenant-integration-${providerKey}-summary`}
        >
          {row.last_4 && (
            <div><span className="font-semibold">API key · last 4:</span>{" "}
              <span className="font-mono" data-testid={`tenant-integration-${providerKey}-last4`}>••••{row.last_4}</span></div>
          )}
        </div>
      )}

      <div className="flex flex-col gap-1" data-testid={`tenant-integration-${providerKey}-usage`}>
        <div className="flex items-center justify-between text-xs" style={{ color: colors.onSurfaceSecondary }}>
          <span>Usage this month</span>
          <span data-testid={`tenant-integration-${providerKey}-usage-label`}>{capLabel}</span>
        </div>
        <div className="w-full h-2 rounded-full overflow-hidden" style={{ backgroundColor: "#E5E7EB" }}>
          {pctDisplay != null && (
            <div
              className="h-full transition-all"
              style={{ width: `${pctDisplay}%`, backgroundColor: barColor }}
              data-testid={`tenant-integration-${providerKey}-usage-bar`}
            />
          )}
        </div>
        {usage && (
          <div className="text-[11px]" style={{ color: colors.onSurfaceSecondary }}
               data-testid={`tenant-integration-${providerKey}-usage-breakdown`}>
            geocode {usage.geocode || 0} · route {usage.route || 0} · static {usage.static_map || 0}
          </div>
        )}
        {usage?.status === "warn" && (
          <div className="text-[11px]" style={{ color: "#854D0E" }}
               data-testid={`tenant-integration-${providerKey}-usage-warn`}>
            ⚠︎ Soft warning · ≥ 80% of monthly cap consumed.
          </div>
        )}
        {usage?.status === "blocked" && (
          <div className="text-[11px]" style={{ color: "#991B1B" }}
               data-testid={`tenant-integration-${providerKey}-usage-blocked`}>
            ✕ Monthly cap reached · requests will return 429 until next month or you raise the cap.
          </div>
        )}
      </div>

      {canWrite && (
        <div className="flex flex-col gap-2">
          <label className="text-xs flex flex-col gap-1" style={{ color: colors.onSurfaceSecondary }}>
            <span>API key<span style={{ color: "#991B1B" }}> *</span></span>
            <input
              type="password"
              value={form.api_key ?? ""}
              onChange={(e) => setForm((prev) => ({ ...prev, api_key: e.target.value }))}
              autoComplete="off"
              placeholder={isConnected ? "•••• (leave blank to keep current)" : ""}
              className="rounded-lg px-2 py-1 text-sm"
              style={{ border: `1px solid ${colors.border}`, backgroundColor: "white", color: colors.onSurface }}
              data-testid={`tenant-integration-${providerKey}-field-api_key`}
            />
          </label>

          {nonSecretFields.map((f) => (
            <label key={f.name} className="text-xs flex flex-col gap-1"
                    style={{ color: colors.onSurfaceSecondary }}>
              <span>{f.label}{f.required && <span style={{ color: "#991B1B" }}> *</span>}</span>
              <input
                type="text"
                value={form[f.name] ?? ""}
                onChange={(e) => setForm((prev) => ({ ...prev, [f.name]: e.target.value }))}
                className="rounded-lg px-2 py-1 text-sm"
                style={{ border: `1px solid ${colors.border}`, backgroundColor: "white", color: colors.onSurface }}
                data-testid={`tenant-integration-${providerKey}-field-${f.name}`}
              />
            </label>
          ))}

          <label className="text-xs flex flex-col gap-1" style={{ color: colors.onSurfaceSecondary }}>
            <span>
              Monthly request cap
              <span className="italic" style={{ color: colors.onSurfaceSecondary }}> · empty = unlimited · 0 = block all</span>
            </span>
            <input
              type="number"
              min="0"
              step="1"
              value={capInput}
              onChange={(e) => setCapInput(e.target.value)}
              placeholder="Unlimited"
              className="rounded-lg px-2 py-1 text-sm"
              style={{ border: `1px solid ${colors.border}`, backgroundColor: "white", color: colors.onSurface }}
              data-testid={`tenant-integration-${providerKey}-cap-input`}
            />
          </label>

          <div className="flex items-center gap-2 flex-wrap mt-1">
            <button
              onClick={save}
              disabled={!!busy[busyKey]}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
              style={{ backgroundColor: colors.brand, opacity: busy[busyKey] ? 0.6 : 1 }}
              data-testid={`tenant-integration-${providerKey}-save`}
            >
              {busy[busyKey] === "save" ? "Saving…" : (isConnected ? "Save (rotate)" : "Save")}
            </button>
            {isConnected && (
              <button
                onClick={remove}
                disabled={!!busy[busyKey]}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                style={{ backgroundColor: "#FEE2E2", color: "#991B1B", opacity: busy[busyKey] ? 0.6 : 1 }}
                data-testid={`tenant-integration-${providerKey}-disconnect`}
              >
                {busy[busyKey] === "delete" ? "Removing…" : "Disconnect"}
              </button>
            )}
          </div>
        </div>
      )}
      {!canWrite && (
        <span className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
          Ask an admin to connect this provider.
        </span>
      )}
    </div>
  );
}


/** ————————————————————————————————————————————————————————————
 *  Phase I1.7.c.3 · Feb-2026 — Per-technician Calendars BYO card.
 *
 *  Unlike SMS / Email / AI / Maps (tenant-level API key), a Calendar
 *  connection is per-technician OAuth. The card therefore shows:
 *   • A cap input (monthly sync-op cap · same semantics as Maps).
 *   • A "Connect …" launcher per technician + Disconnect action.
 *   • A per-technician list of currently-connected accounts.
 *  ———————————————————————————————————————————————————————————— */
function CalendarsCard({
  schema, usage, links, technicians,
  canWrite, busy, setBusyFor, reload,
}) {
  const providerKey = schema.provider_key;
  const shortName = (CALENDARS_PROVIDER_LABELS[providerKey] || {}).short || providerKey;
  const label = (CALENDARS_PROVIDER_LABELS[providerKey] || {}).label || providerKey;
  const desc = (CALENDARS_PROVIDER_LABELS[providerKey] || {}).desc || "";

  const busyKey = providerKey;
  const [capInput, setCapInput] = useState(
    usage?.monthly_sync_op_cap == null ? "" : String(usage.monthly_sync_op_cap),
  );
  const [selectedTech, setSelectedTech] = useState(
    (technicians && technicians[0]?.id) || "",
  );
  useEffect(() => {
    if (usage?.monthly_sync_op_cap != null) {
      setCapInput(String(usage.monthly_sync_op_cap));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usage?.monthly_sync_op_cap]);
  useEffect(() => {
    if (!selectedTech && technicians && technicians[0]?.id) {
      setSelectedTech(technicians[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [technicians?.length]);

  const connectedForProvider = (links || []).filter(
    (l) => l.provider_key === providerKey && l.connected,
  );
  const isConnected = connectedForProvider.length > 0;
  const stateLabel = isConnected
    ? `${connectedForProvider.length} technician${connectedForProvider.length === 1 ? "" : "s"} connected`
    : "No technicians connected";

  const saveCap = async () => {
    setBusyFor(busyKey, "save");
    try {
      const body = {
        config: {},
        monthly_sync_op_cap: capInput === "" ? null : Number(capInput),
      };
      const r = await api.put(`/tenants/me/integrations/${providerKey}`, body);
      if (r?.saved) toast.success(`${label} cap saved.`);
      await reload();
    } catch (e) {
      toast.error(e?.message || `${label} save failed`);
    } finally { setBusyFor(busyKey, null); }
  };

  const connect = async () => {
    if (!selectedTech) {
      toast.error("Pick a technician first.");
      return;
    }
    setBusyFor(busyKey, "connect");
    try {
      const r = await api.get(
        `/tenants/me/integrations/${providerKey}/oauth/start`
          + `?technician_user_id=${encodeURIComponent(selectedTech)}&format=json`,
      );
      if (r?.auth_url) {
        // Full-page redirect so the OAuth callback bounces back with
        // ``calendar_connect=success|error`` (absorbed by the root
        // effect below).
        window.location.assign(r.auth_url);
      } else {
        toast.error(`${label} connect failed — no auth URL returned`);
      }
    } catch (e) { toast.error(e?.message || `${label} connect failed`); }
    finally { setBusyFor(busyKey, null); }
  };

  const disconnectTechnician = async (techUserId, techLabel) => {
    if (!(await _confirmDisconnect(`${label} for ${techLabel}`))) return;
    setBusyFor(`${busyKey}:${techUserId}`, "delete");
    try {
      const r = await api.post(
        `/tenants/me/integrations/${providerKey}/disconnect`,
        { technician_user_id: techUserId },
      );
      if (r?.removed) toast.success(`${label} disconnected for ${techLabel}.`);
      else toast(`${label} was not connected for ${techLabel}.`);
      await reload();
    } catch (e) { toast.error(e?.message || `${label} disconnect failed`); }
    finally { setBusyFor(`${busyKey}:${techUserId}`, null); }
  };

  const pct = usage?.pct_used ?? 0;
  const pctDisplay = usage?.monthly_sync_op_cap == null
    ? null
    : Math.min(100, Math.round((pct || 0) * 100));
  const barColor = usage?.status === "blocked" ? "#DC2626"
    : usage?.status === "warn" ? "#F59E0B"
    : "#16A34A";
  const capLabel = usage?.monthly_sync_op_cap == null
    ? "Unlimited"
    : usage.monthly_sync_op_cap === 0
    ? "Blocked (cap = 0)"
    : `${(usage.total || 0).toLocaleString()} / ${usage.monthly_sync_op_cap.toLocaleString()}`;

  return (
    <div
      className="rounded-xl p-4 flex flex-col gap-3"
      style={{ border: `1px solid ${colors.border}` }}
      data-testid={`tenant-integration-${providerKey}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="font-semibold text-sm" style={{ color: colors.onSurface }}>{label}</div>
            <StatusPill tone={isConnected ? "connected" : "disconnected"}
                          testid={`tenant-integration-${providerKey}-status`}>
              {stateLabel}
            </StatusPill>
          </div>
          <div className="text-xs mt-0.5" style={{ color: colors.onSurfaceSecondary }}>{desc}</div>
        </div>
      </div>

      <div className="flex flex-col gap-1" data-testid={`tenant-integration-${providerKey}-usage`}>
        <div className="flex items-center justify-between text-xs" style={{ color: colors.onSurfaceSecondary }}>
          <span>Sync ops this month</span>
          <span data-testid={`tenant-integration-${providerKey}-usage-label`}>{capLabel}</span>
        </div>
        <div className="w-full h-2 rounded-full overflow-hidden" style={{ backgroundColor: "#E5E7EB" }}>
          {pctDisplay != null && (
            <div
              className="h-full transition-all"
              style={{ width: `${pctDisplay}%`, backgroundColor: barColor }}
              data-testid={`tenant-integration-${providerKey}-usage-bar`}
            />
          )}
        </div>
        {usage && (
          <div className="text-[11px]" style={{ color: colors.onSurfaceSecondary }}
                data-testid={`tenant-integration-${providerKey}-usage-breakdown`}>
            push {usage.push_event || 0} · pull {usage.pull_delta || 0}
          </div>
        )}
        {usage?.status === "warn" && (
          <div className="text-[11px]" style={{ color: "#854D0E" }}
                data-testid={`tenant-integration-${providerKey}-usage-warn`}>
            ⚠︎ Soft warning · ≥ 80% of monthly sync-op cap consumed.
          </div>
        )}
        {usage?.status === "blocked" && (
          <div className="text-[11px]" style={{ color: "#991B1B" }}
                data-testid={`tenant-integration-${providerKey}-usage-blocked`}>
            ✕ Monthly sync cap reached · syncs will 429 until next month or you raise the cap.
          </div>
        )}
      </div>

      {/* Connected-technician list. */}
      {connectedForProvider.length > 0 && (
        <div className="flex flex-col gap-1"
              data-testid={`tenant-integration-${providerKey}-technicians`}>
          <div className="text-xs font-semibold" style={{ color: colors.onSurface }}>
            Connected technicians
          </div>
          <ul className="text-xs flex flex-col gap-1">
            {connectedForProvider.map((l) => {
              const nm = l.technician_name || l.technician_email || l.technician_user_id;
              const bk = `${busyKey}:${l.technician_user_id}`;
              return (
                <li key={l.technician_user_id}
                    className="flex items-center justify-between gap-2 rounded-lg px-2 py-1"
                    style={{ backgroundColor: colors.surfaceSecondary }}
                    data-testid={`tenant-integration-${providerKey}-tech-${l.technician_user_id}`}>
                  <span className="min-w-0 truncate" style={{ color: colors.onSurface }}>
                    {nm}
                    {l.connected_email && (
                      <span style={{ color: colors.onSurfaceSecondary }}>{" "}
                        · <span className="font-mono">{l.connected_email}</span>
                      </span>
                    )}
                  </span>
                  {canWrite && (
                    <button
                      onClick={() => disconnectTechnician(l.technician_user_id, nm)}
                      disabled={!!busy[bk]}
                      className="px-2 py-0.5 rounded text-[11px] font-semibold"
                      style={{ backgroundColor: "#FEE2E2", color: "#991B1B",
                                  opacity: busy[bk] ? 0.6 : 1 }}
                      data-testid={`tenant-integration-${providerKey}-tech-${l.technician_user_id}-disconnect`}
                    >
                      {busy[bk] === "delete" ? "Removing…" : "Disconnect"}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {canWrite && (
        <div className="flex flex-col gap-2">
          <label className="text-xs flex flex-col gap-1" style={{ color: colors.onSurfaceSecondary }}>
            <span>
              Monthly sync-op cap
              <span className="italic" style={{ color: colors.onSurfaceSecondary }}> · empty = unlimited · 0 = block all</span>
            </span>
            <input
              type="number"
              min="0"
              step="1"
              value={capInput}
              onChange={(e) => setCapInput(e.target.value)}
              placeholder="Unlimited"
              className="rounded-lg px-2 py-1 text-sm"
              style={{ border: `1px solid ${colors.border}`, backgroundColor: "white", color: colors.onSurface }}
              data-testid={`tenant-integration-${providerKey}-cap-input`}
            />
          </label>

          {technicians?.length > 0 && (
            <label className="text-xs flex flex-col gap-1"
                    style={{ color: colors.onSurfaceSecondary }}>
              <span>Technician to connect</span>
              <select
                value={selectedTech}
                onChange={(e) => setSelectedTech(e.target.value)}
                className="rounded-lg px-2 py-1 text-sm"
                style={{ border: `1px solid ${colors.border}`, backgroundColor: "white", color: colors.onSurface }}
                data-testid={`tenant-integration-${providerKey}-tech-select`}
              >
                {technicians.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name || t.email || t.id}
                  </option>
                ))}
              </select>
            </label>
          )}

          <div className="flex items-center gap-2 flex-wrap mt-1">
            <button
              onClick={saveCap}
              disabled={!!busy[busyKey]}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
              style={{ backgroundColor: colors.brand, opacity: busy[busyKey] ? 0.6 : 1 }}
              data-testid={`tenant-integration-${providerKey}-save`}
            >
              {busy[busyKey] === "save" ? "Saving…" : "Save cap"}
            </button>
            <button
              onClick={connect}
              disabled={!!busy[busyKey] || !selectedTech}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold"
              style={{ backgroundColor: colors.brandSurface || "#E0F2FE",
                        color: colors.brand,
                        opacity: (busy[busyKey] || !selectedTech) ? 0.6 : 1 }}
              data-testid={`tenant-integration-${providerKey}-connect`}
            >
              {busy[busyKey] === "connect" ? "Redirecting…" : `Connect ${label}`}
            </button>
          </div>
        </div>
      )}
      {!canWrite && (
        <span className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
          Ask an admin to connect this provider.
        </span>
      )}
    </div>
  );
}


/** ————————————————————————————————————————————————————————————
 *  Root component.
 *  ———————————————————————————————————————————————————————————— */
export default function TenantIntegrationsCard() {
  const [rows, setRows] = useState(null);
  const [schemas, setSchemas] = useState({ sms: [], email: [], ai: [], maps: [], calendars: [] });
  const [aiUsage, setAiUsage] = useState({});     // { openai: {...}, anthropic: {...}, gemini: {...} }
  const [mapsUsage, setMapsUsage] = useState({}); // { google: {...}, mapbox: {...} }
  // Phase I1.7.c.3 — Calendars per-tenant usage + per-technician
  // link summaries. ``calendarsLinks`` mirrors the shape returned by
  // ``GET /calendars/usage.technicians``.
  const [calendarsUsage, setCalendarsUsage] = useState({});
  const [calendarsLinks, setCalendarsLinks] = useState([]);
  const [technicians, setTechnicians] = useState([]);
  const [busy, setBusy] = useState({});
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
      const [listRes, schemaRes, usageRes, mapsUsageRes, calUsageRes, techListRes] = await Promise.all([
        api.get("/tenants/me/integrations"),
        api.get("/tenants/me/integrations/schemas"),
        api.get("/tenants/me/integrations/ai/usage").catch(() => ({ providers: [] })),
        api.get("/tenants/me/integrations/maps/usage").catch(() => ({ providers: [] })),
        api.get("/tenants/me/integrations/calendars/usage").catch(() => ({ providers: [], technicians: [] })),
        // Best-effort — the ``/users`` endpoint 403s for non-admins,
        // which is fine (the connect button is only rendered for
        // admins anyway).
        api.get("/users?role=tech").catch(() => api.get("/users").catch(() => [])),
      ]);
      const map = {};
      (listRes?.integrations || []).forEach((row) => { map[row.provider_key] = row; });
      setRows(map);
      setSchemas({
        sms: schemaRes?.sms || [],
        email: schemaRes?.email || [],
        ai: schemaRes?.ai || [],
        maps: schemaRes?.maps || [],
        calendars: schemaRes?.calendars || [],
      });
      const usageByShort = {};
      (usageRes?.providers || []).forEach((u) => { usageByShort[u.provider] = u; });
      setAiUsage(usageByShort);
      const mapsByShort = {};
      (mapsUsageRes?.providers || []).forEach((u) => { mapsByShort[u.provider] = u; });
      setMapsUsage(mapsByShort);
      const calByShort = {};
      (calUsageRes?.providers || []).forEach((u) => { calByShort[u.provider] = u; });
      setCalendarsUsage(calByShort);
      setCalendarsLinks((calUsageRes?.technicians || []).map((t) => ({
        ...t,
        connected: t.connected !== false,
      })));
      // Normalise ``techListRes`` — the API returns a raw array or
      // ``{items:[…]}`` depending on the tenant seed.
      const techArr = Array.isArray(techListRes)
        ? techListRes
        : (techListRes?.items || techListRes?.users || []);
      setTechnicians((techArr || []).map((t) => ({
        id: t.id || t.user_id,
        name: t.name || t.full_name,
        email: t.email,
      })).filter((t) => t.id));
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
      if (flag === "success") toast.success("Stripe connected successfully.");
      else if (flag === "error") {
        const reason = params.get("reason") || "unknown";
        toast.error(`Stripe connection failed: ${reason}`);
      }
      // Phase I1.7.c.3 — Calendars OAuth callback bounce.
      const calFlag = params.get("calendar_connect");
      const calProv = params.get("provider") || "calendar";
      if (calFlag === "success") toast.success(`Calendar (${calProv}) connected.`);
      else if (calFlag === "error") {
        const err = params.get("error") || "unknown";
        toast.error(`Calendar (${calProv}) connect failed: ${err}`);
      }
      if (flag || calFlag) {
        const clean = window.location.pathname + window.location.hash;
        window.history.replaceState({}, "", clean);
      }
    } catch { /* window unavailable in SSR/test — no-op */ }
  }, []);

  const setBusyFor = (k, val) => setBusy((b) => ({ ...b, [k]: val }));

  const connectedRowInKeys = (keys) => {
    if (!rows) return null;
    for (const k of keys) {
      const r = rows[k];
      if (r?.connected) return r;
    }
    return null;
  };

  const smsRow = useMemo(
    () => connectedRowInKeys(schemas.sms.map((s) => s.provider_key)),
    [rows, schemas.sms],
  );
  const emailRow = useMemo(
    () => connectedRowInKeys(schemas.email.map((s) => s.provider_key)),
    [rows, schemas.email],
  );

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
        <StripeCard
          row={rows?.stripe}
          canWrite={canWrite} busy={busy} setBusyFor={setBusyFor} reload={load}
        />

        <MessagingCard
          kind="sms" label="SMS provider"
          desc="Twilio · TextMagic · RingCentral. Configure once — messages go out under your brand."
          schemas={schemas.sms} connectedRow={smsRow}
          canWrite={canWrite} busy={busy} setBusyFor={setBusyFor} reload={load}
        />

        <MessagingCard
          kind="email" label="Email provider"
          desc="Resend · SendGrid · Postmark · Mailgun · custom SMTP."
          schemas={schemas.email} connectedRow={emailRow}
          canWrite={canWrite} busy={busy} setBusyFor={setBusyFor} reload={load}
        />

        {/* Phase I1.7.c.1 · Feb-2026 — AI BYO cards (OpenAI, Anthropic, Gemini). */}
        {schemas.ai.map((s) => {
          const short = (AI_PROVIDER_LABELS[s.provider_key] || {}).short || s.provider_key;
          return (
            <AICard
              key={s.provider_key}
              schema={s}
              row={rows?.[s.provider_key]}
              usage={aiUsage[short]}
              canWrite={canWrite} busy={busy} setBusyFor={setBusyFor} reload={load}
            />
          );
        })}

        {/* Phase I1.7.c.2 · Feb-2026 — Maps BYO cards (Google Maps, Mapbox). */}
        {schemas.maps.map((s) => {
          const short = (MAPS_PROVIDER_LABELS[s.provider_key] || {}).short || s.provider_key;
          return (
            <MapsCard
              key={s.provider_key}
              schema={s}
              row={rows?.[s.provider_key]}
              usage={mapsUsage[short]}
              canWrite={canWrite} busy={busy} setBusyFor={setBusyFor} reload={load}
            />
          );
        })}

        {/* Phase I1.7.c.3 · Feb-2026 — Calendars BYO cards
              (Google Calendar + Outlook, per-technician OAuth). */}
        {schemas.calendars.map((s) => {
          const short = (CALENDARS_PROVIDER_LABELS[s.provider_key] || {}).short || s.provider_key;
          return (
            <CalendarsCard
              key={s.provider_key}
              schema={s}
              usage={calendarsUsage[short]}
              links={calendarsLinks}
              technicians={technicians}
              canWrite={canWrite} busy={busy} setBusyFor={setBusyFor} reload={load}
            />
          );
        })}

        {COMING_SOON.map((p) => (
          <div
            key={p.key}
            className="rounded-xl p-4 flex flex-col gap-3"
            style={{ border: `1px solid ${colors.border}`, opacity: 0.72 }}
            data-testid={`tenant-integration-${p.key}`}
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="flex items-center gap-2">
                  <div className="font-semibold text-sm" style={{ color: colors.onSurface }}>{p.label}</div>
                  <StatusPill tone="coming" testid={`tenant-integration-${p.key}-status`}>Coming soon</StatusPill>
                </div>
                <div className="text-xs mt-0.5" style={{ color: colors.onSurfaceSecondary }}>{p.desc}</div>
              </div>
            </div>
            <div>
              <span className="text-xs italic" style={{ color: colors.onSurfaceSecondary }}>
                Ships in a follow-up phase (I1.7.c–d).
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
