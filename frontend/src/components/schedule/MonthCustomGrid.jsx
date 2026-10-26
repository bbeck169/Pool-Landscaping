/**
 * Ticket W · Feb-2026 — Custom Month grid for the Schedule page.
 *
 * Replaces the react-big-calendar built-in month view inside
 * ``mode === "calendar" && view === "month"`` with a Mon-Sun grid
 * matching the operator's spec:
 *
 *   - 5 or 6 week rows (auto-fit the visible month)
 *   - Today cell highlighted via existing accent token
 *   - Adjacent-month cells visible but muted
 *   - ← / Today / → nav + Month | Agenda view switcher
 *   - Each day cell: overflow-y-auto scroll + ``+N more`` pill (click
 *     opens a popover) when visits exceed the preview threshold
 *   - Cards: two lines (job name, customer name) with status-color
 *     left-border via the shared ``STATUS_COLORS`` map
 *   - Card click → the parent-page ``onSelectEvent`` handler (no new
 *     detail surface)
 *
 * The grid is DRAG-LESS by design — Option α scope lock. ``mode="grid"``
 * route-planner + ``view="agenda"`` RBC Agenda remain unchanged. The
 * drag-less posture is regression-locked by vitest (asserts no
 * ``onDragStart`` / ``draggable`` attributes on cells + cards).
 *
 * Data source: parent passes in the pre-fetched ``events`` array
 * (same shape the DnDCalendar consumes). Date range widening on
 * navigate flows through the parent's existing ``onNavigate`` so no
 * new fetch path is introduced.
 */
import React, { useMemo, useState } from "react";
import {
  startOfMonth, endOfMonth, startOfWeek, endOfWeek,
  eachDayOfInterval, isSameMonth, isSameDay, format,
  addMonths, subMonths,
} from "date-fns";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { colors } from "@/theme";
// Ticket X · Feb-2026 — MISSED → OPEN inline action on each
// Schedule surface's card. ``MarkOpenAction`` is self-contained
// (owns its own API call + optimistic patch + toast + undo).
// MonthCustomGrid only has to pass through ``job`` + ``onPatch``.
import MarkOpenAction from "@/components/schedule/MarkOpenAction";


const WEEKDAY_HEADERS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const CARD_PREVIEW_LIMIT = 3;


function MonthCard({ event, statusColors, onSelectEvent, testId,
                     onPatchJob }) {
  const job = (event && event.resource && event.resource.job) || {};
  const status = (job.status || "scheduled").toLowerCase();
  const borderColor = statusColors[status] || "#64748B";
  const customerName = job.customer_name || "";
  const jobName = job.service_type || event?.title || "Job";
  return (
    <div
      data-testid={testId}
      data-status={status}
      data-status-color={borderColor}
      onClick={() => onSelectEvent && onSelectEvent(event)}
      className="w-full rounded px-1.5 py-1 text-[11px] leading-tight transition hover:brightness-95 cursor-pointer"
      style={{
        borderLeft: `3px solid ${borderColor}`,
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
        borderLeftWidth: 3,
        borderLeftStyle: "solid",
        borderLeftColor: borderColor,
      }}
    >
      <div
        className="font-semibold truncate"
        style={{ color: colors.onSurface }}
        data-testid={`${testId}-jobname`}
      >
        {jobName}
      </div>
      <div
        className="truncate opacity-70"
        style={{ color: colors.onSurface }}
        data-testid={`${testId}-customername`}
      >
        {customerName || "—"}
      </div>
      {/* Ticket X · Feb-2026 — MISSED-only inline action. The
          component self-returns null for non-missed jobs so the
          non-missed card chrome is byte-identical to the pre-
          Ticket-X cards (zero visual churn on the common path).
          MarkOpenAction stops propagation on its own click so a
          Mark-open click never also fires the parent-card
          ``onSelectEvent`` (regression-locked in the vitest). */}
      {status === "missed" && onPatchJob ? (
        <div className="mt-1">
          <MarkOpenAction
            job={job}
            onPatch={onPatchJob}
            size="xs"
            testIdSuffix={`month-${job.id}`}
          />
        </div>
      ) : null}
    </div>
  );
}


