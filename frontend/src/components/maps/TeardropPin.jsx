/**
 * Phase M1 · Feb-2026 — Sitewide custom teardrop map pin.
 *
 * Draws a classic teardrop map-marker silhouette (round head +
 * tapered tail) with a HOLLOW center — the "circle in the middle"
 * is a transparent hole, not a darker dot.  Anchored at the bottom
 * tip so map libs (Google, HERE, Leaflet) place the pin exactly on
 * the ``{lat, lng}`` coordinate.
 *
 * Design constants (locked)
 * -------------------------
 * * Canonical size:  36 px × 48 px viewport (a 3:4 tear-drop).
 *   ``size`` prop scales BOTH width + height in that ratio.
 * * Head radius:     9 units (out of 24-unit viewBox width).
 * * Hollow radius:   4.5 units (a 50% inset — enough to feel like
 *                    a ring, not a donut).
 * * Anchor:          bottom tip = (viewBoxW / 2, viewBoxH).
 * * Stroke:          1 px, ``deriveDarker(color)`` unless the
 *                    caller passes an explicit ``stroke`` prop.
 * * Halo:            radius 12 (larger than head), same color,
 *                    30% opacity, ~2px stroke.  Animated pulse
 *                    via a CSS ``@keyframes`` — inline
 *                    ``<style>`` scoped by a randomised class so
 *                    the same rule is emitted at most once per
 *                    consumer (jsdom is happy with duplicates
 *                    anyway).
 *
 * Google Maps icon fallback
 * -------------------------
 * The site's primary map surfaces (Dispatch, Schedule,
 * RouteReplay) use ``AdvancedMarkerElement`` with React HTML
 * content, so the pulsing halo renders NATURALLY via CSS.
 *
 * ``toGoogleMapsIcon({ color, pulse })`` still exists for legacy
 * classic ``google.maps.Marker(icon: …)`` surfaces — it emits a
 * data-URL SVG string.  Rasterised icons CANNOT be CSS-animated,
 * so when ``pulse=true`` the emitted SVG carries a STATIC halo
 * ring at 30% opacity (visible but not animated).  Consumers that
 * need an animated fresh-pin overlay must migrate to
 * ``AdvancedMarkerElement`` or use a DOM overlay.
 */
import React, { useId, useMemo } from "react";

export const CANONICAL_WIDTH  = 36;
export const CANONICAL_HEIGHT = 48;

// 12-color deterministic palette used by ``colorFromId``.  Picked
// for accessible contrast against a white background AND against a
// road-style Google Maps tile (no near-yellows / near-whites).
const _SAFE_PALETTE = [
  "#EF4444", // red-500
  "#F97316", // orange-500
  "#EAB308", // yellow-500
  "#22C55E", // green-500
  "#10B981", // emerald-500
  "#06B6D4", // cyan-500
  "#0EA5E9", // sky-500
  "#3B82F6", // blue-500
  "#6366F1", // indigo-500
  "#8B5CF6", // violet-500
  "#EC4899", // pink-500
  "#14B8A6", // teal-500
];


/**
 * Deterministic hash → one of the 12 safe palette colors.  Same
 * ``id`` always resolves to the same color across processes.
 */
export function colorFromId(id) {
  if (!id) return _SAFE_PALETTE[0];
  const s = String(id);
  let hash = 0;
  for (let i = 0; i < s.length; i += 1) {
    // 31·h + c — the classic Java ``String.hashCode`` recipe;
    // fast + platform-independent.
    hash = ((hash * 31) + s.charCodeAt(i)) | 0;
  }
  const idx = Math.abs(hash) % _SAFE_PALETTE.length;
  return _SAFE_PALETTE[idx];
}


/**
 * Monotonically darken a hex or ``rgb(r,g,b)`` input by ~18%.
 * Preserves the input's alpha where applicable.  Non-parseable
 * inputs fall through to a neutral slate stroke.
 */
export function deriveDarker(input) {
  if (!input || typeof input !== "string") return "#334155";
  const s = input.trim();
  let r; let g; let b;
  if (s.startsWith("#")) {
    const hex = s.slice(1);
    if (hex.length === 3) {
      r = parseInt(hex[0] + hex[0], 16);
      g = parseInt(hex[1] + hex[1], 16);
      b = parseInt(hex[2] + hex[2], 16);
    } else if (hex.length === 6) {
      r = parseInt(hex.slice(0, 2), 16);
      g = parseInt(hex.slice(2, 4), 16);
      b = parseInt(hex.slice(4, 6), 16);
    } else {
      return "#334155";
    }
  } else if (s.startsWith("rgb")) {
    const m = s.match(/rgba?\(([^)]+)\)/i);
    if (!m) return "#334155";
    const parts = m[1].split(",").map((p) => parseFloat(p.trim()));
    if (parts.length < 3) return "#334155";
    [r, g, b] = parts;
  } else {
    return "#334155";
  }
  if ([r, g, b].some((v) => Number.isNaN(v))) return "#334155";
  const _darken = (v) => Math.max(0, Math.min(255, Math.round(v * 0.72)));
  const hex = (v) => v.toString(16).padStart(2, "0");
  return `#${hex(_darken(r))}${hex(_darken(g))}${hex(_darken(b))}`;
}


