/**
 * Phase M1 · Apr-2026 — Sitewide custom teardrop map pin.
 *
 * Classic teardrop map-marker silhouette:
 *   • Round head + tapered tail pointing down
 *   • Anchor at bottom tip
 *   • Hollow center (transparent circular cutout)
 *   • Solid fill (`color` prop) with 1px darker stroke
 *   • Optional pulsing halo ring for "fresh GPS" state
 *
 * Fixed size: 36 × 48 px.
 *
 * Exports:
 *   - <TeardropPin />        — the SVG component
 *   - colorFromId(id)        — 12-color deterministic palette
 *   - deriveDarker(hex, pct) — darken a hex color
 */
import React from "react";
import { View, StyleSheet } from "react-native";
import Svg, { Path, Circle } from "react-native-svg";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withTiming,
  Easing,
} from "react-native-reanimated";

/* ── Helpers ────────────────────────────────────────────────────────── */

/**
 * 12-color deterministic palette — matches the web counterpart.
 * Given a string id, returns one of 12 fixed hex colors.
 */
const PALETTE_12 = [
  "#EF4444", // red-500
  "#F97316", // orange-500
  "#EAB308", // yellow-500
  "#22C55E", // green-500
  "#14B8A6", // teal-500
  "#06B6D4", // cyan-500
  "#3B82F6", // blue-500
  "#6366F1", // indigo-500
  "#8B5CF6", // violet-500
  "#A855F7", // purple-500
  "#EC4899", // pink-500
  "#F43F5E", // rose-500
] as const;

export function colorFromId(id: string): string {
  let h = 0;
  for (let i = 0; i < (id || "").length; i++) {
    h = ((h << 5) - h + id.charCodeAt(i)) | 0;
  }
  return PALETTE_12[Math.abs(h) % PALETTE_12.length];
}

/**
 * Darken a hex color by `pct` (0-1, default 0.25).
 * E.g. deriveDarker("#EF4444", 0.25) → a 25% darker red.
 */
export function deriveDarker(hex: string, pct: number = 0.25): string {
  const c = hex.replace("#", "");
  const r = Math.max(0, Math.round(parseInt(c.substring(0, 2), 16) * (1 - pct)));
  const g = Math.max(0, Math.round(parseInt(c.substring(2, 4), 16) * (1 - pct)));
  const b = Math.max(0, Math.round(parseInt(c.substring(4, 6), 16) * (1 - pct)));
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

/* ── Teardrop SVG ──────────────────────────────────────────────────── */

// The teardrop path in a 36×48 viewBox:
// Round head centered at (18, 18) with radius 14,
// tapered tail converging to the bottom tip at (18, 46).
//
// M 18 2                          — top of the head
// C 8 2, 2 9, 2 18               — left side of round head
// C 2 27, 18 46, 18 46           — left taper to bottom tip
// C 18 46, 34 27, 34 18          — right taper from bottom tip
// C 34 9, 28 2, 18 2 Z           — right side of round head, close
const TEARDROP_PATH =
  "M 18 2 C 8 2, 2 9, 2 18 C 2 27, 18 46, 18 46 C 18 46, 34 27, 34 18 C 34 9, 28 2, 18 2 Z";

const PIN_W = 36;
const PIN_H = 48;
// Hollow-center hole: circle at center of head (18,18), radius ~7
const HOLE_CX = 18;
const HOLE_CY = 18;
const HOLE_R = 7;

/* ── Component ─────────────────────────────────────────────────────── */

export interface TeardropPinProps {
  /** Fill color for the pin body */
  color: string;
  /** Whether to show the pulsing halo ring (fresh GPS) */
  pulse?: boolean;
  /** Optional children rendered inside the pin head (e.g. initials, number) */
  children?: React.ReactNode;
  /** testID for the outer wrapper */
  testID?: string;
}

export default function TeardropPin({
  color,
  pulse = false,
  children,
  testID,
}: TeardropPinProps) {
  const strokeColor = deriveDarker(color, 0.3);

  return (
    <View style={styles.wrapper} testID={testID}>
      {/* Pulsing halo ring (renders behind the pin) */}
      {pulse ? <PulseHalo color={color} /> : null}

      {/* SVG teardrop shape */}
      <Svg
        width={PIN_W}
        height={PIN_H}
        viewBox={`0 0 ${PIN_W} ${PIN_H}`}
        style={styles.svg}
      >
        <Path
          d={TEARDROP_PATH}
          fill={color}
          stroke={strokeColor}
          strokeWidth={1}
        />
        {/* Hollow center (transparent hole) */}
        <Circle
          cx={HOLE_CX}
          cy={HOLE_CY}
          r={HOLE_R}
          fill="white"
        />
      </Svg>

      {/* Optional overlay content (initials, numbers) inside the head */}
      {children ? (
        <View style={styles.childOverlay} pointerEvents="none">
          {children}
        </View>
      ) : null}
    </View>
  );
}

/* ── Pulse Halo ────────────────────────────────────────────────────── */

function PulseHalo({ color }: { color: string }) {
  const opacity = useSharedValue(0.6);

  React.useEffect(() => {
    opacity.value = withRepeat(
      withTiming(0, { duration: 1500, easing: Easing.out(Easing.ease) }),
      -1, // infinite
      true, // reverse
    );
  }, [opacity]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
    transform: [{ scale: 1 + (1 - opacity.value) * 0.5 }],
  }));

  return (
    <Animated.View
      style={[
        styles.halo,
        { borderColor: color },
        animatedStyle,
      ]}
      testID="teardrop-pin-pulse-halo"
    />
  );
}

/* ── Styles ─────────────────────────────────────────────────────────── */

const styles = StyleSheet.create({
  wrapper: {
    width: PIN_W,
    height: PIN_H,
    alignItems: "center",
    justifyContent: "flex-start",
  },
  svg: {
    // Pin SVG sits at the top of the wrapper
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
  halo: {
    position: "absolute",
    top: 2,
    left: -2,
    width: 40,
    height: 40,
    borderRadius: 20,
    borderWidth: 3,
    backgroundColor: "transparent",
  },
});
