/**
 * Phase M1 · Feb-2026 — Sitewide custom teardrop map pin.
 *
 * **Canonical fallback palette**: /app/memory/tech_color_palette.md v1
 * — the ``_SAFE_PALETTE`` + ``colorFromId`` hash below are the
 * web source of truth for that memo. Any tweak to either MUST bump
 * the memo's ``version`` field AND be coordinated with the mobile
 * port so LiveTech pins agree byte-for-byte across surfaces.
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

// Feb-2026 · Numbered-pin variant. When ``TeardropPin`` receives a
// ``label`` prop, we drop the inner hollow-circle sub-path (which
// would sit under the number and read as noise) and switch to the
// solid teardrop silhouette below. Byte-identical outer curve as
// ``_TEARDROP_PATH`` — only the inner cutout differs.
const _TEARDROP_PATH_SOLID =
  "M 12 31 C 6.5 24 3 16 3 10 A 9 9 0 1 1 21 10 C 21 16 17.5 24 12 31 Z";


/**
 * Perceived-brightness threshold for choosing white vs dark text on
 * top of ``color``. Uses the classic ITU-R BT.601 luma formula —
 * cheap + good-enough for hex swatches. Threshold 128 lands the
 * flip near the middle of the usable range (matches the
 * WCAG-friendly cutoff used in ``routers/income_categories`` for
 * category chip contrast).
 */
export function pickLabelTextColor(bgHex) {
  if (!bgHex || typeof bgHex !== "string") return "#FFFFFF";
  const s = bgHex.trim();
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
      return "#FFFFFF";
    }
  } else {
    return "#FFFFFF";
  }
  if ([r, g, b].some((v) => Number.isNaN(v))) return "#FFFFFF";
  const luma = (r * 299 + g * 587 + b * 114) / 1000;
  return luma < 140 ? "#FFFFFF" : "#0F172A";
}


/** Feb-2026 · Numbered-pin label formatter. Pads left to 2 digits
 * for readability (``1`` → ``"01"``) but never truncates 3+ digit
 * inputs (``100`` → ``"100"``). Accepts number OR numeric string;
 * anything else stringifies as-is. */
export function formatPinLabel(label) {
  if (label === null || label === undefined || label === "") return null;
  if (typeof label === "number") {
    if (!Number.isFinite(label)) return String(label);
    if (label < 10 && label >= 0) return `0${label}`;
    return String(label);
  }
  const s = String(label);
  if (/^\d+$/.test(s)) {
    return s.length === 1 ? `0${s}` : s;
  }
  return s;
}


/**
 * Feb-2026 · Redesigned pin helper — lighten (positive amount) or
 * darken (negative amount) a hex by ``amt`` (0..1). Used to build
 * the glossy top/bottom stops of the head gradient.
 */
export function mixWithWhite(hex, amt) {
  if (!hex || typeof hex !== "string") return "#FFFFFF";
  const s = hex.trim();
  if (!s.startsWith("#")) return hex;
  const raw = s.slice(1);
  let r; let g; let b;
  if (raw.length === 3) {
    r = parseInt(raw[0] + raw[0], 16);
    g = parseInt(raw[1] + raw[1], 16);
    b = parseInt(raw[2] + raw[2], 16);
  } else if (raw.length === 6) {
    r = parseInt(raw.slice(0, 2), 16);
    g = parseInt(raw.slice(2, 4), 16);
    b = parseInt(raw.slice(4, 6), 16);
  } else {
    return hex;
  }
  if ([r, g, b].some((v) => Number.isNaN(v))) return hex;
  const mix = (channel) => {
    if (amt >= 0) return Math.round(channel + (255 - channel) * amt);
    return Math.round(channel + channel * amt);  // amt is negative
  };
  const hx = (v) => Math.max(0, Math.min(255, v)).toString(16).padStart(2, "0").toUpperCase();
  return `#${hx(mix(r))}${hx(mix(g))}${hx(mix(b))}`;
}


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
 * @param {(string|number)=} p.label  — Feb-2026 · Optional numbered
 *   label to render inside the pin head. When provided, the inner
 *   hollow-circle cutout is replaced with a solid silhouette + a
 *   centered zero-padded text element. Auto-picks white / dark
 *   text based on background luma. When absent, byte-identical to
 *   the pre-Feb-2026 hollow pin.
 * @param {number=} p.headingDegrees  — Feb-2026 · Optional heading
 *   angle in degrees (0 = north / up, 90 = east, 180 = south,
 *   270 = west) used by LiveTech pins to indicate the tech's
 *   current direction of travel. When a finite number is provided,
 *   a small filled chevron is rendered above the pin head and
 *   rotated by ``headingDegrees`` around the head centre (12, 10).
 *   Non-finite or missing values suppress the chevron.
 */
