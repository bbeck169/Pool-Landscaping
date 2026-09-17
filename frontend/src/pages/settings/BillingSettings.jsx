/**
 * Phase 20A.2 · Billing Settings — auto-invoice on service-report submit.
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Save, Receipt, CreditCard, RefreshCw, PlayCircle, CheckCircle2, AlertTriangle } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { TimezoneSelect } from "@/components/settings/TimezoneSelect";

export default function BillingSettings() {
  const nav = useNavigate();
  const [cfg, setCfg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");
  // Phase 12 · Feb 2026 — tenant-wide "require card on file" default.
  const [tenantSettings, setTenantSettings] = useState(null);
  const [savingTenant, setSavingTenant] = useState(false);

  useEffect(() => {
    api.get("/settings/billing")
      .then((r) => { setCfg(r); setLoading(false); })
      .catch((e) => { setToast(e.message); setLoading(false); });
    api.get("/tenants/current")
      .then((t) => setTenantSettings(t))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put("/settings/billing", {
        auto_invoice_on_submit: !!cfg.auto_invoice_on_submit,
      });
      setCfg(r);
      setToast("Settings saved");
    } catch (e) { setToast(e.message); }
    finally { setSaving(false); }
  };

  if (loading) return (
    <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>
  );

  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="billing-settings-page">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav(-1)}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="billing-back-btn">
          <ArrowLeft size={16} />
        </button>
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            Billing Settings
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Automatic invoicing behavior when a technician submits a service report.
          </p>
        </div>
      </div>

      <div className="rounded-2xl p-6 mb-4"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="billing-auto-invoice-card">
        <label className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <Receipt size={20} style={{ color: colors.brand }}/>
            <div>
              <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                Auto-invoice on service report submit
              </div>
              <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                When a tech submits a report, automatically generate a draft invoice
                for the job. Skips non-billable jobs and zero-price line items.
                Applies pending referral credits (Phase 19).
              </div>
            </div>
          </div>
          <button onClick={() => setCfg({ ...cfg, auto_invoice_on_submit: !cfg.auto_invoice_on_submit })}
                  className="w-11 h-6 rounded-full relative transition ml-3 shrink-0"
                  style={{ backgroundColor: cfg.auto_invoice_on_submit ? colors.brand : colors.surfaceTertiary }}
                  data-testid="auto-invoice-toggle">
            <span className="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all shadow"
                  style={{ left: cfg.auto_invoice_on_submit ? 22 : 2 }} />
          </button>
        </label>

        <div className="flex justify-end items-center pt-4"
             style={{ borderTop: `1px solid ${colors.border}` }}>
          <button onClick={save} disabled={saving}
                  className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-lg disabled:opacity-60"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="billing-save-btn">
            <Save size={13} /> {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {/* Phase 12 · Feb 2026 — Payment defaults section. Admin flips
          the tenant-wide "Require card on file by default" toggle
          here; per-customer overrides live on the customer detail
          page. Changes are timestamped + attributed on the tenant
          document. */}
      {tenantSettings && (
        <div className="rounded-2xl p-6 mb-4"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="tenant-payment-defaults-card">
          <div className="flex items-center gap-3 mb-3">
            <CreditCard size={20} style={{ color: colors.brand }} />
            <div>
              <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                Payment defaults
              </div>
              <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                Tenant-wide fallbacks for new customers.
              </div>
            </div>
          </div>
          <label className="flex items-center justify-between">
            <div className="flex-1 min-w-0 pr-4">
              <div className="text-sm font-medium" style={{ color: colors.onSurface }}>
                Require card on file by default for all customers
              </div>
              <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                Individual customers can override this on their profile.
              </div>
            </div>
            <button
              onClick={async () => {
                if (savingTenant) return;
                setSavingTenant(true);
                try {
                  const next = !tenantSettings.require_card_on_file_default;
                  const doc = await api.patch("/tenants/mine/settings", {
                    require_card_on_file_default: next,
                  });
                  setTenantSettings((s) => ({ ...s, ...doc }));
                  setToast("Payment defaults saved");
                } catch (e) {
                  setToast(e.message || "Save failed");
                } finally {
                  setSavingTenant(false);
                }
              }}
              className="w-11 h-6 rounded-full relative transition ml-3 shrink-0"
              style={{
                backgroundColor: tenantSettings.require_card_on_file_default
                  ? colors.brand : colors.surfaceTertiary,
                opacity: savingTenant ? 0.6 : 1,
              }}
              data-testid="tenant-require-card-toggle">
              <span className="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all shadow"
                    style={{ left: tenantSettings.require_card_on_file_default ? 22 : 2 }} />
            </button>
          </label>

          {/* Batch 12C · Feb 2026 — Timezone picker. Feb-2026 ·
              Timezone Finalization ship — rendered via the shared
              TimezoneSelect component so this page and BusinessSettings
              stay option-for-option identical. Both routes save through
              the same PATCH /api/tenants/mine/settings endpoint. */}
          <div className="mt-4 pt-4"
                style={{ borderTop: "1px solid #E5E7EB" }}>
            <TimezoneSelect
              value={tenantSettings.timezone || "America/Phoenix"}
              disabled={savingTenant}
              label="Tenant timezone"
              helperText="Used to dispatch the weekly Stripe sync + other per-tenant crons."
              testid="tenant-timezone-picker"
              onChange={async (e) => {
                const nextTz = e.target.value;
                if (savingTenant) return;
                setSavingTenant(true);
                try {
                  const doc = await api.patch("/tenants/mine/settings", {
                    timezone: nextTz,
                  });
                  setTenantSettings((s) => ({ ...s, ...doc, timezone: doc.timezone || nextTz }));
                  setToast("Timezone updated");
                } catch (err) {
                  setToast(err.message || "Save failed");
                } finally {
                  setSavingTenant(false);
                }
              }}
            />
          </div>

          {/* Batch 12C · Feb 2026 — Auto-send add-card link on new
              customer creation. Default OFF. */}
          <label className="mt-4 pt-4 flex items-center justify-between"
                  style={{ borderTop: "1px solid #E5E7EB" }}>
            <div className="flex-1 min-w-0 pr-4">
              <div className="text-sm font-medium" style={{ color: colors.onSurface }}>
                Auto-send add-card link on new customer
              </div>
              <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                Automatically email + SMS a card-add link when a new customer
                is created and no card is on file.
              </div>
            </div>
            <button
              onClick={async () => {
                if (savingTenant) return;
                setSavingTenant(true);
                try {
                  const next = !tenantSettings.auto_send_card_add_on_create;
                  const doc = await api.patch("/tenants/mine/settings", {
                    auto_send_card_add_on_create: next,
                  });
                  setTenantSettings((s) => ({ ...s, ...doc }));
                  setToast("Auto-send preference saved");
                } catch (err) {
                  setToast(err.message || "Save failed");
                } finally {
                  setSavingTenant(false);
                }
              }}
              className="w-11 h-6 rounded-full relative transition ml-3 shrink-0"
              style={{
                backgroundColor: tenantSettings.auto_send_card_add_on_create
                  ? colors.brand : colors.surfaceTertiary,
                opacity: savingTenant ? 0.6 : 1,
              }}
              data-testid="tenant-auto-send-card-toggle">
              <span className="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all shadow"
                    style={{ left: tenantSettings.auto_send_card_add_on_create ? 22 : 2 }} />
            </button>
          </label>

          {/* Phase 12B · Feb 2026 — Stripe cross-reference sync. */}
          <StripeSyncSection tenantSettings={tenantSettings}
                              onToast={setToast} />

          {/* Feb-2026 follow-up — audit banner. Shows a muted
              "Last changed <relative> by <actor>" footer sourced from
              the ``settings_updated_at`` / ``settings_updated_by_name``
              stamps written by ``PATCH /api/tenants/mine/settings``.
              Silent when no PATCH has happened yet on this tenant. */}
          <SettingsAuditBanner tenantSettings={tenantSettings} />
        </div>
      )}

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-xl text-sm font-semibold shadow-lg"
             style={{ backgroundColor: colors.onSurface, color: "#fff" }}
             data-testid="billing-toast">
          {toast}
        </div>
      )}
    </div>
  );
}


