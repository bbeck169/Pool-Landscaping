import React from "react";
import { View, Text, StyleSheet, ActivityIndicator, Pressable, Modal, ScrollView } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize, statusMeta, brandGradient } from "@/src/theme";

export function StatusChip({ status, testID }: { status: string; testID?: string }) {
  const m = statusMeta[status] || { label: status, bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary };
  return (
    <View testID={testID} style={[styles.chip, { backgroundColor: m.bg }]}>
      <Text style={[styles.chipText, { color: m.fg }]}>{m.label}</Text>
    </View>
  );
}

export function Card({ children, style }: { children: React.ReactNode; style?: any }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function Loading({ testID }: { testID?: string }) {
  return (
    <View testID={testID} style={styles.center}>
      <ActivityIndicator size="large" color={colors.brand} />
    </View>
  );
}

export function EmptyState({
  icon = "documents-outline",
  title,
  subtitle,
  testID,
}: {
  icon?: any;
  title: string;
  subtitle?: string;
  testID?: string;
}) {
  return (
    <View testID={testID} style={styles.center}>
      <View style={styles.emptyIcon}>
        <Ionicons name={icon} size={38} color={colors.brandSecondary} />
      </View>
      <Text style={styles.emptyTitle}>{title}</Text>
      {subtitle ? <Text style={styles.emptySub}>{subtitle}</Text> : null}
    </View>
  );
}

export function PrimaryButton({
  title,
  onPress,
  loading,
  disabled,
  testID,
  icon,
  variant = "primary",
}: {
  title: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
  testID?: string;
  icon?: any;
  variant?: "primary" | "outline" | "success";
}) {
  const isOutline = variant === "outline";
  const isPrimary = variant === "primary";
  const fg = isOutline ? colors.brand : "#FFFFFF";
  const content = loading ? (
    <ActivityIndicator color={fg} />
  ) : (
    <>
      {icon ? <Ionicons name={icon} size={18} color={fg} style={{ marginRight: 8 }} /> : null}
      <Text style={[styles.btnText, { color: fg }]}>{title}</Text>
    </>
  );

  if (isPrimary) {
    return (
      <Pressable
        testID={testID}
        onPress={onPress}
        disabled={disabled || loading}
        style={({ pressed }) => [styles.btnWrap, { opacity: disabled ? 0.5 : pressed ? 0.9 : 1 }]}
      >
        <LinearGradient
          colors={brandGradient}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 0 }}
          style={styles.btn}
        >
          {content}
        </LinearGradient>
      </Pressable>
    );
  }

  const bg = variant === "success" ? colors.success : "transparent";
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.btn,
        { backgroundColor: bg, opacity: disabled ? 0.5 : pressed ? 0.85 : 1 },
        isOutline && { borderWidth: 1.5, borderColor: colors.brand },
      ]}
    >
      {content}
    </Pressable>
  );
}

export function Sheet({
  visible,
  onClose,
  title,
  children,
  testID,
  header,
}: {
  visible: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  testID?: string;
  /** Optional pinned content between the title row and the scrolling list (e.g. a search box). */
  header?: React.ReactNode;
}) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} testID={testID ? `${testID}-backdrop` : undefined} />
      <View style={styles.sheet} testID={testID}>
        <View style={styles.sheetHandle} />
        {title ? (
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>{title}</Text>
            <Pressable onPress={onClose} testID={testID ? `${testID}-close` : undefined} hitSlop={10}>
              <Ionicons name="close" size={24} color={colors.onSurfaceSecondary} />
            </Pressable>
          </View>
        ) : null}
        {header}
        <ScrollView contentContainerStyle={{ paddingBottom: spacing.xl }} keyboardShouldPersistTaps={header ? "handled" : undefined}>{children}</ScrollView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  chip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill, alignSelf: "flex-start" },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: "#0B3B54",
    shadowOpacity: 0.06,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  emptyIcon: {
    width: 84,
    height: 84,
    borderRadius: 42,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.lg,
  },
  emptyTitle: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface, textAlign: "center" },
  emptySub: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    textAlign: "center",
    marginTop: spacing.xs,
  },
  btnWrap: { borderRadius: radius.md, overflow: "hidden" },
  btn: {
    height: 52,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    paddingHorizontal: spacing.lg,
  },
  btnText: { fontFamily: font.semibold, fontSize: fontSize.lg },
  backdrop: { flex: 1, backgroundColor: "rgba(10,25,40,0.45)" },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    maxHeight: "80%",
  },
  sheetHandle: {
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.borderStrong,
    alignSelf: "center",
    marginBottom: spacing.md,
  },
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.md,
  },
  sheetTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
});
