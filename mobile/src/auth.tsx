import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";
import { storage } from "@/src/utils/storage";
import { api, TOKEN_KEY, registerLogoutOn401 } from "@/src/api";
// Feb-2026 · Phase 1 offline foundation — persist a 24-hour expiry
// sidecar so ``getFreshCachedJwt()`` can decide if the tech is
// allowed to hydrate offline, and wipe the SQLite read cache on
// sign-out so a shared device doesn't leak the previous user's
// route to the next one.
import {
  persistJwtExpiry, clearJwtExpiry,
} from "@/src/lib/offline/jwtCache";
import { wipeCache, initCache } from "@/src/lib/offline/cache";
import { writeThroughMe } from "@/src/lib/offline/apiCache";
import { clearTechnicianIdCache } from "@/lib/technicianResolver";
import { clearAllCache as clearAllReadCache } from "@/src/services/readCache";

export type User = {
  id: string;
  email: string;
  role: "admin" | "technician" | "customer";
  name: string;
  avatar?: string;
  technician_id?: string | null;
  customer_id?: string | null;
  department?: string | null;
  /** TD-64 · BE-resolved (users.department → technicians.department). */
  effective_department?: string | null;
  /** TD-64 · single source of truth for Time Clock visibility. */
  show_time_clock?: boolean;
};

type AuthCtx = {
  user: User | null;
  loading: boolean;
  isImpersonating: boolean;
  impersonatorName: string;
  login: (email: string, password: string) => Promise<any>;
  signup: (payload: { name: string; email: string; password: string; phone?: string; address?: string }) => Promise<void>;
  logout: () => Promise<void>;
  startImpersonation: (customerId: string) => Promise<void>;
  stopImpersonation: () => Promise<void>;
  finalizeAccountChoice: (choiceToken: string, accountId: string) => Promise<any>;
  /** Re-reads `/auth/me` and merges it over the cached user (web auth.jsx parity). */
  refreshUser: () => Promise<void>;
};

