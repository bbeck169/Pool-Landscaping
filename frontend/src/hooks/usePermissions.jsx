import { useEffect, useState, useCallback, createContext, useContext } from "react";
import { api } from "@/api";

/**
 * Client-side permissions matrix + "Test as..." preview mode.
 *
 * Phase 14 shipped the base hook. Phase 29C extended it with:
 *   • Shape-tolerant `can()` — accepts both `{feature: "write"}` (server v1)
 *     and `{feature: ["read","write"]}` (server v2) matrix shapes so we don't
 *     silently over-deny when the API is upgraded.
 *   • `useRole()` alias so callers that only want the effective role don't have
 *     to spread the whole context.
 *   • `<Gate perm="…" [showForbidden]>` + `<Forbidden reason="…"/>` +
 *     `<RequirePermission perm="…">` for route-level guards.
 *   • `sessionStorage` persistence of the preview role — survives page reloads
 *     until the tab is closed. Deliberately session-scoped so a super-admin
 *     never accidentally leaves themselves in "preview as customer" across
 *     sessions.
 *   • `AVAILABLE_ROLES` — canonical list of roles the picker offers.
 *
 * The preview role is **UI-only**. All backend calls still carry the real
 * JWT, so RBAC on the server is unaffected; this is a "show me the app the
 * way a technician sees it" affordance, not a security bypass.
 */

const LS_KEY = "aq-permissions-v1";
const SS_PREVIEW_ROLE = "aq-preview-role-v1";
const CACHE_TTL_MS = 5 * 60 * 1000;

// Canonical roles the "Test as…" switcher offers. Kept in sync with the DB
// roles column + the seeded matrix. `super_admin` is included so admins can
// preview what super-admins see; `sales` / `marketer` are stub roles that
// exist in the matrix but have no seeded user — still useful for previews.
export const AVAILABLE_ROLES = [
  "super_admin",
  "admin",
  "marketer",
  "sales",
  "technician",
  "customer",
];

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

/**
 * Normalize a role's matrix value into an array of allowed actions.
 *
 * The `/api/permissions` endpoint has been observed returning two shapes:
 *   • `{"Customers": "write"}`         (single verb, PascalCase key)
 *   • `{"customers": ["read","write"]}` (verb list, snake_case key)
 *
 * We honor either and — since "write" implies "read" — expand accordingly.
 */
function normalizeActions(val) {
  if (Array.isArray(val)) return val;
  if (typeof val === "string" && val) {
    return val === "write" ? ["read", "write"]
         : val === "publish" ? ["read", "write", "publish"]
         : val === "approve" ? ["read", "write", "approve"]
         : [val];
  }
  return [];
}

/** Case-insensitive matrix lookup for a `(role, feature)` pair. */
function actionsFor(roleMatrix, feature) {
  if (!roleMatrix) return [];
  if (Object.prototype.hasOwnProperty.call(roleMatrix, feature)) {
    return normalizeActions(roleMatrix[feature]);
  }
  const lc = String(feature).toLowerCase();
  for (const [k, v] of Object.entries(roleMatrix)) {
    if (String(k).toLowerCase() === lc) return normalizeActions(v);
  }
  return [];
}

const Ctx = createContext(null);

