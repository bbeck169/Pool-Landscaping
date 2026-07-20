import React from "react";
import { colors } from "@/theme";
import { StarRatingDisplay } from "@/components/reviews/StarRatingDisplay";
import { PlatformIcon } from "@/components/reviews/PlatformIcon";

/**
 * Compact review tile used in the admin dashboard + widget preview.
 * Accepts a raw ``reviews`` doc:
 *   { star_rating, review_text, reviewer_name, platform, created_at }
 */
export function ReviewCard({ review, showPlatform = true, className = "",
                              testid }) {
  const r = review || {};
  const when = (r.created_at || "").slice(0, 10);
  return (
    <div className={`rounded-2xl p-4 ${className}`}
          style={{ background: colors.surface,
                   border: `1px solid ${colors.border}` }}
          data-testid={testid}>
      <div className="flex items-center justify-between mb-2">
        <StarRatingDisplay value={r.star_rating || 0} size={16} />
        {showPlatform && r.platform ? (
          <span className="inline-flex items-center gap-1.5 text-xs font-semibold"
                 style={{ color: colors.muted }}>
            <PlatformIcon code={r.platform} size={14} />
            <span className="capitalize">{r.platform}</span>
          </span>
        ) : null}
      </div>
      {r.review_text ? (
        <div className="text-sm leading-relaxed mb-3"
             style={{ color: colors.onSurface }}>
          {r.review_text}
        </div>
      ) : (
        <div className="text-sm italic mb-3" style={{ color: colors.muted }}>
          No written review — star rating only.
        </div>
      )}
      <div className="text-xs" style={{ color: colors.muted }}>
        {r.reviewer_name || "Anonymous"}{when ? ` · ${when}` : ""}
      </div>
    </div>
  );
}

export default ReviewCard;
