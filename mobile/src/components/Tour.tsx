/**
 * Phase 34 · Portal Tour v2 — lightweight tooltip-spotlight engine.
 *
 * Usage:
 *   import Tour, { TourStep } from "@/src/components/Tour";
 *   const steps: TourStep[] = [
 *     { targetTestID: "portal-cta-call", title: "Call Us", body: "Tap here to call" },
 *     ...
 *   ];
 *   <Tour steps={steps} visible={showTour} onFinish={() => setShowTour(false)} />
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, Modal, Dimensions } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export type TourStep = {
  targetTestID: string;
  title: string;
  body: string;
  icon?: string;
};

type Props = {
  steps: TourStep[];
  visible: boolean;
  onFinish: () => void;
};

const _SW = Dimensions.get("window").width;

export default function Tour({ steps, visible, onFinish }: Props) {
  const [idx, setIdx] = useState(0);

  if (!visible || steps.length === 0) return null;

  const step = steps[idx];
  const isLast = idx === steps.length - 1;
  const progress = ((idx + 1) / steps.length) * 100;

  const next = () => {
    if (isLast) {
      setIdx(0);
      onFinish();
    } else {
      setIdx(idx + 1);
    }
  };

  const skip = () => {
    setIdx(0);
    onFinish();
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={skip}>
      <View style={s.overlay}>
        <View style={s.card} testID="tour-card">
          {/* Progress bar */}
          <View style={s.progressBg}>
            <View style={[s.progressFg, { width: `${progress}%` }]} />
          </View>

          <View style={s.stepCount}>
            <Text style={s.stepCountText} testID="tour-step-counter">
              {idx + 1} of {steps.length}
            </Text>
          </View>

          {step.icon ? (
            <View style={s.iconWrap}>
              <Ionicons name={step.icon as any} size={28} color={colors.brand} />
            </View>
          ) : null}

          <Text style={s.title} testID="tour-step-title">{step.title}</Text>
          <Text style={s.body} testID="tour-step-body">{step.body}</Text>

          <View style={s.btnRow}>
            {!isLast ? (
              <Pressable onPress={skip} style={s.skipBtn} testID="tour-skip">
                <Text style={s.skipText}>Skip</Text>
              </Pressable>
            ) : <View />}
            <Pressable onPress={next} style={s.nextBtn} testID="tour-next">
              <Text style={s.nextText}>{isLast ? "Done" : "Next"}</Text>
              <Ionicons name={isLast ? "checkmark" : "arrow-forward"} size={16} color="#fff" />
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  overlay: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.6)",
    alignItems: "center", justifyContent: "center",
    paddingHorizontal: spacing.xl,
  },
  card: {
    width: "100%", maxWidth: 380, backgroundColor: colors.surface,
    borderRadius: 20, padding: spacing.xl, paddingTop: spacing.md,
    shadowColor: "#000", shadowOpacity: 0.2, shadowOffset: { width: 0, height: 8 },
    shadowRadius: 20, elevation: 10,
  },
  progressBg: { height: 4, backgroundColor: colors.surfaceTertiary, borderRadius: 2, marginBottom: spacing.md },
  progressFg: { height: 4, backgroundColor: colors.brand, borderRadius: 2 },
  stepCount: { alignItems: "flex-end", marginBottom: spacing.sm },
  stepCountText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  iconWrap: {
    width: 56, height: 56, borderRadius: 28, backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center", alignSelf: "center", marginBottom: spacing.md,
  },
  title: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, textAlign: "center", marginBottom: spacing.sm },
  body: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center", lineHeight: 22, marginBottom: spacing.xl },
  btnRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  skipBtn: { paddingVertical: 10, paddingHorizontal: 16 },
  skipText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.muted },
  nextBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brand, borderRadius: radius.pill,
    paddingVertical: 10, paddingHorizontal: 20,
  },
  nextText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
});
