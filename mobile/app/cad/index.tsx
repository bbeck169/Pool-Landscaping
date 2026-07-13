import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useRouter, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { PrimaryButton, EmptyState, Loading } from "@/src/components/ui";

export default function CadList() {
  const router = useRouter();
  const [designs, setDesigns] = useState<any[] | null>(null);

  const load = useCallback(async () => {
    try {
      setDesigns(await api.get("/designs"));
    } catch {
      setDesigns([]);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={styles.root}>
      <Header title="Design Studio" subtitle="2D pool & landscape plans" back />
      <View style={{ padding: spacing.lg, paddingBottom: 0 }}>
        <PrimaryButton title="New Design" icon="add-outline" onPress={() => router.push("/cad/editor")} testID="cad-new" />
      </View>
      {designs === null ? (
        <Loading />
      ) : designs.length === 0 ? (
        <EmptyState icon="grid-outline" title="No designs yet" subtitle="Sketch a pool & landscape plan, set the scale, and save it to a customer or lead." />
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] }}>
          {designs.map((d) => (
            <Pressable key={d.id} style={styles.card} onPress={() => router.push(`/cad/editor?id=${d.id}`)} testID={`cad-design-${d.id}`}>
              <View style={styles.thumb}>
                {d.thumbnail ? (
                  <Image source={{ uri: d.thumbnail }} style={styles.thumbImg} contentFit="cover" />
                ) : (
                  <Ionicons name="grid-outline" size={28} color={colors.muted} />
                )}
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.cardTitle} numberOfLines={1}>{d.name}</Text>
                <Text style={styles.cardMeta}>
                  {d.area_sqft ? `${Math.round(d.area_sqft).toLocaleString()} sq ft` : `${Math.round(d.canvas_w_ft)}×${Math.round(d.canvas_h_ft)} ft`}
                  {d.perimeter_ft ? ` · ${Math.round(d.perimeter_ft)} ft perimeter` : ""}
                </Text>
                <Text style={styles.cardSub} numberOfLines={1}>
                  {new Date(d.updated_at).toLocaleDateString()}
                </Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.muted} />
            </Pressable>
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  thumb: { width: 64, height: 64, borderRadius: radius.md, backgroundColor: colors.surfaceSecondary, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  thumbImg: { width: "100%", height: "100%" },
  cardTitle: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  cardMeta: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand, marginTop: 2 },
  cardSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
});
