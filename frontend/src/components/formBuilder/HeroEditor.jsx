/**
 * CUS-Marketing-Form-Builder · Feb-2026 — Phase 3.
 *
 * Hero-band designer that lives inside ``FormEditorDrawer`` in
 * ``MarketingFormsPage``. Collapsible panel with:
 *   - Enable Hero toggle. Off → onChange(null) → renderer skips
 *     the whole hero band. Back-compat sentinel for pre-Phase-3
 *     forms — ``value == null`` renders ONLY the toggle so the
 *     drawer looks byte-identical to Phase 2.
 *   - Rich-text heading + sub-heading (Tiptap via RichTextField).
 *   - Background: radio choice of
 *       * ``color``    — single color picker.
 *       * ``image``    — MediaLibraryPicker + overlay-opacity slider.
 *       * ``gradient`` — angle + from + to. Pragmatic copy of the
 *                        ThemePanel gradient block (see note below).
 *   - Optional special-offer badge — MediaLibraryPicker asset.
 *
 * Emits: ``onChange(hero | null)`` — the full hero object, or
 * null when the toggle is off. Persistence is the caller's
 * responsibility (MarketingFormsPage folds this into the save
 * payload as ``hero``).
 *
 * Backend contract (Phase 1 `marketing_forms.py`): ``hero`` is a
 * freeform ``Optional[Dict[str, Any]]`` — no server-side schema
 * validation beyond null-vs-dict. The renderer is the source of
 * truth for hero shape.
 */
import React, { useState } from "react";
import { ChevronDown, ChevronRight, X as XIcon } from "lucide-react";
import RichTextField from "./RichTextField";
import { MediaLibraryPicker } from "../marketing/MediaLibraryPicker";

const DEFAULT_HERO = () => ({
  heading_html: "",
  subheading_html: "",
  background: { kind: "color", color: "#F8FAFC" },
  badge: null,
});

const DEFAULT_IMAGE_BG = (url) => ({
  kind: "image",
  url: url || "",
  overlay_opacity: 30,
});

const DEFAULT_GRADIENT_BG = () => ({
  kind: "gradient",
  angle_deg: 135,
  from: "#0EA5E9",
  to: "#1B1F5C",
});

