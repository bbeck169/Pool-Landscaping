/**
 * Phase 20B.1c · Customer photo history — grid gallery with zoom + filters.
 *
 * DTP-2 · Feb-2026 — migrated onto the shared ``<Lightbox>`` component
 * (``@/components/portal/Lightbox``) so the zoom viewer inherits the
 * portal-dark palette, ESC + arrow keys, focus-trap, and title/counter
 * chrome. The pre-DTP-2 inline zoom overlay has been retired.
 *
 * TD-76c · Feb-2026 — grouped layout: date header + divider → service
 * sub-header → photos row (one row per visit). Groups sorted newest
 * date first; within a date, visits tiebreak by ``submitted_at`` ASC
 * (earliest visit of the day appears first) with ``job_id`` as the
 * final deterministic tiebreak. Thumbnails route through the TD-76a
 * canonical URL (``/api/public/job-photo/<jid>/<pid>``) emitted by
 * ``services/customer_media.get_customer_media`` — no client-side URL
 * composition.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Camera, ImageOff } from 'lucide-react';
import { api } from "@/api";
// DTP-2 · Feb-2026 — dark portal palette.
import { portalColors as colors } from "@/theme";
import Lightbox from "@/components/portal/Lightbox";
// TD-portal-photos-page-wire-grouping · Feb-2026 — the TD-76c
// grouping helper has been extracted to a shared module so the
// active ``PortalPhotosPage.jsx`` can import the same primitive.
// This file re-exports it unchanged so the canonical vitest at
// ``test/portal-photos-td76-canonical.test.jsx`` keeps its
// shipped import target.
import {
  groupPhotosByDateAndVisit as _groupPhotosByDateAndVisit,
} from "./_photoGrouping";

const FILTERS = [
  { key: "", label: "All service types" },
  { key: "Weekly Pool Service", label: "Pool" },
  { key: "Monthly Landscaping", label: "Landscape" },
];

// Re-export under the shipped name for backwards compatibility.
export const groupPhotosByDateAndVisit = _groupPhotosByDateAndVisit;

// TD-76c · Feb-2026 — ``groupPhotosByDateAndVisit`` was moved to
// ``./_photoGrouping`` and re-exported at the top of this file so
// the existing canonical vitest import keeps working.  Keeping
// the inline body here would drift the two definitions.

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

  // Grouped structure drives both the render AND the flat ordered
  // list the lightbox consumes — iterate in the SAME order so a
  // click resolves to the right lightbox index.
  const groups = useMemo(
    () => groupPhotosByDateAndVisit(data.photos),
    [data],
  );
  const orderedPhotos = useMemo(() => {
    const flat = [];
    for (const g of groups) {
      for (const v of g.visits) {
        for (const p of v.photos) flat.push(p);
      }
    }
    return flat;
  }, [groups]);

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
          // TD-76c · Feb-2026 — resolve the flat-index for a click
          // handler.  Walk groups → visits → photos in the SAME
          // order used by ``orderedPhotos`` above.
          const indexFor = (gi, vi, pi) => {
            let acc = 0;
            for (let gIdx = 0; gIdx < groups.length; gIdx++) {
              for (let vIdx = 0; vIdx < groups[gIdx].visits.length; vIdx++) {
                for (let pIdx = 0;
                      pIdx < groups[gIdx].visits[vIdx].photos.length;
                      pIdx++) {
                  if (gIdx === gi && vIdx === vi && pIdx === pi) return acc;
                  acc += 1;
                }
              }
            }
            return acc;
          };
          return (
            <div data-testid="portal-photos-grouped">
              {groups.map((g, gi) => (
                <div key={g.day}
                      data-testid={`portal-photos-date-group-${g.day}`}
                      className={gi > 0 ? "pt-6 mt-6" : ""}
                      style={gi > 0 ? { borderTop: `1px solid ${colors.border}` } : {}}>
                  <h2 className="text-lg font-bold mb-1"
                      style={{ color: colors.onSurface }}
                      data-testid={`portal-photos-date-header-${g.day}`}>
                    {g.header}
                  </h2>
                  {/* Divider under the date header — matches operator
                      spec (horizontal rule). */}
                  <div className="mb-4"
                        style={{ borderBottom: `1px solid ${colors.border}` }}
                        data-testid={`portal-photos-date-divider-${g.day}`} />
                  {g.visits.map((v, vi) => (
                    <div key={`${g.day}:${v.visitKey}`}
                          className="mb-5"
                          data-testid={`portal-photos-visit-${g.day}-${v.visitKey}`}>
                      <h3 className="text-sm font-semibold mb-2"
                          style={{ color: colors.onSurfaceSecondary || colors.muted }}
                          data-testid={`portal-photos-visit-header-${g.day}-${v.visitKey}`}>
                        {v.jobTitle}
                      </h3>
                      {/* Photos row — horizontal flex row that wraps
                          cleanly on narrow widths.  Fixed-width tiles
                          so the row reads as a row even when wrapped. */}
                      <div className="flex flex-wrap gap-3"
                            data-testid={`portal-photos-row-${g.day}-${v.visitKey}`}>
                        {v.photos.map((p, pi) => (
                          <button key={`${g.day}:${v.visitKey}:${pi}`}
                                  onClick={() => setZoomIdx(indexFor(gi, vi, pi))}
                                  className="group relative overflow-hidden rounded-xl hover:scale-[1.02] transition"
                                  style={{
                                    width: 120, height: 120,
                                    backgroundColor: colors.surface,
                                    border: `1px solid ${colors.border}`,
                                  }}
                                  data-testid={`portal-photo-${g.day}-${v.visitKey}-${pi}`}>
                            {/* TD-76d · consume BE-resolved
                                ``thumb_url`` directly. Legacy
                                ``thumb`` / ``url`` kept as the
                                defensive fallback until Phase B
                                removes them from BE emission. */}
                            <img src={p.thumb_url || p.thumb || p.url}
                                  alt={p.caption || "Service photo"}
                                  className="w-full h-full object-cover"
                                  loading="lazy" />
                            <div className="absolute bottom-0 left-0 right-0 p-2 text-left opacity-0 group-hover:opacity-100 transition"
                                  style={{ background: "linear-gradient(0deg, rgba(0,0,0,.75), transparent)" }}>
                              <div className="text-[10px] text-white font-semibold truncate">
                                {p.caption || ""}
                              </div>
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
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
        items={orderedPhotos.map((photo) => ({
          // TD-76d · prefer BE-resolved ``full_url`` with
          // ``thumb_url`` and legacy fields as defensive fallback.
          url: photo.full_url || photo.url || photo.thumb_url || photo.thumb,
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
