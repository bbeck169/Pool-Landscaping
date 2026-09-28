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
//   * Themed with ``.dark portal-dark`` scope regardless of
//     parent — the lightbox is always dark.
//
// Testids are parameterised via ``testidPrefix`` so a callsite
// can preserve pre-existing test contracts (e.g. PortalPhotosPage
// keeps ``portal-photo-lightbox`` / ``-close`` / ``-title``).
import React, { useCallback, useEffect, useRef, useState } from "react";
import { X, ChevronLeft, ChevronRight } from "lucide-react";

export default function Lightbox({
  items,
  initialIndex = 0,
  open,
  onClose,
  testidPrefix = "portal-lightbox",
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

  const advance = useCallback(
    (delta) => {
      const len = items?.length || 0;
      if (len < 2) return;
      setIndex((i) => (i + delta + len) % len);
    },
    [items],
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

  if (!open || !items || items.length === 0) return null;
  const safeIndex = Math.max(0, Math.min(index, items.length - 1));
  const item = items[safeIndex] || {};
  const isVideo = item.kind === "video";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 dark portal-dark"
      style={{ background: "rgba(3,0,46,0.92)" }}
      onClick={() => onClose && onClose()}
      role="dialog"
      aria-modal="true"
      data-testid={testidPrefix}
    >
      <button
        ref={closeBtnRef}
        type="button"
        onClick={(e) => { e.stopPropagation(); onClose && onClose(); }}
        aria-label="Close"
        className="absolute top-4 right-4 text-white p-2 rounded-full hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-white"
        data-testid={`${testidPrefix}-close`}
      >
        <X size={28} />
      </button>

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
