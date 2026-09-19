/**
 * Feb-2026 · Interactive Flipbook Estimate Viewer — admin compose.
 *
 * Two per-estimate controls that drive the customer-facing viewer:
 *
 *   1. **Toggle** ``flipbook_enabled`` — when ``true`` the customer
 *      magic-link surface renders the estimate as a page-flip book
 *      (``react-pageflip``) instead of the classic scrollable view.
 *   2. **Backgrounds** ``flipbook_background_ids`` — up to 10 media-
 *      library image IDs. Order matters: image ``[i % length]``
 *      renders behind page ``i``. Ordering is exposed via up/down
 *      arrows (drag-to-reorder deferred to a P2 polish pass — the
 *      arrows cover the 90 % path with 5 % of the code).
 *
 * Admin-only + quote/estimate-only. The parent (``QuoteInvoiceDetail``)
 * gates on ``isStaff && !isInvoice`` before mounting us.
 *
 * Persists via the same ``PUT /api/quotes/{id}`` endpoint the rest of
 * the compose page uses. The backend validates image kind +
 * per-estimate max of 10 (see ``routers/quotes.py`` — 400
 * ``too_many_backgrounds`` / 400 ``background_must_be_image`` /
 * 404 ``file_not_found``).
 */
import React, { useEffect, useMemo, useState } from "react";
import { X, ArrowUp, ArrowDown, ImagePlus, Book } from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";
import { MediaLibraryPicker } from "@/components/marketing/MediaLibraryPicker";


const MAX_BACKGROUNDS = 10;


function _mediaThumbUrl(id) {
  // Same signed-URL endpoint the MediaLibraryPicker uses for
  // previews (see routers/marketing_media.py line 330).
  return `/api/marketing/media/${id}/download`;
}


