import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Linking, Pressable } from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header, JobCard } from "@/src/components/widgets";

export default function TechnicianDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [t, setT] = useState<any>(null);
  const [loading, setLoading] = useState(true);

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
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: spacing.xl, marginBottom: spacing.md },
  empty: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
});
