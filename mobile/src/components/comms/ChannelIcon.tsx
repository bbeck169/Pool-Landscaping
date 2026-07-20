import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { font } from "@/src/theme";

const CHANNEL_META: Record<string, { icon: string; bg: string; fg: string; border: string }> = {
  email: { icon: "mail-outline", bg: "#DBEAFE", fg: "#1E3A8A", border: "#93C5FD" },
  sms: { icon: "chatbubble-outline", bg: "#FEF3C7", fg: "#854D0E", border: "#FDE68A" },
};

const FALLBACK = { icon: "help-outline", bg: "#F4F4F5", fg: "#71717A", border: "#E4E4E7" };

export default function ChannelIcon({ channel }: { channel?: string }) {
  const m = CHANNEL_META[channel || ""] || FALLBACK;
  return (
    <View
      testID={`channel-icon-${channel || "unknown"}`}
      style={[styles.badge, { backgroundColor: m.bg, borderColor: m.border }]}
    >
      <Ionicons name={m.icon as any} size={11} color={m.fg} />
      <Text style={[styles.label, { color: m.fg }]}>
        {String(channel || "unknown").toUpperCase()}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 3,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    borderWidth: 1,
  },
  label: {
    fontSize: 10,
    fontFamily: font.bold,
    letterSpacing: 0.5,
  },
});
