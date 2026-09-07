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


const STALE_DAYS = 30;
const COMING_SOON = [
  { key: "ai",        label: "AI provider",      desc: "OpenAI · Claude · Gemini. BYO API key or Emergent-managed." },
  { key: "maps",      label: "Maps provider",    desc: "Google Maps · Mapbox · OpenStreetMap." },
  { key: "calendars", label: "Calendar sync",    desc: "Google Calendar · Outlook · iCloud." },
  { key: "storage",   label: "Object storage",   desc: "S3 · GCS · Emergent-managed default." },
];


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
    if (typeof window !== "undefined" && window.confirm
        && !window.confirm("Disconnect Stripe? Your saved credentials will be permanently removed.")) return;
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
    if (typeof window !== "undefined" && window.confirm
        && !window.confirm(`Disconnect ${connectedRow.provider_key}? Your saved credentials will be permanently removed.`)) return;
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
 *  Root component.
 *  ———————————————————————————————————————————————————————————— */
export default function TenantIntegrationsCard() {
  const [rows, setRows] = useState(null);
  const [schemas, setSchemas] = useState({ sms: [], email: [] });
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
      const [listRes, schemaRes] = await Promise.all([
        api.get("/tenants/me/integrations"),
        api.get("/tenants/me/integrations/schemas"),
      ]);
      const map = {};
      (listRes?.integrations || []).forEach((row) => { map[row.provider_key] = row; });
      setRows(map);
      setSchemas({ sms: schemaRes?.sms || [], email: schemaRes?.email || [] });
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
      if (flag) {
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
