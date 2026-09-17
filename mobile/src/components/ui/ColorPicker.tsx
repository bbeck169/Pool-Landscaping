/**
 * Feb-2026 · Global Custom Color Picker — React Native.
 *
 * Mirrors `frontend/src/components/ui/ColorPicker.jsx`:
 *   1. Preset swatches row from `GET /api/tech-colors/palette`.
 *   2. Recently used row from `GET /api/users/me/recent-colors` (max 8).
 *   3. Freeform hex input + live preview + HSL hue slider.
 *   4. Contrast guard: blocks colors below WCAG 3:1 vs white.
 *   5. Apply button → onChange callback + POST recent-colors.
 *
 * Zero new native modules — the hue picker is a pure-RN Slider.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, TextInput, Pressable, ScrollView,
  StyleSheet, ActivityIndicator,
} from "react-native";
import Slider from "@react-native-community/slider";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import {
  MIN_CONTRAST_VS_WHITE,
  contrastRatioVsWhite,
  validateColorHexForPin,
} from "@/src/lib/colorContrast";

/* ── Helpers ────────────────────────────────────────────────────────── */

function _norm(hex: string | undefined | null): string {
  if (!hex || typeof hex !== "string") return "";
  const s = hex.trim();
  if (!s) return "";
  return (s.startsWith("#") ? s : `#${s}`).toUpperCase();
}

/** Convert HSL (h 0-360, s 0-1, l 0-1) to hex. */
function hslToHex(h: number, s: number, l: number): string {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let r = 0, g = 0, b = 0;
  if (h < 60)       { r = c; g = x; }
  else if (h < 120) { r = x; g = c; }
  else if (h < 180) { g = c; b = x; }
  else if (h < 240) { g = x; b = c; }
  else if (h < 300) { r = x; b = c; }
  else              { r = c; b = x; }
  const to255 = (v: number) =>
    Math.round((v + m) * 255).toString(16).padStart(2, "0").toUpperCase();
  return `#${to255(r)}${to255(g)}${to255(b)}`;
}

/* ── Component ──────────────────────────────────────────────────────── */

export interface ColorPickerProps {
  /** Current committed hex. */
  value?: string;
  /** Fires only when a valid, contrast-passing hex is committed. */
  onChange?: (hex: string) => void | Promise<void>;
  /** Gates every interactive element. */
  disabled?: boolean;
  /** testID prefix. */
  testidPrefix?: string;
}

