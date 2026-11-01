/**
 * Portal Photos · Feb-2026
 *
 * Aggregated gallery of every image visible to the current portal
 * customer — job files + customer-linked files + service report photos.
 * Backend: GET /api/portal/photos.
 *
 * TD-portal-photos-page-wire-grouping · Feb-2026 — adopts the
 * shipped TD-76c grouping helper so the active page renders
 * labeled date-divider headers between calendar-day groups
 * (newest first).  Date buckets use the customer's BROWSER
 * timezone, matching the shipped portal convention elsewhere
 * (`PortalHome.jsx:33,746`, `PortalServiceReports.jsx:116,297`,
 * etc.).  The helper itself lives at `./_photoGrouping` so this
 * file and the legacy `PortalPhotos.jsx` share one owner.
 */
import React, { useEffect, useMemo, useState } from "react";
import { X, Image as ImageIcon } from "lucide-react";
// DTP-1 · Feb-2026 — dark theme pilot. Alias so every inline
// ``colors.X`` read below resolves to the portal-dark palette
// without a JSX-body diff.
import { portalColors as colors } from "@/theme";
import { api, TOKEN_KEY } from "@/api";
import { Skeleton } from "@/components/ui-kit";
// DTP-1 · Feb-2026 — shared portal lightbox (extracted from this
// file's prior inline implementation). Legacy testids
// ``portal-photo-lightbox`` / ``-close`` / ``-title`` are preserved
// via ``testidPrefix``.
import Lightbox from "@/components/portal/Lightbox";
// Phase 18b · Feb-2026 — Portal white-card shell. Wraps the
// export(s) in this file so content renders inside the Phase
// 3d-portal white dashboard card on the deep-navy page bg.
import PortalPageShell from "@/components/portal/PortalPageShell";
// TD-portal-photos-page-wire-grouping · Feb-2026 — shared helpers.
import {
  groupPhotosByDateAndVisit,
  flattenGrouped,
} from "./_photoGrouping";


const PAGE = 24;

function resolveUrl(relUrl) {
  if (!relUrl) return "";
  if (relUrl.startsWith("http")) return relUrl;
  const base = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
  return `${base}${relUrl}`;
}

function authedImgUrl(url) {
  // Files download endpoint accepts ?auth=<token> for <img> src.
  if (!url || !url.includes("/api/files/")) return resolveUrl(url);
  try {
    const tok = localStorage.getItem(TOKEN_KEY) || "";
    const abs = resolveUrl(url);
    if (!tok) return abs;
    const joiner = abs.includes("?") ? "&" : "?";
    return `${abs}${joiner}auth=${encodeURIComponent(tok)}`;
  } catch {
    return resolveUrl(url);
  }
}

