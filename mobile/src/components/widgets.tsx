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
import Breadcrumbs from "@/src/components/nav/Breadcrumbs";
import BrandLogo from "@/src/components/BrandLogo";
import { useBreadcrumbs } from "@/src/hooks/useBreadcrumbs";
import { openGlobalMenu } from "@/src/components/tools/GlobalMenu";

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

function SettingsSprocket() {
  const { user } = useAuth();
  const router = useRouter();
  const role = String((user as any)?.role || "");
  if (role !== "admin" && role !== "super_admin") return null;
  return (
    <Pressable
      onPress={() => router.push("/settings")}
      style={styles.sprocketBtn}
      hitSlop={8}
      testID="header-settings-sprocket"
      accessibilityLabel="Settings"
      accessibilityRole="button"
    >
      <Ionicons name="settings-outline" size={20} color={colors.onSurface} />
    </Pressable>
  );
}

function HamburgerButton() {
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const allowed = role === "admin" || role === "super_admin" || role === "technician";
  if (!allowed) return null;
  return (
    <Pressable
      onPress={openGlobalMenu}
      style={styles.hamburgerBtn}
      hitSlop={10}
      testID="mobile-menu-trigger"
      accessibilityLabel="Open menu"
      accessibilityRole="button"
    >
      <Ionicons name="menu-outline" size={24} color={colors.onSurface} />
    </Pressable>
  );
}

