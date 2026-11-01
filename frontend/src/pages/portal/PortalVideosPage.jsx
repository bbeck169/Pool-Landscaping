/**
 * Portal Videos · Feb-2026
 *
 * Videos from submitted service reports (poster on grid tile, streaming
 * inline in a modal). Backend: GET /api/portal/videos — currently the
 * only video source is db.service_reports[].videos.
 *
 * DTP-2 · Feb-2026 — migrated to the shared ``<Lightbox>`` component so
 * the modal player inherits the portal-dark palette, ESC + arrow-key
 * nav, focus-trap, and title/counter chrome. The legacy inline modal
 * has been retired.
 *
 * TD-portal-videos-page-wire-grouping · Feb-2026 — mirrors the
 * `bbecd6da1` Photos fix: adopts the shared grouping helper so
 * the active page renders labeled date-divider headers between
 * calendar-day groups (newest first).  Grouping uses the
 * customer's BROWSER timezone, consistent with the shipped
 * portal convention and the Photos page's identical pattern.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Video as VideoIcon, Play } from "lucide-react";
import { portalColors as colors } from "@/theme";
import { api } from "@/api";
import { Skeleton } from "@/components/ui-kit";
import Lightbox from "@/components/portal/Lightbox";
// Phase 18b · Feb-2026 — Portal white-card shell. Wraps the
// export(s) in this file so content renders inside the Phase
// 3d-portal white dashboard card on the deep-navy page bg.
import PortalPageShell from "@/components/portal/PortalPageShell";
// TD-portal-videos-page-wire-grouping · Feb-2026 — shared helpers.
import {
  groupVideosByDateAndVisit,
  flattenGrouped,
} from "./_photoGrouping";


const PAGE = 24;

function resolveUrl(rel) {
  if (!rel) return "";
  if (rel.startsWith("http")) return rel;
  const base = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
  return `${base}${rel}`;
}

function fmtDuration(secs) {
  if (!secs || Number.isNaN(secs)) return "";
  const s = Math.round(Number(secs));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

export default function PortalVideosPage() {
  const [items, setItems] = useState(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [selectedIdx, setSelectedIdx] = useState(null);
  const [err, setErr] = useState("");

  const load = async (nextOffset) => {
    try {
      const res = await api.get(`/portal/videos?limit=${PAGE}&offset=${nextOffset}`);
      setTotal(res.total || 0);
      // TD-67 · Feb-2026 — BE emits ``videos`` (see
      // ``routers/portal_videos.py``). Pre-TD-67 the FE read
      // ``res.items`` which never existed on this payload — items
      // was always undefined, every portal customer saw "No videos
      // yet" regardless of actual history. ``items`` kept as a
      // defensive secondary fallback for a future wire-shape
      // convergence.
      const nextRows = res.videos || res.items || [];
      setItems((prev) => (nextOffset === 0 ? nextRows : [...(prev || []), ...nextRows]));
    } catch (e) {
      setErr(e?.message || "Failed to load videos.");
      setItems([]);
    }
  };

  useEffect(() => { load(0); }, []); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3 mount-only + explicit param deps

  const loadMore = () => {
    const next = offset + PAGE;
    setOffset(next);
    load(next);
  };

  // TD-portal-videos-page-wire-grouping · Feb-2026 — mirror of
  // the Photos pattern.  ``items`` is the flat BE-sorted list
  // (DESC ``uploaded_at`` per ``routers/portal_videos.py:30``).
  // ``groups`` is the grouped-by-calendar-day tree the shared
  // ``groupVideosByDateAndVisit`` adapter produces (delegates to
  // the Photos helper after field-mapping).  ``orderedVideos``
  // is the same flat stream the shared ``<Lightbox>`` consumes,
  // iterated via the group → visit → photo order the helper
  // produced — guaranteeing a tile's ``startIndex + j`` click
  // resolves to the right lightbox index.  Rebucketing on every
  // ``items`` change means trailing + leading same-day items
  // across ``Load more`` pages fuse into one group — no
  // duplicate dividers.
  const groups = useMemo(
    () => groupVideosByDateAndVisit(items || []),
    [items],
  );
  const orderedVideos = useMemo(() => flattenGrouped(groups), [groups]);
  const groupsWithFlatIndex = useMemo(() => {
    const out = [];
    let acc = 0;
    for (const g of groups) {
      out.push({ group: g, startIndex: acc });
      for (const v of g.visits) acc += v.photos.length;
    }
    return out;
  }, [groups]);

  // Mapped once here so the <Lightbox> definition below stays terse.
  const lightboxItems = orderedVideos.map((v) => ({
    url:   resolveUrl(v.url),
    kind:  "video",
    title: v.entity_title || v.job_title || v.caption || "Video",
    subtitle: v.uploaded_at
      ? new Date(v.uploaded_at).toLocaleString()
        + (v.duration_seconds ? ` · ${fmtDuration(v.duration_seconds)}` : "")
      : "",
  }));

  return (
    <PortalPageShell>
    <div className="max-w-6xl mx-auto p-4" data-testid="portal-videos-page">
      <h1
        className="text-2xl font-black mb-1"
        style={{ color: colors.onSurface }}
      >Videos</h1>
      <p className="text-sm mb-5" style={{ color: colors.muted }}>
        Videos your technician captured during service visits.
      </p>

      {err ? (
        <div
          className="rounded-xl p-3 text-sm mb-4"
          style={{ background: "#FEE2E2", color: "#7F1D1D",
                    border: "1px solid #FCA5A5" }}
          data-testid="portal-videos-error"
        >{err}</div>
      ) : null}

      {items === null ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3"
              data-testid="portal-videos-loading">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div
          className="rounded-2xl p-10 text-center"
          style={{ background: colors.surface,
                    border: `1px dashed ${colors.border}` }}
          data-testid="portal-videos-empty"
        >
          <div
            className="mx-auto mb-3 w-12 h-12 rounded-full flex items-center justify-center"
            style={{ background: colors.surfaceSecondary, color: colors.muted }}
          ><VideoIcon size={22} /></div>
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            No videos yet
          </div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>
            Service report videos will appear here once your technician uploads them.
          </div>
        </div>
      ) : (
        <>
          {/*
            TD-portal-videos-page-wire-grouping · Feb-2026 —
            labeled date-divider headers between calendar-day
            groups.  Mirrors the Photos page pattern byte-for-
            byte: `<section aria-labelledby>` → `<h2 id>` →
            `<div role="separator">`.  Legacy
            ``portal-video-${i}`` testids are preserved on the
            buttons via flat `startIndex + j` index threading.
          */}
          <div data-testid="portal-videos-grouped">
            {groupsWithFlatIndex.map(({ group, startIndex }) => (
              <section
                key={group.day}
                className="mb-6"
                data-testid={`portal-videos-date-group-${group.day}`}
                aria-labelledby={`portal-videos-date-header-${group.day}`}
              >
                <h2
                  id={`portal-videos-date-header-${group.day}`}
                  className="text-sm font-black uppercase tracking-wide mb-2"
                  style={{ color: colors.onSurface }}
                  data-testid={`portal-videos-date-header-${group.day}`}
                >
                  {group.header}
                </h2>
                <div
                  role="separator"
                  aria-hidden="true"
                  className="mb-4"
                  style={{ borderTop: `1px solid ${colors.border}` }}
                  data-testid={`portal-videos-date-divider-${group.day}`}
                />
                <div
                  className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3"
                  data-testid={`portal-videos-grid-${group.day}`}
                >
                  {group.visits.flatMap((vv) => vv.photos).map((v, j) => {
                    const i = startIndex + j;
                    const poster = v.poster_url ? resolveUrl(v.poster_url) : "";
                    const _key = `${v.source || "src"}|${v.video_id || v.entity_id || "x"}|${i}`;
                    return (
                      <button
                        key={_key}
                        onClick={() => setSelectedIdx(i)}
                        className="rounded-xl overflow-hidden transition hover:brightness-95"
                        style={{ background: colors.surfaceSecondary,
                                  border: `1px solid ${colors.border}` }}
                        data-testid={`portal-video-${i}`}
                      >
                        <div
                          className="relative w-full h-40 flex items-center justify-center"
                          style={{
                            background: poster ? "#000" : "#111827",
                            backgroundImage: poster ? `url(${poster})` : "none",
                            backgroundSize: "cover",
                            backgroundPosition: "center",
                          }}
                        >
                          <div
                            className="w-12 h-12 rounded-full flex items-center justify-center"
                            style={{ background: "rgba(0,0,0,0.6)", color: "#fff" }}
                          ><Play size={22} /></div>
                          {v.duration_seconds ? (
                            <div
                              className="absolute bottom-1 right-1 text-xs px-1.5 py-0.5 rounded"
                              style={{ background: "rgba(0,0,0,0.7)", color: "#fff" }}
                            >{fmtDuration(v.duration_seconds)}</div>
                          ) : null}
                        </div>
                        <div className="p-2 text-left">
                          <div className="text-xs font-semibold truncate"
                                style={{ color: colors.onSurface }}
                                title={v.entity_title || v.job_title || ""}>
                            {v.entity_title || v.job_title || "Service report"}
                          </div>
                          <div className="text-xs" style={{ color: colors.muted }}>
                            {v.uploaded_at
                              ? new Date(v.uploaded_at).toLocaleDateString()
                              : ""}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>

          {items.length < total ? (
            <div className="mt-4 flex justify-center">
              <button
                className="rounded-full px-5 py-2 text-sm font-semibold"
                style={{ background: colors.brand, color: "#fff" }}
                onClick={loadMore}
                data-testid="portal-videos-load-more"
              >Load more · {total - items.length} left</button>
            </div>
          ) : null}
        </>
      )}

      {/* DTP-2 · Feb-2026 — shared portal Lightbox. ``testidPrefix``
          preserves the legacy ``portal-video-modal`` selector so
          existing tests keep resolving the modal + close button. */}
      <Lightbox
        items={lightboxItems}
        initialIndex={selectedIdx == null ? 0 : selectedIdx}
        open={selectedIdx !== null}
        onClose={() => setSelectedIdx(null)}
        testidPrefix="portal-video-modal"
      />
    </div>
      </PortalPageShell>
  );
}
