/**
 * Feb-2026 · Phase C — Drag-and-drop Reorder Route modal (WEB only).
 *
 * Replaces the prior "type a unique 1–50 number" input model with a
 * drag-and-drop list where positions are read-only, always
 * contiguous 1..N. Mobile parity ships in Phase E.
 *
 * Contract:
 *   • Persistence endpoint is unchanged — POST /api/jobs/reorder
 *     with { tech_user_id, date, ordered_job_ids: [...] }. Backend
 *     derives `route_index` from array position, so array order IS
 *     the position — the 1..N contiguous contract is inherent.
 *   • Response shape is unchanged; the caller's `onSaved` gets the
 *     same payload it always did.
 *
 * Accessibility:
 *   • dnd-kit's KeyboardSensor provides Tab / Space/Enter to pick,
 *     Arrow keys to move, Space/Enter to drop, Esc to cancel.
 *   • Every row also carries visible ↑/↓ arrow buttons as a
 *     mouse/touch fallback (disabled at list boundaries).
 *   • `aria-live="polite"` region announces every move so screen
 *     readers hear "Moved <name> from position X to Y. New order:
 *     1..N".
 *
 * data-testids:
 *   reorder-route-modal            — root
 *   reorder-route-cancel           — cancel button
 *   reorder-route-save             — save button
 *   reorder-route-empty            — 0-job empty state
 *   reorder-route-live-region      — aria-live announcements
 *   reorder-route-row-<jobId>      — each sortable row
 *   reorder-route-badge-<jobId>    — read-only position pill
 *   reorder-route-handle-<jobId>   — drag handle
 *   reorder-route-up-<jobId>       — up arrow button
 *   reorder-route-down-<jobId>     — down arrow button
 */
