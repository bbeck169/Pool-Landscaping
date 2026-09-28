/**
 * SO-A · Feb-2026 — "Best Fit" green sparkle for the tech
 * assignment dropdown.
 *
 * Rendered next to a tech's name when the active recommendation
 * ranks that tech #1.  Consumer supplies a ``recommendation``
 * object (the /schedule/ai-recommendation response payload) and
 * the ``technicianId`` we're evaluating.
 */
import React from "react";
import { Sparkles } from "lucide-react";

export function BestFitSpark({ recommendation, technicianId }) {
  if (!recommendation || !recommendation.suggestions
      || recommendation.suggestions.length === 0) {
    return null;
  }
  const top = recommendation.suggestions[0];
  if (!top || top.technician_id !== technicianId) return null;
  const detour = Number.isFinite(top.detour_minutes)
    ? top.detour_minutes.toFixed(1)
    : "?";
  return (
    <span
      className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded"
      style={{ background: "#DCFCE7", color: "#166534",
                border: "1px solid #BBF7D0" }}
      title={`Best fit per MARCO — +${detour} min detour`}
      data-testid={`best-fit-spark-${technicianId}`}
    >
      <Sparkles size={12} />
      <span data-testid={`best-fit-spark-detour-${technicianId}`}>
        +{detour}m
      </span>
    </span>
  );
}

export default BestFitSpark;
