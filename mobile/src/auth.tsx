import React, { createContext, useContext, useEffect, useState } from "react";
import { storage } from "@/src/utils/storage";
import { api, TOKEN_KEY, registerLogoutOn401 } from "@/src/api";

export type User = {
  id: string;
  email: string;
  role: "admin" | "technician" | "customer";
  name: string;
  avatar?: string;
  technician_id?: string | null;
  customer_id?: string | null;
};

type AuthCtx = {
  user: User | null;
  loading: boolean;
  isImpersonating: boolean;
  impersonatorName: string;
  login: (email: string, password: string) => Promise<void>;
  signup: (payload: { name: string; email: string; password: string; phone?: string; address?: string }) => Promise<void>;
  logout: () => Promise<void>;
  startImpersonation: (customerId: string) => Promise<void>;
  stopImpersonation: () => Promise<void>;
};

const Ctx = createContext<AuthCtx>({} as AuthCtx);
const USER_KEY = "pool_crm_user";
const IMP_KEY = "pool_crm_impersonation";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [isImpersonating, setIsImpersonating] = useState(false);
  const [impersonatorName, setImpersonatorName] = useState("");

  useEffect(() => {
    (async () => {
      const stored = await storage.getItem<string>(USER_KEY, "");
      const token = await storage.secureGet<string>(TOKEN_KEY, "");
      if (stored && token) {
        try {
          setUser(JSON.parse(stored));
        } catch {}
        const imp = await storage.getItem<string>(IMP_KEY, "");
        if (imp) {
          try {
            const { name } = JSON.parse(imp);
            setIsImpersonating(true);
            setImpersonatorName(name || "Admin");
          } catch {}
        }
      }
      setLoading(false);
    })();
  }, []);

  // JWT soft-delete enforcement: register the 401 logout callback so
  // the API layer can kick the user out when the backend rejects a
  // soft-deleted user's token.
  useEffect(() => {
    registerLogoutOn401(() => {
      storage.secureRemove(TOKEN_KEY).catch(() => {});
      storage.removeItem(USER_KEY).catch(() => {});
      setUser(null);
    });
  }, []);

  const clearImpersonation = async () => {
    await storage.removeItem(IMP_KEY);
    setIsImpersonating(false);
    setImpersonatorName("");
  };

  const login = async (email: string, password: string) => {
    const res = await api.post("/auth/login", { email, password });
    await storage.secureSet(TOKEN_KEY, res.access_token);
    await storage.setItem(USER_KEY, JSON.stringify(res.user));
    await clearImpersonation();
    setUser(res.user);
  };

  const signup = async (payload: { name: string; email: string; password: string; phone?: string; address?: string }) => {
    const res = await api.post("/auth/signup", payload);
    await storage.secureSet(TOKEN_KEY, res.access_token);
    await storage.setItem(USER_KEY, JSON.stringify(res.user));
    await clearImpersonation();
    setUser(res.user);
  };

  const logout = async () => {
    await storage.secureRemove(TOKEN_KEY);
    await storage.removeItem(USER_KEY);
    await clearImpersonation();
    setUser(null);
  };

  const startImpersonation = async (customerId: string) => {
    const res = await api.post(`/admin/impersonate/${customerId}`, {});
    await storage.secureSet(TOKEN_KEY, res.access_token);
    await storage.setItem(USER_KEY, JSON.stringify(res.user));
    await storage.setItem(IMP_KEY, JSON.stringify({ name: res.impersonator_name || "Admin" }));
    setIsImpersonating(true);
    setImpersonatorName(res.impersonator_name || "Admin");
    setUser(res.user);
  };

  const stopImpersonation = async () => {
    try {
      const res = await api.post("/auth/revert-impersonation", {});
      await storage.secureSet(TOKEN_KEY, res.access_token);
      await storage.setItem(USER_KEY, JSON.stringify(res.user));
      await clearImpersonation();
      setUser(res.user);
    } catch {
      // Session likely expired — fall back to a full sign-out.
      await logout();
    }
  };

  return (
    <Ctx.Provider
      value={{ user, loading, isImpersonating, impersonatorName, login, signup, logout, startImpersonation, stopImpersonation }}
    >
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);
