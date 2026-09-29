/**
 * Phase 5A · Customer portal — shareable videos surface (Feb 2026 fix).
 *
 * Parallel to ``PortalPhotos.jsx``. Consumes ``GET /api/portal/videos``
 * (server-side filters ``visibility=="customer" AND !is_deleted``),
 * groups the results by parent entity, and streams playback through
 * ``/api/media/videos/{path}?auth={token}`` — same proxy the admin
 * MediaUploader uses.
 *
 * DTP-2 · Feb-2026 — the pre-DTP-2 inline lightbox modal has been
 * retired in favour of the shared ``<Lightbox>`` component so the
 * portal-dark palette, ESC / arrow-key nav, focus-trap, and
 * title/counter chrome are inherited from a single source.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Film, Play, Video } from "lucide-react";
import { api, api_base, TOKEN_KEY } from "@/api";
import { portalColors as colors } from "@/theme";
import Lightbox from "@/components/portal/Lightbox";

function bytesLabel(n) {
  if (!n) return "";
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function durationLabel(s) {
  if (s == null) return "";
  const total = Math.max(0, Math.round(Number(s)));
  const m = Math.floor(total / 60);
  const r = total % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

function tokenizedSrc(path) {
  const token = localStorage.getItem(TOKEN_KEY) || "";
  return `${api_base()}/media/videos/${path}?auth=${encodeURIComponent(token)}`;
}

export default function PortalVideos() {
  const [data, setData] = useState({ videos: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [lightboxIdx, setLightboxIdx] = useState(null);

  useEffect(() => {
    setLoading(true);
    api.get("/portal/videos")
      .then((d) => { setData(d || { videos: [], total: 0 }); setLoading(false); })
      .catch(() => { setData({ videos: [], total: 0 }); setLoading(false); });
  }, []);

  // Group by parent entity so the customer sees which job/estimate the
  // clip belongs to. Order groups newest-first by their newest video.
  const groups = useMemo(() => {
    const map = new Map();
    for (const v of (data.videos || [])) {
      const key = `${v.kind}:${v.entity_id}`;
      if (!map.has(key)) {
        map.set(key, {
          kind: v.kind,
          entity_id: v.entity_id,
          entity_title: v.entity_title,
          job_scheduled_date: v.job_scheduled_date,
          videos: [],
        });
      }
      map.get(key).videos.push(v);
    }
    const arr = Array.from(map.values());
    arr.sort((a, b) => {
      const ax = a.videos[0]?.uploaded_at || "";
      const bx = b.videos[0]?.uploaded_at || "";
      return bx.localeCompare(ax);
    });
    return arr;
  }, [data]);

  // Flat ordered list of playable clips — the shared <Lightbox> steps
  // through this sequence when the user hits ArrowLeft / ArrowRight.
  const orderedVideos = useMemo(() => {
    const flat = [];
    for (const g of groups) {
      for (const v of g.videos) {
        flat.push({
          url:      tokenizedSrc(v.storage_path),
          kind:     "video",
          title:    v.caption || g.entity_title || "",
          subtitle: [
            g.kind === "estimate" ? "Estimate" : "Job",
            g.job_scheduled_date ? g.job_scheduled_date.slice(0, 10) : "",
          ].filter(Boolean).join(" · "),
        });
      }
    }
    return flat;
  }, [groups]);

  // Given a group + inner video index, resolve the corresponding slot
  // inside the flat ``orderedVideos`` list.
  const indexFor = (groupKey, innerIdx) => {
    let acc = 0;
    for (const g of groups) {
      const key = `${g.kind}:${g.entity_id}`;
      if (key === groupKey) return acc + innerIdx;
      acc += g.videos.length;
    }
    return acc;
  };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="portal-videos-page">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-1">
          <Film size={22} style={{ color: colors.brand }} />
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
            Service Videos
          </h1>
        </div>
        <p className="text-sm" style={{ color: colors.muted }}>
          Every video shared with you by our team — {data.total} total.
        </p>
      </div>

      {loading ? (
        <div className="text-sm py-16 text-center" style={{ color: colors.muted }}
             data-testid="portal-videos-loading">
          Loading videos…
        </div>
      ) : groups.length === 0 ? (
        <div className="text-center py-20 rounded-2xl"
             style={{ backgroundColor: colors.surface, border: `1px dashed ${colors.border}` }}
             data-testid="portal-videos-empty">
          <Video size={40} className="mx-auto mb-3" style={{ color: colors.muted }} />
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            No videos shared yet
          </div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>
            When our team shares a video from a job or estimate, it will appear here.
          </div>
        </div>
      ) : (
        (() => {
          // Phase 34 · Feb 2026 — additional grouping by date on top of
          // the existing entity-groups. Each date header + horizontal
          // divider separates entity-groups whose ``job_scheduled_date``
          // (fall back: earliest video ``uploaded_at``) falls on a
          // different day. Newest date first; original per-entity
          // rendering unchanged.
          const dayOf = (g) => {
            const d = g.job_scheduled_date
              || (g.videos && g.videos[0] && g.videos[0].uploaded_at)
              || "";
            return d.slice(0, 10) || "Unknown date";
          };
          const byDay = new Map();
          for (const g of groups) {
            const d = dayOf(g);
            if (!byDay.has(d)) byDay.set(d, []);
            byDay.get(d).push(g);
          }
          const dayKeys = Array.from(byDay.keys()).sort((a, b) => b.localeCompare(a));
          const fmtHeader = (d) => {
            if (d === "Unknown date") return d;
            try {
              return new Date(d + "T00:00:00").toLocaleDateString(undefined,
                { weekday: "long", month: "short", day: "numeric", year: "numeric" });
            } catch { return d; }
          };
          return (
            <div data-testid="portal-videos-grouped">
              {dayKeys.map((day, di) => (
                <div key={day} data-testid={`portal-videos-date-group-${day}`}
                     className={di > 0 ? "pt-6 mt-6" : ""}
                     style={di > 0 ? { borderTop: `1px solid ${colors.border}` } : {}}>
                  <h2 className="text-sm font-bold mb-3"
                      style={{ color: colors.onSurface }}
                      data-testid={`portal-videos-date-header-${day}`}>
                    {fmtHeader(day)}
                  </h2>
                  <div className="space-y-6" data-testid="portal-videos-groups">
                    {byDay.get(day).map((g) => {
                      const groupKey = `${g.kind}:${g.entity_id}`;
                      return (
                        <section key={groupKey}
                                 className="rounded-2xl p-5"
                                 style={{ backgroundColor: colors.surface,
                                          border: `1px solid ${colors.border}` }}
                                 data-testid={`portal-video-group-${g.entity_id}`}>
                          <div className="flex items-baseline gap-2 mb-3">
                            <h3 className="text-base font-bold" style={{ color: colors.onSurface }}>
                              {g.entity_title}
                            </h3>
                            <span className="text-[11px] uppercase tracking-wider font-semibold"
                                  style={{ color: colors.muted }}>
                              {g.kind === "estimate" ? "Estimate" : "Job"}
                              {g.job_scheduled_date ? ` · ${g.job_scheduled_date.slice(0, 10)}` : ""}
                            </span>
                          </div>
                          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                            {g.videos.map((v, i) => (
                              <PortalVideoTile
                                key={v.video_id}
                                video={v}
                                onPlay={() => setLightboxIdx(indexFor(groupKey, i))}
                              />
                            ))}
                          </div>
                        </section>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          );
        })()
      )}

      {/* DTP-2 · Feb-2026 — shared portal Lightbox in place of the
          pre-DTP-2 inline modal.  ``testidPrefix`` retains the
          legacy ``portal-video-lightbox`` selectors so downstream
          tests keep resolving. */}
      <Lightbox
        items={orderedVideos}
        initialIndex={lightboxIdx == null ? 0 : lightboxIdx}
        open={lightboxIdx !== null}
        onClose={() => setLightboxIdx(null)}
        testidPrefix="portal-video-lightbox"
      />
    </div>
  );
}