export function PermissionsProvider({ user, children }) {
  const [matrix, setMatrix] = useState(DEFAULT_MATRIX);
  const [loading, setLoading] = useState(true);
  const [previewRole, setPreviewRoleRaw] = useState(() => {
    try { return sessionStorage.getItem(SS_PREVIEW_ROLE) || null; }
    catch { return null; }
  });

  const setPreviewRole = useCallback((r) => {
    setPreviewRoleRaw(r || null);
    try {
      if (r) sessionStorage.setItem(SS_PREVIEW_ROLE, r);
      else sessionStorage.removeItem(SS_PREVIEW_ROLE);
    } catch { /* incognito / disabled — in-memory only, no crash */ }
  }, []);

  useEffect(() => {
    let cancelled = false;
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
    // Real super-admins bypass everything, EVEN while previewing another role
    // — the whole point of "test as" is to see what the OTHER role sees, but
    // if we're previewing "customer" the check should honor the customer
    // matrix. So: super-admin bypass only applies when NOT previewing.
    const previewing = !!previewRole && previewRole !== role;
    if (!previewing && (role === "admin" || role === "super_admin")) return true;
    if (effectiveRole === "admin" || effectiveRole === "super_admin") return true;
    // Tech hard rule.
    if (effectiveRole === "technician" && ADMIN_ONLY_FEATURES.has(feature)) return false;
    const acts = actionsFor(matrix?.[effectiveRole], feature);
    return acts.includes(action);
  }, [matrix, effectiveRole, previewRole, role]);

  const value = {
    can, loading, matrix, role, effectiveRole,
    previewRole, setPreviewRole,
    isPreviewing: !!previewRole && previewRole !== role,
    // Only real admins (never techs previewing as admin) get the picker.
    canPreview: role === "admin" || role === "super_admin",
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePermissions() {
  const ctx = useContext(Ctx);
  if (!ctx) {
    // Safe fallback when provider is missing (test environments).
    return {
      can: () => true, loading: false, matrix: DEFAULT_MATRIX, role: "admin",
      effectiveRole: "admin", previewRole: null, setPreviewRole: () => {},
      isPreviewing: false, canPreview: false,
    };
  }
  return ctx;
}

/** Convenience — returns the effective role (real OR impersonated). */
export function useRole() {
  return usePermissions().effectiveRole;
}

/** Convenience — boolean per matrix key (accepts "feature.action" or plain feature). */
export function useCan(perm, action = "read") {
  const { can } = usePermissions();
  const [f, a] = String(perm || "").includes(".")
    ? String(perm).split(".", 2)
    : [perm, action];
  return can(f, a || "read");
}

/**
 * Renders children when the current effective role can perform the action.
 * When denied and `showForbidden` is true, renders a `<Forbidden>` block
 * with the given `reason`. Otherwise renders `fallback` (default: null).
 *
 *   <Gate perm="checks.write">          — silently hidden if denied
 *   <Gate perm="dispatch.write" showForbidden reason="Dispatcher role required">
 */
export function Gate({ perm, action = "read", showForbidden, reason, fallback = null, children }) {
  const allowed = useCan(perm, action);
  if (allowed) return children;
  if (showForbidden) return <Forbidden reason={reason || `You don't have permission to ${action} ${perm}.`} />;
  return fallback;
}

/**
 * Small inline "access denied" block. Route-level guards use it too; pages
 * can use it to replace a section that's been gated out.
 */
export function Forbidden({ reason, onHome }) {
  return (
    <div
      data-testid="forbidden-block"
      style={{
        padding: "24px",
        borderRadius: 12,
        border: "1px solid #FCA5A5",
        background: "#FEF2F2",
        color: "#991B1B",
        maxWidth: 520,
        margin: "24px auto",
      }}
    >
      <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 6 }} data-testid="forbidden-title">
        Access denied
      </div>
      <div style={{ fontSize: 13, lineHeight: 1.5 }} data-testid="forbidden-reason">
        {reason || "Your current role can't view this page."}
      </div>
      <button
        type="button"
        onClick={onHome || (() => { window.location.href = "/"; })}
        style={{
          marginTop: 12,
          padding: "6px 14px",
          borderRadius: 8,
          border: "1px solid #B45309",
          background: "#F59E0B",
          color: "#fff",
          fontWeight: 700,
          fontSize: 12,
          cursor: "pointer",
        }}
        data-testid="forbidden-home"
      >
        Return home
      </button>
    </div>
  );
}

/**
 * Route wrapper — renders children only when `perm` is granted, else the
 * `<Forbidden />` block. Useful for deep-link protection so a stale
 * bookmark from a demoted user doesn't render a broken page.
 */
export function RequirePermission({ perm, action = "read", reason, children }) {
  const allowed = useCan(perm, action);
  if (allowed) return children;
  return <Forbidden reason={reason || `You don't have permission to view this page (${perm}).`} />;
}

/** Legacy alias — kept so existing PermGate call-sites keep working. */
export function PermGate({ feature, action = "read", fallback = null, children }) {
  const { can } = usePermissions();
  return can(feature, action) ? children : fallback;
}
