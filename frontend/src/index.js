import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
// Phase D3 · Feb 2026 — i18n bootstrap runs BEFORE `<App />` mounts
// so the first render already sees the resolved locale.
import "@/i18n";
import App from "@/App";
// K37 · Top-level portal error boundary. Wraps `<App />` inside
// `<StrictMode>` so it catches the pre-mount K13 impersonation
// preamble side-effects, every public deep-link route, and any
// top-level provider throw. `label="app-root"` disambiguates this
// mount from the nested `portal-shell` mount in `ProtectedShell`
// when triaging `/api/client-errors` rows.
import PortalErrorBoundary from "@/components/errors/PortalErrorBoundary";

// Phase K13 · Feb-2026 — portal impersonation token bootstrap.
// Runs BEFORE React mounts so ``AuthProvider``'s initial
// ``/auth/me`` fetch already sees the impersonation token via
// ``sessionStorage`` and returns the target customer's identity.
// Doing this inside a React ``useEffect`` was too late — the
// auth-context bootstrap kicked off first with the admin's
// localStorage token and produced a flash of admin UI.
(() => {
  try {
    const params = new URLSearchParams(window.location.search || "");
    const impTok = params.get("impersonation_token");
    if (impTok) {
      window.sessionStorage.setItem("portal_token", impTok);
      params.delete("impersonation_token");
      const qs = params.toString();
      const cleanUrl = window.location.pathname + (qs ? `?${qs}` : "")
        + (window.location.hash || "");
      window.history.replaceState({}, "", cleanUrl);
      // Decode the JWT payload (no verification — display only) and
      // seed ``localStorage["user"]`` with a minimal customer shape so
      // ``_readCachedUserSync`` returns a customer identity synchronously.
      // Without this seed, AuthProvider hydrates from the admin cache
      // and route guards / TosGate fire against the admin identity
      // BEFORE the async ``/auth/me`` completes with the impersonation
      // token — causing a redirect to ``/``.  ``/auth/me`` will
      // overwrite this seed with the full customer payload once it
      // returns.
      const parts = impTok.split(".");
      if (parts.length >= 2) {
        const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
        const padded = b64 + "=".repeat((4 - b64.length % 4) % 4);
        try {
          const payload = JSON.parse(atob(padded));
          if (payload && payload.role === "customer") {
            const seed = {
              id: payload.sub,
              role: "customer",
              customer_id: payload.customer_id || null,
              name: payload.name || "Customer",
              email: payload.email || "",
              tenant_id: payload.tenant_id || null,
              is_impersonated: true,
              impersonator_id: payload.act ? payload.act.sub : null,
            };
            window.localStorage.setItem("user", JSON.stringify(seed));
          }
        } catch { /* JWT payload not JSON — leave admin cache alone */ }
      }
    }
  } catch { /* ignore — best-effort pre-mount hook */ }
})();

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <PortalErrorBoundary label="app-root">
      <App />
    </PortalErrorBoundary>
  </React.StrictMode>,
);
