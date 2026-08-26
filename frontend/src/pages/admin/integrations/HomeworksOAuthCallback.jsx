/**
 * Phase 0 POC · Feb-2026 — Homeworks OAuth callback landing page.
 *
 * Route: /admin/integrations/homeworks/oauth/callback
 *
 * The browser lands here after home.works redirects with ?code=&state=.
 * We POST both to the backend, then bounce back to the integration
 * page with a status query string that the parent page can react to.
 */
import React from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Loader2, ShieldCheck, AlertTriangle } from "lucide-react";

import { api } from "@/api";


export default function HomeworksOAuthCallback() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [status, setStatus] = React.useState("running"); // running | ok | error
  const [reason, setReason] = React.useState(null);

  React.useEffect(() => {
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const providerError = searchParams.get("error");
    if (providerError) {
      setStatus("error");
      setReason(providerError);
      toast.error(`Homeworks OAuth error: ${providerError}`);
      return;
    }
    if (!code || !state) {
      setStatus("error");
      setReason("missing_params");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        // Backend GET expects code + state in the query string.
        const qs = new URLSearchParams({ code, state }).toString();
        const r = await api.get(`/admin/integrations/homeworks/oauth/callback?${qs}`);
        if (cancelled) return;
        if (r?.ok) {
          setStatus("ok");
          toast.success("Homeworks connected");
          // Bounce back after a short pause so the toast is visible.
          setTimeout(() => {
            navigate("/admin/integrations/homeworks?homeworks=connected",
                      { replace: true });
          }, 800);
        } else {
          setStatus("error");
          setReason(r?.reason || "unknown");
          toast.error(`Callback failed: ${r?.reason || "unknown"}`);
        }
      } catch (e) {
        if (cancelled) return;
        setStatus("error");
        setReason(e.message || "callback_failed");
        toast.error(e.message || "Callback failed");
      }
    })();
    return () => { cancelled = true; };
  }, [searchParams, navigate]);

  return (
    <div
      className="min-h-[60vh] flex items-center justify-center p-8"
      data-testid="homeworks-oauth-callback-page"
    >
      <div className="max-w-md w-full rounded-2xl border border-slate-200 bg-white p-6 text-center">
        {status === "running" ? (
          <>
            <Loader2
              size={28} className="animate-spin mx-auto mb-3 text-slate-600"
              data-testid="homeworks-callback-running"
            />
            <div className="text-sm text-slate-700">
              Completing Homeworks OAuth handshake…
            </div>
          </>
        ) : null}
        {status === "ok" ? (
          <>
            <ShieldCheck
              size={28} className="mx-auto mb-3"
              style={{ color: "#166534" }}
              data-testid="homeworks-callback-ok"
            />
            <div className="text-sm font-bold text-slate-900 mb-1">
              Homeworks connected
            </div>
            <div className="text-xs text-slate-500">
              Redirecting back to the integration page…
            </div>
          </>
        ) : null}
        {status === "error" ? (
          <>
            <AlertTriangle
              size={28} className="mx-auto mb-3"
              style={{ color: "#7F1D1D" }}
              data-testid="homeworks-callback-error"
            />
            <div className="text-sm font-bold text-slate-900 mb-1">
              Handshake failed
            </div>
            <div className="text-xs text-slate-500 mb-4">
              Reason: <code data-testid="homeworks-callback-reason">{reason || "unknown"}</code>
            </div>
            <button
              type="button"
              onClick={() => navigate("/admin/integrations/homeworks", { replace: true })}
              className="px-4 py-2 rounded-lg text-sm font-bold text-white"
              style={{ backgroundColor: "#0F172A" }}
              data-testid="homeworks-callback-back-btn"
            >
              Back to Homeworks integration
            </button>
          </>
        ) : null}
      </div>
    </div>
  );
}
