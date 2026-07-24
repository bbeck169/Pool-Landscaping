import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, Pressable } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize, money, IMAGES } from "@/src/theme";
import { Loading, StatusChip } from "@/src/components/ui";
import { Header, NotificationBell } from "@/src/components/widgets";

const SECTIONS: { key: string; label: string; icon: any; route: string }[] = [
  { key: "services", label: "Service Records", icon: "clipboard-outline", route: "/portal/services" },
  { key: "service-reports", label: "Service Reports", icon: "document-text-outline", route: "/portal/service-reports" },
  { key: "book",     label: "Book Service",    icon: "calendar-outline", route: "/portal/book" },
  { key: "appts",    label: "Appointments",    icon: "checkmark-done-outline", route: "/portal/appointments" },
  { key: "photos",   label: "Photos",          icon: "images-outline", route: "/portal/photos" },
  { key: "videos",   label: "Videos",           icon: "videocam-outline", route: "/portal/videos" },
  { key: "chats",    label: "Chat Threads",    icon: "chatbubbles-outline", route: "/portal/chats" },
  { key: "invoices", label: "Invoices", icon: "receipt-outline", route: "/portal/invoices" },
  { key: "estimates", label: "Estimates", icon: "document-text-outline", route: "/portal/estimates" },
  { key: "payments", label: "Payments", icon: "card-outline", route: "/portal/payments" },
  { key: "paymethod", label: "Payment Method", icon: "wallet-outline", route: "/portal/payment-method" },
  { key: "messages", label: "Messages (AI)", icon: "chatbubble-outline", route: "/portal/messages" },
  { key: "documents", label: "Documents", icon: "folder-open-outline", route: "/portal/documents" },
  { key: "request", label: "Work Request", icon: "add-circle-outline", route: "/request-service" },
  { key: "card", label: "Business Card", icon: "id-card-outline", route: "/card" },
  { key: "referrals", label: "Refer & Earn", icon: "gift-outline", route: "/referrals" },
  { key: "profile", label: "My Profile", icon: "person-outline", route: "/portal/profile" },
];

export default function PortalHome() {
  const { user } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.get("/dashboard"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const badgeFor = (key: string) => {
    if (!data) return 0;
    if (key === "invoices") return data.unpaid_invoices || 0;
    if (key === "estimates") return data.pending_estimates || 0;
    if (key === "messages") return data.unread_messages || 0;
    return 0;
  };

  return (
    <View style={styles.root}>
      <Header title="My Account" subtitle={`Hi, ${user?.name?.split(" ")[0] || ""}`} right={<NotificationBell />} />
      {loading || !data ? (
        <Loading testID="portal-home-loading" />
      ) : (
        <ScrollView
          testID="portal-home-scroll"
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        >
          <View style={styles.hero}>
            <Image source={{ uri: IMAGES.dashboardHero }} style={StyleSheet.absoluteFill} contentFit="cover" />
            <LinearGradient colors={["rgba(0,60,95,0.55)", "rgba(26,43,60,0.92)"]} style={StyleSheet.absoluteFill} />
            <View style={styles.heroInner}>
              <Text style={styles.heroLabel}>Balance Due</Text>
              <Text style={styles.heroValue} testID="portal-balance">{money(data.outstanding)}</Text>
              <View style={styles.heroRow}>
                <View style={styles.heroPill}>
                  <Ionicons name="flash" size={14} color="#fff" />
                  <Text style={styles.heroPillText}>{data.active_jobs} upcoming</Text>
                </View>
                <View style={styles.heroPill}>
                  <Ionicons name="checkmark-done" size={14} color="#fff" />
                  <Text style={styles.heroPillText}>{data.completed_jobs} completed</Text>
                </View>
              </View>
            </View>
          </View>

          {data.next_service ? (
            <Pressable style={styles.nextCard} onPress={() => router.push(`/job/${data.next_service.id}`)} testID="portal-next-service">
              <View style={styles.nextIcon}>
                <Ionicons name="calendar" size={20} color={colors.brand} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.nextLabel}>Next Service</Text>
                <Text style={styles.nextTitle} numberOfLines={1}>{data.next_service.title}</Text>
                <Text style={styles.nextMeta}>{(data.next_service.scheduled_date || "").slice(0, 10) || "To be scheduled"}</Text>
              </View>
              <StatusChip status={data.next_service.status} />
            </Pressable>
          ) : null}

          <Text style={styles.gridTitle}>Explore</Text>
          <View style={styles.grid}>
            {SECTIONS.map((s) => {
              const badge = badgeFor(s.key);
              return (
                <Pressable key={s.key} style={styles.card} onPress={() => router.push(s.route as any)} testID={`portal-card-${s.key}`}>
                  {badge > 0 ? (
                    <View style={styles.cardBadge}><Text style={styles.cardBadgeText}>{badge}</Text></View>
                  ) : null}
                  <View style={styles.cardIcon}>
                    <Ionicons name={s.icon} size={22} color={colors.brand} />
                  </View>
                  <Text style={styles.cardLabel}>{s.label}</Text>
                </Pressable>
              );
            })}
          </View>
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  hero: { height: 150, borderRadius: radius.lg, overflow: "hidden", marginBottom: spacing.lg },
  heroInner: { flex: 1, padding: spacing.lg, justifyContent: "flex-end" },
  heroLabel: { fontFamily: font.medium, fontSize: fontSize.base, color: "rgba(255,255,255,0.85)" },
  heroValue: { fontFamily: font.bold, fontSize: 34, color: "#fff", marginTop: 2 },
  heroRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  heroPill: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill },
  heroPillText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#fff" },
  nextCard: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.lg },
  nextIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  nextLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  nextTitle: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  nextMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  gridTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginBottom: spacing.md },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  card: { width: "47.5%", flexGrow: 1, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border },
  cardIcon: { width: 44, height: 44, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center", marginBottom: spacing.sm },
  cardLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  cardBadge: { position: "absolute", top: spacing.md, right: spacing.md, minWidth: 22, height: 22, paddingHorizontal: 6, borderRadius: 11, backgroundColor: colors.error, alignItems: "center", justifyContent: "center" },
  cardBadgeText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.sm },
});
