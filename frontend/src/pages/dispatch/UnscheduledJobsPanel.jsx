// Phase 4 · Feb-2026 — Unscheduled jobs panel (drag source).
//
// Lists tenant jobs with no tech and no scheduled_date. Each row is
// a dnd-kit `useDraggable` source (id = "unsched:<jobId>") so the
// parent Dispatch Board's DndContext can wire drop targets. Each row
// also carries a fallback "Assign" button that opens the popup
// modal handled by the parent.
import React from "react";
import { useDraggable } from "@dnd-kit/core";
import {
  Package, MapPin, PlusCircle, AlertCircle, ChevronDown, ChevronUp,
} from "lucide-react";
import { colors } from "@/theme";
import formatAddress from "@/utils/formatAddress";

function DraggableJobRow({ job, onAssignClick, previewKm, previewMissing }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `unsched:${job.id}`,
    data: { kind: "unscheduled-job", jobId: job.id, title: job.title,
             hasCoords: job.has_coords },
  });
  // Phase 10 · sub-item E — preview pill colour bucket.
  let pill = null;
  if (previewMissing) {
    pill = { label: "no coords", bg: "#F1F5F9", fg: "#475569", border: "#CBD5E1" };
  } else if (typeof previewKm === "number") {
    const km = previewKm;
    if (km <= 5) pill = { label: `+${km.toFixed(1)} km`, bg: "#DCFCE7", fg: "#166534", border: "#BBF7D0" };
    else if (km <= 15) pill = { label: `+${km.toFixed(1)} km`, bg: "#FEF3C7", fg: "#92400E", border: "#FDE68A" };
    else pill = { label: `+${km.toFixed(1)} km`, bg: "#FEE2E2", fg: "#991B1B", border: "#FECACA" };
  }
  return (
    <li
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className="rounded-lg p-2 cursor-grab select-none transition"
      style={{
        backgroundColor: colors.surfaceSecondary,
        border: `1px solid ${isDragging ? colors.brand : colors.border}`,
        opacity: isDragging ? 0.5 : 1,
      }}
      data-testid={`dispatch-unsched-job-row-${job.id}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <div className="text-xs font-semibold truncate"
                  style={{ color: colors.onSurface }}>
              {job.title || "(untitled)"}
            </div>
            {pill ? (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full shrink-0"
                     style={{ backgroundColor: pill.bg, color: pill.fg,
                               border: `1px solid ${pill.border}` }}
                     data-testid={`dispatch-unsched-preview-${job.id}`}>
                {pill.label}
              </span>
            ) : null}
          </div>
          <div className="text-[11px] flex items-center gap-1 truncate"
                style={{ color: colors.muted }}>
            <MapPin size={10} />
            {formatAddress(job.address) || "No address"}
          </div>
          {!job.has_coords ? (
            <div className="text-[10px] mt-0.5 flex items-center gap-1"
                  style={{ color: "#B45309" }}
                  data-testid={`dispatch-unsched-nocoords-${job.id}`}>
              <AlertCircle size={10} />
              No coords — geocode before scheduling
            </div>
          ) : null}
        </div>
        <button
          type="button"
          onClick={(e) => {
            // Prevent dnd-kit from starting a drag on button clicks.
            e.stopPropagation();
            e.preventDefault();
            onAssignClick(job);
          }}
          onPointerDown={(e) => e.stopPropagation()}
          className="text-[11px] font-semibold px-1.5 py-0.5 rounded-md hover:brightness-95 flex items-center gap-1 shrink-0"
          style={{
            backgroundColor: colors.brand, color: "#fff",
          }}
          data-testid={`dispatch-unsched-assign-${job.id}`}
        >
          <PlusCircle size={10} /> Assign
        </button>
      </div>
    </li>
  );
}

export default function UnscheduledJobsPanel({
  jobs = [],
  onAssignClick = () => {},
  previewsById = {},
}) {
  const [open, setOpen] = React.useState(true);
  if (!jobs.length) {
    return (
      <div
        className="rounded-xl p-3"
        style={{ backgroundColor: colors.surface,
                  border: `1px solid ${colors.border}` }}
        data-testid="dispatch-unsched-jobs-empty"
      >
        <div className="text-xs uppercase tracking-wide font-semibold mb-1 flex items-center gap-1"
              style={{ color: colors.muted }}>
          <Package size={12} /> Unscheduled jobs (0)
        </div>
        <div className="text-xs" style={{ color: colors.muted }}>
          Every job in the pipeline is scheduled. Nice.
        </div>
      </div>
    );
  }
  return (
    <div
      className="rounded-xl p-3 space-y-2"
      style={{ backgroundColor: colors.surface,
                border: `1px solid ${colors.border}` }}
      data-testid="dispatch-unsched-jobs-panel"
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between text-xs uppercase tracking-wide font-semibold"
        style={{ color: colors.muted }}
        data-testid="dispatch-unsched-jobs-toggle"
      >
        <span className="flex items-center gap-1">
          <Package size={12} /> Unscheduled jobs
          <span
            className="ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-bold"
            style={{ backgroundColor: "#0EA5E9", color: "#fff" }}
            data-testid="dispatch-unsched-jobs-count"
          >
            {jobs.length}
          </span>
        </span>
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && (
        <ul className="space-y-1.5" data-testid="dispatch-unsched-jobs-list">
          {jobs.map((j) => {
            const p = previewsById[j.id];
            return (
              <DraggableJobRow key={j.id} job={j}
                                 onAssignClick={onAssignClick}
                                 previewKm={p?.added_distance_km ?? null}
                                 previewMissing={!!p?.currently_missing_coords} />
            );
          })}
        </ul>
      )}
      <div className="text-[10px] italic" style={{ color: colors.muted }}>
        Drag a job onto the highlighted day cell, or use Assign.
      </div>
    </div>
  );
}
