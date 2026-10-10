/**
 * Phase 30 — Team Aggregation client-side shift pairing helper.
 *
 * The admin aggregation endpoint (GET /api/timeclock/admin-summary)
 * returns a flat ``punches[]`` array per technician with ISO
 * timestamps + ``punch_type: "in" | "out"``.  Phase 30 renders those
 * as paired shift rows (Date | Clock In | Clock Out | Hours Worked
 * | Location).  This helper owns the pairing + per-day grouping +
 * display-string formatting so the component JSX stays declarative.
 *
 * Rules (per user-approved Phase 30 spec):
 *   • Sort punches ASC by ``ts`` before walking.
 *   • Walk: ``in`` opens a shift; the next ``out`` closes it.
 *   • Prior still-open ``in`` encountered before its ``out`` is
 *     flushed as an orphan (still-clocked-in row, ``out = null``).
 *   • Orphan ``out`` (no prior open ``in``) is skipped +
 *     ``console.warn``'d so admins can spot data-quality issues.
 *   • Group by local-tz **date of clock-in** so overnight shifts
 *     bucket under the day they started (payroll convention).
 *   • Date label format: ``Mon 10/06`` (short weekday + MM/DD).
 *   • Time label format: ``05:57 AM`` (locale time, 2-digit).
 *   • Lat/lng format: ``.toFixed(4)`` for the Location column
 *     (header summary line stays at 2-decimal — see component).
 *   • Hours label format: ``H:MM`` (no leading-zero on hours per
 *     payroll screenshot: ``9:51``, ``37:53``).
 */
export function fmtHoursMinutes(seconds) {
  if (seconds == null) return "—";
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}:${String(m).padStart(2, "0")}`;
}

export function _fmtDateLabel(d) {
  if (!(d instanceof Date) || Number.isNaN(d.getTime())) return "";
  const wd = d.toLocaleDateString(undefined, { weekday: "short" });
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${wd} ${mm}/${dd}`;
}

export function _dayKey(d) {
  if (!(d instanceof Date) || Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
       + `-${String(d.getDate()).padStart(2, "0")}`;
}

export function _fmtTimeLabel(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString([],
      { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "—";
  }
}

export function _fmtLatLng(lat, lng) {
  if (typeof lat !== "number" || typeof lng !== "number") return "—";
  return `${lat.toFixed(4)},${lng.toFixed(4)}`;
}

/**
 * Build the array of table-row descriptors from a raw punches list.
 * Pure function, safe for unit testing.
 */
export function buildShiftRows(rawPunches) {
  const sorted = [...(rawPunches || [])].sort((a, b) =>
    String(a.ts || "").localeCompare(String(b.ts || "")));

  const shifts = [];
  let openIn = null;
  for (const p of sorted) {
    if (p.punch_type === "in") {
      if (openIn) shifts.push({ in: openIn, out: null, open: true });
      openIn = p;
    } else if (p.punch_type === "out") {
      if (openIn) {
        shifts.push({ in: openIn, out: p, open: false });
        openIn = null;
      } else {
        // eslint-disable-next-line no-console
        console.warn("[timeclock] orphan OUT punch", p);
      }
    }
  }
  if (openIn) shifts.push({ in: openIn, out: null, open: true });

  let lastDateKey = null;
  return shifts.map((sh, idx) => {
    const inDate = new Date(sh.in.ts);
    const key = _dayKey(inDate);
    const showDate = key !== lastDateKey;
    lastDateKey = key;
    const durationSec = sh.out
      ? Math.max(0, Math.floor(
          (new Date(sh.out.ts).getTime() - inDate.getTime()) / 1000))
      : null;
    return {
      shiftKey: sh.in.id || `s-${idx}`,
      dateKey: key,
      dateLabel: _fmtDateLabel(inDate),
      showDate,
      clockInLabel: _fmtTimeLabel(sh.in.ts),
      clockOutLabel: sh.out ? _fmtTimeLabel(sh.out.ts) : "—",
      hoursLabel: durationSec == null ? "—" : fmtHoursMinutes(durationSec),
      inLatLng: _fmtLatLng(sh.in.lat, sh.in.lng),
      outLatLng: sh.out ? _fmtLatLng(sh.out.lat, sh.out.lng) : null,
      open: sh.open,
    };
  });
}
