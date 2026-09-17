import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Linking, Pressable, Alert } from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header, JobCard } from "@/src/components/widgets";
import ColorPicker from "@/src/components/ui/ColorPicker";

export default function TechnicianDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const [t, setT] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [colorOpen, setColorOpen] = useState(false);

  const isAdmin =
    user?.role === "admin" || user?.role === "super_admin";

  const load = useCallback(async () => {
    try {
      setT(await api.get(`/technicians/${id}`));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  /** PATCH the user's display_color_hex. Handle server 400 gracefully. */
  const onColorChange = useCallback(
    async (hex: string) => {
      const userId = t?.user_id;
      if (!userId) {
        Alert.alert("Error", "No linked user account for this technician.");
        return;
      }
      try {
        await api.patch(`/users/${userId}`, { display_color_hex: hex });
        // Refresh tech record to show updated color.
        setT((prev: any) => prev ? { ...prev, display_color_hex: hex } : prev);
        Alert.alert("Saved", `Color set to ${hex}`);
      } catch (e: any) {
        // Handle the server contrast guard 400.
        const body = e?.body || e?.response?.data;
        if (body?.code === "color_contrast_too_low") {
          Alert.alert(
            "Color too light",
            "This color doesn't meet the minimum contrast for the map pin. Pick a darker shade.",
          );
        } else {
          Alert.alert("Save failed", e?.message || "Could not update the color.");
        }
      }
    },
    [t],
  );

  if (loading) return <Loading testID="technician-detail-loading" />;
  if (!t) return null;

  const active = t.jobs?.filter((j: any) => j.status !== "completed") || [];

  return (
    <View style={styles.root}>
      <Header title={t.name} back />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}>
        <View style={styles.profile}>
          {t.avatar ? (
            <Image source={{ uri: t.avatar }} style={styles.avatar} />
          ) : (
            <View style={[styles.avatar, styles.fallback]}>
              <Ionicons name="person" size={30} color={colors.muted} />
            </View>
          )}
          <Text style={styles.name}>{t.name}</Text>
          <Text style={styles.specialty}>{t.specialty}</Text>
          <View style={styles.contactRow}>
            {t.phone ? (
              <Pressable style={styles.contactBtn} onPress={() => Linking.openURL(`tel:${t.phone}`)} testID="tech-call">
                <Ionicons name="call" size={18} color={colors.brand} />
                <Text style={styles.contactText}>Call</Text>
              </Pressable>
            ) : null}
            {t.email ? (
              <Pressable style={styles.contactBtn} onPress={() => Linking.openURL(`mailto:${t.email}`)} testID="tech-email">
                <Ionicons name="mail" size={18} color={colors.brand} />
                <Text style={styles.contactText}>Email</Text>
              </Pressable>
            ) : null}
          </View>
        </View>

        {/* Admin-only crew color editor */}
        {isAdmin ? (
          <View style={styles.colorSection} testID="tech-color-section">
            <Pressable
              style={styles.colorToggleRow}
              onPress={() => setColorOpen((v) => !v)}
              testID="tech-color-toggle"
            >
              <View style={styles.colorToggleLeft}>
                <View
                  style={[
                    styles.colorDot,
                    { backgroundColor: t.display_color_hex || colors.muted },
                  ]}
                  testID="tech-color-dot"
                />
                <Text style={styles.colorToggleLabel}>Map pin color</Text>
              </View>
              <Ionicons
                name={colorOpen ? "chevron-up" : "chevron-down"}
                size={18}
                color={colors.muted}
              />
            </Pressable>
            {colorOpen ? (
              <ColorPicker
                value={t.display_color_hex || ""}
                onChange={onColorChange}
                testidPrefix="tech-color-picker"
              />
            ) : null}
          </View>
        ) : null}

        <Text style={styles.sectionTitle}>Active Jobs ({active.length})</Text>
        {active.length ? (
          active.map((j: any) => <JobCard key={j.id} job={j} testID={`tech-job-${j.id}`} />)
        ) : (
          <Text style={styles.empty}>No active jobs assigned.</Text>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  profile: { alignItems: "center", backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl, borderWidth: 1, borderColor: colors.border },
  avatar: { width: 88, height: 88, borderRadius: 44, backgroundColor: colors.surfaceTertiary, marginBottom: spacing.md },
  fallback: { alignItems: "center", justifyContent: "center" },
  name: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface },
  specialty: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 2 },
  contactRow: { flexDirection: "row", gap: spacing.md, marginTop: spacing.lg },
  contactBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.brandTertiary, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: radius.pill },
  contactText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  colorSection: {
    marginTop: spacing.xl,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.md,
  },
  colorToggleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  colorToggleLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  colorDot: {
    width: 24,
    height: 24,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  colorToggleLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: spacing.xl, marginBottom: spacing.md },
  empty: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
});
