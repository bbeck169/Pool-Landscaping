/**
 * TD-mobile-sync-tech-not-linked · sync error-code helpers.
 *
 * BE contract (any sync endpoint): HTTPException(409, detail={
 *   "error": "technician_not_linked", "detail": "<human message>", "tenant_id", "user_id" })
 * → wire `{"detail": {"error": ..., ...}}` → api.ts puts the inner object on
 * `ApiError.detail`. Matched by error code, not endpoint path (operator Q3).
 */
export const TECH_NOT_LINKED = "technician_not_linked";

export const TECH_NOT_LINKED_COPY =
  "Your account isn't linked to a technician profile. Contact your admin to resolve.";

export function isTechNotLinked(err: unknown): boolean {
  const d: any = (err as any)?.detail;
  return !!d && typeof d === "object" && d.error === TECH_NOT_LINKED;
}