/**
 * Phase 12B · Feb 2026 — "Sync from Stripe" subsection.
 *
 * Sits inside the Payment Defaults card. Buttons:
 *   • Preview sync — POSTs to /admin/stripe-customer-sync/preview.
 *     Renders a summary card with counts + expandable ambiguous list.
 *   • Run sync    — POSTs to /admin/stripe-customer-sync/run.
 *     Same summary shape but past-tense counts.
 * Also shows "Last synced" from ``tenantSettings.stripe_sync_last_run_at``.
 * Ambiguous rows expose a Resolve button that opens a small dialog
 * for picking a specific ``stripe_customer_id`` and calls the /link
 * endpoint.
 */
function StripeSyncSection({ tenantSettings, onToast }) {
  const [busy, setBusy] = useState("");
  const [report, setReport] = useState(null);
  const [resolving, setResolving] = useState(null);

  const preview = async () => {
    setBusy("preview");
    try {
      const r = await api.post("/admin/stripe-customer-sync/preview");
      setReport({ ...r, isDryRun: true });
      onToast("Preview complete");
    } catch (e) { onToast(e.message || "Preview failed"); }
    finally { setBusy(""); }
  };
  const runNow = async () => {
    setBusy("run");
    try {
      const r = await api.post("/admin/stripe-customer-sync/run");
      setReport({ ...r, isDryRun: false });
      onToast("Sync complete");
    } catch (e) { onToast(e.message || "Sync failed"); }
    finally { setBusy(""); }
  };
  const doResolve = async (stripe_customer_id) => {
    if (!resolving) return;
    setBusy("resolve");
    try {
      await api.post("/admin/stripe-customer-sync/link", {
        customer_id: resolving.customer_id,
        stripe_customer_id,
      });
      onToast("Linked to Stripe");
      setResolving(null);
      await preview();
    } catch (e) { onToast(e.message || "Link failed"); }
    finally { setBusy(""); }
  };

  const linked = report ? (report.linked || report.would_link || []) : [];
  const cardUpd = report ? (report.updated_card_flag
                              || report.would_update_card_flag || []) : [];
  const ambig = (report && report.ambiguous_matches) || [];

  return (
    <div className="mt-4 pt-4"
          style={{ borderTop: "1px solid #E5E7EB" }}
          data-testid="stripe-sync-section">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-sm font-semibold text-zinc-900">
            Sync from Stripe
          </div>
          <div className="text-xs text-zinc-500 mt-0.5">
            Reflect Stripe's card-on-file state onto CRM customers.
            {tenantSettings.stripe_sync_last_run_at ? (
              <> · Last synced: <span className="font-medium">
                {new Date(tenantSettings.stripe_sync_last_run_at).toLocaleString()}
              </span></>
            ) : null}
          </div>
          {/* Batch 12C · Feb 2026 — "Next scheduled sync" line.
              Format `Thu 02:00 · <TZ>` using the tenant's configured
              timezone (fallback America/Phoenix). Static — the cron
              dispatch is per-tenant Thu 02:00 local. */}
          <div className="text-[11px] text-zinc-400 mt-0.5"
                data-testid="stripe-sync-next-scheduled">
            Next scheduled sync: Thu 02:00 · {tenantSettings.timezone || "America/Phoenix"}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={preview} disabled={!!busy}
                  data-testid="stripe-sync-preview-btn"
                  className="text-xs font-semibold px-3 py-1.5 rounded-lg inline-flex items-center gap-1.5"
                  style={{ backgroundColor: "#F1F5F9", color: "#0F172A",
                            opacity: busy ? 0.6 : 1 }}>
            <RefreshCw size={12} />
            {busy === "preview" ? "Previewing…" : "Preview sync"}
          </button>
          <button onClick={runNow} disabled={!!busy}
                  data-testid="stripe-sync-run-btn"
                  className="text-xs font-semibold px-3 py-1.5 rounded-lg inline-flex items-center gap-1.5 text-white"
                  style={{ backgroundColor: "#0F172A",
                            opacity: busy ? 0.6 : 1 }}>
            <PlayCircle size={12} />
            {busy === "run" ? "Running…" : "Run sync"}
          </button>
        </div>
      </div>

      {report && (
        <div
          data-testid="stripe-sync-result"
          className="rounded-xl p-4"
          style={{ backgroundColor: report.isDryRun ? "#F8FAFC" : "#ECFDF5",
                    border: `1px solid ${report.isDryRun ? "#E2E8F0" : "#A7F3D0"}` }}
        >
          <div className="flex items-center gap-2 mb-3">
            {report.isDryRun ? (
              <RefreshCw size={14} color="#334155" />
            ) : (
              <CheckCircle2 size={14} color="#059669" />
            )}
            <div className="text-xs font-semibold" style={{
              color: report.isDryRun ? "#334155" : "#065F46",
            }}>
              {report.isDryRun ? "Preview only — nothing written" : "Sync complete"}
            </div>
          </div>
          <div className="grid grid-cols-4 gap-3 mb-3">
            <SyncStat label="Examined" value={report.examined} />
            <SyncStat label={report.isDryRun ? "Would link by email" : "Linked by email"}
                        value={linked.length} />
            <SyncStat label={report.isDryRun ? "Would update card" : "Updated card"}
                        value={cardUpd.length} />
            <SyncStat label="Skipped (no contact)"
                        value={report.skipped_no_contact || 0} muted />
          </div>
          {ambig.length > 0 && (
            <div className="mt-2">
              <div className="text-xs font-semibold text-amber-800 flex items-center gap-1 mb-1">
                <AlertTriangle size={12} /> {ambig.length} ambiguous match{ambig.length === 1 ? "" : "es"}
              </div>
              <div className="rounded-lg bg-white border border-amber-200 overflow-hidden">
                {ambig.map((a) => (
                  <div key={a.customer_id}
                        data-testid={`stripe-sync-ambig-row-${a.customer_id}`}
                        className="flex items-center justify-between px-3 py-2 border-b border-amber-100 last:border-b-0">
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-semibold text-zinc-900 truncate">
                        {a.customer_name || a.customer_id}
                      </div>
                      <div className="text-[11px] text-zinc-500 truncate">
                        {a.email} · {a.stripe_ids.length} candidates
                      </div>
                    </div>
                    <button
                      onClick={() => setResolving(a)}
                      className="text-[11px] font-semibold px-2 py-1 rounded-md bg-amber-100 text-amber-900">
                      Resolve
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {resolving && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
              data-testid="stripe-sync-resolve-dialog">
          <div className="bg-white rounded-2xl p-5 max-w-md w-full">
            <div className="text-sm font-semibold text-zinc-900 mb-1">
              Resolve ambiguous match
            </div>
            <div className="text-xs text-zinc-500 mb-3">
              {resolving.customer_name || resolving.customer_id} · {resolving.email}
            </div>
            <div className="space-y-2">
              {resolving.stripe_ids.map((sid) => (
                <button key={sid}
                        onClick={() => doResolve(sid)}
                        disabled={!!busy}
                        className="w-full text-left px-3 py-2 rounded-lg border border-zinc-200 hover:bg-zinc-50 text-xs font-medium text-zinc-900"
                        data-testid={`stripe-sync-resolve-pick-${sid}`}>
                  <span className="text-zinc-500 mr-2">stripe_customer_id</span>
                  {sid}
                </button>
              ))}
            </div>
            <div className="mt-3 flex justify-end">
              <button onClick={() => setResolving(null)}
                      className="text-xs text-zinc-500 hover:text-zinc-900 px-2 py-1">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


function SyncStat({ label, value, muted }) {
  return (
    <div className="rounded-lg bg-white/80 border border-zinc-100 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-0.5">
        {label}
      </div>
      <div className={`text-lg font-semibold ${muted ? "text-zinc-400" : "text-zinc-900"}`}>
        {value ?? 0}
      </div>
    </div>
  );
}


/**
 * Feb-2026 follow-up — audit banner rendered under Payment Defaults.
 * Reads ``tenantSettings.settings_updated_at`` +
 * ``settings_updated_by_name`` (populated by GET /api/tenants/current).
 * Silent when the tenant has never been PATCHed.
 */
function settingsRelTime(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return String(iso);
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

function SettingsAuditBanner({ tenantSettings }) {
  const at = tenantSettings?.settings_updated_at;
  if (!at) return null;
  const actor = tenantSettings.settings_updated_by_name
    || tenantSettings.settings_updated_by
    || "someone";
  return (
    <div
      className="mt-4 pt-3 text-[11px]"
      style={{
        color: colors.muted,
        borderTop: `1px solid ${colors.border}`,
      }}
      title={at}
      data-testid="tenant-settings-audit-banner"
    >
      Last changed{" "}
      <span data-testid="tenant-settings-audit-when">{settingsRelTime(at)}</span>
      {" by "}
      <span
        style={{ color: colors.onSurface, fontWeight: 600 }}
        data-testid="tenant-settings-audit-actor"
      >
        {actor}
      </span>
    </div>
  );
}
