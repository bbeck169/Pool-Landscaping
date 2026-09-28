/**
 * Portal Photos · Feb-2026
 *
 * Aggregated gallery of every image visible to the current portal
 * customer — job files + customer-linked files + service report photos.
 * Backend: GET /api/portal/photos.
 */
import React, { useEffect, useState } from "react";
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
      setItems((prev) => (nextOffset === 0 ? (res.items || []) : [...(prev || []), ...(res.items || [])]));
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

  return (
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
          <div
            className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3"
            data-testid="portal-photos-grid"
          >
            {items.map((p) => (
              <button
                key={p.file_id}
                onClick={() => setLightboxIdx((items || []).findIndex((x) => x.file_id === p.file_id))}
                className="rounded-xl overflow-hidden transition hover:brightness-95"
                style={{ background: colors.surfaceSecondary,
                          border: `1px solid ${colors.border}` }}
                data-testid={`portal-photo-${p.file_id}`}
              >
                <img
                  src={authedImgUrl(p.url)}
                  alt={p.filename || "Service photo"}
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
                    {p.uploaded_at
                      ? new Date(p.uploaded_at).toLocaleDateString()
                      : ""}
                  </div>
                </div>
              </button>
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
        items={(items || []).map((p) => ({
          url:   authedImgUrl(p.url),
          kind:  "image",
          title: p.job_title || p.filename || "Photo",
          subtitle: (p.uploaded_at
                      ? new Date(p.uploaded_at).toLocaleString()
                      : "")
                   + (p.purpose ? ` · ${p.purpose.replace(/_/g, " ")}` : ""),
        }))}
        initialIndex={lightboxIdx == null ? 0 : lightboxIdx}
        open={lightboxIdx !== null}
        onClose={() => setLightboxIdx(null)}
        testidPrefix="portal-photo-lightbox"
      />
    </div>
  );
}
