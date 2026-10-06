// DTP-1 · Feb-2026 — Shared portal lightbox.
//
// One reusable overlay that renders an image OR video (based on
// ``item.kind``) with:
//   * ESC key + backdrop-click closes.
//   * ArrowLeft / ArrowRight cycles when items.length > 1.
//   * Prev / Next buttons for pointer-driven nav (hidden when
//     items.length <= 1).
//   * Focus lands on the close button when opened; focus
//     restores to the previously-active element on close.
//
// Testids are parameterised via ``testidPrefix`` so a callsite
// can preserve pre-existing test contracts (e.g. PortalPhotosPage
// keeps ``portal-photo-lightbox`` / ``-close`` / ``-title``).
//
// LIGHTBOX-UNIFY-PHASE-A · Feb-2026 — the shared component now
// carries a superset of the inline lightbox features previously
// forked across JobDetail / ServiceLog / WorkstreamJobDrawer /
// ServiceImagesPortalPage.  New opt-in props:
//
//   * ``enableSwipe`` (default true) — 40 px horizontal threshold
//     mirrors the historical ``ServiceLogPage`` implementation.
//     Pointer / touch events are both handled.
//   * ``enableDownload`` (default false) — adds a Download anchor
//     next to the Close button.  Reads ``item.downloadUrl`` first
//     then falls back to ``item.url`` so a caller that signs a
//     separate download URL still gets routed to it.
//   * ``skipVideosOnNav`` (default false) — Arrow / Prev / Next
//     steps over video items so an images-only carousel never
//     opens the overlay on a <video>.  Matches ServiceLog's
//     ``_imageIndices`` filter.
//   * ``theme`` (default ``"inherited"``) — pass ``"dark"`` to
//     restore the pre-Phase-A forced ``.dark portal-dark`` scope.
//     The portal-shell wrapper (``AppLayout`` →
//     ``<PortalThemeShell>``) already applies the dark scope to
//     the entire ``/portal/*`` subtree, so inherited renders the
//     overlay dark on every current portal caller without the
//     belt-and-suspenders class.  Non-portal callers (JobDetail,
//     ServiceLog, WorkstreamJobDrawer, ServiceImagesPortalPage,
//     dispatched for migration in LIGHTBOX-UNIFY Phases B + C)
//     take the inherited theme by default so they render on top
//     of whichever ambient theme the parent dashboard provides.
//
// All existing props (``items``, ``initialIndex``, ``open``,
// ``onClose``, ``testidPrefix``) retain their pre-Phase-A
// semantics byte-for-byte — the extension is strictly additive.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { X, ChevronLeft, ChevronRight, Download } from "lucide-react";

