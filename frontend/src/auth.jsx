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
  const [loading, setLoading] = useState(false);

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
        }
      } catch { /* keep cached copy */ }
    })();
  }, []);

  const persist = (accessToken, u) => {
    localStorage.setItem(TOKEN_KEY, accessToken);
    localStorage.setItem(USER_KEY, JSON.stringify(u));
    setUser(u);
  };

  const login = async (email, password) => {
    const res = await api.post("/auth/login", { email, password });
    persist(res.access_token, res.user);
  };

  const signup = async (payload) => {
    const res = await api.post("/auth/signup", payload);
    persist(res.access_token, res.user);
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
      value={{ user, role, loading, token, login, signup, me, logout, setUser }}
    >
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
