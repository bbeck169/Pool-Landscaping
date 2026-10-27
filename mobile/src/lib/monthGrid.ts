/**
 * M3c · Schedule Month view helpers (web Ticket W `MonthCustomGrid.jsx` parity).
 * Mon-start weeks, 5 or 6 rows auto-fit, ≤42-day fetch window, web STATUS_COLORS
 * border palette, 3-card preview + "+N more".
 */
export const MONTH_CARD_PREVIEW_LIMIT = 3;
/** /jobs default limit is 1000 (asc by date) — a busy month grid exceeds it. */
export const MONTH_FETCH_LIMIT = 5000;

/** Web CalendarSchedule.jsx STATUS_COLORS (card left-border). Fallback #64748B. */
export const MONTH_STATUS_BORDER: Readonly<Record<string, string>> = Object.freeze({
  scheduled: "#0EA5E9", active: "#059669", completed: "#ff4542", pending: "#F59E0B",
  requested: "#8B5CF6", reopened: "#DC2626", cancelled: "#9CA3AF", on_hold: "#F97316",
  missed: "#B91C1C",
});
export const monthBorderColor = (status?: string | null) =>
  MONTH_STATUS_BORDER[String(status || "scheduled").toLowerCase()] || "#64748B";

const pad = (n: number) => String(n).padStart(2, "0");
export const dayKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (d: Date, n: number) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };

export function buildMonthGrid(anchor: Date): { weeks: Date[][]; start: string; end: string } {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
  const gridStart = addDays(first, -((first.getDay() + 6) % 7)); // back to Monday
  const gridEnd = addDays(last, 6 - ((last.getDay() + 6) % 7)); // forward to Sunday
  const weeks: Date[][] = [];
  for (let d = gridStart; d <= gridEnd; d = addDays(d, 7)) {
    weeks.push(Array.from({ length: 7 }, (_, i) => addDays(d, i)));
  }
  return { weeks, start: dayKey(gridStart), end: dayKey(gridEnd) };
}

/** Same /jobs?start&end pattern as Grid/Calendar, widened to the visible grid. */
export function monthJobsUrl(anchor: Date, scopeQuery: string): string {
  const { start, end } = buildMonthGrid(anchor);
  return `/jobs?start=${start}&end=${end}&limit=${MONTH_FETCH_LIMIT}${scopeQuery}`;
}

export function groupJobsByDay(jobs: any[]): Record<string, any[]> {
  const out: Record<string, any[]> = {};
  for (const j of jobs || []) {
    const k = String(j?.scheduled_date || "").slice(0, 10);
    if (k) (out[k] ||= []).push(j);
  }
  return out;
}

/** TD-xx mobile (web XX c19b8daf3) — ids of ALL crews whose `tech_ids` contain `tid`
 *  (plural). null when there is no tech → callers fall back to direct match only. */
export function buildTechCrewIds(crews: any[] | null | undefined, tid?: string | null): Set<string> | null {
  if (!tid) return null;
  const ids = new Set<string>();
  for (const c of crews || []) if (c?.id && (c.tech_ids || []).includes(tid)) ids.add(c.id);
  return ids;
}

/** Direct tech match OR unassigned catch-all (D1a, unchanged) OR crew membership (new). */
export function jobMatchesTech(j: any, tid: string, techCrewIds?: Set<string> | null): boolean {
  if (j.technician_id === tid || !j.technician_id) return true;
  return !!techCrewIds && !!j.crew_id && techCrewIds.has(j.crew_id);
}

const CANCELLED = new Set(["cancelled", "canceled", "skipped"]);
/** Mirrors calendar.tsx filteredJobs + visibleJobs (tech fail-closed, hide cancelled). */
export function filterMonthJobs(jobs: any[], o: { isTech: boolean; techFilter: string; resolvedTechId?: string | null; showCancelled: boolean; techCrewIds?: Set<string> | null }): any[] {
  let arr = jobs || [];
  if (o.isTech) {
    const tid = o.techFilter !== "all" ? o.techFilter : o.resolvedTechId;
    if (!tid) return [];
    arr = arr.filter((j) => jobMatchesTech(j, tid, o.techCrewIds));
  } else if (o.techFilter !== "all") {
    arr = arr.filter((j) => jobMatchesTech(j, o.techFilter, o.techCrewIds));
  }
  return o.showCancelled ? arr : arr.filter((j) => !CANCELLED.has(String(j.status || "").toLowerCase()));
}
