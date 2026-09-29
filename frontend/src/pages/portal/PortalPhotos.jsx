/**
 * Phase 20B.1c · Customer photo history — grid gallery with zoom + filters.
 *
 * DTP-2 · Feb-2026 — migrated onto the shared ``<Lightbox>`` component
 * (``@/components/portal/Lightbox``) so the zoom viewer inherits the
 * portal-dark palette, ESC + arrow keys, focus-trap, and title/counter
 * chrome. The pre-DTP-2 inline zoom overlay has been retired.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Camera, ImageOff } from 'lucide-react';
import { api } from "@/api";
// DTP-2 · Feb-2026 — dark portal palette.
import { portalColors as colors } from "@/theme";
import Lightbox from "@/components/portal/Lightbox";

const FILTERS = [
  { key: "", label: "All service types" },
  { key: "Weekly Pool Service", label: "Pool" },
  { key: "Monthly Landscaping", label: "Landscape" },
];

export default function PortalPhotos() {
  const [data, setData] = useState({ photos: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [zoomIdx, setZoomIdx] = useState(null);

  useEffect(() => {
    const q = filter ? `?service_type=${encodeURIComponent(filter)}` : "";
    setLoading(true);
    api.get(`/portal/photos${q}`)
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => { setData({ photos: [], total: 0 }); setLoading(false); });
  }, [filter]);

  // Flat ordered list (matches the day-grouped render order below).
  const orderedPhotos = useMemo(() => {
    const byDate = new Map();
    for (const p of data.photos) {
      const day = (p.submitted_at || p.uploaded_at || p.created_at || "").slice(0, 10) || "Unknown date";
      if (!byDate.has(day)) byDate.set(day, []);
      byDate.get(day).push(p);
    }
    const dayKeys = Array.from(byDate.keys()).sort((a, b) => b.localeCompare(a));
    const flat = [];
    for (const d of dayKeys) for (const p of byDate.get(d)) flat.push({ day: d, photo: p });
    return flat;
  }, [data]);

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
        (() => {
          // Phase 34 · Feb 2026 — group photos by date, newest first,
          // with a section header + horizontal divider between groups.
          // Groups key on the submitted_at YYYY-MM-DD; items keep their
          // existing intra-group order.
          const byDate = new Map();
          for (const p of data.photos) {
            const day = (p.submitted_at || p.uploaded_at || p.created_at || "").slice(0, 10) || "Unknown date";
            if (!byDate.has(day)) byDate.set(day, []);
            byDate.get(day).push(p);
          }
          const dayKeys = Array.from(byDate.keys()).sort((a, b) => b.localeCompare(a));
          const fmtHeader = (d) => {
            if (d === "Unknown date") return d;
            try {
              return new Date(d + "T00:00:00").toLocaleDateString(undefined,
                { weekday: "long", month: "short", day: "numeric", year: "numeric" });
            } catch { return d; }
          };
          // Global-index lookup so a click resolves to the correct
          // slot in the flat ``orderedPhotos`` list feeding <Lightbox>.
          const indexFor = (day, i) => {
            let acc = 0;
            for (const d of dayKeys) {
              if (d === day) return acc + i;
              acc += byDate.get(d).length;
            }
            return acc;
          };
          return (
            <div data-testid="portal-photos-grouped">
              {dayKeys.map((day, gi) => (
                <div key={day} data-testid={`portal-photos-date-group-${day}`}
                     className={gi > 0 ? "pt-6 mt-6" : ""}
                     style={gi > 0 ? { borderTop: `1px solid ${colors.border}` } : {}}>
                  <h2 className="text-sm font-bold mb-3"
                      style={{ color: colors.onSurface }}
                      data-testid={`portal-photos-date-header-${day}`}>
                    {fmtHeader(day)}
                  </h2>
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3"
                       data-testid="portal-photos-grid">
                    {byDate.get(day).map((p, i) => (
                      <button key={`${day}:${i}`} onClick={() => setZoomIdx(indexFor(day, i))}
                              className="group relative overflow-hidden rounded-xl aspect-square hover:scale-[1.02] transition"
                              style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                              data-testid={`portal-photo-${day}-${i}`}>
                        <img src={p.thumb || p.url} alt={p.caption || "Service photo"}
                             className="w-full h-full object-cover" loading="lazy" />
                        <div className="absolute bottom-0 left-0 right-0 p-2 text-left opacity-0 group-hover:opacity-100 transition"
                             style={{ background: "linear-gradient(0deg, rgba(0,0,0,.75), transparent)" }}>
                          <div className="text-[10px] text-white font-semibold truncate">
                            {p.job_title}
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          );
        })()
      )}

      {/* DTP-2 · Feb-2026 — shared portal Lightbox replaces the
          previous inline zoom overlay. ESC + arrow keys + focus-trap
          are now inherited from the shared component. */}
      <Lightbox
        items={orderedPhotos.map(({ photo }) => ({
          url: photo.url || photo.thumb,
          kind: "image",
          title: photo.caption || photo.job_title || "",
        }))}
        initialIndex={zoomIdx == null ? 0 : zoomIdx}
        open={zoomIdx !== null}
        onClose={() => setZoomIdx(null)}
        testidPrefix="portal-photo-zoom"
      />
    </div>
  );
}
