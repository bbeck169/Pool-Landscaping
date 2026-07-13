import React, { useState } from "react";
import { View, Text, Pressable, StyleSheet, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { font, fontSize } from "@/src/theme";

export function ImpersonationBanner() {
  const { user, isImpersonating, stopImpersonation } = useAuth();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  if (!isImpersonating || !user) return null;

  const exit = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await stopImpersonation();
      router.replace("/(app)");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={[styles.banner, { paddingTop: insets.top + 6 }]} testID="impersonation-banner">
      <Ionicons name="eye-outline" size={16} color="#fff" />
      <Text style={styles.text} numberOfLines={1}>
        Viewing as {user.name || user.email}
      </Text>
      <Pressable style={styles.button} onPress={exit} disabled={busy} testID="impersonation-exit">
        {busy ? (
          <ActivityIndicator size="small" color="#7C2D12" />
        ) : (
          <Text style={styles.buttonText}>Exit to Admin</Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 16,
    paddingBottom: 8,
    backgroundColor: "#EA580C",
  },
  text: { flex: 1, color: "#fff", fontFamily: font.semibold, fontSize: fontSize.sm },
  button: { backgroundColor: "#fff", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999 },
  buttonText: { color: "#7C2D12", fontFamily: font.bold, fontSize: fontSize.sm },
});
