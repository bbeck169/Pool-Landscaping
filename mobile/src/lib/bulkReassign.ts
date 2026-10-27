/**
 * UU-mobile · Schedule bulk-reassign helpers (web CalendarSchedule.jsx
 * AssignTechDropdown parity). BE rejects non-tech roles on new_tech_id
 * ("new_tech_id role … is not a technician role"), so the picker lists the same
 * four roles web does.
 */
export const REASSIGN_TECH_ROLES = new Set(["pool_tech", "landscape_tech", "technician", "tech"]);

/** GET /technicians rows → reassignable techs (named, tech role). Same unwrap as calendar.tsx's /technicians load. */
export function reassignableTechs(res: any): any[] {
  const rows = Array.isArray(res) ? res : Array.isArray(res?.technicians) ? res.technicians : [];
  return rows.filter((u: any) => u?.id && u?.name && REASSIGN_TECH_ROLES.has(String(u.role || "").toLowerCase()));
}