function MoreVisitsPopover({
  events, dayKey, statusColors, onSelectEvent, onClose, onPatchJob,
}) {
  return (
    <div
      className="absolute z-50 top-6 left-1 w-56 max-h-72 overflow-y-auto rounded-lg shadow-xl p-2 space-y-1"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      role="dialog"
      data-testid={`month-popover-${dayKey}`}
      onClick={(e) => e.stopPropagation()}
    >
      <div
        className="flex items-center justify-between pb-1 mb-1 border-b"
        style={{ borderColor: colors.border }}
      >
        <span className="text-xs font-semibold"
              style={{ color: colors.onSurface }}>
          All visits ({events.length})
        </span>
        <button
          type="button"
          className="text-xs opacity-60 hover:opacity-100"
          onClick={onClose}
          data-testid={`month-popover-close-${dayKey}`}
          aria-label="Close popover"
        >✕</button>
      </div>
      {events.map((ev, i) => (
        <MonthCard
          key={ev.id || i}
          event={ev}
          statusColors={statusColors}
          onSelectEvent={(e) => {
            if (onSelectEvent) onSelectEvent(e);
            onClose();
          }}
          onPatchJob={onPatchJob}
          testId={`month-popover-card-${dayKey}-${i}`}
        />
      ))}
    </div>
  );
}