const Ctx = createContext<AuthCtx>({} as AuthCtx);
const USER_KEY = "pool_crm_user";
const IMP_KEY = "pool_crm_impersonation";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [isImpersonating, setIsImpersonating] = useState(false);
  const [impersonatorName, setImpersonatorName] = useState("");
  const refreshing = useRef<Promise<void> | null>(null);
  const userRef = useRef<User | null>(null);
  userRef.current = user;

  // Clock-in gate regression · Oct-2026 — the cached user was never
  // re-read after login, so a server-side department change (e.g. an
  // admin moving a tech to `pool_tech`) never reached the gate until
  // re-login. Mirrors web auth.jsx `/auth/me` self-heal. Network / 5xx
  // errors keep the cached user (offline-safe); 401 is handled by the
  // api layer's logout callback.
  const refreshUser = useCallback(async () => {
    if (refreshing.current) return refreshing.current;
    refreshing.current = (async () => {
      try {
        const token = await storage.secureGet<string>(TOKEN_KEY, "");
        if (!token) return;
        const fresh: any = await api.get("/auth/me");
        if (!fresh || !fresh.id) return;
        if (!(await storage.secureGet<string>(TOKEN_KEY, ""))) return; // logged out mid-flight
        let next: any = null;
        const prev: any = userRef.current;
        if (prev && prev.id === fresh.id) {
          const merged = { ...prev, ...fresh };
          if (JSON.stringify(merged) !== JSON.stringify(prev)) next = merged;
        }
        if (!next) return;
        userRef.current = next;
        setUser(next);
        await storage.setItem(USER_KEY, JSON.stringify(next));
      } catch {
        /* keep cached user */
      } finally {
        refreshing.current = null;
      }
    })();
    return refreshing.current;
  }, []);

  useEffect(() => {
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active") refreshUser();
    });
    return () => sub.remove();
  }, [refreshUser]);

  useEffect(() => {
    (async () => {
      // Boot-time schema init — safe/idempotent; the cache helpers
      // also lazy-init but doing it once at boot avoids a first-call
      // stall on the schedule screen.
      initCache().catch(() => {});
      const stored = await storage.getItem<string>(USER_KEY, "");
      const token = await storage.secureGet<string>(TOKEN_KEY, "");
      if (stored && token) {
        try {
          const parsed = JSON.parse(stored);
          userRef.current = parsed;
          setUser(parsed);
        } catch {}
        // Background self-heal of stale role/department (non-blocking).
        refreshUser();
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
  }, [refreshUser]);

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

  // ── Multi-account choice flow (Task 4 · Feb 2026) ──────────────
  // When backend returns `multi_account_choice_required`, we do NOT
  // persist anything. The caller (login.tsx) gets a `kind: "choice"`
  // return and renders the account picker inline.
  type LoginResult =
    | { kind: "success" }
    | { kind: "choice"; email: string; choices: any[]; choice_token: string }
    | { kind: "password_reset_required"; reset_token: string; user_id: string; token_ttl_minutes: number; email: string };

  const login = async (email: string, password: string): Promise<LoginResult> => {
    const res = await api.post("/auth/login", { email, password });

    if (res && res.status === "multi_account_choice_required") {
      return {
        kind: "choice",
        email: res.email,
        choices: res.choices || [],
        choice_token: res.choice_token,
      };
    }

    // Temp password fork — user must set a permanent password before
    // receiving an access_token.
    if (res && res.status === "password_reset_required") {
      return {
        kind: "password_reset_required",
        reset_token: res.reset_token,
        user_id: res.user_id,
        token_ttl_minutes: res.token_ttl_minutes || 15,
        email,
      };
    }

    await storage.secureSet(TOKEN_KEY, res.access_token);
    await storage.setItem(USER_KEY, JSON.stringify(res.user));
    await persistJwtExpiry().catch(() => {});
    await writeThroughMe(res.user).catch(() => {});
    await clearImpersonation();
    userRef.current = res.user;
    setUser(res.user);
    // TD-64 · the login payload lacks effective_department / show_time_clock;
    // pull /auth/me now so Time Clock visibility is BE-authoritative at once.
    refreshUser();
    return { kind: "success" };
  };

  const finalizeAccountChoice = async (choiceToken: string, accountId: string): Promise<LoginResult> => {
    const res = await api.post("/auth/login/select-account", {
      choice_token: choiceToken,
      account_id: accountId,
    });

    // Temp password fork after account selection.
    if (res && res.status === "password_reset_required") {
      return {
        kind: "password_reset_required",
        reset_token: res.reset_token,
        user_id: res.user_id,
        token_ttl_minutes: res.token_ttl_minutes || 15,
        email: "", // email not returned by select-account; caller must supply
      };
    }

    await storage.secureSet(TOKEN_KEY, res.access_token);
    await storage.setItem(USER_KEY, JSON.stringify(res.user));
    await persistJwtExpiry().catch(() => {});
    await writeThroughMe(res.user).catch(() => {});
    await clearImpersonation();
    userRef.current = res.user;
    setUser(res.user);
    // TD-64 · the login payload lacks effective_department / show_time_clock;
    // pull /auth/me now so Time Clock visibility is BE-authoritative at once.
    refreshUser();
    return { kind: "success" };
  };

  const signup = async (payload: { name: string; email: string; password: string; phone?: string; address?: string }) => {
    const res = await api.post("/auth/signup", payload);
    await storage.secureSet(TOKEN_KEY, res.access_token);
    await storage.setItem(USER_KEY, JSON.stringify(res.user));
    await persistJwtExpiry().catch(() => {});
    await writeThroughMe(res.user).catch(() => {});
    await clearImpersonation();
    setUser(res.user);
  };

  const logout = async () => {
    await storage.secureRemove(TOKEN_KEY);
    await storage.removeItem(USER_KEY);
    // Feb-2026 · Phase 1 offline — wipe the SQLite read cache + JWT
    // expiry sidecar so the next tech logging in on a shared device
    // cannot see the previous tech's route from cache.
    await clearJwtExpiry().catch(() => {});
    await wipeCache().catch(() => {});
    // Phase 1 Offline Read — purge the read_cache (job bootstraps, hydration meta).
    await clearAllReadCache().catch(() => {});
    clearTechnicianIdCache();
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
      value={{ user, loading, isImpersonating, impersonatorName, login, finalizeAccountChoice, signup, logout, startImpersonation, stopImpersonation, refreshUser }}
    >
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);