export default function PortalPhotosPage() {
  const [items, setItems] = useState(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [lightboxIdx, setLightboxIdx] = useState(null);
  const [err, setErr] = useState("");

  const load = async (nextOffset) => {
    try {
      const res = await api.get(`/portal/photos?limit=${PAGE}&offset=${nextOffset}`);
      setTotal(res.total || 0);
      // TD-67 · Feb-2026 — BE emits ``photos`` (see
      // ``routers/portal_photos.py`` and the DATA-PARITY-C3 wrapper
      // around ``services/customer_media.get_customer_media``). The
      // pre-TD-67 code read ``res.items`` which never existed on
      // this payload — ``items === undefined`` collapsed to ``[]``
      // and every portal customer saw "No photos yet" even when
      // their service history had media attached. The
      // ``res.items`` branch is retained as a secondary fallback
      // only so a future BE refactor to the common ``items`` wire
      // shape doesn't silently blank the page again.
      const nextRows = res.photos || res.items || [];
      setItems((prev) => (nextOffset === 0 ? nextRows : [...(prev || []), ...nextRows]));
    } catch (e) {
      setErr(e?.message || "Failed to load photos.");
      setItems([]);
    }
  };

  useEffect(() => {
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadMore = () => {
    const next = offset + PAGE;
    setOffset(next);
    load(next);
  };

  // TD-portal-photos-page-wire-grouping · Feb-2026 — ``items`` is
  // the flat BE-sorted list (DESC ``uploaded_at`` at
  // ``services/customer_media.py:521``).  ``groups`` is the
  // grouped-by-calendar-day tree the TD-76c helper produces.
  // ``orderedPhotos`` is the SAME flat stream the lightbox
  // consumes, iterated via the group → visit → photo order the
  // helper produced — guaranteeing a tile's ``startIndex + j``
  // click resolves to the right lightbox index.  Across
  // ``Load more`` pages, trailing + leading same-day items fuse
  // into one group automatically because the helper rebuckets
  // on every ``items`` change — no duplicate dividers.
  const groups = useMemo(
    () => groupPhotosByDateAndVisit(items || []),
    [items],
  );
  const orderedPhotos = useMemo(() => flattenGrouped(groups), [groups]);
  const groupsWithFlatIndex = useMemo(() => {
    const out = [];
    let acc = 0;
    for (const g of groups) {
      out.push({ group: g, startIndex: acc });
      for (const v of g.visits) acc += v.photos.length;
    }
    return out;
  }, [groups]);

  return (
    <PortalPageShell>
    <div className="max-w-6xl mx-auto p-4" data-testid="portal-photos-page">
      <h1
        className="text-2xl font-black mb-1"
        style={{ color: colors.onSurface }}
      >Photos</h1>
      <p className="text-sm mb-5" style={{ color: colors.muted }}>
        Every photo from your services — before/after, chemical readings, and portal uploads.
      </p>

      {err ? (
        <div
          className="rounded-xl p-3 text-sm mb-4"
          style={{ background: "#FEE2E2", color: "#7F1D1D",
                    border: "1px solid #FCA5A5" }}
          data-testid="portal-photos-error"
        >{err}</div>
      ) : null}

      {items === null ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3"
              data-testid="portal-photos-loading">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div
          className="rounded-2xl p-10 text-center"
          style={{ background: colors.surface,
                    border: `1px dashed ${colors.border}` }}
          data-testid="portal-photos-empty"
        >
          <div
            className="mx-auto mb-3 w-12 h-12 rounded-full flex items-center justify-center"
            style={{ background: colors.surfaceSecondary, color: colors.muted }}
          ><ImageIcon size={22} /></div>
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            No photos yet
          </div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>
            Photos from your services will show up here.
          </div>
        </div>
      ) : (
        <>
          {/*
            TD-portal-photos-page-wire-grouping · Feb-2026 —
            labeled date-divider headers between calendar-day
            groups.  Within a day the shipped TD-76c visit-sort
            is preserved via ``flattenGrouped``, keeping the
            lightbox click→index mapping deterministic.  Legacy
            ``portal-photo-${i}`` testids are preserved on the
            buttons so shipped vitest / e2e selectors keep
            resolving.
          */}
          <div data-testid="portal-photos-grouped">
            {groupsWithFlatIndex.map(({ group, startIndex }) => (
              <section
                key={group.day}
                className="mb-6"
                data-testid={`portal-photos-date-group-${group.day}`}
                aria-labelledby={`portal-photos-date-header-${group.day}`}
              >
                <h2
                  id={`portal-photos-date-header-${group.day}`}
                  className="text-sm font-black uppercase tracking-wide mb-2"
                  style={{ color: colors.onSurface }}
                  data-testid={`portal-photos-date-header-${group.day}`}
                >
                  {group.header}
                </h2>
                <div
                  role="separator"
                  aria-hidden="true"
                  className="mb-4"
                  style={{ borderTop: `1px solid ${colors.border}` }}
                  data-testid={`portal-photos-date-divider-${group.day}`}
                />
                <div
                  className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3"
                  data-testid={`portal-photos-grid-${group.day}`}
                >
                  {group.visits.flatMap((v) => v.photos).map((p, j) => {
                    const i = startIndex + j;
                    const _key = `${p.source || "src"}|${p.report_id || p.job_id || "x"}|${i}`;
                    return (
                      <button
                        key={_key}
                        onClick={() => setLightboxIdx(i)}
                        className="rounded-xl overflow-hidden transition hover:brightness-95"
                        style={{ background: colors.surfaceSecondary,
                                  border: `1px solid ${colors.border}` }}
                        data-testid={`portal-photo-${i}`}
                      >
                        <img
                          src={authedImgUrl(p.url)}
                          alt={p.caption || p.job_title || "Service photo"}
                          loading="lazy"
                          className="w-full h-40 object-cover"
                        />
                        <div className="p-2 text-left">
                          <div className="text-xs font-semibold truncate"
                                style={{ color: colors.onSurface }}
                                title={p.job_title || ""}>
                            {p.job_title || "Portal upload"}
                          </div>
                          <div className="text-xs" style={{ color: colors.muted }}>
                            {p.submitted_at || p.uploaded_at
                              ? new Date(p.submitted_at || p.uploaded_at).toLocaleDateString()
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
                data-testid="portal-photos-load-more"
              >Load more · {total - items.length} left</button>
            </div>
          ) : null}
        </>
      )}

      {/* Lightbox (DTP-1 · Feb-2026 — extracted to shared
          <Lightbox> component; legacy testids preserved via
          testidPrefix). */}
      <Lightbox
        items={orderedPhotos.map((p) => ({
          url:   authedImgUrl(p.url),
          kind:  "image",
          title: p.job_title || p.caption || "Photo",
          subtitle: ((p.submitted_at || p.uploaded_at)
                      ? new Date(p.submitted_at || p.uploaded_at).toLocaleString()
                      : "")
                   + (p.caption ? ` · ${p.caption}` : ""),
        }))}
        initialIndex={lightboxIdx == null ? 0 : lightboxIdx}
        open={lightboxIdx !== null}
        onClose={() => setLightboxIdx(null)}
        testidPrefix="portal-photo-lightbox"
      />
    </div>
      </PortalPageShell>
  );
}
