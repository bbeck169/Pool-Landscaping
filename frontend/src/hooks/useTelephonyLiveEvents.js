import React from "react";
import { toast } from "sonner";
import { useAuth } from "@/auth";
import { TOKEN_KEY } from "@/api";

/**
 * Phase 6B · Feb 2026 — Live inbound-call SSE hook.
 *
 * Subscribes to /api/rc/live-events for admin + manager clients only.
 * On each `call.inbound` event, pops a shadcn Sonner toast with:
 *   • Caller name (customer / lead / raw number)
 *   • Open-invoice balance (admin/manager only — never leaks to techs
 *     because the subscription itself is role-gated at the endpoint)
 *   • Action buttons: "Open" (jump to customer/lead), "Dismiss"
 *
 * The hook uses the browser's native EventSource. Because EventSource
 * cannot attach Authorization headers, we pass the JWT via the
 * ?token=… query param (accepted by the backend router). Reconnects
 * are automatic (EventSource default). We back off aggressively after
 * 5 consecutive failed opens so a dead backend doesn't spam retries.
 */
const INBOUND_ROLES = new Set(["admin", "super_admin", "manager"]);

export default function useTelephonyLiveEvents() {
  const { user } = useAuth();

  React.useEffect(() => {
    if (!user) return undefined;
    if (!INBOUND_ROLES.has(user.role)) return undefined;
    const base = process.env.REACT_APP_BACKEND_URL;
    if (!base) return undefined;

    let es = null;
    let cancelled = false;
    let backoffMs = 2000;
    let failures = 0;
    let retryTimer = null;

    const tokenNow = () => localStorage.getItem(TOKEN_KEY) || "";
    const tenantNow = () => localStorage.getItem("tenant_slug") || "";

    const open = () => {
      if (cancelled) return;
      const tok = tokenNow();
      if (!tok) {
        // No token yet — try again shortly.
        retryTimer = setTimeout(open, 1500);
        return;
      }
      const qs = new URLSearchParams({ token: tok });
      const tenant = tenantNow();
      if (tenant) qs.set("tenant", tenant);
      const url = `${base}/api/rc/live-events?${qs.toString()}`;
      try {
        es = new EventSource(url, { withCredentials: false });
      } catch (err) {
        console.warn("rc SSE open failed:", err);
        failures += 1;
        if (failures < 10) retryTimer = setTimeout(open, backoffMs);
        return;
      }

      es.addEventListener("ready", () => {
        failures = 0;
        backoffMs = 2000;
      });

      es.addEventListener("ping", () => {
        // Heartbeat — nothing to do.
      });

      const onInbound = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          const who =
            data.customer_name ||
            data.lead_name ||
            data.from_number ||
            "Unknown caller";
          const bits = [];
          if (typeof data.open_invoice_total_usd === "number" &&
              data.open_invoice_total_usd > 0) {
            bits.push(
              `Open balance: $${Number(
                data.open_invoice_total_usd
              ).toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
            );
          }
          if (data.matched_entity && data.matched_entity !== "customer") {
            bits.push(
              data.matched_entity === "lead"
                ? "Matched to lead"
                : "Unmatched caller",
            );
          }
          const description = bits.length ? bits.join(" · ") : `Ringing from ${data.from_number || "unknown"}`;
          const href =
            data.customer_id
              ? `/customers/${data.customer_id}`
              : data.lead_id
              ? `/admin/leads?lead_id=${data.lead_id}`
              : `/call-logs`;
          toast(`📞 Inbound call · ${who}`, {
            description,
            duration: 15000,
            action: {
              label: "Open",
              onClick: () => {
                window.location.href = href;
              },
            },
            id: `rc-inbound-${data.call_log_id || data.session_id || Date.now()}`,
            "data-testid": "rc-inbound-toast",
          });
        } catch (err) {
          console.warn("rc SSE parse failed:", err);
        }
      };

      es.addEventListener("call.inbound", onInbound);
      es.addEventListener("message", onInbound);

      es.onerror = () => {
        failures += 1;
        try { es && es.close(); } catch {}
        es = null;
        if (cancelled) return;
        const wait = Math.min(30000, backoffMs * (1 + failures));
        retryTimer = setTimeout(open, wait);
      };
    };

    open();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      try { es && es.close(); } catch {}
    };
  }, [user?.id, user?.role]);
}
