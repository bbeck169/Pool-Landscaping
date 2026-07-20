import React, { useState } from "react";
import { Star } from "lucide-react";

/**
 * Interactive 5-star picker used on the public review-request landing
 * page. Hover previews are honored on pointer devices; touch devices
 * commit on tap.
 *
 *   <StarRatingInput value={0} onChange={(n) => setStar(n)} size={40} />
 */
export function StarRatingInput({ value = 0, onChange, size = 36,
                                    color = "#F59E0B", bgColor = "#D1D5DB",
                                    disabled = false, testid = "star-input" }) {
  const [hover, setHover] = useState(0);
  const paint = hover || value;
  const stars = [1, 2, 3, 4, 5];
  return (
    <div className="inline-flex items-center gap-1" data-testid={testid}
          onMouseLeave={() => setHover(0)}>
      {stars.map((i) => {
        const active = i <= paint;
        return (
          <button
            key={i}
            type="button"
            disabled={disabled}
            onMouseEnter={() => setHover(i)}
            onClick={() => !disabled && onChange && onChange(i)}
            className="p-1 rounded-full transition-transform disabled:opacity-40"
            style={{
              transform: active ? "scale(1.08)" : "scale(1)",
              cursor: disabled ? "not-allowed" : "pointer",
              background: "transparent",
              border: "none",
            }}
            aria-label={`${i} star`}
            data-testid={`${testid}-btn-${i}`}
          >
            <Star size={size}
                   fill={active ? color : "none"}
                   style={{ color: active ? color : bgColor }} />
          </button>
        );
      })}
    </div>
  );
}

export default StarRatingInput;
