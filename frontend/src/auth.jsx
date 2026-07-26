import React, { createContext, useContext, useEffect, useState } from "react";
import { api, TOKEN_KEY } from "@/api";

const USER_KEY = "user";
const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    const stored = localStorage.getItem(USER_KEY);
    if (token && stored) {
      try {
        setUser(JSON.parse(stored));
      } catch {
        localStorage.removeItem(USER_KEY);
      }
      // Feb-2026 · self-heal against a stale localStorage user object
      // (e.g., when a user's role is promoted server-side while their
      // session is still live). Fires ``/auth/me`` in the background —
      // if the response comes back with a fresher record we swap it in.
      // On any failure we leave the cached copy in place so we don't
      // flap the guards during a transient blip.
      (async () => {
        try {
          const fresh = await api.get("/auth/me");
          if (fresh && fresh.id) {
            localStorage.setItem(USER_KEY, JSON.stringify(fresh));
            setUser(fresh);
          }
        } catch { /* keep cached copy */ }
      })();
    }
    setLoading(false);
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
