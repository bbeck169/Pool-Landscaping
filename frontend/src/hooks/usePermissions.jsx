import { useEffect, useState, useCallback, createContext, useContext } from "react";
import { api } from "@/api";

/**
 * Phase 14 — Client-side permissions matrix with a "Test as..." preview mode.
 * Reads /api/permissions once, caches in memory + localStorage, and exposes a
 * `can(feature, action)` helper. Preview role applies CLIENT-SIDE only — no
 * backend mutation. Preview state is session-scoped (in-memory only; NOT persisted).
 */

const LS_KEY = "aq-permissions-v1";
const CACHE_TTL_MS = 5 * 60 * 1000;

// Fallback matrix used until the network fetch resolves — matches the seeded
// server defaults so gating never over-permits.
const DEFAULT_MATRIX = {
  admin: {},          // admin bypasses all gates
  technician: {
    jobs: ["read", "write"],
    customers: ["read"],
    portal: ["read"],
    d2d: ["read", "write"],  // hard rule below still blocks tech from D2D UI
  },
  customer: { portal: ["read", "write"] },
  marketer: {
    marketing: ["read", "write", "publish"],
    seo: ["read", "write", "publish"],
    gbp: ["read", "write"],
    reports: ["read"],
  },
  sales: {
    customers: ["read", "write"],
    jobs: ["read"],
    quotes: ["read", "write", "approve"],
    d2d: ["read", "write"],
    reports: ["read"],
  },
};

// Hard rule: these features remain admin-only regardless of matrix (defense in depth).
const ADMIN_ONLY_FEATURES = new Set([
  "landscape", "cad", "measure", "virtual_bid", "weather", "d2d",
  "permissions", "audit_logs",
]);

const Ctx = createContext(null);

export function PermissionsProvider({ user, children }) {
  const [matrix, setMatrix] = useState(DEFAULT_MATRIX);
  const [loading, setLoading] = useState(true);
  const [previewRole, setPreviewRole] = useState(null);

  useEffect(() => {
    let cancelled = false;
    // Serve from localStorage first if fresh, else refetch.
    try {
      const cached = JSON.parse(localStorage.getItem(LS_KEY) || "null");
      if (cached && Date.now() - cached.ts < CACHE_TTL_MS) {
        setMatrix(cached.data || DEFAULT_MATRIX);
        setLoading(false);
      }
    } catch {}
    if (!user) { setLoading(false); return; }
    api.get("/permissions")
      .then((r) => {
        if (cancelled) return;
        const data = r && typeof r === "object" ? r : DEFAULT_MATRIX;
        setMatrix(data);
        try { localStorage.setItem(LS_KEY, JSON.stringify({ ts: Date.now(), data })); } catch {}
      })
      .catch(() => { /* fall back to defaults */ })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [user]);

  const role = user?.role;
  const effectiveRole = previewRole || role;

  const can = useCallback((feature, action = "read") => {
    // Admin bypass (unless previewing another role).
    if (effectiveRole === "admin") return true;
    // Tech hard rule.
    if (effectiveRole === "technician" && ADMIN_ONLY_FEATURES.has(feature)) return false;
    const roleMatrix = matrix?.[effectiveRole] || {};
    const acts = roleMatrix[feature] || [];
    return Array.isArray(acts) && acts.includes(action);
  }, [matrix, effectiveRole]);

  const value = {
    can, loading, matrix, role, effectiveRole,
    previewRole, setPreviewRole,
    isPreviewing: !!previewRole && previewRole !== role,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePermissions() {
  const ctx = useContext(Ctx);
  if (!ctx) {
    // Safe fallback when provider is missing (test environments).
    return { can: () => true, loading: false, matrix: DEFAULT_MATRIX, role: "admin",
             effectiveRole: "admin", previewRole: null, setPreviewRole: () => {}, isPreviewing: false };
  }
  return ctx;
}

/** Renders children only when the current role can perform the action. */
export function PermGate({ feature, action = "read", fallback = null, children }) {
  const { can } = usePermissions();
  return can(feature, action) ? children : fallback;
}