// The canonical teardrop SVG path (viewBox 0 0 24 32).
//   Outer teardrop:  bottom-tip (12, 31) → sweeps up through a
//                    round head centered at (12, 10) with r=9.
//   Inner circle:    counter-clockwise 4.5-r hole centered at the
//                    same head origin.
// ``fill-rule="evenodd"`` on the parent path makes the inner
// circle a transparent hole regardless of the fill color.
const _TEARDROP_PATH =
  "M 12 31 C 6.5 24 3 16 3 10 A 9 9 0 1 1 21 10 C 21 16 17.5 24 12 31 Z " +
  "M 12 5.5 A 4.5 4.5 0 1 0 12 14.5 A 4.5 4.5 0 1 0 12 5.5 Z";


/**
 * Inline React teardrop pin.
 *
 * @param {object}  p
 * @param {string}  p.color   — solid fill (required).
 * @param {string=} p.stroke  — override the auto-derived darker stroke.
 * @param {boolean=} p.pulse  — render an animated halo around the head.
 * @param {number=} p.size    — override the canonical 36px width.
 * @param {string=} p.title   — accessible label (``<title>`` element).
 * @param {string=} p.testid  — data-testid on the SVG root.
 */
export default function TeardropPin({
  color,
  stroke,
  pulse = false,
  size = CANONICAL_WIDTH,
  title,
  testid = "teardrop-pin",
}) {
  const fill = color || _SAFE_PALETTE[0];
  const outerStroke = stroke || deriveDarker(fill);
  const height = Math.round((size * CANONICAL_HEIGHT) / CANONICAL_WIDTH);
  // Randomised id → scoped ``@keyframes`` name so multiple pins on
  // the same page don't clash if consumers ever forget to
  // singleton-ify the ``<style>``.
  const rid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const pulseClass = useMemo(() => `td-pulse-${rid}`, [rid]);
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={height}
      viewBox="0 0 24 32"
      role={title ? "img" : "presentation"}
      aria-label={title || undefined}
      data-testid={testid}
      data-pulse={pulse ? "true" : "false"}
      style={{ overflow: "visible", display: "inline-block" }}
    >
      {title ? <title>{title}</title> : null}
      {pulse ? (
        <>
          <style>{`
            @keyframes ${pulseClass} {
              0%   { transform: scale(0.85); opacity: 0.55; }
              70%  { transform: scale(1.35); opacity: 0.08; }
              100% { transform: scale(1.55); opacity: 0.00; }
            }
            .${pulseClass} {
              transform-origin: 12px 10px;
              transform-box: fill-box;
              animation: ${pulseClass} 1.7s ease-out infinite;
            }
          `}</style>
          <circle
            cx="12" cy="10" r="10"
            fill={fill} fillOpacity="0.35"
            data-testid={`${testid}-halo`}
            className={pulseClass}
          />
        </>
      ) : null}
      <path
        d={_TEARDROP_PATH}
        fill={fill}
        stroke={outerStroke}
        strokeWidth="1"
        fillRule="evenodd"
        clipRule="evenodd"
        data-testid={`${testid}-body`}
      />
    </svg>
  );
}


/**
 * Emit a Google-Maps-compatible ``icon`` object usable by classic
 * ``google.maps.Marker`` OR ``@react-google-maps/api``'s
 * ``<Marker icon=…>``.  Anchor is the bottom tip.
 *
 * Halo behaviour on rasterised icons: because the icon is a static
 * ``url(data:image/svg+xml;base64,…)`` bitmap, we cannot CSS-animate
 * it.  When ``pulse=true`` we emit a STATIC halo ring at 30%
 * opacity — visible enough to distinguish fresh from stale pins
 * without motion.  For animated haloes, migrate the consumer to
 * ``AdvancedMarkerElement`` (see ``DispatchMapView.jsx`` +
 * ``ScheduleMap.jsx`` for the pattern).
 */
export function toGoogleMapsIcon({ color, pulse = false, size = CANONICAL_WIDTH } = {}) {
  const fill = color || _SAFE_PALETTE[0];
  const outerStroke = deriveDarker(fill);
  const height = Math.round((size * CANONICAL_HEIGHT) / CANONICAL_WIDTH);
  const haloSvg = pulse
    ? `<circle cx="12" cy="10" r="10" fill="${fill}" fill-opacity="0.30"/>`
    : "";
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${height}" viewBox="0 0 24 32">` +
    haloSvg +
    `<path d="${_TEARDROP_PATH}" fill="${fill}" stroke="${outerStroke}" stroke-width="1" fill-rule="evenodd" clip-rule="evenodd"/>` +
    "</svg>";
  const encoded =
    typeof btoa === "function"
      ? btoa(svg)
      // Node/SSR fallback for tests.
      : Buffer.from(svg, "utf-8").toString("base64");
  const url = `data:image/svg+xml;base64,${encoded}`;
  // Only expose Google-shaped ``Size`` / ``Point`` constructors
  // when they exist (i.e. after the Maps JS SDK is loaded).  In
  // jsdom / SSR we return a plain-object icon that
  // ``@react-google-maps/api`` will lift through its own guards.
  const _g = (typeof window !== "undefined" && window.google && window.google.maps) || null;
  if (_g && _g.Size && _g.Point) {
    return {
      url,
      scaledSize: new _g.Size(size, height),
      anchor:     new _g.Point(size / 2, height),
      labelOrigin: new _g.Point(size / 2, 12),
    };
  }
  return {
    url,
    // Plain-object shapes — some libraries accept these directly.
    scaledSize: { width: size, height },
    anchor:     { x: size / 2, y: height },
    labelOrigin: { x: size / 2, y: 12 },
  };
}
