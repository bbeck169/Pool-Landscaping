/**
 * Feb-2026 · Phase Schedule-UI · WeekStrip.
 *
 * Compact 7-day (Mon–Sun) strip that renders at the top of the
 * ``/schedule`` page. Left/right chevrons shift the visible week;
 * clicking a day fires ``onSelectDate(iso)`` with the yyyy-mm-dd
 * ISO string.
 *
 * Rendering rules:
 *   • The day matching ``selectedDate`` is drawn in a filled circle
 *     with white text — the primary highlight.
 *   • "Today" (system clock) always gets a small dot below the number
 *     so users can find their way home when navigating other weeks.
 *   • Layout mirrors the mockup — a horizontally-centered row with
 *     chevrons flush to the ends: `<  MON 12  TUE 13  WED 14  THU 15  FRI 16  SAT 17  SUN 18  >`.
 *
 * Auto-selects today on mount when ``selectedDate`` is not provided.
 */
import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { colors } from "@/theme";


const DAY_LABELS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];


function _todayIso() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}


function _isoToDate(iso) {
  // Parse as local midnight — matches the yyyy-MM-dd convention used
  // by the Schedule page's ``focusISO`` calculation.
  if (!iso || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return new Date();
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}


function _dateToIso(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}


function _startOfWeekMonday(d) {
  // JS getDay(): 0=Sun, 1=Mon ... 6=Sat. Shift so Monday is the start.
  const day = d.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  const monday = new Date(d.getFullYear(), d.getMonth(), d.getDate() + diff);
  return monday;
}


export default function WeekStrip({
  selectedDate,
  onSelectDate,
}) {
  const [anchor, setAnchor] = React.useState(() =>
    _startOfWeekMonday(_isoToDate(selectedDate || _todayIso())));

  // If the parent's ``selectedDate`` shifts to a different week (e.g.
  // via URL params, another nav control), keep the strip in sync.
  React.useEffect(() => {
    if (!selectedDate) return;
    const sd = _isoToDate(selectedDate);
    const monday = _startOfWeekMonday(sd);
    setAnchor((prev) => {
      if (_dateToIso(prev) === _dateToIso(monday)) return prev;
      return monday;
    });
  }, [selectedDate]);

  // Auto-select today on mount when parent didn't seed a date.
  React.useEffect(() => {
    if (selectedDate) return;
    onSelectDate?.(_todayIso());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const todayIso = _todayIso();
  const selIso = selectedDate || todayIso;

  const days = React.useMemo(() => {
    return Array.from({ length: 7 }).map((_, i) => {
      const d = new Date(anchor.getFullYear(), anchor.getMonth(),
                            anchor.getDate() + i);
      return {
        iso: _dateToIso(d),
        label: DAY_LABELS[i],
        num: d.getDate(),
      };
    });
  }, [anchor]);

  const shiftWeek = (dir) => {
    setAnchor((prev) => new Date(prev.getFullYear(), prev.getMonth(),
                                     prev.getDate() + dir * 7));
  };

  return (
    <div
      className="flex items-center gap-1 sm:gap-2 rounded-xl p-2 mb-3"
      style={{ backgroundColor: colors.surface,
                 border: `1px solid ${colors.border}` }}
      data-testid="schedule-week-strip"
      role="tablist"
      aria-label="Select a day of the week"
    >
      <button
        type="button"
        onClick={() => shiftWeek(-1)}
        className="w-8 h-8 rounded-full flex items-center justify-center hover:bg-black/5"
        style={{ color: colors.onSurface }}
        aria-label="Previous week"
        data-testid="week-strip-prev"
      >
        <ChevronLeft size={16} />
      </button>

      <div className="flex-1 flex items-center justify-between gap-0.5 sm:gap-1"
           data-testid="week-strip-days">
        {days.map((d) => {
          const isSelected = d.iso === selIso;
          const isToday = d.iso === todayIso;
          return (
            <button
              key={d.iso}
              type="button"
              role="tab"
              aria-selected={isSelected}
              aria-current={isToday ? "date" : undefined}
              onClick={() => onSelectDate?.(d.iso)}
              className="flex-1 flex flex-col items-center gap-0.5 py-1.5 rounded-lg select-none"
              style={{
                backgroundColor: "transparent",
                minWidth: 40,
                cursor: "pointer",
              }}
              data-testid={`week-strip-day-${d.iso}`}
              data-selected={isSelected ? "true" : "false"}
              data-today={isToday ? "true" : "false"}
            >
              <span
                className="text-[10px] font-bold tracking-wider"
                style={{
                  color: isSelected ? colors.brand
                    : (isToday ? colors.onSurface : colors.muted),
                }}
              >
                {d.label}
              </span>
              <span
                className="flex items-center justify-center rounded-full text-sm font-bold"
                style={{
                  width: 30, height: 30,
                  backgroundColor: isSelected ? colors.brand : "transparent",
                  color: isSelected ? "#FFFFFF" : colors.onSurface,
                  boxShadow: isSelected ? "0 2px 6px rgba(37,99,235,.25)" : "none",
                }}
              >
                {d.num}
              </span>
              <span
                className="block rounded-full"
                style={{
                  width: 4, height: 4,
                  backgroundColor: isToday && !isSelected ? colors.brand : "transparent",
                }}
                data-testid={isToday ? `week-strip-today-dot-${d.iso}` : undefined}
              />
            </button>
          );
        })}
      </div>

      <button
        type="button"
        onClick={() => shiftWeek(1)}
        className="w-8 h-8 rounded-full flex items-center justify-center hover:bg-black/5"
        style={{ color: colors.onSurface }}
        aria-label="Next week"
        data-testid="week-strip-next"
      >
        <ChevronRight size={16} />
      </button>
    </div>
  );
}
