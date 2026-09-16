import React, { createContext, useContext, useEffect, useState } from "react";
import { api, TOKEN_KEY } from "@/api";

const USER_KEY = "user";
const AuthCtx = createContext(null);

/** Feb-2026 · Fix 2 — bootstrap race helper.
 *  Read the cached user object out of localStorage synchronously so
 *  the very first render already sees ``user != null`` when a token
 *  is present. Previously the effect ran AFTER paint and any
 *  auth-guarded route could flash to /login before storage was read.
 *  Playwright's ``page.evaluate(localStorage.setItem…)`` before
 *  ``page.goto`` now works end-to-end.
 */
function _readCachedUserSync() {
  if (typeof window === "undefined") return null;
  try {
    const token = window.localStorage.getItem(TOKEN_KEY);
    const stored = window.localStorage.getItem(USER_KEY);
    if (!token || !stored) return null;
    return JSON.parse(stored);
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  // Initial state is derived from localStorage synchronously — the
  // useEffect below now ONLY runs the ``/auth/me`` self-heal, it no
  // longer bootstraps ``user``.
  const [user, setUser] = useState(() => _readCachedUserSync());
  const [loading, _setLoading] = useState(false);

  useEffect(() => {
    // If we bootstrapped from cache, background-refresh /auth/me so
    // stale role/tenant changes get picked up. Same behavior as
    // before, just decoupled from the initial-mount race.
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) return;
    (async () => {
      try {
        const fresh = await api.get("/auth/me");
        if (fresh && fresh.id) {
          localStorage.setItem(USER_KEY, JSON.stringify(fresh));
          setUser(fresh);
          // Phase D3 · Feb 2026 — hydrate the i18n locale from the
          // authoritative user record so the user's choice follows
          // them across browsers / devices. Wrapped in a lazy import
          // so a broken i18n bundle never bounces the auth boot.
          if (fresh.locale && ["en", "es", "fr"].includes(fresh.locale)) {
            try {
              const stored = localStorage.getItem("lang");
              if (stored !== fresh.locale) {
                localStorage.setItem("lang", fresh.locale);
                const mod = await import("@/i18n");
                await mod.default.changeLanguage(fresh.locale);
              }
            } catch { /* i18n hydration is best-effort */ }
          }
        }
      } catch (e) {
        // Feb-2026 · Zombie-session hotfix — if /auth/me itself returned
        // 401 with a known auth-token failure, clear the cached user
        // right now instead of silently keeping a dead session. Other
        // errors (network, 5xx) still get swallowed for offline
        // resilience — matches prior behavior.
        const status = e?.status;
        const msg = (e?.message || "").toLowerCase();
        const isAuthTokenFailure =
          status === 401 && (
            msg === "token expired" ||
            msg === "invalid token" ||
            msg === "account_deleted" ||
            msg === "account is deactivated"
          );
        if (isAuthTokenFailure) {
          // api.js has already fired the interceptor + redirect at
          // this point; local state cleanup keeps the tree consistent
          // for the microtask before the location.assign takes effect.
          logout();
        }
        /* else: keep cached copy */
      }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- logout() is stable within provider scope; effect must run once on mount.

  const persist = (accessToken, u) => {
    localStorage.setItem(TOKEN_KEY, accessToken);
    localStorage.setItem(USER_KEY, JSON.stringify(u));
    setUser(u);
  };

  const login = async (email, password) => {
    const res = await api.post("/auth/login", { email, password });
    // Feb-2026 · Task 4 · Option A account chooser.
    // When the backend returns ``multi_account_choice_required`` the
    // FE must NOT persist anything — no access_token was issued.
    // We bubble the chooser payload up so ``Login.jsx`` can render
    // the picker inline.  Downstream callers should branch on the
    // returned ``kind``:
    //   * ``kind: "success"``  → user is now signed in (persisted).
    //   * ``kind: "choice"``   → render the account chooser using
    //                             ``choices`` + ``choice_token``.
    if (res && res.status === "multi_account_choice_required") {
      return {
        kind: "choice",
        email: res.email,
        choices: res.choices || [],
        choice_token: res.choice_token,
      };
    }
    // Feb-2026 · Customer temp password flow — backend returns
    // ``password_reset_required`` when the matched user carries
    // ``must_change_password_on_next_login=True``. No access token
    // is issued; the FE must redirect to the reset-password page
    // with the mid-flow token pre-filled.
    if (res && res.status === "password_reset_required") {
      return {
        kind: "reset_required",
        reset_token: res.reset_token,
        user_id: res.user_id,
        token_ttl_minutes: res.token_ttl_minutes,
        // Feb-2026 · P0 loop fix — bubble the backend-supplied role
        // so the Login page can defense-in-depth gate the redirect.
        // Only ``customer`` should ever trigger the temp-password
        // reset UX; a non-customer payload is treated as unexpected.
        role: res.role,
      };
    }
    persist(res.access_token, res.user);
    return { kind: "success" };
  };

  const finalizeAccountChoice = async (choiceToken, accountId) => {
    // Feb-2026 · Task 4 · Option A — completes a login started by
    // the chooser branch above.  Server issues the normal auth
    // response for the picked record; we persist identically to a
    // single-record login.  Any 401/403 propagates so ``Login.jsx``
    // can show it inline (expired choice_token, bogus account_id,
    // soft-deleted, deactivated, etc.).
    const res = await api.post("/auth/login/select-account", {
      choice_token: choiceToken,
      account_id: accountId,
    });
    if (res && res.status === "password_reset_required") {
      return {
        kind: "reset_required",
        reset_token: res.reset_token,
        user_id: res.user_id,
        token_ttl_minutes: res.token_ttl_minutes,
        role: res.role,
      };
    }
    persist(res.access_token, res.user);
    return { kind: "success" };
  };

  const signup = async (payload) => {
    const res = await api.post("/auth/signup", payload);
    persist(res.access_token, res.user);
  };

  // Feb-2026 · P0 loop fix — the reset-password page calls this
  // when the ``/auth/reset-password`` response carries a fresh
  // ``access_token`` + ``user`` (the auto-login envelope). We
  // persist identically to a normal login so the caller can drop
  // straight into the portal home, no re-authentication needed.
  const applyResetAutoLogin = (accessToken, u) => {
    if (!accessToken || !u) return false;
    persist(accessToken, u);
    return true;
  };

  const me = async () => {
    const u = await api.get("/auth/me");
    localStorage.setItem(USER_KEY, JSON.stringify(u));
    setUser(u);
    return u;
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem("tenant_slug");
    localStorage.removeItem("tenant_name");
    setUser(null);
  };

  const token = () => localStorage.getItem(TOKEN_KEY) || "";
  const role = user?.role ?? null;

  return (
    <AuthCtx.Provider
      value={{ user, role, loading, token, login, finalizeAccountChoice, signup, applyResetAutoLogin, me, logout, setUser }}
    >
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
