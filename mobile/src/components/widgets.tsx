import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { StatusChip } from "@/src/components/ui";

export function OfflineBanner({ testID }: { testID?: string }) {
  return (
    <View style={styles.offlineBanner} testID={testID || "offline-banner"}>
      <Ionicons name="cloud-offline-outline" size={16} color="#9A3412" />
      <Text style={styles.offlineText}>Offline — showing saved data. Changes sync when you reconnect.</Text>
    </View>
  );
}

export function NotificationBell() {
  const router = useRouter();
  const [count, setCount] = useState(0);
  useFocusEffect(
    useCallback(() => {
      let active = true;
      const fetchCount = () =>
        api.get("/notifications/unread-count").then((r) => active && setCount(r?.count || 0)).catch(() => {});
      fetchCount();
      const interval = setInterval(fetchCount, 20000);
      return () => {
        active = false;
        clearInterval(interval);
      };
    }, [])
  );
  return (
    <Pressable onPress={() => router.push("/notifications")} style={styles.bellBtn} testID="notification-bell" hitSlop={8}>
      <Ionicons name="notifications-outline" size={22} color={colors.brand} />
      {count > 0 ? (
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{count > 9 ? "9+" : count}</Text>
        </View>
      ) : null}
    </Pressable>
  );
}

export function Header({
  title,
  subtitle,
  right,
  back,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
  back?: boolean;
}) {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  return (
    <View style={[styles.header, { paddingTop: insets.top + spacing.sm }]}>
      <View style={{ flexDirection: "row", alignItems: "center", flex: 1 }}>
        {back ? (
          <Pressable onPress={() => router.back()} hitSlop={10} style={styles.backBtn} testID="header-back">
            <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
          </Pressable>
        ) : null}
        <View style={{ flex: 1 }}>
          <Text style={styles.headerTitle} numberOfLines={1}>
            {title}
          </Text>
          {subtitle ? <Text style={styles.headerSub}>{subtitle}</Text> : null}
        </View>
      </View>
      {right}
    </View>
  );
}

export function IconButton({ icon, onPress, testID }: { icon: any; onPress: () => void; testID?: string }) {
  return (
    <Pressable onPress={onPress} style={styles.iconBtn} testID={testID} hitSlop={8}>
      <Ionicons name={icon} size={22} color={colors.brand} />
    </Pressable>
  );
}

export function JobCard({ job, testID, locked }: { job: any; testID?: string; locked?: boolean }) {
  const router = useRouter();
  const { user } = useAuth();
  const hidePrice = user?.role === "technician";
  return (
    <Pressable
      testID={testID}
      onPress={() => (locked ? undefined : router.push(`/job/${job.id}`))}
      disabled={locked}
      style={({ pressed }) => [styles.jobCard, pressed && !locked && { opacity: 0.9 }, locked && styles.jobCardLocked]}
    >
      {locked ? (
        <View style={styles.lockBadge}>
          <Ionicons name="lock-closed" size={12} color={colors.muted} />
        </View>
      ) : null}
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
        <View style={{ flex: 1, paddingRight: spacing.sm }}>
          <Text style={styles.jobTitle} numberOfLines={1}>
            {job.title}
          </Text>
          <Text style={styles.jobCustomer}>{job.customer_name}</Text>
        </View>
        <StatusChip status={job.status} />
      </View>
      <View style={styles.jobMetaRow}>
        <Ionicons name="location-outline" size={14} color={colors.muted} />
        <Text style={styles.jobMeta} numberOfLines={1}>
          {job.address || "No address"}
        </Text>
      </View>
      <View style={styles.jobFooter}>
        <View style={styles.jobMetaRow}>
          <Ionicons name="calendar-outline" size={14} color={colors.muted} />
          <Text style={styles.jobMeta}>{job.scheduled_date || "Unscheduled"}</Text>
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          {job.technician_avatar ? (
            <Image source={{ uri: job.technician_avatar }} style={styles.avatarSm} />
          ) : (
            <View style={[styles.avatarSm, styles.avatarFallback]}>
              <Ionicons name="person" size={12} color={colors.muted} />
            </View>
          )}
          <Text style={styles.techName}>{job.technician_name || "Unassigned"}</Text>
          {!hidePrice ? <Text style={styles.price}>· {money(job.price)}</Text> : null}
        </View>
      </View>
      {job.gate_code || job.account_notes ? (
        <View style={styles.infoBlock}>
          {job.gate_code ? (
            <View style={styles.gateChip}>
              <Ionicons name="key" size={13} color="#92400E" />
              <Text style={styles.gateText}>Gate {job.gate_code}</Text>
            </View>
          ) : null}
          {job.account_notes ? (
            <View style={styles.noteRow}>
              <Ionicons name="document-text-outline" size={13} color={colors.muted} style={{ marginTop: 1 }} />
              <Text style={styles.noteText} numberOfLines={4}>{job.account_notes}</Text>
            </View>
          ) : null}
        </View>
      ) : null}
    </Pressable>
  );
}

