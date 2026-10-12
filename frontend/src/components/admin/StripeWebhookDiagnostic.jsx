// P0c Stage 2 · S2-2 · Feb-2026 — Admin diagnostic panel for the
// Stripe webhook pipeline. Super_admin-only. Renders the response
// from ``GET /api/admin/stripe/webhook-diagnostic`` in a two-column
// grid with mode / mode_match / registered paths at top, issues +
// suggested next action in the middle, and recent events +
// dead-letter rows at the bottom.
//
// Secret values are never shown — the backend returns only the
// first-8-char prefix + length. If prefix is null, we render
// ``<not set>`` so the operator can tell a missing env from a
// present-but-redacted one at a glance.
//
// This component is DISPLAY-ONLY — it does not mutate anything on
// the backend. All remediation happens via env var edits on the
// pod + a backend restart.
import React, { useEffect, useState, useCallback } from "react";
import { api } from "../../api";

const _MODE_MATCH_BADGE = {
  live: { label: "LIVE OK", cls: "bg-green-100 text-green-800 border-green-300" },
  test: { label: "TEST OK", cls: "bg-blue-100 text-blue-800 border-blue-300" },
  mismatch: { label: "MISMATCH", cls: "bg-red-100 text-red-800 border-red-300" },
  unknown: { label: "UNKNOWN", cls: "bg-amber-100 text-amber-800 border-amber-300" },
};

export const StripeWebhookDiagnostic = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const body = await api.get("/admin/stripe/webhook-diagnostic");
      setData(body);
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  if (loading && !data) {
    return (
      <div data-testid="stripe-webhook-diagnostic-loading" className="p-6 text-sm text-slate-500">
        Loading Stripe webhook diagnostic…
      </div>
    );
  }
  if (error) {
    return (
      <div data-testid="stripe-webhook-diagnostic-error" className="p-6 text-sm text-red-700">
        Failed to load diagnostic: {error}
        <button
          type="button"
          onClick={reload}
          data-testid="stripe-webhook-diagnostic-retry"
          className="ml-3 underline"
        >
          Retry
        </button>
      </div>
    );
  }
  if (!data) return null;

  const cfg = data.config || {};
  const badge = _MODE_MATCH_BADGE[cfg.mode_match] || _MODE_MATCH_BADGE.unknown;

  return (
    <div data-testid="stripe-webhook-diagnostic" className="space-y-6">
      {/* Header + reload */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Stripe Webhook Diagnostic</h2>
        <button
          type="button"
          onClick={reload}
          data-testid="stripe-webhook-diagnostic-reload"
          className="text-sm underline"
        >
          Reload
        </button>
      </div>

      {/* Config grid */}
      <div className="grid grid-cols-2 gap-4 border rounded-md p-4">
        <div>
          <div className="text-xs uppercase text-slate-500">Mode</div>
          <div data-testid="stripe-diag-mode" className="font-mono">
            {cfg.mode || "<unset>"}
          </div>
        </div>
        <div>
          <div className="text-xs uppercase text-slate-500">Mode Match</div>
          <span
            data-testid="stripe-diag-mode-match"
            className={`inline-block px-2 py-0.5 rounded text-xs font-bold border ${badge.cls}`}
          >
            {badge.label}
          </span>
        </div>
        <div>
          <div className="text-xs uppercase text-slate-500">API Key</div>
          <div data-testid="stripe-diag-api-key" className="font-mono text-sm">
            {cfg.api_key_configured
              ? `${cfg.api_key_prefix || "???"} (${cfg.api_key_length} chars)`
              : "<not set>"}
          </div>
        </div>
        <div>
          <div className="text-xs uppercase text-slate-500">Webhook Signing Secret</div>
          <div data-testid="stripe-diag-webhook-secret" className="font-mono text-sm">
            {cfg.webhook_secret_configured
              ? `${cfg.webhook_secret_prefix || "???"} (${cfg.webhook_secret_length} chars)`
              : "<not set>"}
          </div>
        </div>
        <div className="col-span-2">
          <div className="text-xs uppercase text-slate-500">Registered Webhook URLs</div>
          <ul data-testid="stripe-diag-paths" className="font-mono text-sm space-y-0.5">
            {(data.registered_webhook_paths || []).map((p) => (
              <li key={p} className="truncate">{p}</li>
            ))}
          </ul>
        </div>
      </div>

      {/* Issues */}
      {Array.isArray(cfg.issues) && cfg.issues.length > 0 && (
        <div data-testid="stripe-diag-issues" className="border border-red-200 bg-red-50 rounded-md p-4">
          <div className="font-semibold text-red-800 mb-2">Issues detected</div>
          <ul className="space-y-2 text-sm">
            {cfg.issues.map((iss, i) => (
              <li key={i} data-testid={`stripe-diag-issue-${iss.code}`}>
                <span className="font-mono text-xs text-red-600">[{iss.code}]</span>{" "}
                <span className="text-red-800">{iss.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Suggested next action */}
      {data.suggested_next_action && (
        <div
          data-testid="stripe-diag-suggestion"
          className="border border-sky-200 bg-sky-50 rounded-md p-4 text-sm text-sky-900"
        >
          <div className="font-semibold mb-1">Suggested next action</div>
          <div>{data.suggested_next_action}</div>
        </div>
      )}

      {/* Recent events */}
      <div className="border rounded-md p-4">
        <div className="font-semibold mb-2">
          Recent webhook events ({data.recent_events_total || 0})
        </div>
        {data.recent_events_total === 0 ? (
          <div data-testid="stripe-diag-no-events" className="text-sm text-slate-500">
            No webhook events have reached this pod yet. If Stripe
            reports delivery failures, verify the Dashboard endpoint
            URL exactly matches one of the paths above.
          </div>
        ) : (
          <ul data-testid="stripe-diag-events" className="space-y-1 text-xs font-mono">
            {(data.recent_events || []).map((ev) => (
              <li key={ev.event_id} className="truncate">
                <span className="inline-block w-32 text-slate-500">
                  {(ev.received_at || "").slice(11, 19)}
                </span>
                <span className="inline-block w-10 font-bold">
                  {ev.status === "handled" ? "OK" :
                   ev.status === "failed" ? "ERR" : "---"}
                </span>
                <span className="inline-block w-56 truncate">{ev.event_type}</span>
                <span className="text-slate-500 truncate">{ev.event_id}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Dead letters */}
      {data.recent_dead_letters_total > 0 && (
        <div
          data-testid="stripe-diag-dead-letters"
          className="border border-amber-200 bg-amber-50 rounded-md p-4"
        >
          <div className="font-semibold text-amber-900 mb-2">
            Dead-letter events ({data.recent_dead_letters_total})
          </div>
          <ul className="space-y-1 text-xs font-mono">
            {(data.recent_dead_letters || []).map((dl) => (
              <li key={dl.event_id} data-testid={`stripe-diag-dl-${dl.event_id}`}>
                <span className="inline-block w-32 text-amber-800">
                  {dl.error_class}
                </span>
                <span className="inline-block w-56 truncate">{dl.event_type}</span>
                <span className="text-slate-700 truncate">{dl.error_message}</span>
              </li>
            ))}
          </ul>
          <div className="text-xs text-amber-800 mt-2">
            Replay a dead-letter via{" "}
            <code>POST /api/admin/stripe/dead-letter/{"{event_id}"}/retry</code> after fixing the handler.
          </div>
        </div>
      )}

      <div className="text-xs text-slate-400" data-testid="stripe-diag-generated-at">
        Generated at {data.generated_at}
      </div>
    </div>
  );
};

export default StripeWebhookDiagnostic;
