/**
 * Feb-2026 · Schedule DnD Panel
 *
 * Route-order reorder + cross-tech reassign via drag-and-drop for a
 * single day. Rendered below the calendar in Day/Grid mode.
 *
 * UX:
 *   • One column per tech (grouped from the day's jobs).
 *   • Drag a card within its column → PATCHes route_index via
 *     ``POST /api/jobs/reorder``.
 *   • Drag a card across columns → PATCHes ``technician_id`` +
 *     appends to the new tech's list, then reorders both columns.
 *   • Admin / manager / super_admin only. Techs see a read-only list.
 *
 * Backed by ``@dnd-kit/core`` + ``@dnd-kit/sortable`` (already in
 * package.json — no new deps).
 */
import React, { useState, useMemo } from "react";
import {
  DndContext, closestCenter, PointerSensor, useSensor, useSensors,
  DragOverlay,
} from "@dnd-kit/core";
import {
  SortableContext, arrayMove, useSortable, verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, User } from "lucide-react";

import { api } from "@/api";
import { colors, font } from "@/theme";


const UNASSIGNED = "__unassigned__";


function techOfJob(j) {
  return j.tech_user_id || j.assigned_to || j.technician_id || UNASSIGNED;
}


function SortableCard({ job, canDrag, palette }) {
  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({ id: job.id, disabled: !canDrag });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.35 : 1,
    background: palette?.bg || "#fff",
    color: palette?.fg || colors.text,
    border: `1px solid ${colors.border}`,
    borderRadius: 10,
    padding: "8px 10px",
    marginBottom: 6,
    display: "flex", alignItems: "center", gap: 8,
    cursor: canDrag ? "grab" : "default",
    fontSize: 13,
  };
  return (
    <div ref={setNodeRef} style={style}
         data-testid={`dnd-job-${job.id}`}
         {...attributes} {...(canDrag ? listeners : {})}>
      {canDrag ? (
        <GripVertical size={14} style={{ color: colors.muted, flexShrink: 0 }}
                       data-testid={`dnd-grip-${job.id}`} />
      ) : null}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, whiteSpace: "nowrap",
                       textOverflow: "ellipsis", overflow: "hidden" }}>
          {job.title || job.service_type || "Job"}
        </div>
        <div style={{ fontSize: 11, color: colors.muted, whiteSpace: "nowrap",
                       textOverflow: "ellipsis", overflow: "hidden" }}>
          {job.customer_name || job.address || ""}
        </div>
      </div>
    </div>
  );
}


function TechColumn({ techId, techLabel, jobs, canDrag, servicePalette }) {
  return (
    <div
      data-testid={`dnd-tech-column-${techId}`}
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
        borderRadius: 12,
        padding: 10,
        minWidth: 220,
        flex: "1 1 240px",
      }}
    >
      <div style={{
        fontWeight: 700, fontSize: 12, textTransform: "uppercase",
        letterSpacing: 0.4, color: colors.muted, marginBottom: 8,
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <User size={12} /> {techLabel}
        <span style={{ marginLeft: "auto", fontWeight: 500 }}>
          {jobs.length}
        </span>
      </div>
      <SortableContext items={jobs.map((j) => j.id)}
                       strategy={verticalListSortingStrategy}>
        {jobs.map((j) => (
          <SortableCard key={j.id} job={j} canDrag={canDrag}
                         palette={servicePalette?.(j.service_type)} />
        ))}
        {jobs.length === 0 ? (
          <div style={{ fontSize: 12, color: colors.muted, fontStyle: "italic",
                        padding: "12px 4px" }}>
            (drop here to reassign)
          </div>
        ) : null}
      </SortableContext>
    </div>
  );
}


