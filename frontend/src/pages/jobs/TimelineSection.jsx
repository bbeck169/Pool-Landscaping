/**
 * Slice M5 · Job Timeline section.
 *
 * Reads the workstream_events slice from GET /api/jobs/{id}/detail
 * so no separate roundtrip is needed on the Job Detail page.  The
 * parent component fetches once and passes the events array in;
 * this component is purely presentational.
 */
import React from "react";
import { Clock, User } from "lucide-react";
import { colors } from "@/theme";

function relTime(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

export default function TimelineSection({ events = [] }) {
  return (
    <div
      className="rounded-2xl p-6 mb-4"
      style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="job-timeline-section"
    >
      <div className="flex items-center gap-2 mb-3">
        <Clock size={16} color={colors.brand} />
        <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>
          Timeline
        </h3>
      </div>
      {events.length === 0 ? (
        <div
          className="p-6 text-sm text-center rounded-lg"
          style={{ background: colors.surfaceSecondary, color: colors.muted }}
          data-testid="timeline-empty"
        >
          No workstream events yet.
        </div>
      ) : (
        <ol className="space-y-3" data-testid="timeline-list">
          {events.map((ev) => (
            <li
              key={ev.id}
              className="flex items-start gap-3"
              data-testid={`timeline-item-${ev.id}`}
            >
              <div
                className="mt-1 flex-none rounded-full"
                style={{
                  width: 8,
                  height: 8,
                  background: colors.brand,
                }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="flex items-center gap-2 flex-wrap">
                  <div
                    className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded-full whitespace-nowrap"
                    style={{ background: colors.brandTertiary, color: colors.onBrandTertiary }}
                  >
                    {ev.type}
                  </div>
                  <div
                    className="text-[11px] inline-flex items-center gap-1"
                    style={{ color: colors.muted }}
                  >
                    <User size={10} /> {ev.actor_role || "system"}
                  </div>
                </div>
                {ev.payload && Object.keys(ev.payload).length ? (
                  <div className="text-xs mt-1" style={{ color: colors.onSurfaceSecondary }}>
                    {[
                      ev.payload.customer_name,
                      ev.payload.tech_name && `by ${ev.payload.tech_name}`,
                      ev.payload.template && `tpl:${ev.payload.template}`,
                      ev.payload.chemicals_added_count != null && `${ev.payload.chemicals_added_count} chem`,
                      ev.payload.photos_count != null && `${ev.payload.photos_count} photos`,
                    ].filter(Boolean).join(" · ")}
                  </div>
                ) : null}
              </div>
              <div
                className="text-[11px] whitespace-nowrap"
                style={{ color: colors.muted }}
                title={ev.created_at}
              >
                {relTime(ev.created_at)}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