export default function MonthCustomGrid({
  date, events, onNavigate, onSelectEvent, onViewChange,
  statusColors, onPatchJob,
}) {
  const [popoverDay, setPopoverDay] = useState(null);

  const gridDays = useMemo(() => {
    const monthStart = startOfMonth(date);
    const monthEnd = endOfMonth(date);
    const gridStart = startOfWeek(monthStart, { weekStartsOn: 1 });
    const gridEnd = endOfWeek(monthEnd, { weekStartsOn: 1 });
    return eachDayOfInterval({ start: gridStart, end: gridEnd });
  }, [date]);

  const eventsByDay = useMemo(() => {
    const map = {};
    for (const ev of (events || [])) {
      try {
        if (!ev || !ev.start) continue;
        const key = format(ev.start, "yyyy-MM-dd");
        if (!map[key]) map[key] = [];
        map[key].push(ev);
      } catch { /* skip malformed event */ }
    }
    return map;
  }, [events]);

  const weeks = useMemo(() => {
    const chunks = [];
    for (let i = 0; i < gridDays.length; i += 7) {
      chunks.push(gridDays.slice(i, i + 7));
    }
    return chunks;
  }, [gridDays]);

  const today = new Date();
  const monthLabel = format(date, "MMMM yyyy");

  return (
    <div
      data-testid="month-custom-grid"
      data-row-count={weeks.length}
      className="w-full"
    >
      {/* Toolbar: ← Today → · month label · view switch */}
      <div
        className="flex items-center justify-between flex-wrap gap-2 mb-2 px-1"
        data-testid="month-toolbar"
      >
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="px-2 py-1 rounded text-sm transition hover:brightness-95"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            onClick={() => onNavigate && onNavigate(subMonths(date, 1))}
            data-testid="month-nav-prev"
            aria-label="Previous month"
          >
            <ChevronLeft size={14} />
          </button>
          <button
            type="button"
            className="px-3 py-1 rounded text-sm font-semibold transition hover:brightness-95"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            onClick={() => onNavigate && onNavigate(new Date())}
            data-testid="month-nav-today"
          >Today</button>
          <button
            type="button"
            className="px-2 py-1 rounded text-sm transition hover:brightness-95"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            onClick={() => onNavigate && onNavigate(addMonths(date, 1))}
            data-testid="month-nav-next"
            aria-label="Next month"
          >
            <ChevronRight size={14} />
          </button>
        </div>
        <div
          className="text-base font-bold"
          style={{ color: colors.onSurface }}
          data-testid="month-label"
        >{monthLabel}</div>
        <div
          className="flex gap-0.5 p-0.5 rounded-md"
          style={{
            backgroundColor: colors.surfaceSecondary || colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          role="tablist"
          data-testid="month-view-switcher"
        >
          <button
            type="button"
            role="tab"
            aria-selected="true"
            onClick={() => onViewChange && onViewChange("month")}
            className="px-2 py-1 rounded text-xs font-semibold transition"
            style={{ backgroundColor: colors.brand, color: "#fff" }}
            data-testid="month-view-switch-month"
          >Month</button>
          <button
            type="button"
            role="tab"
            aria-selected="false"
            onClick={() => onViewChange && onViewChange("agenda")}
            className="px-2 py-1 rounded text-xs font-semibold transition"
            style={{ backgroundColor: "transparent", color: colors.onSurface }}
            data-testid="month-view-switch-agenda"
          >Agenda</button>
        </div>
      </div>

      {/* Column headers (Mon-Sun) */}
      <div
        className="grid grid-cols-7 border-t border-l"
        style={{ borderColor: colors.border }}
        data-testid="month-weekday-header-row"
      >
        {WEEKDAY_HEADERS.map((wd) => (
          <div
            key={wd}
            className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-center border-r border-b"
            style={{
              borderColor: colors.border,
              color: colors.onSurfaceSecondary || colors.onSurface,
            }}
            data-testid={`month-weekday-${wd.toLowerCase()}`}
          >{wd}</div>
        ))}
      </div>

      {/* Week rows */}
      <div data-testid="month-weeks-container">
        {weeks.map((week, wi) => (
          <div
            key={wi}
            className="grid grid-cols-7 border-l"
            style={{ borderColor: colors.border }}
            data-testid={`month-week-row-${wi}`}
          >
            {week.map((day) => {
              const dayKey = format(day, "yyyy-MM-dd");
              const inMonth = isSameMonth(day, date);
              const isToday = isSameDay(day, today);
              const dayEvents = eventsByDay[dayKey] || [];
              const visible = dayEvents.slice(0, CARD_PREVIEW_LIMIT);
              const overflow = Math.max(
                0, dayEvents.length - CARD_PREVIEW_LIMIT,
              );
              return (
                <div
                  key={dayKey}
                  className="relative border-r border-b"
                  style={{
                    borderColor: colors.border,
                    backgroundColor: isToday
                      ? ((colors.accent && colors.accent[50]) || "#DBEAFE")
                      : colors.surface,
                    minHeight: 108,
                  }}
                  data-testid={`month-cell-${dayKey}`}
                  data-in-month={inMonth ? "true" : "false"}
                  data-today={isToday ? "true" : "false"}
                >
                  <div
                    className="flex items-center justify-between px-1.5 py-0.5 text-[11px]"
                    style={{
                      opacity: inMonth ? 1 : 0.4,
                      color: isToday ? colors.brand : colors.onSurface,
                      fontWeight: isToday ? 700 : 500,
                    }}
                  >
                    <span data-testid={`month-cell-daynum-${dayKey}`}>
                      {format(day, "d")}
                    </span>
                  </div>
                  <div
                    className="px-1 pb-1 space-y-1 overflow-y-auto"
                    style={{
                      maxHeight: 80,
                      opacity: inMonth ? 1 : 0.55,
                    }}
                    data-testid={`month-cell-cards-${dayKey}`}
                  >
                    {visible.map((ev, i) => (
                      <MonthCard
                        key={ev.id || i}
                        event={ev}
                        statusColors={statusColors}
                        onSelectEvent={onSelectEvent}
                        onPatchJob={onPatchJob}
                        testId={`month-card-${dayKey}-${i}`}
                      />
                    ))}
                  </div>
                  {overflow > 0 ? (
                    <button
                      type="button"
                      className="absolute bottom-1 left-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full transition hover:brightness-95"
                      style={{
                        backgroundColor:
                          colors.surfaceSecondary || "#E2E8F0",
                        color: colors.onSurface,
                        border: `1px solid ${colors.border}`,
                      }}
                      onClick={(e) => {
                        e.stopPropagation();
                        setPopoverDay(
                          popoverDay === dayKey ? null : dayKey,
                        );
                      }}
                      data-testid={`month-more-pill-${dayKey}`}
                    >
                      +{overflow} more
                    </button>
                  ) : null}
                  {popoverDay === dayKey ? (
                    <MoreVisitsPopover
                      events={dayEvents}
                      dayKey={dayKey}
                      statusColors={statusColors}
                      onSelectEvent={onSelectEvent}
                      onPatchJob={onPatchJob}
                      onClose={() => setPopoverDay(null)}
                    />
                  ) : null}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
