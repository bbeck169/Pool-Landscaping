/**
 * Portal Videos · Feb-2026
 *
 * Videos from submitted service reports (poster on grid tile, streaming
 * inline in a modal). Backend: GET /api/portal/videos — currently the
 * only video source is db.service_reports[].videos.
 */
import React, { useEffect, useState } from "react";
import { X, Video as VideoIcon, Play } from "lucide-react";
import { colors } from "@/theme";
import { api } from "@/api";
import { Skeleton } from "@/components/ui-kit";

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
  const [selected, setSelected] = useState(null);
  const [err, setErr] = useState("");

  const load = async (nextOffset) => {
    try {
      const res = await api.get(`/portal/videos?limit=${PAGE}&offset=${nextOffset}`);
      setTotal(res.total || 0);
      setItems((prev) => (nextOffset === 0 ? (res.items || []) : [...(prev || []), ...(res.items || [])]));
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

  return (
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
          <div
            className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3"
            data-testid="portal-videos-grid"
          >
            {items.map((v) => {
              const poster = v.poster_url ? resolveUrl(v.poster_url) : "";
              return (
                <button
                  key={v.file_id}
                  onClick={() => setSelected(v)}
                  className="rounded-xl overflow-hidden transition hover:brightness-95"
                  style={{ background: colors.surfaceSecondary,
                            border: `1px solid ${colors.border}` }}
                  data-testid={`portal-video-${v.file_id}`}
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
                          title={v.job_title || ""}>
                      {v.job_title || "Service report"}
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

      {selected ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.9)" }}
          onClick={() => setSelected(null)}
          data-testid="portal-video-modal"
        >
          <button
            onClick={() => setSelected(null)}
            className="absolute top-4 right-4 text-white"
            data-testid="portal-video-modal-close"
          ><X size={28} /></button>
          <div
            className="max-w-4xl w-full text-center"
            onClick={(e) => e.stopPropagation()}
          >
            <video
              src={resolveUrl(selected.url)}
              controls
              autoPlay
              poster={selected.poster_url ? resolveUrl(selected.poster_url) : undefined}
              className="max-h-[75vh] mx-auto rounded-xl shadow-2xl"
              data-testid="portal-video-modal-player"
            >
              Your browser doesn't support inline video playback.
            </video>
            <div className="mt-3 text-white">
              <div className="font-semibold">
                {selected.job_title || selected.filename || "Video"}
              </div>
              <div className="text-xs opacity-80">
                {selected.uploaded_at
                  ? new Date(selected.uploaded_at).toLocaleString()
                  : ""}
                {selected.duration_seconds
                  ? ` · ${fmtDuration(selected.duration_seconds)}` : ""}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
