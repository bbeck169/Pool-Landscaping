/**
 * Feb-2026 · Payment Processor Primary/Backup section (BusinessSettings).
 *
 * Admin-only section that lets tenants pick primary + backup payment
 * providers with an inline Test Connection button and a recent-
 * failover events table.
 *
 * API surface used:
 *   GET   /api/tenants/mine/settings/payment-providers
 *   PATCH /api/tenants/mine/settings/payment-providers
 *   POST  /api/tenants/mine/payment-providers/test
 *   GET   /api/tenants/mine/payment-audit
 */
import React from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Loader2, PlugZap } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";


const NONE_VALUE = "__none__";


function ProviderOption({ opt }) {
  const dot = opt.is_configured ? "#10B981" : "#94A3B8";
  const label = opt.short_name.charAt(0).toUpperCase() + opt.short_name.slice(1);
  return (
    <option value={opt.short_name}
             data-testid={`payment-providers-option-${opt.short_name}`}>
      {label}{opt.is_configured ? " · Configured" : " · Missing keys"}
    </option>
  );
}


function TestButton({ shortName, disabled, onResult }) {
  const { t } = useTranslation("common");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState(null);
  return (
    <div className="flex items-center gap-2 ml-3">
      <button
        type="button"
        disabled={disabled || busy}
        onClick={async () => {
          setBusy(true);
          try {
            const r = await api.post(
              "/tenants/mine/payment-providers/test",
              { provider: shortName },
            );
            setResult(r);
            onResult && onResult(shortName, r);
          } catch (err) {
            const msg = err?.message || "network error";
            setResult({ ok: false, error: msg, latency_ms: null });
            onResult && onResult(shortName, { ok: false, error: msg });
          } finally {
            setBusy(false);
          }
        }}
        className="px-3 py-1.5 rounded text-sm border"
        style={{
          borderColor: colors.border,
          background: disabled ? "#F3F4F6" : "#FFFFFF",
          color: disabled ? "#94A3B8" : colors.onSurface,
          cursor: (disabled || busy) ? "not-allowed" : "pointer",
        }}
        data-testid={`payment-providers-test-${shortName || "empty"}`}
      >
        {busy ? (
          <span className="inline-flex items-center gap-1">
            <Loader2 className="animate-spin" size={14} />
            {t("payment_providers.testing", "Testing…")}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1">
            <PlugZap size={14} />
            {t("payment_providers.test_button", "Test connection")}
          </span>
        )}
      </button>
      {result ? (
        result.ok ? (
          <span className="text-xs" style={{ color: "#10B981" }}
                 data-testid={`payment-providers-test-result-${shortName}`}>
            {t("payment_providers.result_ok", "Connected")}
            {result.latency_ms != null ? ` · ${result.latency_ms}ms` : ""}
          </span>
        ) : (
          <span className="text-xs" style={{ color: "#DC2626" }}
                 data-testid={`payment-providers-test-result-${shortName}`}>
            {result.error || t("payment_providers.result_fail", "Failed")}
          </span>
        )
      ) : null}
    </div>
  );
}


