/**
 * Sep-2026 · Per-tenant DFS creds · DataForSEO integration card.
 *
 * Rendered on the Tenant Integrations page below the existing
 * ``TenantIntegrationsCard`` (Stripe / Twilio / AI / Maps / …).
 * Mirrors the Maps card's IA: title + status pill + description
 * + two labelled fields + button row (Save · Test · Remove) +
 * last-verified footer.
 *
 * Contract:
 *   • Save saves via ``PUT /api/tenants/me/integrations/dataforseo``.
 *   • Test hits ``POST /api/tenants/me/integrations/dataforseo/test``
 *     (rate-limited 5/hour server-side).
 *   • Remove uses ``DELETE …/dataforseo`` and requires confirm.
 *   • Password is write-only — never redisplayed. After save, the
 *     card shows ``login_masked`` (from the server) + a ``••••••••``
 *     placeholder for the password. A Change button clears the
 *     fields so the tenant can enter fresh values.
 *   • Never renders plaintext credentials of another tenant.
 */
import React from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { api } from "@/api";


function StatusPill({ configured, testid }) {
  const { t } = useTranslation("common");
  const style = configured
    ? { backgroundColor: "#DCFCE7", color: "#166534" }
    : { backgroundColor: "#F1F5F9", color: "#64748B" };
  const label = configured
    ? t("integrations.dataforseo.status.configured", "Configured")
    : t("integrations.dataforseo.status.default", "Using platform default");
  return (
    <span data-testid={testid || "dfs-status-pill"}
          className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold"
          style={style}>
      {label}
    </span>
  );
}


