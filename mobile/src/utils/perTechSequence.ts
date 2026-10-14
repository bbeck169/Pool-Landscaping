/**
 * Per-tech stop numbering — mobile port of web ScheduleMap
 * `_buildPerTechSequence` (9eb08b5c1).
 *
 *  - Grouped by technician_id ("__unassigned__" bucket); 1..N per tech.
 *  - Order: route_index (when finite) → scheduled_at / _start / _time /
 *    _date → id (stable tiebreak).
 *  - Count-but-hide: computed over ALL jobs (incl. coord-less ones) so
 *    visible pin numbers match the operator's ordering.
 */
type SeqJob = {
  id?: string;
  technician_id?: string | null;
  route_index?: number | null;
  scheduled_at?: string | null;
  scheduled_start?: string | null;
  scheduled_time?: string | null;
  scheduled_date?: string | null;
};

const schedKey = (j: SeqJob) => j?.scheduled_at || j?.scheduled_start || j?.scheduled_time || j?.scheduled_date || "";

export function buildPerTechSequence(jobs: SeqJob[]): Map<string, number> {
  const groups: Record<string, SeqJob[]> = Object.create(null);
  for (const j of jobs || []) {
    if (!j || !j.id) continue;
    const key = j.technician_id || "__unassigned__";
    (groups[key] = groups[key] || []).push(j);
  }
  const seq = new Map<string, number>();
  for (const key of Object.keys(groups)) {
    const sorted = groups[key].slice().sort((a, b) => {
      const ai = Number.isFinite(a?.route_index as number) ? (a.route_index as number) : null;
      const bi = Number.isFinite(b?.route_index as number) ? (b.route_index as number) : null;
      if (ai != null && bi != null) return ai - bi;
      if (ai != null) return -1;
      if (bi != null) return 1;
      const as = schedKey(a);
      const bs = schedKey(b);
      if (as && bs && as !== bs) return as < bs ? -1 : 1;
      return String(a.id).localeCompare(String(b.id));
    });
    sorted.forEach((j, i) => seq.set(j.id as string, i + 1));
  }
  return seq;
}

/** technician_id → stop count (assigned jobs only), for the legend. */
export function perTechStopCounts(jobs: SeqJob[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const j of jobs || []) {
    if (!j?.technician_id) continue;
    counts.set(j.technician_id, (counts.get(j.technician_id) || 0) + 1);
  }
  return counts;
}