function AuditTable({ rows }) {
  const { t } = useTranslation("common");
  if (!rows || rows.length === 0) return null;
  return (
    <div className="mt-6 pt-4"
          style={{ borderTop: "1px solid #E5E7EB" }}
          data-testid="payment-providers-audit-table">
      <h3 className="text-sm font-semibold mb-2">
        {t("payment_providers.recent_failovers", "Recent failover events")}
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr style={{ color: colors.muted }}>
              <th className="text-left py-1">{t("payment_providers.audit_when", "When")}</th>
              <th className="text-left py-1">{t("payment_providers.audit_op", "Operation")}</th>
              <th className="text-left py-1">{t("payment_providers.audit_primary", "Primary")}</th>
              <th className="text-left py-1">{t("payment_providers.audit_backup", "Backup")}</th>
              <th className="text-left py-1">{t("payment_providers.audit_reason", "Reason")}</th>
              <th className="text-left py-1">{t("payment_providers.audit_resolution", "Resolution")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 10).map((r) => (
              <tr key={r.id} data-testid={`payment-providers-audit-row-${r.id}`}>
                <td className="py-1">{new Date(r.timestamp).toLocaleString()}</td>
                <td className="py-1">{r.operation}</td>
                <td className="py-1">{r.primary_provider}</td>
                <td className="py-1">{r.backup_provider || "—"}</td>
                <td className="py-1">{r.error_from_primary}</td>
                <td className="py-1">{r.resolution}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


export default function PaymentProvidersCard() {
  const { t } = useTranslation("common");
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [available, setAvailable] = React.useState([]);
  const [primary, setPrimary] = React.useState("stripe");
  const [backup, setBackup] = React.useState(null);
  const [audit, setAudit] = React.useState([]);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/tenants/mine/settings/payment-providers");
      setAvailable(r?.available || []);
      setPrimary(r?.primary_provider || "stripe");
      setBackup(r?.backup_provider || null);
    } catch (err) {
      toast.error(err?.message || "Failed to load payment providers");
    } finally {
      setLoading(false);
    }
    try {
      const a = await api.get("/tenants/mine/payment-audit?limit=10");
      setAudit(a?.rows || []);
    } catch (_e) {
      // Non-fatal — table is hidden when empty.
      setAudit([]);
    }
  }, []);

  React.useEffect(() => { refresh(); }, [refresh]);

  const sameProviderError =
    primary && backup && primary === backup
      ? t(
          "payment_providers.same_provider_error",
          "Primary and backup must be different providers.",
        )
      : "";

  const configured = React.useMemo(() => {
    const map = {};
    for (const o of available) map[o.short_name] = !!o.is_configured;
    return map;
  }, [available]);

  const canSave =
    !loading && !saving && !sameProviderError;

  const onSave = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      const patchBody = {
        primary_provider: primary,
        backup_provider: backup,
      };
      const r = await api.patch(
        "/tenants/mine/settings/payment-providers",
        patchBody,
      );
      setAvailable(r?.available || []);
      setPrimary(r?.primary_provider || "stripe");
      setBackup(r?.backup_provider || null);
      toast.success(
        t("payment_providers.saved", "Payment processors updated"),
      );
    } catch (err) {
      toast.error(err?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <section
        className="lg:col-span-3 bg-white rounded-lg border p-5"
        style={{ borderColor: colors.border }}
        data-testid="business-settings-payment-providers-section"
      >
        <div className="flex items-center gap-2"
              data-testid="payment-providers-loading">
          <Loader2 className="animate-spin" size={16} />
          <span className="text-sm">{t("loading", "Loading…")}</span>
        </div>
      </section>
    );
  }

  return (
    <section
      className="lg:col-span-3 bg-white rounded-lg border p-5"
      style={{ borderColor: colors.border }}
      data-testid="business-settings-payment-providers-section"
    >
      <h2 className="text-lg font-semibold mb-1">
        {t("payment_providers.title", "Payment Processors")}
      </h2>
      <p className="text-xs mb-4" style={{ color: colors.muted }}>
        {t(
          "payment_providers.description",
          "Pick a primary processor for charging cards and an optional backup used automatically when the primary is unavailable.",
        )}
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Primary */}
        <div>
          <label className="block text-xs font-medium mb-1"
                  style={{ color: colors.muted }}>
            {t("payment_providers.primary_label", "Primary payment processor")}
          </label>
          <div className="flex items-center">
            <select
              className="flex-1 border rounded px-3 py-2 text-sm"
              style={{ borderColor: colors.border }}
              value={primary || ""}
              onChange={(e) => setPrimary(e.target.value)}
              data-testid="payment-providers-primary-select"
            >
              {available.map((opt) => (
                <ProviderOption key={opt.short_name} opt={opt} />
              ))}
            </select>
            <TestButton
              shortName={primary}
              disabled={!primary || !configured[primary]}
            />
          </div>
        </div>

        {/* Backup */}
        <div>
          <label className="block text-xs font-medium mb-1"
                  style={{ color: colors.muted }}>
            {t("payment_providers.backup_label", "Backup payment processor")}
          </label>
          <div className="flex items-center">
            <select
              className="flex-1 border rounded px-3 py-2 text-sm"
              style={{ borderColor: colors.border }}
              value={backup || NONE_VALUE}
              onChange={(e) => {
                const v = e.target.value;
                setBackup(v === NONE_VALUE ? null : v);
              }}
              data-testid="payment-providers-backup-select"
            >
              <option value={NONE_VALUE}
                       data-testid="payment-providers-option-none">
                {t("payment_providers.backup_none", "None (no failover)")}
              </option>
              {available.map((opt) => (
                <ProviderOption key={opt.short_name} opt={opt} />
              ))}
            </select>
            <TestButton
              shortName={backup}
              disabled={!backup || !configured[backup]}
            />
          </div>
        </div>
      </div>

      {sameProviderError ? (
        <div className="text-xs mt-2 flex items-center gap-1"
              style={{ color: "#DC2626" }}
              data-testid="payment-providers-same-provider-error">
          <AlertTriangle size={13} /> {sameProviderError}
        </div>
      ) : null}

      <div className="mt-4">
        <button
          type="button"
          onClick={onSave}
          disabled={!canSave}
          className="px-4 py-2 rounded text-white text-sm font-medium"
          style={{
            background: canSave ? colors.brand : "#94A3B8",
            cursor: canSave ? "pointer" : "not-allowed",
          }}
          data-testid="payment-providers-save-button"
        >
          {saving
            ? t("payment_providers.saving", "Saving…")
            : t("payment_providers.save", "Save")}
        </button>
      </div>

      <AuditTable rows={audit} />
    </section>
  );
}