function _humanTs(iso) {
  if (!iso) return null;
  try {
    const dt = new Date(iso);
    const now = new Date();
    const mins = Math.round((now - dt) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins} min ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs} hr ago`;
    return dt.toLocaleDateString();
  } catch (_e) { return iso; }
}


export default function DataForSEOIntegrationCard() {
  const { t } = useTranslation("common");
  const [state, setState] = React.useState(null);
  const [editing, setEditing] = React.useState(false);
  const [form, setForm] = React.useState({ login: "", password: "" });
  const [busy, setBusy] = React.useState(false);
  const [testResult, setTestResult] = React.useState(null);
  const [showRemoveConfirm, setShowRemoveConfirm] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const r = await api.get("/tenants/me/integrations/dataforseo");
      setState(r);
    } catch (_e) {
      // Keep state=null → card shows unconfigured skeleton.
    }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!form.login || !form.password) return;
    setBusy(true);
    try {
      const r = await api.put("/tenants/me/integrations/dataforseo", form);
      setState(r);
      setEditing(false);
      setForm({ login: "", password: "" });
      toast.success(t("integrations.dataforseo.saved",
                          "DataForSEO credentials saved."));
    } catch (e) {
      toast.error(String(e?.message || e || "Save failed."));
    } finally {
      setBusy(false);
    }
  };

  const testConnection = async () => {
    setBusy(true);
    setTestResult(null);
    try {
      const r = await api.post("/tenants/me/integrations/dataforseo/test");
      setTestResult(r);
      if (r.ok) {
        toast.success(t("integrations.dataforseo.test_ok",
                            "Connection successful — {{ms}}ms",
                            { ms: r.latency_ms }));
        setState((prev) => ({ ...(prev || {}),
                                 last_verified_at: r.last_verified_at }));
      } else {
        toast.error(`${t("integrations.dataforseo.test_fail",
                              "Test failed")}: ${r.error}`);
      }
    } catch (e) {
      toast.error(String(e?.message || e || "Test failed."));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      const r = await api.delete("/tenants/me/integrations/dataforseo");
      setState(r);
      setShowRemoveConfirm(false);
      setForm({ login: "", password: "" });
      setEditing(false);
      setTestResult(null);
      toast.success(t("integrations.dataforseo.removed",
                          "DataForSEO credentials removed. Reverted to platform default."));
    } catch (e) {
      toast.error(String(e?.message || e || "Remove failed."));
    } finally {
      setBusy(false);
    }
  };

  const configured = !!(state && state.configured);
  const showFields = editing || !configured;

  return (
    <div className="rounded-2xl p-4 md:p-5 space-y-3"
         data-testid="dfs-integration-card"
         style={{ backgroundColor: "#fff", border: "1px solid #E2E8F0" }}>
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-base font-semibold" data-testid="dfs-integration-title">
            {t("integrations.dataforseo.title", "DataForSEO")}
          </h3>
          <p className="text-xs text-slate-500 mt-1 max-w-md">
            {t("integrations.dataforseo.description",
                "Bring your own DataForSEO account so Rank Heatmap and " +
                "Rank Tracker runs bill to your credits instead of the " +
                "platform default.")}
          </p>
        </div>
        <StatusPill configured={configured} />
      </div>

      {showFields ? (
        <div className="space-y-2">
          <label className="block text-xs font-semibold text-slate-600">
            {t("integrations.dataforseo.login_label", "Login")}
            <input type="email" data-testid="dfs-login-input"
                    autoComplete="off"
                    placeholder="user@example.com"
                    value={form.login}
                    onChange={(e) => setForm({ ...form, login: e.target.value })}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-md border border-slate-300" />
          </label>
          <label className="block text-xs font-semibold text-slate-600">
            {t("integrations.dataforseo.password_label", "Password")}
            <input type="password" data-testid="dfs-password-input"
                    autoComplete="new-password"
                    placeholder="••••••••••••"
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    className="w-full mt-1 px-3 py-2 text-sm rounded-md border border-slate-300" />
          </label>
          {editing && configured ? (
            <button type="button" data-testid="dfs-cancel-edit"
                     onClick={() => { setEditing(false); setForm({ login: "", password: "" }); }}
                     className="text-xs text-slate-500 underline">
              {t("integrations.dataforseo.cancel", "Cancel")}
            </button>
          ) : null}
        </div>
      ) : (
        <div className="space-y-1 text-sm">
          <div data-testid="dfs-login-masked">
            <span className="text-slate-500">
              {t("integrations.dataforseo.login_label", "Login")}:
            </span>{" "}
            <span className="font-mono">{state?.login_masked || "—"}</span>
          </div>
          <div>
            <span className="text-slate-500">
              {t("integrations.dataforseo.password_label", "Password")}:
            </span>{" "}
            <span className="font-mono">••••••••</span>
          </div>
          <button type="button" data-testid="dfs-change-btn"
                    onClick={() => setEditing(true)}
                    className="text-xs text-blue-600 underline">
            {t("integrations.dataforseo.change", "Change")}
          </button>
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap pt-2">
        {showFields ? (
          <button type="button" data-testid="dfs-save-btn"
                    disabled={busy || !form.login || !form.password}
                    onClick={save}
                    className="px-3 py-1.5 text-sm font-semibold text-white rounded-md"
                    style={{ backgroundColor: (busy || !form.login || !form.password) ? "#94A3B8" : "#0F766E" }}>
            {t("integrations.dataforseo.save", "Save")}
          </button>
        ) : null}
        {configured ? (
          <button type="button" data-testid="dfs-test-btn"
                    disabled={busy || showFields}
                    onClick={testConnection}
                    className="px-3 py-1.5 text-sm font-semibold rounded-md border border-slate-300 disabled:opacity-50">
            {t("integrations.dataforseo.test", "Test connection")}
          </button>
        ) : null}
        {configured ? (
          <button type="button" data-testid="dfs-remove-btn"
                    disabled={busy}
                    onClick={() => setShowRemoveConfirm(true)}
                    className="ml-auto text-xs text-red-600 underline">
            {t("integrations.dataforseo.remove", "Remove")}
          </button>
        ) : null}
      </div>

      {testResult ? (
        <div data-testid="dfs-test-result"
              className={`text-xs ${testResult.ok ? "text-emerald-700" : "text-red-700"}`}>
          {testResult.ok
            ? t("integrations.dataforseo.test_success_detail",
                "Connected in {{ms}}ms", { ms: testResult.latency_ms })
            : `${t("integrations.dataforseo.test_fail_detail", "Failed")}: ${testResult.error}`}
        </div>
      ) : null}

      {state?.last_verified_at ? (
        <div className="text-[11px] text-slate-500"
              data-testid="dfs-last-verified">
          {t("integrations.dataforseo.last_verified",
              "Last verified: {{when}}",
              { when: _humanTs(state.last_verified_at) })}
        </div>
      ) : null}

      {showRemoveConfirm ? (
        <div className="rounded-lg p-3 border border-red-200 bg-red-50"
              data-testid="dfs-remove-confirm">
          <p className="text-sm text-red-800 mb-2">
            {t("integrations.dataforseo.remove_confirm",
                "This will revert Rank Heatmap and Rank Tracker to platform " +
                "defaults. Continue?")}
          </p>
          <div className="flex gap-2">
            <button type="button" data-testid="dfs-remove-confirm-yes"
                     onClick={remove} disabled={busy}
                     className="px-3 py-1 text-xs font-semibold text-white bg-red-600 rounded-md">
              {t("integrations.dataforseo.remove_confirm_yes", "Yes, remove")}
            </button>
            <button type="button" data-testid="dfs-remove-confirm-no"
                     onClick={() => setShowRemoveConfirm(false)}
                     className="px-3 py-1 text-xs rounded-md border border-slate-300">
              {t("integrations.dataforseo.remove_confirm_no", "Cancel")}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
