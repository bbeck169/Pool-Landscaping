/**
 * Phase I1.5.c · Feb-2026 — useTenantTheme hook + provider.
 *
 * Fetches ``GET /api/tenants/me/theme`` once at app mount, exposes
 * a stable ``{ theme, isLoading, error, refetch, applyOverride }``
 * shape via context, and writes every slot to
 * ``document.documentElement`` as a CSS custom property.
 *
 * Consumers:
 *   * ``useTenantTheme()`` — for React components that want the
 *     full theme object or a refetch trigger (e.g. the theme editor
 *     in ``settings/ThemeSettings.jsx`` calls ``refetch()`` on save
 *     success so the app re-skins in place).
 *   * ``tenantCssVar(...)`` from ``@/theme/tenantVars`` — for
 *     surfaces that want tenant overrides but don't need a
 *     subscription (inline styles).
 *
 * Contract:
 *   * ``theme`` is always defined (falls back to the client-side
 *     ``default`` preset before the API resolves and on error).
 *   * ``applyOverride(next)`` optimistically swaps the working
 *     theme so the editor's Save handler can trigger the reskin
 *     without waiting for the follow-up GET. Idempotent.
 *   * ``refetch()`` re-runs GET (invalidates the local cache).
 *
 * Public / auth routes that render outside ``<TenantThemeProvider>``
 * fall through to ``useTenantTheme()``'s default context value —
 * they see the ``default`` preset with ``isLoading=false``.
 */
import React from "react";

import { api } from "@/api";
import { useAuth } from "@/auth";
import { getClientPreset } from "@/theme/presets";
import { writeTenantCssVars, clearTenantCssVars } from "@/theme/tenantVars";


const DEFAULT_STATE = Object.freeze({
  theme: null,
  isLoading: false,
  error: null,
});


const TenantThemeContext = React.createContext({
  ...DEFAULT_STATE,
  theme: getClientPreset("default"),
  refetch: async () => {},
  applyOverride: () => {},
});


/**
 * Runs a GET / applies CSS vars / returns the theme. Kept as a
 * module-level helper so tests can call it directly if they want.
 */
async function _fetchTenantTheme() {
  try {
    const theme = await api.get("/tenants/me/theme");
    return { theme, error: null };
  } catch (e) {
    // Fall through to default — either the endpoint 404'd, the
    // network failed, or the caller is on a public route without
    // a session. Never break the render.
    return { theme: getClientPreset("default"), error: e };
  }
}


/**
 * Wrap the authenticated app tree with this provider. Public
 * routes (``/login``, ``/portal/login``, ``/privacy-policy`` etc.)
 * render outside it; ``useTenantTheme()`` in those contexts
 * returns the default fallback with no fetch.
 */
export function TenantThemeProvider({ children, enabled = true }) {
  const [state, setState] = React.useState(() => ({
    theme: getClientPreset("default"),
    isLoading: enabled,
    error: null,
  }));

  // Auth-aware refetch: on the login → dashboard transition the
  // provider mounted before the user had a token, so the initial
  // fetch 401'd and fell back to the default preset. Re-run when
  // ``user`` transitions to non-null so the tenant palette lands
  // as soon as the dashboard renders.
  //
  // ``useAuth()`` returns ``null`` outside an ``<AuthProvider>``
  // (e.g. the hook contract tests) — treat that as "always fetch"
  // so provider-only tests keep working without a mock auth tree.
  const auth = useAuth();
  const authKey = auth === null ? "__no-auth-provider__" : (auth?.user?.id ?? null);

  const alive = React.useRef(true);
  React.useEffect(() => {
    // ``alive`` guards ``setState`` after ``await`` — React
    // StrictMode double-mounts the provider in development, which
    // flips ``alive.current`` to ``false`` on the first unmount.
    // Restore it here so post-mount ``refetch()`` calls still
    // reach ``setState`` + ``applyToDom``.
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const applyToDom = React.useCallback((theme) => {
    if (typeof document === "undefined") return;
    if (!theme) return;
    writeTenantCssVars(document.documentElement, theme);
  }, []);

  const refetch = React.useCallback(async () => {
    if (!enabled) return;
    setState((s) => ({ ...s, isLoading: true }));
    const { theme, error } = await _fetchTenantTheme();
    if (!alive.current) return;
    setState({ theme, isLoading: false, error });
    applyToDom(theme);
  }, [enabled, applyToDom]);

  const applyOverride = React.useCallback((next) => {
    if (!next) return;
    setState((s) => ({ ...s, theme: next, error: null }));
    applyToDom(next);
  }, [applyToDom]);

  // Initial fetch on mount + re-fetch when the user signs in /
  // switches accounts. On sign-out (``user`` → null), clear the
  // overlay so the next tenant's palette doesn't bleed through.
  React.useEffect(() => {
    if (!enabled) {
      if (typeof document !== "undefined") {
        clearTenantCssVars(document.documentElement);
      }
      return;
    }
    if (authKey === null) {
      // Signed-out: clear vars but keep the default preset in
      // state so consumers still get a well-formed shape.
      if (typeof document !== "undefined") {
        clearTenantCssVars(document.documentElement);
      }
      setState({
        theme: getClientPreset("default"),
        isLoading: false,
        error: null,
      });
      return;
    }
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, authKey]);

  // Phase I1.5.c.fix.2 · Feb-2026 — belt-and-suspenders CSS-var
  // writer. Every prior code path (mount fetch, refetch,
  // applyOverride) already calls ``applyToDom`` inline, but this
  // effect guarantees the DOM stays in sync with ``state.theme``
  // on ANY future mutation path (StrictMode double-mount,
  // component-tree-reparent, remote-hot-reload of the provider,
  // future ``setState`` callers). Skipped when signed-out so the
  // sign-out branch's ``clearTenantCssVars`` isn't immediately
  // undone (empty CSS vars fall back to the ``#1B1F5C`` etc.
  // fallbacks in ``index.css`` — matches the pre-refactor pixels
  // on the login route).
  React.useEffect(() => {
    if (!enabled) return;
    if (authKey === null) return;
    if (typeof document === "undefined") return;
    if (!state.theme) return;
    writeTenantCssVars(document.documentElement, state.theme);
  }, [enabled, authKey, state.theme]);

  const value = React.useMemo(() => ({
    ...state,
    refetch,
    applyOverride,
  }), [state, refetch, applyOverride]);

  return (
    <TenantThemeContext.Provider value={value}>
      {children}
    </TenantThemeContext.Provider>
  );
}


export function useTenantTheme() {
  return React.useContext(TenantThemeContext);
}


// Re-export the helper so consumers can grab the CSS-var API
// from a single import site.
export { tenantCssVar } from "@/theme/tenantVars";
