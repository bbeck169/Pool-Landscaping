import React from "react";
import { Star } from "lucide-react";

/**
 * Reusable star row for read-only display. Supports fractional stars
 * (avg values like 4.3) via a two-layer painter: a grey background of
 * 5 empty stars plus a clipped amber overlay.
 *
 *   <StarRatingDisplay value={4.3} size={18} />
 */
export function StarRatingDisplay({ value = 0, size = 16, color = "#F59E0B",
                                     bgColor = "#D1D5DB", showValue = false,
                                     testid }) {
  const v = Math.max(0, Math.min(5, Number(value) || 0));
  const pct = (v / 5) * 100;
  const stars = [0, 1, 2, 3, 4];
  return (
    <span className="inline-flex items-center gap-2" data-testid={testid}>
      <span className="relative inline-flex" aria-label={`${v} out of 5 stars`}>
        <span className="flex" style={{ gap: 2 }}>
          {stars.map((i) => (
            <Star key={i} size={size} style={{ color: bgColor }} />
          ))}
        </span>
        <span className="absolute top-0 left-0 flex overflow-hidden"
               style={{ gap: 2, width: `${pct}%` }}>
          {stars.map((i) => (
            <Star key={i} size={size} fill={color}
                   style={{ color, minWidth: size }} />
          ))}
        </span>
      </span>
      {showValue ? (
        <span className="text-sm font-semibold" style={{ color: "inherit" }}>
          {v.toFixed(1)}
        </span>
      ) : null}
    </span>
  );
}

export default StarRatingDisplay;