export function FilterRow({
  options,
  value,
  onChange,
  testID,
}: {
  options: { key: string; label: string }[];
  value: string;
  onChange: (k: string) => void;
  testID?: string;
}) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={styles.filterRowWrap}
      contentContainerStyle={styles.filterRowContent}
    >
      {options.map((o) => {
        const active = o.key === value;
        return (
          <Pressable
            key={o.key}
            onPress={() => onChange(o.key)}
            testID={testID ? `${testID}-${o.key}` : undefined}
            style={[styles.chipFilter, active ? styles.chipFilterActive : styles.chipFilterIdle]}
          >
            <Text style={[styles.chipFilterText, { color: active ? "#fff" : colors.onSurfaceSecondary }]}>
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  header: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.md,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    flexDirection: "row",
    alignItems: "flex-end",
  },
  backBtn: { marginRight: spacing.xs, marginLeft: -6 },
  headerTitle: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface },
  headerSub: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 2 },
  iconBtn: {
    width: 42,
    height: 42,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  bellBtn: {
    width: 42,
    height: 42,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  badge: {
    position: "absolute",
    top: 4,
    right: 4,
    minWidth: 16,
    height: 16,
    paddingHorizontal: 3,
    borderRadius: 8,
    backgroundColor: colors.error,
    alignItems: "center",
    justifyContent: "center",
  },
  badgeText: { color: "#fff", fontFamily: font.bold, fontSize: 9 },
  offlineBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: "#FFEDD5",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  offlineText: { flex: 1, fontFamily: font.medium, fontSize: fontSize.sm, color: "#9A3412" },
  jobCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
    gap: spacing.sm,
  },
  jobCardLocked: { opacity: 0.55 },
  lockBadge: {
    position: "absolute",
    top: spacing.sm,
    right: spacing.sm,
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1,
  },
  jobTitle: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  jobCustomer: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, marginTop: 2 },
  jobMetaRow: { flexDirection: "row", alignItems: "center", gap: 5, flexShrink: 1 },
  jobMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, flexShrink: 1 },
  jobFooter: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    borderTopWidth: 1,
    borderTopColor: colors.divider,
    paddingTop: spacing.sm,
    marginTop: 2,
  },
  avatarSm: { width: 22, height: 22, borderRadius: 11, backgroundColor: colors.surfaceTertiary },
  avatarFallback: { alignItems: "center", justifyContent: "center" },
  techName: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  price: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  infoBlock: { borderTopWidth: 1, borderTopColor: colors.divider, paddingTop: spacing.sm, marginTop: 2, gap: 6 },
  gateChip: { flexDirection: "row", alignItems: "center", gap: 5, alignSelf: "flex-start", backgroundColor: "#FEF3C7", paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  gateText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#92400E", letterSpacing: 0.5 },
  noteRow: { flexDirection: "row", gap: 6, alignItems: "flex-start" },
  noteText: { flex: 1, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, lineHeight: 18 },
  filterRowWrap: { flexGrow: 0, maxHeight: 56, backgroundColor: colors.surface },
  filterRowContent: { gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, alignItems: "center" },
  chipFilter: {
    height: 36,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  chipFilterActive: { backgroundColor: colors.brand },
  chipFilterIdle: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  chipFilterText: { fontFamily: font.semibold, fontSize: fontSize.sm },
});