export default function HeroEditor({ value, onChange }) {
  const enabled = value !== null && value !== undefined;
  const [expanded, setExpanded] = useState(enabled);
  const [pickerFor, setPickerFor] = useState(null); // 'image' | 'badge' | null

  const bg = enabled ? (value.background || { kind: "color", color: "#F8FAFC" }) : null;
  const bgKind = bg?.kind || "color";

  // ── Handlers ─────────────────────────────────────────────────
  const enable = () => {
    onChange(DEFAULT_HERO());
    setExpanded(true);
  };
  const disable = () => {
    onChange(null);
  };

  const patch = (p) => onChange({ ...value, ...p });
  const patchBg = (p) => onChange({ ...value, background: { ...value.background, ...p } });

  const setBgKind = (kind) => {
    if (kind === "color") {
      onChange({ ...value, background: { kind: "color", color: "#F8FAFC" } });
    } else if (kind === "image") {
      onChange({ ...value, background: DEFAULT_IMAGE_BG(bg?.url || "") });
    } else if (kind === "gradient") {
      onChange({ ...value, background: DEFAULT_GRADIENT_BG() });
    }
  };

  const onPickBgImage = (m) => {
    if (!m) return;
    const url = m.cdn_url || m.url || "";
    onChange({
      ...value,
      background: { kind: "image", url,
                    overlay_opacity: bg?.overlay_opacity ?? 30 },
    });
    setPickerFor(null);
  };

  const onPickBadge = (m) => {
    if (!m) return;
    onChange({
      ...value,
      badge: {
        url: m.cdn_url || m.url || "",
        alt_text: m.alt_text || "",
      },
    });
    setPickerFor(null);
  };

  const removeBadge = () => onChange({ ...value, badge: null });
  const removeBgImage = () => onChange({
    ...value,
    background: { kind: "image", url: "", overlay_opacity: bg?.overlay_opacity ?? 30 },
  });

  return (
    <div className="rounded-lg border border-zinc-200 bg-white"
         data-testid="hero-editor">
      {/* Header row — enable toggle + expand chevron */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-100">
        <label className="flex items-center gap-2 text-sm font-semibold text-zinc-800 cursor-pointer">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => e.target.checked ? enable() : disable()}
            data-testid="hero-enable-toggle"
          />
          Hero (optional)
        </label>
        {enabled && (
          <button
            type="button"
            onClick={() => setExpanded((x) => !x)}
            className="ml-auto p-1 text-zinc-500 hover:text-zinc-900"
            data-testid="hero-expand-toggle"
            aria-label={expanded ? "Collapse hero editor" : "Expand hero editor"}
          >
            {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </button>
        )}
      </div>

      {/* Body — rendered only when enabled AND expanded */}
      {enabled && expanded && (
        <div className="p-3 space-y-4" data-testid="hero-editor-body">
          {/* Heading */}
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 mb-1">
              Heading
            </div>
            <RichTextField
              value={value.heading_html || ""}
              onChange={(html) => patch({ heading_html: html })}
              placeholder="e.g. Get a free pool inspection"
              testid="hero-heading-editor"
            />
          </div>

          {/* Sub-heading */}
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 mb-1">
              Sub-heading
            </div>
            <RichTextField
              value={value.subheading_html || ""}
              onChange={(html) => patch({ subheading_html: html })}
              placeholder="e.g. We'll be in touch within 24 hours."
              testid="hero-subheading-editor"
            />
          </div>

          {/* Background type */}
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 mb-2">
              Background
            </div>
            <div className="flex items-center gap-4 mb-3" data-testid="hero-bg-kind-radio">
              {[
                { k: "color",    label: "Color"    },
                { k: "image",    label: "Image"    },
                { k: "gradient", label: "Gradient" },
              ].map(({ k, label }) => (
                <label key={k} className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="radio"
                    name="hero-bg-kind"
                    checked={bgKind === k}
                    onChange={() => setBgKind(k)}
                    data-testid={`hero-bg-kind-${k}`}
                  />
                  {label}
                </label>
              ))}
            </div>

            {/* Per-kind controls */}
            {bgKind === "color" && (
              <div className="flex items-center gap-2" data-testid="hero-bg-color-controls">
                <input
                  type="color"
                  value={bg.color || "#F8FAFC"}
                  onChange={(e) => patchBg({ color: e.target.value })}
                  data-testid="hero-bg-color-picker"
                  className="h-8 w-10 rounded border border-zinc-300"
                />
                <input
                  type="text"
                  value={bg.color || ""}
                  onChange={(e) => patchBg({ color: e.target.value })}
                  className="flex-1 rounded-md border-zinc-300 text-xs px-2 py-1 border"
                />
              </div>
            )}

            {bgKind === "image" && (
              <div className="space-y-3" data-testid="hero-bg-image-controls">
                {bg.url ? (
                  <div className="flex items-center gap-3">
                    <img
                      src={bg.url}
                      alt="Hero background"
                      className="w-20 h-20 rounded object-cover border border-zinc-200"
                      data-testid="hero-bg-image-thumb"
                    />
                    <div className="flex-1 flex flex-col gap-1 items-start">
                      <button
                        type="button"
                        onClick={() => setPickerFor("image")}
                        className="text-xs font-semibold text-zinc-700 hover:text-zinc-900 underline"
                        data-testid="hero-bg-image-replace-btn"
                      >
                        Replace
                      </button>
                      <button
                        type="button"
                        onClick={removeBgImage}
                        className="text-xs font-semibold text-zinc-500 hover:text-zinc-900"
                        data-testid="hero-bg-image-remove-btn"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setPickerFor("image")}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold text-zinc-700 bg-zinc-50 border border-zinc-200 hover:bg-zinc-100"
                    data-testid="hero-bg-image-pick-btn"
                  >
                    Choose from Media Library
                  </button>
                )}

                <label className="block text-xs" data-testid="hero-bg-overlay-wrap">
                  <span className="text-zinc-600">
                    Overlay darkness — {bg.overlay_opacity ?? 0}%
                  </span>
                  <input
                    type="range"
                    min="0" max="100" step="1"
                    value={bg.overlay_opacity ?? 0}
                    onChange={(e) => patchBg({ overlay_opacity: Number(e.target.value) })}
                    data-testid="hero-bg-overlay-slider"
                    className="mt-1 block w-full"
                  />
                </label>
              </div>
            )}

            {bgKind === "gradient" && (
              // gradient controls: pragmatic copy of ThemePanel's; extract to shared if a 3rd consumer emerges
              <div className="space-y-3" data-testid="hero-bg-gradient-controls">
                <label className="block text-xs">
                  <span className="text-zinc-600">
                    Angle — {bg.angle_deg ?? 135}°
                  </span>
                  <input
                    type="range"
                    min="0" max="360" step="1"
                    value={bg.angle_deg ?? 135}
                    onChange={(e) => patchBg({ angle_deg: Number(e.target.value) || 0 })}
                    data-testid="hero-bg-gradient-angle"
                    className="mt-1 block w-full"
                  />
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="block text-xs">
                    <span className="text-zinc-600">From</span>
                    <div className="mt-1 flex items-center gap-2">
                      <input
                        type="color"
                        value={bg.from || "#0EA5E9"}
                        onChange={(e) => patchBg({ from: e.target.value })}
                        data-testid="hero-bg-gradient-from"
                        className="h-8 w-10 rounded border border-zinc-300"
                      />
                      <input
                        type="text"
                        value={bg.from || ""}
                        onChange={(e) => patchBg({ from: e.target.value })}
                        className="flex-1 rounded-md border-zinc-300 text-xs px-2 py-1 border"
                      />
                    </div>
                  </label>
                  <label className="block text-xs">
                    <span className="text-zinc-600">To</span>
                    <div className="mt-1 flex items-center gap-2">
                      <input
                        type="color"
                        value={bg.to || "#1B1F5C"}
                        onChange={(e) => patchBg({ to: e.target.value })}
                        data-testid="hero-bg-gradient-to"
                        className="h-8 w-10 rounded border border-zinc-300"
                      />
                      <input
                        type="text"
                        value={bg.to || ""}
                        onChange={(e) => patchBg({ to: e.target.value })}
                        className="flex-1 rounded-md border-zinc-300 text-xs px-2 py-1 border"
                      />
                    </div>
                  </label>
                </div>
              </div>
            )}
          </div>

          {/* Special-offer badge */}
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 mb-2">
              Special-offer badge (optional)
            </div>
            {value.badge ? (
              <div className="flex items-center gap-3" data-testid="hero-badge-preview">
                <img
                  src={value.badge.url}
                  alt={value.badge.alt_text || "Badge"}
                  className="w-14 h-14 rounded object-contain border border-zinc-200 bg-zinc-50"
                  data-testid="hero-badge-thumb"
                />
                <div className="flex-1 flex flex-col gap-1 items-start">
                  <input
                    type="text"
                    value={value.badge.alt_text || ""}
                    onChange={(e) => patch({ badge: { ...value.badge, alt_text: e.target.value } })}
                    placeholder="Alt text (accessibility)"
                    className="w-full rounded-md border-zinc-300 text-xs px-2 py-1 border"
                    data-testid="hero-badge-alt-input"
                  />
                  <button
                    type="button"
                    onClick={removeBadge}
                    className="inline-flex items-center gap-1 text-xs font-semibold text-zinc-500 hover:text-zinc-900"
                    data-testid="hero-badge-remove-btn"
                  >
                    <XIcon className="w-3 h-3" />
                    Remove badge
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setPickerFor("badge")}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold text-zinc-700 bg-zinc-50 border border-zinc-200 hover:bg-zinc-100"
                data-testid="hero-badge-pick-btn"
              >
                Add badge graphic
              </button>
            )}
          </div>
        </div>
      )}

      {/* Shared MediaLibraryPicker — the ``pickerFor`` state decides
          which onSelect handler fires. Kept as a single mount so
          the picker's internal state is preserved when re-opening. */}
      <MediaLibraryPicker
        open={pickerFor !== null}
        onOpenChange={(v) => { if (!v) setPickerFor(null); }}
        onSelect={pickerFor === "image" ? onPickBgImage : onPickBadge}
        kind="image"
      />
    </div>
  );
}