export default function ScheduleDayDnDPanel({
  date, jobs, techs, canDrag, toast, onSaved, servicePalette,
}) {
  // Group jobs by tech.
  const initialGrouped = useMemo(() => {
    const map = {};
    for (const j of jobs) {
      const t = techOfJob(j);
      (map[t] = map[t] || []).push(j);
    }
    for (const t of Object.keys(map)) {
      map[t].sort((a, b) => (a.route_index ?? 999) - (b.route_index ?? 999));
    }
    return map;
  }, [jobs]);

  const [grouped, setGrouped] = useState(initialGrouped);
  React.useEffect(() => { setGrouped(initialGrouped); }, [initialGrouped]);

  const [activeId, setActiveId] = useState(null);
  const sensors = useSensors(useSensor(PointerSensor, {
    activationConstraint: { distance: 5 },
  }));

  const techLabel = React.useCallback((tid) => {
    if (tid === UNASSIGNED) return "Unassigned";
    const t = techs.find((x) => x.id === tid || x.user_id === tid);
    return t?.name || t?.full_name || t?.email || "Unknown";
  }, [techs]);

  // Locate which column contains a given job id.
  const findColumnOf = React.useCallback((id) => {
    for (const t of Object.keys(grouped)) {
      if (grouped[t].some((j) => j.id === id)) return t;
    }
    return null;
  }, [grouped]);

  const persistReorder = async (techId, orderedJobIds) => {
    // Skip persistence for the synthetic Unassigned column.
    if (techId === UNASSIGNED) return;
    try {
      const r = await api.post("/jobs/reorder", {
        tech_user_id: techId, date,
        ordered_job_ids: orderedJobIds,
      });
      toast?.(`Route saved · ${r.updated}/${r.expected} jobs`);
      onSaved?.();
    } catch (e) {
      toast?.(`Reorder failed: ${e.message || e}`, "err");
      // Rollback to server truth.
      onSaved?.();
    }
  };

  const persistTechChange = async (jobId, newTechId, newOrderedIds) => {
    if (newTechId === UNASSIGNED) return;
    try {
      await api.patch(`/jobs/${jobId}`, { technician_id: newTechId,
                                            tech_user_id: newTechId });
      await api.post("/jobs/reorder", {
        tech_user_id: newTechId, date,
        ordered_job_ids: newOrderedIds,
      });
      toast?.(`Reassigned to ${techLabel(newTechId)}`);
      onSaved?.();
    } catch (e) {
      toast?.(`Reassign failed: ${e.message || e}`, "err");
      onSaved?.();
    }
  };

  const onDragStart = ({ active }) => setActiveId(active.id);
  const onDragEnd = ({ active, over }) => {
    setActiveId(null);
    if (!over) return;
    if (!canDrag) return;
    const fromTech = findColumnOf(active.id);
    // ``over.id`` is either a job id or a tech column id (SortableContext id).
    let toTech = findColumnOf(over.id);
    if (!toTech && Object.prototype.hasOwnProperty.call(grouped, over.id)) {
      toTech = over.id;
    }
    if (!fromTech || !toTech) return;

    if (fromTech === toTech) {
      const col = grouped[fromTech];
      const oldIdx = col.findIndex((j) => j.id === active.id);
      const newIdx = col.findIndex((j) => j.id === over.id);
      if (oldIdx === newIdx || oldIdx < 0 || newIdx < 0) return;
      const reordered = arrayMove(col, oldIdx, newIdx);
      setGrouped((cur) => ({ ...cur, [fromTech]: reordered }));
      persistReorder(fromTech, reordered.map((j) => j.id));
    } else {
      // Cross-tech drag.
      const fromCol = grouped[fromTech];
      const toCol = grouped[toTech] || [];
      const moved = fromCol.find((j) => j.id === active.id);
      if (!moved) return;
      const newFrom = fromCol.filter((j) => j.id !== active.id);
      // Append to end of destination.
      const newTo = [...toCol, { ...moved, tech_user_id: toTech,
                                    technician_id: toTech }];
      setGrouped((cur) => ({ ...cur, [fromTech]: newFrom, [toTech]: newTo }));
      persistTechChange(active.id, toTech, newTo.map((j) => j.id));
      // Also renumber the source column.
      if (newFrom.length) {
        persistReorder(fromTech, newFrom.map((j) => j.id));
      }
    }
  };

  const columns = Object.keys(grouped).sort((a, b) => {
    if (a === UNASSIGNED) return 1;
    if (b === UNASSIGNED) return -1;
    return techLabel(a).localeCompare(techLabel(b));
  });

  const activeJob = activeId
    ? Object.values(grouped).flat().find((j) => j.id === activeId)
    : null;

  if (!columns.length) return null;

  return (
    <div data-testid="schedule-dnd-panel" style={{ marginTop: 12 }}>
      <div style={{ fontFamily: font.family, fontSize: 12,
                     color: colors.muted, marginBottom: 8,
                     textTransform: "uppercase", letterSpacing: 0.5 }}>
        Route order · drag to reorder within a tech, drop across techs
        to reassign
      </div>
      <DndContext sensors={sensors} collisionDetection={closestCenter}
                   onDragStart={onDragStart} onDragEnd={onDragEnd}>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap",
                       alignItems: "flex-start" }}>
          {columns.map((tid) => (
            <TechColumn key={tid} techId={tid} techLabel={techLabel(tid)}
                         jobs={grouped[tid]} canDrag={canDrag}
                         servicePalette={servicePalette} />
          ))}
        </div>
        <DragOverlay>
          {activeJob ? (
            <div style={{ background: "#fff", border: `1px solid ${colors.brand}`,
                           borderRadius: 10, padding: "8px 10px",
                           boxShadow: "0 8px 20px rgba(0,0,0,0.12)",
                           minWidth: 200, fontSize: 13, fontWeight: 600 }}>
              {activeJob.title || activeJob.service_type || "Job"}
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}
