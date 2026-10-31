/**
 * Schedule declutter (S3a) · bottom sheet = RN Modal + PanResponder.
 * Dismiss: backdrop tap · close button · swipe-down on the grabber/header
 * (> SWIPE_CLOSE_PX or a fast flick). No new deps; Schedule-only usage.
 * The content area is NOT a pan target, so inner ScrollViews still scroll.
 */
import React, { useEffect, useMemo, useRef } from "react";
import { View, Text, Pressable, Modal, Animated, PanResponder, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, font, fontSize, spacing, radius } from "@/src/theme";

export const SWIPE_CLOSE_PX = 80;
export const SWIPE_CLOSE_VY = 0.8;

/** Pure release rule — exported for tests. */
export function shouldCloseOnRelease(dy: number, vy: number): boolean {
  return dy > SWIPE_CLOSE_PX || vy > SWIPE_CLOSE_VY;
}

export function createSwipeConfig(onClose: () => void, dragY: Animated.Value) {
  const snapBack = () => Animated.spring(dragY, { toValue: 0, useNativeDriver: true }).start();
  return {
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: (_e: any, g: any) => g.dy > 4 && Math.abs(g.dy) > Math.abs(g.dx),
    onPanResponderMove: (_e: any, g: any) => { if (g.dy > 0) dragY.setValue(g.dy); },
    onPanResponderRelease: (_e: any, g: any) => { if (shouldCloseOnRelease(g.dy, g.vy)) onClose(); else snapBack(); },
    onPanResponderTerminate: snapBack,
  };
}

type Props = { visible: boolean; onClose: () => void; title: string; testID: string; children: React.ReactNode };

export default function SwipeSheet({ visible, onClose, title, testID, children }: Props) {
  const dragY = useRef(new Animated.Value(0)).current;
  useEffect(() => { if (visible) dragY.setValue(0); }, [visible, dragY]);
  const pan = useMemo(() => PanResponder.create(createSwipeConfig(onClose, dragY)), [onClose, dragY]);
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={s.root}>
        <Pressable style={s.backdrop} onPress={onClose} testID={`${testID}-backdrop`} accessibilityLabel="Close" />
        <Animated.View style={[s.sheet, { transform: [{ translateY: dragY }] }]} testID={testID}>
          <View {...pan.panHandlers} testID={`${testID}-handle`}>
            <View style={s.grabber} />
            <View style={s.head}>
              <Text style={s.title} accessibilityRole="header">{title}</Text>
              <Pressable onPress={onClose} hitSlop={10} style={s.close} testID={`${testID}-close`} accessibilityRole="button" accessibilityLabel={`Close ${title.toLowerCase()}`}>
                <Ionicons name="close" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
          </View>
          {children}
        </Animated.View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.4)" },
  sheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
    paddingHorizontal: spacing.lg, paddingBottom: spacing["2xl"], maxHeight: "80%",
  },
  grabber: { alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, marginTop: spacing.sm },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: spacing.sm },
  title: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  close: { minWidth: 44, minHeight: 44, alignItems: "flex-end", justifyContent: "center" },
});
