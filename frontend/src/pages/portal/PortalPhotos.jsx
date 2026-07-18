/**
 * Phase 20B.1c · Customer photo history — grid gallery with zoom + filters.
 */
import React, { useEffect, useState } from "react";
import { Camera, ImageOff, X } from 'lucide-react';
import { api } from "@/api";
import { colors } from "@/theme";

const FILTERS = [
  { key: "", label: "All service types" },
  { key: "Weekly Pool Service", label: "Pool" },
  { key: "Monthly Landscaping", label: "Landscape" },
];

export default function PortalPhotos() {
  const [data, setData] = useState({ photos: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [zoom, setZoom] = useState(null);

  useEffect(() => {
    const q = filter ? `?service_type=${encodeURIComponent(filter)}` : "";
    setLoading(true);
    api.get(`/portal/photos${q}`)
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => { setData({ photos: [], total: 0 }); setLoading(false); });
  }, [filter]);

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="portal-photos-page">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-1">
          <Camera size={22} style={{ color: colors.brand }}/>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
            Service Photos
          </h1>
        </div>
        <p className="text-sm" style={{ color: colors.muted }}>
          Every before/after shot from your visits — {data.total} total.
        </p>
      </div>

      <div className="flex gap-2 mb-6 flex-wrap" data-testid="portal-photos-filters">
        {FILTERS.map((f) => (
          <button key={f.key} onClick={() => setFilter(f.key)}
                  className="px-4 py-2 text-sm font-semibold rounded-full transition"
                  style={{
                    backgroundColor: filter === f.key ? colors.brand : colors.surface,
                    color: filter === f.key ? "#fff" : colors.onSurface,
                    border: `1px solid ${filter === f.key ? colors.brand : colors.border}`,
                  }}
                  data-testid={`portal-photo-filter-${f.key || "all"}`}>
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="text-sm py-16 text-center" style={{ color: colors.muted }}>
          Loading photos…
        </div>
      ) : data.photos.length === 0 ? (
        <div className="text-center py-20 rounded-2xl"
             style={{ backgroundColor: colors.surface, border: `1px dashed ${colors.border}` }}>
          <ImageOff size={40} className="mx-auto mb-3" style={{ color: colors.muted }} />
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            No photos yet
          </div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>
            After your first service visit, all photos will appear here.
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3"
             data-testid="portal-photos-grid">
          {data.photos.map((p, i) => (
            <button key={i} onClick={() => setZoom(p)}
                    className="group relative overflow-hidden rounded-xl aspect-square hover:scale-[1.02] transition"
                    style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                    data-testid={`portal-photo-${i}`}>
              <img src={p.thumb || p.url} alt={p.caption || "Service photo"}
                   className="w-full h-full object-cover" loading="lazy" />
              <div className="absolute bottom-0 left-0 right-0 p-2 text-left opacity-0 group-hover:opacity-100 transition"
                   style={{ background: "linear-gradient(0deg, rgba(0,0,0,.75), transparent)" }}>
                <div className="text-[10px] text-white font-semibold truncate">
                  {p.job_title}
                </div>
                <div className="text-[9px] text-white/80">
                  {(p.submitted_at || "").slice(0, 10)}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

      {zoom && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ background: "rgba(0,0,0,0.85)" }}
             onClick={() => setZoom(null)}
             data-testid="portal-photo-zoom">
          <button onClick={() => setZoom(null)}
                  className="absolute top-4 right-4 p-2 rounded-full"
                  style={{ backgroundColor: "rgba(255,255,255,0.15)", color: "#fff" }}>
            <X size={20}/>
          </button>
          <img src={zoom.url} alt={zoom.caption} className="max-w-full max-h-full rounded-lg" />
        </div>
      )}
    </div>
  );
}
