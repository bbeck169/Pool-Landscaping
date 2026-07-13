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
    setUser(null);
  };

  const token = () => localStorage.getItem(TOKEN_KEY) || "";
  const role = user?.role ?? null;

  return (
    <AuthCtx.Provider
      value={{ user, role, loading, token, login, signup, me, logout }}
    >
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