function PortalVideoTile({ video, onPlay }) {
  const src = tokenizedSrc(video.storage_path);
  return (
    <div className="rounded-xl overflow-hidden"
         style={{ backgroundColor: colors.surfaceSecondary,
                  border: `1px solid ${colors.border}` }}
         data-testid={`portal-video-tile-${video.video_id}`}>
      <div className="relative aspect-video bg-black">
        <video preload="metadata" src={src}
               className="w-full h-full object-cover"
               data-testid={`portal-video-el-${video.video_id}`} />
        <button type="button"
                onClick={onPlay}
                className="absolute inset-0 flex items-center justify-center cursor-pointer"
                style={{ background: "rgba(0,0,0,0.15)" }}
                aria-label="Play video"
                data-testid={`portal-video-play-${video.video_id}`}>
          <span className="rounded-full p-3"
                style={{ background: "rgba(0,0,0,0.65)" }}>
            <Play size={20} color="#fff" />
          </span>
        </button>
      </div>
      <div className="p-2.5">
        {video.caption ? (
          <p className="text-xs mb-1.5" style={{ color: colors.onSurface }}>
            {video.caption}
          </p>
        ) : null}
        <p className="text-[11px]" style={{ color: colors.muted }}>
          {bytesLabel(video.size_bytes)}
          {video.duration_seconds ? ` · ${durationLabel(video.duration_seconds)}` : ""}
          {video.uploaded_by_name ? ` · ${video.uploaded_by_name}` : ""}
        </p>
        <p className="text-[10px] mt-0.5" style={{ color: colors.muted }}>
          {(video.uploaded_at || "").slice(0, 10)}
        </p>
      </div>
    </div>
  );
}
