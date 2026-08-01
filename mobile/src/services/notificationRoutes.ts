/**
 * Phase 20 · Feb-2026 · Sub-item B — notification route resolver.
 *
 * Pure function so the router logic is unit-testable in isolation
 * (mobile-side test frameworks are limited, so a plain-JS resolver
 * is the highest-leverage test surface).
 *
 * Input:  { kind: string, href?: string, job_id?: string, role: string }
 * Output: string route path, or null when no routing action applies.
 *
 * Routing table (extend as new kinds are added):
 *   inventory_low_stock  · tech       → /inventory/my-inventory
 *                        · admin+     → /admin/inventory
 *   * (default)          · job_id set → /job/{job_id}
 *                        · href set   → href (used verbatim)
 *                        · else       → null
 */
export type NotificationLike = {
  kind?: string | null;
  href?: string | null;
  job_id?: string | null;
};

export type UserLike = {
  role?: string | null;
};

const ADMIN_ROLES = new Set([
  "admin", "super_admin", "owner", "manager", "office",
]);

export function resolveNotificationRoute(
  notif: NotificationLike | null | undefined,
  user: UserLike | null | undefined,
): string | null {
  if (!notif) return null;
  const kind = (notif.kind || "").toString();
  const role = ((user && user.role) || "").toString();

  // Phase 18 inventory alerts route by role.
  if (kind === "inventory_low_stock") {
    if (ADMIN_ROLES.has(role)) return "/admin/inventory";
    // Techs (and any non-customer non-admin role) land on their
    // read-only view.
    return "/inventory/my-inventory";
  }

  // Generic fallbacks preserved from existing behaviour.
  if (notif.job_id) return `/job/${notif.job_id}`;
  if (notif.href) return String(notif.href);
  return null;
}