export default function TeardropPin({
  color,
  stroke,
  pulse = false,
  size = CANONICAL_WIDTH,
  title,
  testid = "teardrop-pin",
  label,
  // Feb-2026 · Redesigned pin — new "selected/active" prop drives
  // the scale + heavier shadow + brighter ring. Default (false) is
  // byte-compatible with existing consumers.
  selected = false,
  // Feb-2026 · Section D · Direction chevron. Numeric heading in
  // degrees clockwise-from-north. See JSDoc above.
  headingDegrees,
}) {
  const fill = color || _SAFE_PALETTE[0];
  const outerStroke = stroke || deriveDarker(fill);
  const height = Math.round((size * CANONICAL_HEIGHT) / CANONICAL_WIDTH);
  // Randomised id → scoped ``@keyframes`` name so multiple pins on
  // the same page don't clash if consumers ever forget to
  // singleton-ify the ``<style>``.
  const rid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const pulseClass = useMemo(() => `td-pulse-${rid}`, [rid]);
  const formattedLabel = formatPinLabel(label);
  const isLabeled = formattedLabel !== null;
  // Font size scales with pin size — head diameter is 18/24 of the
  // viewBox width, so a font size ~55% of head diameter reads
  // legibly at typical zoom levels (10px at size=36, 14px at
  // size=52). Longer labels (3+ chars) tighten by ~15%.
  const labelFontPx = React.useMemo(() => {
    const base = size * (18 / 24) * 0.55;
    const chars = (formattedLabel || "").length;
    if (chars >= 3) return Math.round(base * 0.82);
    return Math.round(base);
  }, [size, formattedLabel]);
  const labelTextColor = isLabeled ? pickLabelTextColor(fill) : null;
  // Feb-2026 · Redesigned pin — unique gradient/shadow ids per-pin
  // so multiple pins on the same page don't collide on the SVG
  // ``defs`` namespace (jsdom-safe + Safari-safe).
  const gradId = `td-grad-${rid}`;
  const shadowId = `td-shadow-${rid}`;
  const highlightId = `td-highlight-${rid}`;
  // Selected state boosts the ring saturation (via lighter mix with
  // white on the highlight stop) + doubles shadow opacity + adds a
  // 1.10x CSS transform anchored on the tip. Keeps the same size
  // envelope so parent-level layout math isn't affected — the
  // scale-up happens INSIDE the SVG via ``transform`` on the
  // teardrop <g> element.
  const shadowOpacity = selected ? 0.36 : 0.20;
  const shadowRy = selected ? 1.7 : 1.2;
  const selectedGroupTransform = selected
    ? "translate(12 31) scale(1.10) translate(-12 -31)"
    : undefined;
  // Slightly brighter ring when selected — mix the base fill with
  // white by 22%. Uses the shared ``mixWithWhite`` helper below.
  const ringFillTop = selected ? mixWithWhite(fill, 0.35) : mixWithWhite(fill, 0.20);
  const ringFillBottom = selected ? mixWithWhite(fill, -0.12) : mixWithWhite(fill, -0.20);
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={height}
      viewBox="0 0 24 32"
      role={title ? "img" : "presentation"}
      aria-label={title || (isLabeled ? `Map pin ${formattedLabel}` : undefined)}
      data-testid={testid}
      data-pulse={pulse ? "true" : "false"}
      data-label={isLabeled ? formattedLabel : undefined}
      data-selected={selected ? "true" : "false"}
      data-heading={Number.isFinite(headingDegrees) ? String(headingDegrees) : undefined}
      style={{ overflow: "visible", display: "inline-block" }}
    >
      {title ? <title>{title}</title> : null}
      {/* Feb-2026 · Redesigned pin — original SVG artwork.
           Defs = per-pin gradient (glossy head), highlight ellipse,
           soft drop-shadow filter. All ids are scoped by ``rid`` so
           multiple pins on the same page don't clash. */}
      <defs>
        <linearGradient id={gradId} x1="0.15" y1="0.15" x2="0.85" y2="0.85">
          <stop offset="0" stopColor={ringFillTop} />
          <stop offset="0.55" stopColor={fill} />
          <stop offset="1" stopColor={ringFillBottom} />
        </linearGradient>
        <radialGradient id={highlightId} cx="0.32" cy="0.30" r="0.38">
          <stop offset="0" stopColor="#FFFFFF" stopOpacity="0.55" />
          <stop offset="1" stopColor="#FFFFFF" stopOpacity="0" />
        </radialGradient>
        <filter id={shadowId} x="-40%" y="-20%" width="180%" height="160%">
          <feGaussianBlur in="SourceAlpha" stdDeviation="0.6" />
          <feOffset dx="0" dy="0.4" result="offset" />
          <feComponentTransfer>
            <feFuncA type="linear" slope={shadowOpacity} />
          </feComponentTransfer>
          <feMerge>
            <feMergeNode />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {/* Soft blurred ellipse under the tip. Independent of the
           SVG filter so it always renders (older engines that skip
           filters still show a grounded pin). */}
      <ellipse
        cx="12"
        cy="31.4"
        rx={selected ? 5 : 4.2}
        ry={shadowRy}
        fill="#000000"
        fillOpacity={shadowOpacity}
        data-testid={`${testid}-shadow`}
      />
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
      <g transform={selectedGroupTransform}
          data-testid={`${testid}-group`}>
        {/* Colored teardrop body — glossy linear gradient. Always
             renders as the solid silhouette; the inner white disc
             below sits ON TOP when a label is present. */}
        <path
          d={_TEARDROP_PATH_SOLID}
          fill={`url(#${gradId})`}
          stroke={outerStroke}
          strokeWidth={selected ? "1.2" : "1"}
          strokeLinejoin="round"
          data-color={fill}
          data-testid={`${testid}-body`}
        />
        {/* Glossy highlight — top-left → transparent. Reads as a
             specular sheen without disturbing the underlying color. */}
        <circle
          cx="12" cy="10" r="8.2"
          fill={`url(#${highlightId})`}
          data-testid={`${testid}-highlight`}
        />
        {isLabeled ? (
          <>
            {/* White inner disc that hosts the numbered label. Kept
                 slightly smaller than the head to leave a colored
                 ring visible. */}
            <circle
              cx="12" cy="10" r="5.6"
              fill="#FFFFFF"
              stroke={outerStroke}
              strokeOpacity="0.35"
              strokeWidth="0.4"
              data-testid={`${testid}-disc`}
            />
            <text
              x="12"
              y="10"
              textAnchor="middle"
              dominantBaseline="central"
              fontSize={labelFontPx}
              fontFamily="system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
              fontWeight="700"
              fill="#0F172A"
              style={{ pointerEvents: "none", userSelect: "none" }}
              data-testid={`${testid}-label`}
            >
              {formattedLabel}
            </text>
          </>
        ) : null}
        {/* Feb-2026 · Section D · Direction chevron. Rendered only
             when ``headingDegrees`` is a finite number. Tip sits
             above the head silhouette (y = -2) and the base spans
             (9.5..14.5) at y = 3, so the chevron reads as a small
             arrow pointing "up" at heading 0. Rotated around the
             head centre (12, 10) so any heading orbits smoothly.
             ``pointerEvents:none`` keeps the click surface on the
             pin body — the chevron is decorative. */}
        {Number.isFinite(headingDegrees) ? (
          <g
            transform={`rotate(${headingDegrees} 12 10)`}
            data-testid={`${testid}-chevron`}
            data-heading={headingDegrees}
            style={{ pointerEvents: "none" }}
          >
            <path
              d="M 12 -2 L 14.5 3 L 9.5 3 Z"
              fill={fill}
              stroke={outerStroke}
              strokeWidth="0.6"
              strokeLinejoin="round"
              data-testid={`${testid}-chevron-tip`}
            />
          </g>
        ) : null}
      </g>
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
