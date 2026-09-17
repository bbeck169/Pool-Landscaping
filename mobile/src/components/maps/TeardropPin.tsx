/**
 * Phase M1 · Redesigned TeardropPin — React Native (react-native-svg).
 *
 * Mirrors `frontend/src/components/maps/TeardropPin.jsx` v2:
 *   • Glossy gradient body (linear gradient top-left → bottom-right)
 *   • White inner disc for numbered/text label
 *   • Soft drop-shadow ellipse under the tip
 *   • Radial highlight (top-left specular sheen)
 *   • `selected` prop → 1.1x scale + heavier shadow + brighter ring
 *   • `label` prop → centered text inside white disc
 *   • `size` prop → proportional scaling (default 36)
 *
 * Exports:
 *   - <TeardropPin />
 *   - colorFromId(id) — 12-color deterministic palette
 *   - deriveDarker(hex, pct) — darken a hex
 *   - mixWithWhite(hex, amt) — lighten/darken by amount
 *   - formatPinLabel(label) — zero-pad single digits
 *   - pickLabelTextColor(bgHex) — BT.601 luma → white/dark text
 */
import React, { useMemo } from "react";
import { View, StyleSheet } from "react-native";
import Svg, {
  Path, Circle, Ellipse, Defs,
  LinearGradient, RadialGradient, Stop,
  G, Text as SvgText,
} from "react-native-svg";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withTiming,
  Easing,
} from "react-native-reanimated";

/* ── Constants ──────────────────────────────────────────────────────── */

export const CANONICAL_WIDTH = 36;
export const CANONICAL_HEIGHT = 48;

// ViewBox is 24×32; head centered at (12,10) r=9.
const VB_W = 24;
const VB_H = 32;

// Solid teardrop silhouette (no inner cutout).
const TEARDROP_PATH_SOLID =
  "M 12 31 C 6.5 24 3 16 3 10 A 9 9 0 1 1 21 10 C 21 16 17.5 24 12 31 Z";

/* ── Palette ────────────────────────────────────────────────────────── */

const PALETTE = [
  "#EF4444", "#F97316", "#EAB308", "#22C55E", "#10B981", "#06B6D4",
  "#0EA5E9", "#3B82F6", "#6366F1", "#8B5CF6", "#EC4899", "#14B8A6",
] as const;

/**
 * Deterministic hash → one of 12 safe palette colors.
 * Same `id` always resolves the same color across platforms.
 */
export function colorFromId(id: string | null | undefined): string {
  if (!id) return PALETTE[0];
  const s = String(id);
  let hash = 0;
  for (let i = 0; i < s.length; i += 1) {
    hash = ((hash * 31) + s.charCodeAt(i)) | 0;
  }
  return PALETTE[Math.abs(hash) % 12];
}

/* ── Color helpers ──────────────────────────────────────────────────── */