export default function Lightbox({
  items,
  initialIndex = 0,
  open,
  onClose,
  testidPrefix = "portal-lightbox",
  // LIGHTBOX-UNIFY-PHASE-A · Feb-2026 — superset props.
  enableSwipe = true,
  enableDownload = false,
  skipVideosOnNav = false,
  theme = "inherited",
}) {
  const [index, setIndex] = useState(initialIndex || 0);
  const closeBtnRef = useRef(null);
  const prevActiveEl = useRef(null);

  // Sync index when the caller opens the lightbox at a new starting point.
  useEffect(() => {
    if (open) setIndex(Number.isInteger(initialIndex) ? initialIndex : 0);
  }, [open, initialIndex]);

  // Focus trap — grab focus on open, restore on close.
  useEffect(() => {
    if (!open) return;
    prevActiveEl.current = document.activeElement;
    if (closeBtnRef.current && typeof closeBtnRef.current.focus === "function") {
      closeBtnRef.current.focus();
    }
    return () => {
      const el = prevActiveEl.current;
      if (el && typeof el.focus === "function") el.focus();
    };
  }, [open]);

  // ── Navigation helpers ─────────────────────────────────────────
  // ``advance(delta)`` walks the items array by ``delta`` steps and
  // wraps at the ends.  When ``skipVideosOnNav`` is on we filter the
  // candidate index set to image items only before stepping — same
  // posture as ServiceLog's ``_imageIndices`` pre-Phase-A.
  const advance = useCallback(
    (delta) => {
      const len = items?.length || 0;
      if (len < 2) return;
      if (!skipVideosOnNav) {
        setIndex((i) => (i + delta + len) % len);
        return;
      }
      const imageIdx = (items || [])
        .map((it, i) => (it && it.kind === "video" ? -1 : i))
        .filter((i) => i >= 0);
      if (imageIdx.length < 2) return;
      setIndex((i) => {
        const curSlot = Math.max(0, imageIdx.indexOf(i));
        const nextSlot = (curSlot + delta + imageIdx.length) % imageIdx.length;
        return imageIdx[nextSlot];
      });
    },
    [items, skipVideosOnNav],
  );

  // Keyboard: ESC + arrows.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); onClose && onClose(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); advance(1); }
      else if (e.key === "ArrowLeft")  { e.preventDefault(); advance(-1); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose, advance]);

  // Swipe (LIGHTBOX-UNIFY-PHASE-A) — opt-in gesture nav on touch.
  // 40 px threshold mirrors the historical ServiceLog impl.  Guarded
  // by ``enableSwipe`` so a caller that doesn't want swipe can keep
  // the pre-Phase-A behaviour.
  const touchStart = useRef(null);
  const onTouchStart = (e) => {
    if (!enableSwipe) return;
    touchStart.current = e.touches?.[0]?.clientX ?? null;
  };
  const onTouchEnd = (e) => {
    if (!enableSwipe) return;
    const start = touchStart.current;
    touchStart.current = null;
    if (start == null) return;
    const end = e.changedTouches?.[0]?.clientX ?? start;
    const delta = end - start;
    if (Math.abs(delta) < 40) return;
    if (delta > 0) advance(-1); else advance(1);
  };

  if (!open || !items || items.length === 0) return null;
  const safeIndex = Math.max(0, Math.min(index, items.length - 1));
  const item = items[safeIndex] || {};
  const isVideo = item.kind === "video";
  const downloadHref = item.downloadUrl || item.url || "";
  const themeClass = theme === "dark" ? " dark portal-dark" : "";

  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center p-4${themeClass}`}
      style={{ background: "rgba(3,0,46,0.92)" }}
      onClick={() => onClose && onClose()}
      onTouchStart={onTouchStart}
      onTouchEnd={onTouchEnd}
      role="dialog"
      aria-modal="true"
      data-testid={testidPrefix}
    >
      {/* Top-right controls — close + (optional) download. */}
      <div
        className="absolute top-4 right-4 flex items-center gap-2"
        onClick={(e) => e.stopPropagation()}
      >
        {enableDownload && downloadHref ? (
          <a
            href={downloadHref}
            download
            aria-label="Download"
            className="text-white p-2 rounded-full hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-white"
            data-testid={`${testidPrefix}-download`}
            onClick={(e) => e.stopPropagation()}
          >
            <Download size={22} />
          </a>
        ) : null}
        <button
          ref={closeBtnRef}
          type="button"
          onClick={(e) => { e.stopPropagation(); onClose && onClose(); }}
          aria-label="Close"
          className="text-white p-2 rounded-full hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-white"
          data-testid={`${testidPrefix}-close`}
        >
          <X size={28} />
        </button>
      </div>

      {items.length > 1 && (
        <>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); advance(-1); }}
            aria-label="Previous"
            className="absolute left-4 top-1/2 -translate-y-1/2 text-white p-2 rounded-full hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-white"
            data-testid={`${testidPrefix}-prev`}
          >
            <ChevronLeft size={28} />
          </button>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); advance(1); }}
            aria-label="Next"
            className="absolute right-4 top-1/2 -translate-y-1/2 text-white p-2 rounded-full hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-white"
            data-testid={`${testidPrefix}-next`}
          >
            <ChevronRight size={28} />
          </button>
        </>
      )}

      <div
        className="max-w-5xl w-full text-center"
        onClick={(e) => e.stopPropagation()}
      >
        {isVideo ? (
          <video
            src={item.url}
            controls
            autoPlay
            className="max-h-[80vh] mx-auto rounded-xl shadow-2xl"
            data-testid={`${testidPrefix}-video`}
          />
        ) : (
          <img
            src={item.url}
            alt={item.title || "Photo"}
            className="max-h-[80vh] mx-auto rounded-xl shadow-2xl"
            data-testid={`${testidPrefix}-image`}
          />
        )}
        {item.title ? (
          <div
            className="mt-3 text-white font-semibold"
            data-testid={`${testidPrefix}-title`}
          >
            {item.title}
          </div>
        ) : null}
        {item.subtitle ? (
          <div className="text-xs text-white/70 mt-1">
            {item.subtitle}
          </div>
        ) : null}
        {items.length > 1 ? (
          <div
            className="text-xs text-white/60 mt-1"
            data-testid={`${testidPrefix}-counter`}
          >
            {safeIndex + 1} / {items.length}
          </div>
        ) : null}
      </div>
    </div>
  );
}