export function FlipbookComposeSection({ doc, onDocRefresh }) {
  const [enabled, setEnabled] = useState(!!doc?.flipbook_enabled);
  const [bgIds, setBgIds] = useState(
    Array.isArray(doc?.flipbook_background_ids)
      ? [...doc.flipbook_background_ids]
      : [],
  );
  // Keyed url map so chip thumbs render even before the picker
  // opens (once the picker fires it enriches the map).
  const [urlById, setUrlById] = useState({});
  const [pickerOpen, setPickerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    setEnabled(!!doc?.flipbook_enabled);
    setBgIds(Array.isArray(doc?.flipbook_background_ids)
      ? [...doc.flipbook_background_ids]
      : []);
  }, [doc?.id, doc?.flipbook_enabled, doc?.flipbook_background_ids]);

  const disabledAdd = useMemo(
    () => bgIds.length >= MAX_BACKGROUNDS,
    [bgIds.length],
  );

  async function _persist(nextEnabled, nextBgIds) {
    setSaving(true);
    try {
      await api.put(`/quotes/${doc.id}`, {
        flipbook_enabled: nextEnabled,
        flipbook_background_ids: nextBgIds,
      });
      if (onDocRefresh) await onDocRefresh();
    } catch (e) {
      const detail = e?.data?.detail;
      const msg = (detail && (detail.message || detail.error))
                    || e?.message || "Save failed";
      setToast({ tone: "error", message: msg });
    } finally {
      setSaving(false);
    }
  }

  async function _onToggle(next) {
    setEnabled(next);
    await _persist(next, bgIds);
  }

  async function _onPickerSelectMultiple(items) {
    // items: [{id, url, cdn_url, alt_text}]
    const _incoming = (items || []).map((it) => ({
      id: it.id,
      url: it.url || it.cdn_url || _mediaThumbUrl(it.id),
    }));
    const _next = [...bgIds];
    const _seen = new Set(_next);
    const _nextUrls = { ...urlById };
    for (const it of _incoming) {
      if (_seen.has(it.id)) continue;
      if (_next.length >= MAX_BACKGROUNDS) break;
      _next.push(it.id);
      _seen.add(it.id);
      _nextUrls[it.id] = it.url;
    }
    setBgIds(_next);
    setUrlById(_nextUrls);
    setPickerOpen(false);
    await _persist(enabled, _next);
  }

  async function _onRemove(id) {
    const _next = bgIds.filter((x) => x !== id);
    setBgIds(_next);
    await _persist(enabled, _next);
  }

  async function _onMove(id, delta) {
    const _next = [...bgIds];
    const idx = _next.indexOf(id);
    if (idx < 0) return;
    const _to = idx + delta;
    if (_to < 0 || _to >= _next.length) return;
    [_next[idx], _next[_to]] = [_next[_to], _next[idx]];
    setBgIds(_next);
    await _persist(enabled, _next);
  }

  return (
    <div
      className="rounded-2xl p-6 mb-4"
      data-testid="flipbook-compose-section"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Book size={18} style={{ color: colors.onSurface }} />
          <h2
            className="text-lg font-bold"
            style={{ color: colors.onSurface }}
          >
            Flipbook viewer
          </h2>
        </div>
        <label
          className="flex items-center gap-2 text-sm cursor-pointer"
          style={{ color: colors.onSurfaceSecondary }}
        >
          <span>Show as flipbook to customer</span>
          <input
            type="checkbox"
            checked={enabled}
            disabled={saving}
            onChange={(e) => _onToggle(e.target.checked)}
            className="w-4 h-4"
            data-testid="flipbook-enabled-toggle"
          />
        </label>
      </div>

      {enabled ? (
        <div className="space-y-3">
          <div
            className="text-xs"
            style={{ color: colors.onSurfaceSecondary }}
            data-testid="flipbook-helper-text"
          >
            1–{MAX_BACKGROUNDS} images. The order below matches page
            order — image N renders behind page N, and the sequence
            cycles when there are more pages than images. Each page
            uses its assigned image as a subtle background with a
            legibility overlay.
          </div>

          {bgIds.length > 0 ? (
            <ul
              className="flex flex-wrap gap-2"
              data-testid="flipbook-bg-chips"
            >
              {bgIds.map((id, idx) => {
                const src = urlById[id] || _mediaThumbUrl(id);
                return (
                  <li
                    key={id}
                    data-testid={`flipbook-bg-chip-${id}`}
                    className="flex items-center gap-2 rounded-full pl-1 pr-2 py-1"
                    style={{
                      backgroundColor: colors.background,
                      border: `1px solid ${colors.border}`,
                    }}
                  >
                    <img
                      src={src}
                      alt=""
                      className="w-8 h-8 rounded-full object-cover"
                      style={{ border: `1px solid ${colors.border}` }}
                      onError={(e) => {
                        // Broken image (deleted / cross-tenant / etc.):
                        // fall back to a neutral placeholder so the
                        // chip layout doesn't collapse.
                        e.currentTarget.style.visibility = "hidden";
                      }}
                    />
                    <span
                      className="text-[11px] font-mono"
                      style={{ color: colors.muted }}
                    >
                      #{idx + 1}
                    </span>
                    <button
                      type="button"
                      onClick={() => _onMove(id, -1)}
                      disabled={idx === 0 || saving}
                      title="Move earlier"
                      aria-label={`Move image ${idx + 1} earlier`}
                      data-testid={`flipbook-bg-chip-${id}-up`}
                      className="p-0.5 disabled:opacity-40"
                      style={{ color: colors.onSurface }}
                    >
                      <ArrowUp size={12} />
                    </button>
                    <button
                      type="button"
                      onClick={() => _onMove(id, +1)}
                      disabled={idx === bgIds.length - 1 || saving}
                      title="Move later"
                      aria-label={`Move image ${idx + 1} later`}
                      data-testid={`flipbook-bg-chip-${id}-down`}
                      className="p-0.5 disabled:opacity-40"
                      style={{ color: colors.onSurface }}
                    >
                      <ArrowDown size={12} />
                    </button>
                    <button
                      type="button"
                      onClick={() => _onRemove(id)}
                      disabled={saving}
                      title="Remove"
                      aria-label={`Remove image ${idx + 1}`}
                      data-testid={`flipbook-bg-chip-${id}-remove`}
                      className="p-0.5 disabled:opacity-40"
                      style={{ color: colors.danger || "#dc2626" }}
                    >
                      <X size={12} />
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div
              className="text-xs italic"
              style={{ color: colors.muted }}
              data-testid="flipbook-bg-empty"
            >
              No background images selected — the flipbook will
              render pages against a soft tenant-primary background.
            </div>
          )}

          <button
            type="button"
            onClick={() => setPickerOpen(true)}
            disabled={disabledAdd || saving}
            className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-full disabled:opacity-40"
            style={{
              backgroundColor: colors.primary,
              color: colors.onPrimary || "#fff",
            }}
            data-testid="flipbook-open-picker"
          >
            <ImagePlus size={14} />
            {disabledAdd
              ? `Max ${MAX_BACKGROUNDS} images reached`
              : "Add background image(s)"}
          </button>
        </div>
      ) : null}

      {pickerOpen ? (
        <MediaLibraryPicker
          open={pickerOpen}
          onOpenChange={setPickerOpen}
          kind="image"
          multiSelect
          onSelectMultiple={_onPickerSelectMultiple}
        />
      ) : null}

      {toast ? (
        <div
          className="text-xs mt-2"
          style={{
            color: toast.tone === "error"
                    ? (colors.danger || "#dc2626")
                    : colors.onSurfaceSecondary,
          }}
          data-testid="flipbook-toast"
        >
          {toast.message}
        </div>
      ) : null}
    </div>
  );
}


export default FlipbookComposeSection;