function _parseHex6(hex: string): [number, number, number] | null {
  if (!hex || typeof hex !== "string") return null;
  const s = hex.trim().replace(/^#/, "");
  if (s.length === 3) {
    return [
      parseInt(s[0] + s[0], 16),
      parseInt(s[1] + s[1], 16),
      parseInt(s[2] + s[2], 16),
    ];
  }
  if (s.length === 6) {
    return [
      parseInt(s.slice(0, 2), 16),
      parseInt(s.slice(2, 4), 16),
      parseInt(s.slice(4, 6), 16),
    ];
  }
  return null;
}

const _hx = (v: number) =>
  Math.max(0, Math.min(255, v)).toString(16).padStart(2, "0");

/** Darken a hex color by `pct` (0-1, default 0.28). */
export function deriveDarker(hex: string, pct: number = 0.28): string {
  const rgb = _parseHex6(hex);
  if (!rgb) return "#334155";
  const [r, g, b] = rgb;
  const d = (v: number) => Math.max(0, Math.round(v * (1 - pct)));
  return `#${_hx(d(r))}${_hx(d(g))}${_hx(d(b))}`;
}

/** Lighten (+amt) or darken (-amt) a hex by `amt` (0..1). */
export function mixWithWhite(hex: string, amt: number): string {
  const rgb = _parseHex6(hex);
  if (!rgb) return "#FFFFFF";
  const mix = (ch: number) => {
    if (amt >= 0) return Math.round(ch + (255 - ch) * amt);
    return Math.round(ch + ch * amt); // amt is negative
  };
  return `#${_hx(mix(rgb[0]))}${_hx(mix(rgb[1]))}${_hx(mix(rgb[2]))}`.toUpperCase();
}

/**
 * BT.601 luma → white or dark-slate text for labels on colored bg.
 * Threshold 140 matches the web pin.
 */
export function pickLabelTextColor(bgHex: string): string {
  const rgb = _parseHex6(bgHex);
  if (!rgb) return "#FFFFFF";
  const luma = (rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114) / 1000;
  return luma < 140 ? "#FFFFFF" : "#0F172A";
}

/**
 * Zero-pad single-digit numbers: 1 → "01", 10 → "10", "A" → "A".
 */
export function formatPinLabel(
  label: string | number | null | undefined,
): string | null {
  if (label === null || label === undefined || label === "") return null;
  if (typeof label === "number") {
    if (!Number.isFinite(label)) return String(label);
    if (label < 10 && label >= 0) return `0${label}`;
    return String(label);
  }
  const s = String(label);
  if (/^\d+$/.test(s)) return s.length === 1 ? `0${s}` : s;
  return s;
}

/* ── Component ──────────────────────────────────────────────────────── */

export interface TeardropPinProps {
  /** Fill color (hex, required). */
  color: string;
  /** Optional label rendered inside the white disc. */
  label?: string | number;
  /** Selected state: scale 1.1x, brighter ring, heavier shadow. */
  selected?: boolean;
  /** Override the canonical 36px width. */
  size?: number;
  /** Pulsing halo for fresh GPS state. */
  pulse?: boolean;
  /** Backward-compat: arbitrary overlay children. */
  children?: React.ReactNode;
  /** testID for the outer wrapper. */
  testID?: string;
}

let _idCounter = 0;

export default function TeardropPin({
  color,
  label,
  selected = false,
  size = CANONICAL_WIDTH,
  pulse = false,
  children,
  testID,
}: TeardropPinProps) {
  const fill = color || PALETTE[0];
  const outerStroke = deriveDarker(fill);
  const height = Math.round((size * CANONICAL_HEIGHT) / CANONICAL_WIDTH);

  // Unique IDs for SVG defs so multiple pins don't clash.
  const uid = useMemo(() => `tp${++_idCounter}`, []);

  const formattedLabel = formatPinLabel(label);
  const isLabeled = formattedLabel !== null;

  // Font size scales with pin: head ≈ 18/24 of viewBox → 55% of head diameter.
  const labelFontSize = useMemo(() => {
    const base = (18 / VB_W) * VB_W * 0.55;
    const chars = (formattedLabel || "").length;
    return chars >= 3 ? Math.round(base * 0.82) : Math.round(base);
  }, [formattedLabel]);

  // Gradient stops for the glossy head.
  const ringFillTop = selected
    ? mixWithWhite(fill, 0.35)
    : mixWithWhite(fill, 0.20);
  const ringFillBottom = selected
    ? mixWithWhite(fill, -0.12)
    : mixWithWhite(fill, -0.20);

  const shadowOpacity = selected ? 0.36 : 0.20;
  const shadowRy = selected ? 1.7 : 1.2;
  const strokeW = selected ? 1.2 : 1;

  // Scale transform for selected state, anchored at the tip (12, 31).
  const groupTransform = selected
    ? "translate(12, 31) scale(1.10) translate(-12, -31)"
    : undefined;

  const accessLabel = isLabeled
    ? `Map pin ${formattedLabel} color ${fill}`
    : `Map pin color ${fill}`;

  return (
    <View
      style={[styles.wrapper, { width: size, height: height + 4 }]}
      testID={testID}
      accessibilityLabel={accessLabel}
    >
      {pulse ? <PulseHalo color={fill} size={size} /> : null}

      <Svg
        width={size}
        height={height}
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        testID={testID ? `${testID}-svg` : undefined}
      >
        <Defs>
          {/* Glossy head gradient */}
          <LinearGradient id={`grad-${uid}`} x1="0.15" y1="0.15" x2="0.85" y2="0.85">
            <Stop offset="0" stopColor={ringFillTop} />
            <Stop offset="0.55" stopColor={fill} />
            <Stop offset="1" stopColor={ringFillBottom} />
          </LinearGradient>
          {/* Specular highlight */}
          <RadialGradient id={`hl-${uid}`} cx="0.32" cy="0.30" r="0.38">
            <Stop offset="0" stopColor="#FFFFFF" stopOpacity={0.55} />
            <Stop offset="1" stopColor="#FFFFFF" stopOpacity={0} />
          </RadialGradient>
        </Defs>

        {/* Drop shadow ellipse */}
        <Ellipse
          cx={12}
          cy={31.4}
          rx={selected ? 5 : 4.2}
          ry={shadowRy}
          fill="#000000"
          fillOpacity={shadowOpacity}
          testID={testID ? `${testID}-shadow` : undefined}
        />

        <G transform={groupTransform} testID={testID ? `${testID}-group` : undefined}>
          {/* Colored teardrop body with gradient */}
          <Path
            d={TEARDROP_PATH_SOLID}
            fill={`url(#grad-${uid})`}
            stroke={outerStroke}
            strokeWidth={strokeW}
            strokeLinejoin="round"
            testID={testID ? `${testID}-body` : undefined}
          />

          {/* Glossy highlight circle */}
          <Circle
            cx={12}
            cy={10}
            r={8.2}
            fill={`url(#hl-${uid})`}
            testID={testID ? `${testID}-highlight` : undefined}
          />

          {isLabeled ? (
            <>
              {/* White inner disc */}
              <Circle
                cx={12}
                cy={10}
                r={5.6}
                fill="#FFFFFF"
                stroke={outerStroke}
                strokeOpacity={0.35}
                strokeWidth={0.4}
                testID={testID ? `${testID}-disc` : undefined}
              />
              {/* Centered label text */}
              <SvgText
                x={12}
                y={10}
                textAnchor="middle"
                alignmentBaseline="central"
                fontSize={labelFontSize}
                fontWeight="700"
                fill="#0F172A"
                testID={testID ? `${testID}-label` : undefined}
              >
                {formattedLabel}
              </SvgText>
            </>
          ) : null}
        </G>
      </Svg>

      {/* Legacy children overlay (backward compat) */}
      {children && !isLabeled ? (
        <View style={styles.childOverlay} pointerEvents="none">
          {children}
        </View>
      ) : null}
    </View>
  );
}

/* ── Pulse Halo ────────────────────────────────────────────────────── */

function PulseHalo({ color, size }: { color: string; size: number }) {
  const opacity = useSharedValue(0.6);

  React.useEffect(() => {
    opacity.value = withRepeat(
      withTiming(0, { duration: 1500, easing: Easing.out(Easing.ease) }),
      -1,
      true,
    );
  }, [opacity]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
    transform: [{ scale: 1 + (1 - opacity.value) * 0.5 }],
  }));

  const haloSize = size + 8;
  return (
    <Animated.View
      style={[
        {
          position: "absolute",
          top: -2,
          left: (size - haloSize) / 2,
          width: haloSize,
          height: haloSize,
          borderRadius: haloSize / 2,
          borderWidth: 3,
          borderColor: color,
          backgroundColor: "transparent",
        },
        animatedStyle,
      ]}
      testID="teardrop-pin-pulse-halo"
    />
  );
}

/* ── Styles ──────────────────────────────────────────────────────────── */

const styles = StyleSheet.create({
  wrapper: {
    alignItems: "center",
    justifyContent: "flex-start",
  },
  childOverlay: {
    position: "absolute",
    top: 6,
    left: 0,
    right: 0,
    height: 24,
    alignItems: "center",
    justifyContent: "center",
  },
});
