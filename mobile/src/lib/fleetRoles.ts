/**
 * TD-fleet-emitter-role-gate · tech-equivalent roles eligible for fleet tracking.
 * Mirrors BE `services/technicians_core.ASSIGNABLE_ROLES` (6 roles). Used by the
 * emitter start gate, the foreground re-grant resume, the status chip and the
 * pause-toggle section so every tracked user also sees the indicator + pause.
 */
export const FLEET_TECH_ROLES = [
  "technician", "tech", "landscaper",
  "landscape_tech", "pool_tech", "tech_both",
] as const;

export const isFleetTechRole = (role?: string | null): boolean =>
  (FLEET_TECH_ROLES as readonly string[]).includes(role || "");