import React, { useCallback, useMemo, useRef, useState } from "react";
import {
  DndContext, closestCenter, KeyboardSensor, PointerSensor,
  useSensor, useSensors,
} from "@dnd-kit/core";
import {
  arrayMove, SortableContext, sortableKeyboardCoordinates,
  useSortable, verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { toast } from "sonner";
import {
  ArrowDownUp, ChevronDown, ChevronUp, GripVertical, Save as SaveIcon, X,
} from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";

// ─── Phase B · Feb-2026 — client-side haversine recompute helpers ──
// Lightweight, no external deps. Used to recompute the header
// "Estimated Xh Ym · M.Mmi · {trivial|short|long}" line whenever the
// operator drags or hits "Reverse Order" so the summary stays in
// sync with the in-modal order without a backend round-trip.
const _EARTH_M = 6371008.8;
export function haversineMeters(aLat, aLng, bLat, bLng) {
  if (aLat == null || aLng == null || bLat == null || bLng == null) {
    return 0;
  }
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(bLat - aLat);
  const dLng = toRad(bLng - aLng);
  const s =
    Math.sin(dLat / 2) ** 2
    + Math.cos(toRad(aLat)) * Math.cos(toRad(bLat))
    * Math.sin(dLng / 2) ** 2;
  return 2 * _EARTH_M * Math.asin(Math.min(1, Math.sqrt(s)));
}
function _jobCoord(j) {
  const lat = j?.location_lat ?? j?.site_lat ?? j?.lat ?? j?.latitude;
  const lng = j?.location_lng ?? j?.site_lng ?? j?.lng ?? j?.longitude;
  return (lat != null && lng != null) ? [Number(lat), Number(lng)] : null;
}
export function totalHaversineMeters(orderedJobs) {
  if (!Array.isArray(orderedJobs) || orderedJobs.length < 2) return 0;
  let total = 0;
  let prev = null;
  for (const j of orderedJobs) {
    const c = _jobCoord(j);
    if (c && prev) total += haversineMeters(prev[0], prev[1], c[0], c[1]);
    if (c) prev = c;
  }
  return total;
}
// Phase B · Feb-2026 — distance classification (dispatch brief §Commit 2):
//   trivial: < 5 mi · short: 5-20 mi · long: > 20 mi.
export function classifyMiles(miles) {
  if (miles < 5) return "trivial";
  if (miles <= 20) return "short";
  return "long";
}
// ~35 km/h neighborhood driving — matches the server-side
// `_estimate_duration_s` in `backend/routers/route_optimization.py`.
function _durationSecondsFromMeters(m) {
  if (m <= 0) return 0;
  return Math.round(m / ((35 * 1000) / 3600));
}
function _formatHeader(meters, overrideSeconds) {
  const miles = meters / 1609.344;
  const secs = overrideSeconds != null
    ? overrideSeconds : _durationSecondsFromMeters(meters);
  const h = Math.floor(secs / 3600);
  const m = Math.round((secs % 3600) / 60);
  return (
    `Estimated ~${h}h ${m}m · ${miles.toFixed(1)}mi `
    + `· ${classifyMiles(miles)}`
  );
}


function Row({ job, index, total, onMoveUp, onMoveDown, disabled }) {
  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({ id: job.id, disabled });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.55 : 1,
    background: colors.surfaceSecondary,
    border: `1px solid ${isDragging ? "#059669" : colors.border}`,
  };

  const label = job.customer_name || job.title || "Job";
  const meta =
    ((job.scheduled_time || job.scheduled_at || "").slice(11, 16) || "") +
    (job.address ? ` · ${job.address}` : "");

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="flex items-center gap-3 rounded-xl px-3 py-2"
      data-testid={`reorder-route-row-${job.id}`}
    >
      <button
        type="button"
        {...attributes}
        {...listeners}
        aria-label={`Drag ${label}`}
        disabled={disabled}
        className="cursor-grab active:cursor-grabbing p-1 rounded"
        style={{ color: colors.muted, touchAction: "none" }}
        data-testid={`reorder-route-handle-${job.id}`}
      >
        <GripVertical size={16} />
      </button>

      <span
        aria-label={`Position ${index + 1}`}
        className="inline-flex items-center justify-center text-xs font-bold rounded-full"
        style={{
          minWidth: 26, height: 26, padding: "0 6px",
          background: "#059669", color: "#fff",
        }}
        data-testid={`reorder-route-badge-${job.id}`}
      >
        {index + 1}
      </span>

      <div className="flex-1 min-w-0">
        <div
          className="text-sm font-semibold truncate"
          style={{ color: colors.onSurface }}
        >
          {label}
        </div>
        <div className="text-xs truncate" style={{ color: colors.muted }}>
          {meta}
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <button
          type="button"
          onClick={() => onMoveUp(job.id)}
          disabled={disabled || index === 0}
          aria-label={`Move ${label} up`}
          className="p-1 rounded disabled:opacity-30"
          style={{
            color: colors.onSurfaceSecondary,
            background: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid={`reorder-route-up-${job.id}`}
        >
          <ChevronUp size={12} />
        </button>
        <button
          type="button"
          onClick={() => onMoveDown(job.id)}
          disabled={disabled || index === total - 1}
          aria-label={`Move ${label} down`}
          className="p-1 rounded disabled:opacity-30"
          style={{
            color: colors.onSurfaceSecondary,
            background: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid={`reorder-route-down-${job.id}`}
        >
          <ChevronDown size={12} />
        </button>
      </div>
    </div>
  );
}


/**
 * `initialOrder` (optional) — pre-seed order by job-id list. Used by
 * the "Optimize Route" button to open with the recommended order.
 * Falls back to sort by `route_index` when omitted.
 */
function _initialOrderedJobs(jobs, initialOrder) {
  if (Array.isArray(initialOrder) && initialOrder.length) {
    const rank = new Map();
    initialOrder.forEach((id, i) => rank.set(id, i));
    return [...jobs].sort(
      (a, b) => (rank.get(a.id) ?? 9999) - (rank.get(b.id) ?? 9999),
    );
  }
  return [...jobs].sort(
    (a, b) => (a.route_index ?? 9999) - (b.route_index ?? 9999),
  );
}


export function ReorderRouteModal({
  jobs, techUserId, date, onClose, onSaved,
  initialOrder = null, optimizeSummary = null, optimizeWarnings = null,
  // Phase B · Feb-2026 — new props so the modal can recompute the
  // header line as the operator drags / reverses, and show a
  // dropped-job yellow banner when the backend indicated some jobs
  // couldn't be geocoded.
  optimizeTotalMeters = null,
  optimizeTotalSeconds = null,
  droppedJobIds = null,
}) {
  const [ordered, setOrdered] = useState(
    () => _initialOrderedJobs(jobs, initialOrder),
  );
  const [saving, setSaving] = useState(false);
  const [liveMsg, setLiveMsg] = useState("");
  // Phase B · track whether the current list order matches the
  // backend's optimized output. When true, we render the server's
  // (typically more accurate) total_distance_m / total_duration_s.
  // When false (operator dragged or reversed), fall back to a
  // client-side haversine recompute.
  const [matchesServerOrder, setMatchesServerOrder] = useState(() => {
    if (!Array.isArray(initialOrder) || initialOrder.length === 0) return false;
    return true;
  });
  const overlayRef = useRef(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const isFallback = Array.isArray(optimizeWarnings)
    && optimizeWarnings.some((w) => /directions unavailable/i.test(String(w)));

  const announce = useCallback((label, from, to, list) => {
    setLiveMsg(
      `Moved ${label} from position ${from} to position ${to}. `
      + `New order: 1 to ${list.length}.`,
    );
  }, []);

  const handleDragEnd = useCallback((evt) => {
    const { active, over } = evt;
    if (!over || active.id === over.id) return;
    setOrdered((cur) => {
      const oldIdx = cur.findIndex((j) => j.id === active.id);
      const newIdx = cur.findIndex((j) => j.id === over.id);
      if (oldIdx < 0 || newIdx < 0) return cur;
      const next = arrayMove(cur, oldIdx, newIdx);
      const moved = cur[oldIdx];
      const label = moved.customer_name || moved.title || "Job";
      announce(label, oldIdx + 1, newIdx + 1, next);
      return next;
    });
    // Phase B · any drag ejects the server's precomputed totals; the
    // header switches to a client-side haversine recompute.
    setMatchesServerOrder(false);
  }, [announce]);

  const moveBy = useCallback((jobId, delta) => {
    setOrdered((cur) => {
      const i = cur.findIndex((j) => j.id === jobId);
      const target = i + delta;
      if (i < 0 || target < 0 || target >= cur.length) return cur;
      const next = arrayMove(cur, i, target);
      const label = cur[i].customer_name || cur[i].title || "Job";
      announce(label, i + 1, target + 1, next);
      return next;
    });
    setMatchesServerOrder(false);
  }, [announce]);

  // Phase B · Feb-2026 — "Reverse Order" button. Non-destructive;
  // operator still clicks "Save order" to commit. Triggers the same
  // header-recompute path as drag (switches to client haversine).
  const reverseOrder = useCallback(() => {
    setOrdered((cur) => {
      if (cur.length < 2) return cur;
      const next = [...cur].reverse();
      setLiveMsg(
        `Reversed order. New order: 1 to ${next.length}.`,
      );
      return next;
    });
    setMatchesServerOrder(false);
  }, []);

  const save = useCallback(async () => {
    if (!ordered.length) return;
    setSaving(true);
    try {
      const body = { ordered_job_ids: ordered.map((j) => j.id) };
      if (techUserId) body.tech_user_id = techUserId;
      if (date) body.date = date;
      const r = await api.post("/jobs/reorder", body);
      toast.success("Route reordered", { duration: 3000 });
      onSaved?.(r);
      onClose?.();
    } catch (e) {
      toast.error(e?.message || "Reorder failed. Please try again.");
    } finally {
      setSaving(false);
    }
  }, [ordered, techUserId, date, onSaved, onClose]);

  const empty = ordered.length === 0;
  const jobIds = useMemo(() => ordered.map((j) => j.id), [ordered]);

  // Phase B · Feb-2026 — derive the modal header. ONLY compute a
  // header when the caller is Phase-B-aware (passed
  // ``optimizeTotalMeters``) OR when the operator re-drags/reverses
  // AFTER a Phase-B initialOrder; otherwise fall back to the pre-
  // Phase-B ``optimizeSummary`` prop (backward compat for callers
  // that haven't been migrated yet, including TodaySchedule.jsx's
  // raw-reorder flow which doesn't optimize at all).
  const headerLine = useMemo(() => {
    if (empty) return null;
    // Phase-B-aware path — server totals available.
    if (Number(optimizeTotalMeters) >= 0
        && optimizeTotalMeters != null
        && Number.isFinite(Number(optimizeTotalMeters))) {
      if (matchesServerOrder
          && Number.isFinite(Number(optimizeTotalSeconds))) {
        return _formatHeader(
          Number(optimizeTotalMeters),
          Number(optimizeTotalSeconds),
        );
      }
      const m = totalHaversineMeters(ordered);
      return _formatHeader(m);
    }
    return null;
  }, [empty, matchesServerOrder, ordered,
      optimizeTotalMeters, optimizeTotalSeconds]);

  // Phase B · dropped-job yellow banner — show when the backend
  // indicated some jobs couldn't be geocoded. The matching job
  // objects are hydrated from the ``jobs`` prop for display.
  const droppedBanner = useMemo(() => {
    const ids = Array.isArray(droppedJobIds) ? droppedJobIds : [];
    if (!ids.length) return null;
    const n = ids.length;
    return `${n} job${n > 1 ? "s" : ""} skipped: no address `
      + `coordinates. Visit Admin → Property Geocoding Health to `
      + `backfill.`;
  }, [droppedJobIds]);

  return (
    <div
      ref={overlayRef}
      onClick={(e) => { if (e.target === overlayRef.current) onClose?.(); }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      data-testid="reorder-route-backdrop"
    >
      <div
        className="w-full max-w-xl rounded-2xl overflow-hidden shadow-2xl flex flex-col"
        style={{ background: colors.surface, maxHeight: "80vh" }}
        data-testid="reorder-route-modal"
      >
        <header
          className="px-5 py-3 flex items-center justify-between"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div>
            <div
              className="text-base font-bold"
              style={{ color: colors.onSurface }}
            >
              Reorder route
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              Drag jobs to reorder. Position updates automatically.
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close reorder route"
            data-testid="reorder-route-close"
            style={{ color: colors.muted }}
          >
            <X size={18} />
          </button>
        </header>

        {headerLine ? (
          <div
            className="px-5 py-2 text-xs font-semibold"
            style={{
              background: "#ECFDF5", color: "#065F46",
              borderBottom: `1px solid ${colors.border}`,
            }}
            data-testid="id-optimize-route-summary"
          >
            {headerLine}
          </div>
        ) : optimizeSummary ? (
          <div
            className="px-5 py-2 text-xs font-semibold"
            style={{
              background: "#ECFDF5", color: "#065F46",
              borderBottom: `1px solid ${colors.border}`,
            }}
            data-testid="id-optimize-route-summary"
          >
            {optimizeSummary}
          </div>
        ) : null}
        {droppedBanner ? (
          <div
            className="px-5 py-2 text-xs font-semibold"
            style={{
              background: "#FEF3C7", color: "#92400E",
              borderBottom: `1px solid ${colors.border}`,
            }}
            data-testid="reorder-route-dropped-banner"
          >
            {droppedBanner}
          </div>
        ) : null}
        {isFallback ? (
          <div
            className="px-5 py-2 text-xs font-semibold"
            style={{
              background: "#FEF3C7", color: "#92400E",
              borderBottom: `1px solid ${colors.border}`,
            }}
            data-testid="id-optimize-route-warning"
          >
            Directions unavailable — using Haversine fallback. Review
            order manually before saving.
          </div>
        ) : null}

        <div
          className="px-5 py-3 overflow-y-auto flex flex-col gap-2"
          style={{ flex: 1 }}
        >
          {empty ? (
            <div
              className="text-sm text-center py-6"
              style={{ color: colors.muted }}
              data-testid="reorder-route-empty"
            >
              No jobs scheduled for this day.
            </div>
          ) : (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext
                items={jobIds}
                strategy={verticalListSortingStrategy}
              >
                {ordered.map((j, i) => (
                  <Row
                    key={j.id}
                    job={j}
                    index={i}
                    total={ordered.length}
                    onMoveUp={(id) => moveBy(id, -1)}
                    onMoveDown={(id) => moveBy(id, +1)}
                    disabled={saving}
                  />
                ))}
              </SortableContext>
            </DndContext>
          )}
        </div>

        {/* Screen-reader live region for move announcements. */}
        <div
          aria-live="polite"
          role="status"
          className="sr-only"
          data-testid="reorder-route-live-region"
        >
          {liveMsg}
        </div>

        <footer
          className="px-5 py-3 flex justify-end gap-2"
          style={{
            borderTop: `1px solid ${colors.border}`,
            background: colors.surfaceSecondary,
          }}
        >
          <button
            onClick={onClose}
            disabled={saving}
            className="px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-40"
            style={{ color: colors.muted, background: "transparent" }}
            data-testid="reorder-route-cancel"
          >
            Cancel
          </button>
          {/* Phase B · Feb-2026 — Reverse Order (ghost button). Flips
              the current in-modal sequence. Non-destructive; operator
              still clicks "Save order" to commit. Triggers the same
              client-side haversine recompute path as a drag. */}
          <button
            type="button"
            onClick={reverseOrder}
            disabled={saving || ordered.length < 2}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-40"
            style={{
              background: "transparent",
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="reorder-route-reverse"
            aria-label="Reverse route order"
          >
            <ArrowDownUp size={14} />
            Reverse Order
          </button>
          <button
            onClick={save}
            disabled={saving || empty}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-bold"
            style={{
              background: "#059669", color: "#fff",
              opacity: saving || empty ? 0.45 : 1,
            }}
            data-testid="reorder-route-save"
          >
            <SaveIcon size={14} />
            {saving ? "Saving…" : "Save order"}
          </button>
        </footer>
      </div>
    </div>
  );
}

export default ReorderRouteModal;
