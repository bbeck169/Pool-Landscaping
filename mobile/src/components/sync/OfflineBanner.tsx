/**
 * Phase O6 · OfflineBanner — persistent top-of-screen banner
 * when the device is offline. Shows pending queue count.
 * Dismissible per session but re-appears on next offline transition.
 */
import React, { useState, useEffect, useRef } from "react";
import { View, Text, StyleSheet, TouchableOpacity, Animated } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSyncStatus } from "@/src/services/sync/status";
import { font, fontSize, spacing } from "@/src/theme";

export function OfflineBanner() {
  const { is_online, pending_count, failed_count } = useSyncStatus();
  const [dismissed, setDismissed] = useState(false);
  const slideAnim = useRef(new Animated.Value(-60)).current;
  const prevOnlineRef = useRef(is_online);

  // Re-show banner on new offline transition.
  useEffect(() => {
    if (prevOnlineRef.current && !is_online) {
      setDismissed(false);
    }
    prevOnlineRef.current = is_online;
  }, [is_online]);

  const visible = !is_online && !dismissed;

  useEffect(() => {
    Animated.timing(slideAnim, {
      toValue: visible ? 0 : -60,
      duration: 300,
      useNativeDriver: true,
    }).start();
  }, [visible, slideAnim]);

  if (is_online && dismissed) return null;

  const totalPending = pending_count + failed_count;

  return (
    <Animated.View
      testID="offline-banner"
      style={[s.container, { transform: [{ translateY: slideAnim }] }]}
      pointerEvents={visible ? "auto" : "none"}
    >
      <View style={s.content}>
        <Ionicons name="cloud-offline" size={18} color="#FEF3C7" />
        <View style={s.textWrap}>
          <Text style={s.title}>{"You're offline"}</Text>
          {totalPending > 0 && (
            <Text style={s.subtitle}>
              {totalPending} change{totalPending !== 1 ? "s" : ""} pending sync
            </Text>
          )}
        </View>
        <TouchableOpacity
          testID="offline-banner-dismiss"
          onPress={() => setDismissed(true)}
          hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
        >
          <Ionicons name="close" size={18} color="#FEF3C7" />
        </TouchableOpacity>
      </View>
    </Animated.View>
  );
}

const s = StyleSheet.create({
  container: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    zIndex: 9999,
    backgroundColor: "#92400E",
  },
  content: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
    gap: spacing.sm,
  },
  textWrap: {
    flex: 1,
  },
  title: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#FEF3C7",
  },
  subtitle: {
    fontFamily: font.regular,
    fontSize: 11,
    color: "#FDE68A",
    marginTop: 1,
  },
});