export default function ColorPicker({
  value,
  onChange,
  disabled = false,
  testidPrefix = "color-picker",
}: ColorPickerProps) {
  const normalized = _norm(value);
  const [draft, setDraft] = useState(normalized || "");
  const [palette, setPalette] = useState<{ name: string; hex: string }[]>([]);
  const [recent, setRecent] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [hue, setHue] = useState(210); // default blue

  useEffect(() => { setDraft(normalized || ""); }, [normalized]);

  // Fetch presets
  useEffect(() => {
    let alive = true;
    api.get("/tech-colors/palette").then((r: any) => {
      if (!alive) return;
      const list = Array.isArray(r?.palette) ? r.palette : [];
      setPalette(list);
    }).catch(() => { /* silent */ });
    return () => { alive = false; };
  }, []);

  // Fetch recents
  useEffect(() => {
    let alive = true;
    api.get("/users/me/recent-colors").then((r: any) => {
      if (!alive) return;
      const list = Array.isArray(r?.recent_colors) ? r.recent_colors : [];
      setRecent(list.map(_norm).filter(Boolean));
    }).catch(() => { /* silent */ });
    return () => { alive = false; };
  }, []);

  const draftValidation = useMemo(
    () => validateColorHexForPin(draft || "#000000"),
    [draft],
  );
  const commitDisabled =
    disabled ||
    saving ||
    !draftValidation.ok ||
    (draftValidation.ok && _norm(draftValidation.canonical) === normalized);

  const commit = useCallback(
    async (hex: string) => {
      const validation = validateColorHexForPin(hex);
      if (!validation.ok) return;
      setSaving(true);
      try {
        const canonical = validation.canonical;
        await Promise.resolve(onChange?.(canonical));
        // Fire-and-forget recent-colors push.
        api.post("/users/me/recent-colors", { color: canonical })
          .then((r: any) => {
            const next = Array.isArray(r?.recent_colors)
              ? r.recent_colors.map(_norm).filter(Boolean)
              : null;
            if (next) setRecent(next);
          })
          .catch(() => { /* silent */ });
      } finally {
        setSaving(false);
      }
    },
    [onChange],
  );

  const onHueChange = useCallback(
    (h: number) => {
      setHue(h);
      // Convert hue to a saturated hex at 50% lightness.
      const hex = hslToHex(h, 0.75, 0.45);
      setDraft(_norm(hex));
    },
    [],
  );

  return (
    <View
      style={s.root}
      testID={`${testidPrefix}-root`}
    >
      {/* ── Presets row ──────────────────────────────────────────── */}
      <Text style={s.sectionLabel}>Presets</Text>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={s.swatchRow}
        testID={`${testidPrefix}-presets`}
      >
        {palette.map((p) => {
          const hex = _norm(p.hex);
          const active = hex === normalized;
          const v = validateColorHexForPin(p.hex);
          const tooLight = !v.ok;
          return (
            <Pressable
              key={hex}
              onPress={() => !tooLight && commit(p.hex)}
              disabled={disabled || tooLight}
              style={[
                s.swatch,
                { backgroundColor: p.hex },
                active && s.swatchActive,
                tooLight && { opacity: 0.35 },
              ]}
              accessibilityLabel={`Set color to ${p.name}${tooLight ? " (low contrast)" : ""}`}
              testID={`${testidPrefix}-preset-${hex}`}
            >
              {active ? (
                <Ionicons name="checkmark" size={14} color="#fff" />
              ) : null}
            </Pressable>
          );
        })}
      </ScrollView>

      {/* ── Recently used ────────────────────────────────────────── */}
      {recent.length > 0 ? (
        <View testID={`${testidPrefix}-recent-row`}>
          <Text style={s.sectionLabel}>Recently used</Text>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={s.swatchRow}
          >
            {recent.map((hex) => {
              const active = hex === normalized;
              return (
                <Pressable
                  key={hex}
                  onPress={() => commit(hex)}
                  disabled={disabled}
                  style={[
                    s.swatch,
                    { backgroundColor: hex },
                    active && s.swatchActive,
                  ]}
                  accessibilityLabel={`Set color to ${hex}`}
                  testID={`${testidPrefix}-recent-${hex}`}
                >
                  {active ? (
                    <Ionicons name="checkmark" size={14} color="#fff" />
                  ) : null}
                </Pressable>
              );
            })}
          </ScrollView>
        </View>
      ) : null}

      {/* ── Freeform section ─────────────────────────────────────── */}
      <View testID={`${testidPrefix}-freeform`}>
        <Text style={s.sectionLabel}>Custom color</Text>

        {/* Hue slider */}
        <Slider
          style={s.slider}
          minimumValue={0}
          maximumValue={360}
          step={1}
          value={hue}
          onValueChange={onHueChange}
          minimumTrackTintColor="#0EA5E9"
          maximumTrackTintColor="#E4E4E7"
          disabled={disabled}
          testID={`${testidPrefix}-hue-slider`}
        />

        {/* Hex input + preview */}
        <View style={s.freeformRow}>
          <View
            style={[
              s.previewSwatch,
              {
                backgroundColor: draftValidation.ok ? draft : "#FFFFFF",
              },
            ]}
            testID={`${testidPrefix}-preview`}
          />
          <TextInput
            value={draft}
            onChangeText={(t) => setDraft(t.toUpperCase())}
            placeholder="#RRGGBB"
            maxLength={7}
            editable={!disabled}
            style={s.hexInput}
            autoCapitalize="characters"
            autoCorrect={false}
            testID={`${testidPrefix}-hex-input`}
          />
        </View>

        {/* Contrast warning */}
        {!draftValidation.ok && draft ? (
          <View style={s.warningRow} testID={`${testidPrefix}-contrast-warning`}>
            <Ionicons name="warning" size={14} color="#B91C1C" />
            <Text style={s.warningText}>
              {draftValidation.reason === "contrast"
                ? "This color is too light to read on the map pin. Pick a darker shade."
                : "Enter a valid 6-digit hex color (e.g. #0EA5E9)."}
            </Text>
          </View>
        ) : null}

        {/* Apply button */}
        <Pressable
          onPress={() => commit(draft)}
          disabled={commitDisabled}
          style={[
            s.applyBtn,
            commitDisabled && s.applyBtnDisabled,
          ]}
          testID={`${testidPrefix}-commit`}
        >
          {saving ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <Text
              style={[
                s.applyBtnText,
                commitDisabled && s.applyBtnTextDisabled,
              ]}
            >
              Apply
            </Text>
          )}
        </Pressable>
      </View>
    </View>
  );
}

/* ── Styles ──────────────────────────────────────────────────────────── */

const s = StyleSheet.create({
  root: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.md,
  },
  sectionLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginBottom: spacing.xs,
  },
  swatchRow: {
    flexDirection: "row",
    gap: spacing.sm,
    paddingBottom: spacing.xs,
  },
  swatch: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
  },
  swatchActive: {
    borderWidth: 2.5,
    borderColor: colors.onSurface,
  },
  slider: {
    width: "100%",
    height: 40,
  },
  freeformRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  previewSwatch: {
    width: 40,
    height: 40,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  hexInput: {
    flex: 1,
    height: 40,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
    paddingHorizontal: spacing.md,
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  warningRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.xs,
    marginTop: spacing.xs,
  },
  warningText: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#B91C1C",
    lineHeight: 18,
  },
  applyBtn: {
    alignSelf: "flex-end",
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
    borderRadius: radius.sm,
    backgroundColor: colors.brand,
    marginTop: spacing.sm,
    minHeight: 40,
  },
  applyBtnDisabled: {
    backgroundColor: "#D1D5DB",
  },
  applyBtnText: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#FFFFFF",
  },
  applyBtnTextDisabled: {
    color: "#6B7280",
  },
});

export { MIN_CONTRAST_VS_WHITE, contrastRatioVsWhite, validateColorHexForPin };
