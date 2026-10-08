/**
 * Templates Library — Phase 3 (Mobile) · library card.
 * Title, category chip, short description, "Fill" button.
 * Tapping anywhere on the card also starts a fill (creates a draft).
 */
import React from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { CATEGORY_LABEL } from "@/src/api/templates";

type Def = { code: string; title: string; description?: string; category?: string; is_system?: boolean };

export default function TemplateCard({ definition, onCreate, busy = false }: {
  definition: Def;
  onCreate: (code: string) => void;
  busy?: boolean;
}) {
  const cat = CATEGORY_LABEL[definition.category || ""] || definition.category || "";
  const fill = () => !busy && onCreate(definition.code);
  return (
    <TouchableOpacity style={styles.card} onPress={fill} activeOpacity={0.8} disabled={busy} testID={`template-card-${definition.code}`}>
      <View style={styles.topRow}>
        {cat ? (
          <View style={styles.catBadge} testID={`template-card-category-${definition.code}`}>
            <Ionicons name="library-outline" size={10} color={colors.onBrandTertiary} />
            <Text style={styles.catText}>{cat}</Text>
          </View>
        ) : <View />}
        {definition.is_system ? <Text style={styles.systemLabel}>System</Text> : null}
      </View>
      <Text style={styles.title}>{definition.title}</Text>
      {definition.description ? (
        <Text style={styles.desc} numberOfLines={3}>{definition.description}</Text>
      ) : null}
      <TouchableOpacity
        testID={`template-card-create-${definition.code}`}
        style={[styles.createBtn, busy && { opacity: 0.6 }]}
        onPress={fill}
        disabled={busy}
        activeOpacity={0.7}
      >
        {busy ? (
          <ActivityIndicator size="small" color="#fff" />
        ) : (
          <>
            <Ionicons name="create-outline" size={16} color="#fff" />
            <Text style={styles.createText}>Fill</Text>
          </>
        )}
      </TouchableOpacity>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.md,
  },
  topRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  catBadge: {
    flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brandTertiary,
    paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999,
  },
  catText: { fontSize: 10, fontFamily: font.bold, color: colors.onBrandTertiary, textTransform: "uppercase", letterSpacing: 0.5 },
  systemLabel: { fontSize: 10, fontFamily: font.bold, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  title: { fontSize: fontSize.lg, fontFamily: font.bold, color: colors.onSurface, marginBottom: 4 },
  desc: { fontSize: fontSize.sm, fontFamily: font.regular, color: colors.onSurfaceSecondary, marginBottom: spacing.md, lineHeight: 18 },
  createBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 44,
    backgroundColor: colors.brand, paddingHorizontal: 16, borderRadius: radius.md, alignSelf: "flex-start",
  },
  createText: { fontSize: fontSize.sm, fontFamily: font.bold, color: "#fff" },
});
