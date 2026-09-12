/**
 * Feb-2026 · Theme Refresh — tenant branding hooks.
 *
 * Two lightweight hooks used across the estimate / quote / invoice
 * surfaces to fetch the Business Settings shipped in the previous
 * phase without threading tenant data through prop chains.
 *
 *   useBusinessSettings()  — admin surface, reads the admin
 *                            endpoint (returns full stored + effective).
 *   useTenantBranding(token) — customer surface, reads the public
 *                              magic-link endpoint (returns only the
 *                              customer-safe subset).
 *
 * Both surfaces return the same shape:
 *   { branding, loading, error, reload }
 *
 * where ``branding`` is either the ``effective`` block (admin) or
 * the redacted customer subset (magic-link). ``brand_primary_hex``
 * and ``brand_secondary_hex`` fall back to sensible defaults so
 * consumers can render without null-guards.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "@/api";

const DEFAULT_PRIMARY_HEX = "#0B4A6F";
const DEFAULT_SECONDARY_HEX = "#F97316";

function _withDefaults(b) {
  if (!b || typeof b !== "object") {
    return {
      brand_primary_hex: DEFAULT_PRIMARY_HEX,
      brand_secondary_hex: DEFAULT_SECONDARY_HEX,
    };
  }
  return {
    ...b,
    brand_primary_hex: b.brand_primary_hex || DEFAULT_PRIMARY_HEX,
    brand_secondary_hex: b.brand_secondary_hex || DEFAULT_SECONDARY_HEX,
  };
}


export function useBusinessSettings(opts) {
  const skip = Boolean(opts && opts.skip);
  const [state, setState] = useState({
    branding: _withDefaults(null),
    loading: !skip,
    error: null,
  });
  const reload = useCallback(async () => {
    if (skip) {
      setState({
        branding: _withDefaults(null),
        loading: false,
        error: null,
      });
      return;
    }
    setState((s) => ({ ...s, loading: true }));
    try {
      const r = await api.get("/tenants/me/business-settings");
      setState({
        branding: _withDefaults(r?.effective || null),
        loading: false,
        error: null,
      });
    } catch (e) {
      setState({
        branding: _withDefaults(null),
        loading: false,
        error: e,
      });
    }
  }, [skip]);
  useEffect(() => { reload(); }, [reload]);
  return { ...state, reload };
}


export function useTenantBranding(token) {
  const [state, setState] = useState({
    branding: _withDefaults(null),
    loading: Boolean(token),
    error: null,
  });
  const reload = useCallback(async () => {
    if (!token) {
      setState({
        branding: _withDefaults(null),
        loading: false,
        error: null,
      });
      return;
    }
    setState((s) => ({ ...s, loading: true }));
    try {
      const r = await api.get(
        `/portal/tenant/branding?token=${encodeURIComponent(token)}`,
      );
      setState({
        branding: _withDefaults(r?.branding || null),
        loading: false,
        error: null,
      });
    } catch (e) {
      // Public endpoint may 401 on bad tokens — fall back silently
      // so the estimate page still renders with default colours.
      // [DEBUG-MAGIC-LINK-RCA — REMOVE AFTER ROOT CAUSE FOUND]
      // Console-only. This hook has no UI error surface, so we log
      // the failure with redacted context to correlate with the
      // EstimateView error surface. See
      // /app/memory/DIAG_MAGIC_LINK_401_RCA.md for removal steps.
      try {
        const _tok = String(token || "");
        const _bodyRaw = typeof e?.data === "string"
          ? e.data : JSON.stringify(e?.data || "");
        const _body = _bodyRaw
          .replace(/Bearer\s+\S+/gi, "Bearer <redacted>")
          .replace(
            /[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/g,
            "<jwt-redacted>",
          )
          .slice(0, 500);
        const _cookieNames = (typeof document !== "undefined")
          ? (document.cookie || "").split(";")
              .map((c) => c.trim().split("=")[0])
              .filter(Boolean).join("; ")
          : "";
        const _sw = (typeof navigator !== "undefined" && navigator.serviceWorker)
          ? (navigator.serviceWorker.controller ? "sw-controlled" : "no-controller")
          : "no-sw-api";
        // eslint-disable-next-line no-console
        console.error("[magic-link-debug:branding]", {
          outbound_url: `/api/portal/tenant/branding?token=<jwt:len=${_tok.length},head=${_tok.slice(0,6)},tail=${_tok.slice(-6)}>`,
          response_status: e?.status == null ? "network" : String(e.status),
          response_body: _body,
          error_message: (e?.message || "").slice(0, 200),
          cookies: _cookieNames,
          sw_controller: _sw,
        });
      } catch { /* diag must never break the silent-fallback path */ }
      // [/DEBUG-MAGIC-LINK-RCA]
      setState({
        branding: _withDefaults(null),
        loading: false,
        error: e,
      });
    }
  }, [token]);
  useEffect(() => { reload(); }, [reload]);
  return { ...state, reload };
}


export const _BRANDING_DEFAULTS = {
  DEFAULT_PRIMARY_HEX,
  DEFAULT_SECONDARY_HEX,
};
