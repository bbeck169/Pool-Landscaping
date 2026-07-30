// Phase 17 · Feb-2026 — Route Details list with lightweight native
// HTML5 drag-and-drop reordering. We avoid pulling a full DnD lib
// because the list is <=30 items and reorder is a single mutation.
import React from "react";
import { GripVertical, MapPin, X } from "lucide-react";
import { colors } from "@/theme";
import formatAddress from "@/utils/formatAddress";

export default function RouteDetailsList({
  stops = [],
  onReorder = () => {},
  onRemove = () => {},
  onSelect = () => {},
  activeCustomerId = null,
  disabled = false,
}) {
  const [dragIdx, setDragIdx] = React.useState(null);
  const [overIdx, setOverIdx] = React.useState(null);

  if (!stops.length) {
    return (
      <div
        className="rounded-xl p-6 text-center text-sm"
        style={{
          border: `1px dashed ${colors.border}`,
          color: colors.muted,
          backgroundColor: colors.surfaceSecondary,
        }}
        data-testid="dispatch-route-details-empty"
      >
        No stops assigned yet. Pick a day + tech to load the sequence.
      </div>
    );
  }

  const move = (from, to) => {
    if (from === to || from == null || to == null) return;
    const next = stops.slice();
    const [it] = next.splice(from, 1);
    next.splice(to, 0, it);
    onReorder(next.map((s) => s.customer_id));
  };

  return (
    <ol
      className="space-y-2"
      data-testid="dispatch-route-details-list"
      aria-label="Route sequence"
    >
      {stops.map((s, idx) => {
        const isActive = activeCustomerId === s.customer_id;
        const isDragOver = overIdx === idx && dragIdx !== null && dragIdx !== idx;
        return (
          <li
            key={s.customer_id}
            draggable={!disabled}
            onDragStart={(e) => {
              if (disabled) return;
              setDragIdx(idx);
              try { e.dataTransfer.effectAllowed = "move"; } catch { /* jsdom */ }
            }}
            onDragEnter={() => setOverIdx(idx)}
            onDragOver={(e) => { e.preventDefault(); }}
            onDrop={(e) => {
              e.preventDefault();
              move(dragIdx, idx);
              setDragIdx(null); setOverIdx(null);
            }}
            onDragEnd={() => { setDragIdx(null); setOverIdx(null); }}
            onClick={() => onSelect(s.customer_id)}
            className="flex items-center gap-3 rounded-xl px-3 py-3 cursor-pointer transition"
            style={{
              backgroundColor: isActive ? "#DBEAFE" : "#EFF6FF",
              border: `1px solid ${isDragOver ? "#0EA5E9" : (isActive ? "#93C5FD" : "#DBEAFE")}`,
              boxShadow: isDragOver ? "0 0 0 2px #0EA5E9 inset" : "none",
              opacity: dragIdx === idx ? 0.55 : 1,
            }}
            data-testid={`dispatch-route-stop-${s.customer_id}`}
          >
            <span
              aria-hidden
              style={{ color: "#1D4ED8" }}
              data-testid={`dispatch-route-drag-${s.customer_id}`}
            >
              <GripVertical size={16} />
            </span>
            <span
              className="flex items-center justify-center rounded-full font-bold text-xs"
              style={{
                width: 22, height: 22,
                background: "#1D4ED8", color: "#fff",
              }}
              data-testid={`dispatch-route-index-${s.customer_id}`}
            >
              {idx + 1}
            </span>
            <div className="flex-1 min-w-0">
              <div
                className="text-sm font-semibold truncate"
                style={{ color: "#1E3A8A" }}
              >
                {s.name || "(unnamed)"}
              </div>
              <div
                className="text-xs truncate flex items-center gap-1"
                style={{ color: "#1E40AF" }}
              >
                <MapPin size={11} />
                {formatAddress(s.address) || "No address"}
              </div>
            </div>
            {!disabled && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onRemove(s.customer_id); }}
                aria-label="Remove stop"
                data-testid={`dispatch-route-remove-${s.customer_id}`}
                className="p-1 rounded-md hover:brightness-95"
                style={{
                  color: "#1D4ED8",
                  backgroundColor: "transparent",
                }}
              >
                <X size={14} />
              </button>
            )}
          </li>
        );
      })}
    </ol>
  );
}