export function Header({
  title,
  subtitle,
  right,
  back,
  left,
  breadcrumbLabel,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
  back?: boolean;
  left?: React.ReactNode;
  breadcrumbLabel?: string;
}) {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const crumbs = useBreadcrumbs(breadcrumbLabel || title);
  return (
    <View style={[styles.header, { paddingTop: insets.top + spacing.sm }]}>
      <View style={styles.headerRow}>
        <View style={styles.headerLeftCluster}>
          {back ? (
            <Pressable onPress={() => router.back()} hitSlop={10} style={styles.backBtn} testID="header-back">
              <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
            </Pressable>
          ) : null}
          {left ? left : !back ? <BrandLogo size="sm" variant="icon" /> : null}
          <View style={{ flex: 1, minWidth: 0, flexShrink: 1, marginLeft: !back && !left ? spacing.sm : 0 }}>
            <Text style={styles.headerTitle} numberOfLines={1}>
              {title}
            </Text>
            {subtitle ? (
              <Text style={styles.headerSub} numberOfLines={1} ellipsizeMode="tail">
                {subtitle}
              </Text>
            ) : null}
          </View>
        </View>
        <View style={styles.headerRightCluster}>
          <SettingsSprocket />
          {right}
          <HamburgerButton />
        </View>
      </View>
      {crumbs.length > 0 && <Breadcrumbs items={crumbs} />}
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

export function JobCard({ job, testID, locked, unread, onView }: { job: any; testID?: string; locked?: boolean; unread?: boolean; onView?: () => void }) {
  const router = useRouter();
  const { user } = useAuth();
  const hidePrice = user?.role === "technician";
  return (
    <Pressable
      testID={testID}
      onPress={() => {
        if (locked) return;
        if (onView) onView();
        router.push(`/job/${job.id}`);
      }}
      disabled={locked}
      style={({ pressed }) => [styles.jobCard, pressed && !locked && { opacity: 0.9 }, locked && styles.jobCardLocked]}
    >
      {unread ? (
        <View
          testID={`job-card-unread-${job.id}`}
          style={{
            position: "absolute", top: 8, right: 8, zIndex: 5,
            minWidth: 10, height: 10, borderRadius: 5,
            backgroundColor: "#DC2626",
            borderWidth: 2, borderColor: "#fff",
          }}
        />
      ) : null}
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
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <Text style={styles.jobCustomer}>{job.customer_name}</Text>
            {job.customer_is_vip ? (
              <View style={styles.vipBadgeSm} testID={`job-vip-badge-${job.id}`}>
                <Ionicons name="star" size={9} color="#92400E" />
                <Text style={styles.vipBadgeSmText}>VIP</Text>
              </View>
            ) : null}
          </View>
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
      {job.gate_code || job.account_notes || job.service_note ? (
        <View style={styles.infoBlock}>
          {job.gate_code ? (
            <View style={styles.gateChip} testID={`job-gate-code-${job.id}`}>
              <Ionicons name="key" size={13} color="#92400E" />
              <Text style={styles.gateText}>Gate {job.gate_code}</Text>
            </View>
          ) : null}
          {/* Feb-2026 Note-pill — specialty-specific service note. */}
          {job.service_note ? (() => {
            const st = String(job.service_type || "").toLowerCase();
            const isLand = st.includes("landscap");
            const isPool = st.includes("pool") || st.includes("clean");
            const bg = isLand ? "#DCFCE7" : isPool ? "#DBEAFE" : "#F3F4F6";
            const fg = isLand ? "#166534" : isPool ? "#075985" : "#4B5563";
            const bd = isLand ? "#86EFAC" : isPool ? "#7DD3FC" : "#D1D5DB";
            const iconName = isLand ? "leaf" : isPool ? "water" : "information-circle-outline";
            return (
              <Pressable
                onPress={() => (locked ? undefined : router.push(`/job/${job.id}?focus=notes`))}
                testID={`service-note-pill-${job.id}`}
                style={{
                  flexDirection: "row", alignItems: "center", gap: 4,
                  paddingHorizontal: 8, paddingVertical: 2, borderRadius: 6,
                  backgroundColor: bg, borderWidth: 1, borderColor: bd,
                }}
              >
                <Ionicons name={iconName as any} size={11} color={fg} />
                <Text style={{ color: fg, fontSize: 10, fontWeight: "700" }}>
                  Note
                </Text>
              </Pressable>
            );
          })() : null}
          {job.account_notes ? (
            <View style={styles.noteRow} testID={`job-notes-preview-${job.id}`}>
              <Ionicons name="document-text-outline" size={13} color={colors.muted} style={{ marginTop: 1 }} />
              <Text style={styles.noteText} numberOfLines={4}>{job.account_notes}</Text>
            </View>
          ) : null}
        </View>
      ) : null}
      {/* Phase 46.2 closeout · Workstream layout — LEFT pills column + RIGHT primary photo */}
      <View style={styles.workstreamRow}>
        <View style={styles.workstreamPillCol}>
          <WorkstreamPillColumn job={job} />
        </View>
        <View style={styles.workstreamPhotoCol}>
          <WorkstreamPhoto job={job}
            onOpen={() => (locked ? undefined : router.push(`/job/${job.id}`))} />
        </View>
      </View>
      {/* Horizontal thumbnail strip (up to 6 extras). */}
      <WorkstreamThumbStrip job={job} />
    </Pressable>
  );
}

// ── Workstream sub-parts ──────────────────────────────────────────────
function WorkstreamPillColumn({ job }: { job: any }) {
  const has = {
    water:    !!(job?.has_water_readings ?? job?.chemical_readings_count),
    chem:     !!(job?.has_chemicals_added ?? job?.chemicals_added_count),
    check:    !!(job?.has_checklist ?? job?.service_report_id),
    private_note: !!(job?.has_private_note ?? (job?.account_notes || job?.tech_note)),
    public_note:  !!(job?.has_public_note ?? job?.customer_note),
    repair:   !!(job?.has_repair_request ?? job?.repair_request),
    shopping: !!(job?.has_shopping_request ?? job?.shopping_request),
    time:     !!(job?.scheduled_start || job?.scheduled_date),
    location: !!(job?.address || job?.lat),
  } as const;
  const rows: { key: keyof typeof has; label: string; icon: any; testKey: string }[] = [
    { key: "water",         label: "Water Test",   icon: "water-outline",         testKey: "water-test" },
    { key: "chem",          label: "Chemicals",    icon: "flask-outline",         testKey: "chemicals" },
    { key: "check",         label: "Checklist",    icon: "checkmark-done-outline", testKey: "checklist" },
    { key: "private_note",  label: "Private Note", icon: "lock-closed-outline",   testKey: "private-note" },
    { key: "public_note",   label: "Public Note",  icon: "chatbox-outline",       testKey: "public-note" },
    { key: "repair",        label: "Repair",       icon: "construct-outline",     testKey: "repair" },
    { key: "shopping",      label: "Shopping",     icon: "cart-outline",          testKey: "shopping" },
    { key: "time",          label: "Time",         icon: "time-outline",          testKey: "time" },
    { key: "location",      label: "Location",     icon: "location-outline",      testKey: "location" },
  ];
  return (
    <View>
      {rows.map((r) => {
        const on = has[r.key];
        return (
          <View
            key={r.key}
            style={[styles.pillV, on ? styles.pillOn : styles.pillOff]}
            testID={`job-card-pill-${r.testKey}-${job.id}`}
          >
            <Ionicons name={r.icon} size={11}
              color={on ? "#166534" : colors.muted} />
            <Text style={[styles.pillText,
              on ? styles.pillTextOn : styles.pillTextOff]}
              numberOfLines={1}>
              {r.label}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

function _photoUri(p: any): string | null {
  if (!p) return null;
  if (typeof p === "string") return p;
  return p?.url || p?.public_url || p?.thumbnail_url || p?.data || null;
}

function WorkstreamPhoto({ job, onOpen }: { job: any; onOpen: () => void }) {
  const photos = Array.isArray(job?.photos) ? job.photos : [];
  const primary = _photoUri(photos[0]);
  return (
    <View style={styles.photoBox} testID={`job-card-photo-${job.id}`}>
      {primary ? (
        <Image source={{ uri: primary }} style={styles.photoImg} />
      ) : (
        <View style={[styles.photoImg, styles.photoPlaceholder]}>
          <Ionicons name="image-outline" size={26} color="#93C5FD" />
          <Text style={styles.photoPlaceholderText}>No primary photo</Text>
        </View>
      )}
      <Pressable
        style={styles.viewDetailsOverlay}
        onPress={onOpen}
        testID={`job-card-view-details-${job.id}`}
      >
        <Text style={styles.viewDetailsText}>VIEW DETAILS</Text>
      </Pressable>
    </View>
  );
}

function WorkstreamThumbStrip({ job }: { job: any }) {
  const router = useRouter();
  const photos: any[] = Array.isArray(job?.photos) ? job.photos.slice(1, 7) : [];
  if (photos.length === 0) return null;
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.thumbStrip}
    >
      {photos.map((p, i) => {
        const uri = _photoUri(p);
        if (!uri) return null;
        return (
          <Pressable
            key={i}
            style={styles.thumb}
            onPress={() => router.push(`/job/${job.id}`)}
            testID={`job-card-thumb-${i}-${job.id}`}
          >
            <Image source={{ uri }} style={styles.thumbImg} />
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

// Phase 46.2 — Legacy WorkstreamPillRow removed (superseded by
// WorkstreamPillColumn in the new left/right layout). ImageStrip and
// pill column now handle the whole row.

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
  vipBadgeSm: {
    flexDirection: "row", alignItems: "center", gap: 2,
    backgroundColor: "#FEF3C7", borderColor: "#F59E0B", borderWidth: 1,
    paddingHorizontal: 6, paddingVertical: 1, borderRadius: 999,
  },
  vipBadgeSmText: {
    fontFamily: font.bold, fontSize: 9, color: "#92400E",
    letterSpacing: 0.8, textTransform: "uppercase",
  },
  header: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.md,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "flex-end",
  },
  headerLeftCluster: {
    flexDirection: "row",
    alignItems: "center",
    flex: 1,
    minWidth: 0,
  },
  headerRightCluster: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flexShrink: 1,
    flexWrap: "wrap",
    maxWidth: "55%",
    justifyContent: "flex-end",
  },
  hamburgerBtn: {
    width: 36,
    height: 36,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  backBtn: { marginRight: spacing.xs, marginLeft: -6 },
  sprocketBtn: {
    width: 34,
    height: 34,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
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
  pillWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: spacing.sm },
  pill: { flexDirection: "row", alignItems: "center", gap: 4,
          paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill,
          borderWidth: 1 },
  pillV: { flexDirection: "row", alignItems: "center", gap: 6,
           paddingHorizontal: 8, paddingVertical: 5, borderRadius: radius.pill,
           borderWidth: 1, marginBottom: 5 },
  pillOn: { backgroundColor: "#DCFCE7", borderColor: "#86EFAC" },
  pillOff: { backgroundColor: colors.surfaceSecondary, borderColor: colors.border },
  pillText: { fontFamily: font.semibold, fontSize: 10, letterSpacing: 0.3 },
  pillTextOn: { color: "#166534" },
  pillTextOff: { color: colors.muted },
  workstreamRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  workstreamPillCol: { width: "40%" },
  workstreamPhotoCol: { flex: 1 },
  photoBox: {
    borderRadius: radius.md, overflow: "hidden", position: "relative",
    minHeight: 200, backgroundColor: colors.surfaceSecondary,
  },
  photoImg: { width: "100%", height: 200 },
  photoPlaceholder: {
    alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: "#EFF6FF",
  },
  photoPlaceholderText: { fontFamily: font.semibold, fontSize: 11, color: "#3B82F6" },
  viewDetailsOverlay: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    backgroundColor: colors.brand, paddingVertical: 10,
    alignItems: "center", justifyContent: "center",
  },
  viewDetailsBtn: {
    marginTop: spacing.sm,
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, backgroundColor: colors.brand,
    paddingVertical: 10, borderRadius: radius.md,
  },
  viewDetailsText: {
    fontFamily: font.bold, fontSize: 13, color: "#fff",
    letterSpacing: 0.7,
  },
  thumbStrip: { flexDirection: "row", gap: 6, paddingTop: spacing.sm, paddingBottom: 2 },
  thumb: { width: 70, height: 70, borderRadius: radius.sm, overflow: "hidden",
           borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary },
  thumbImg: { width: "100%", height: "100%" },
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
