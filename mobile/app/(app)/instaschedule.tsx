/**
 * QuoteIQ Q5 · Mobile — InstaSchedule bookings (admin only).
 *
 * Read + confirm / decline / cancel flow. Deep-edit of the config
 * stays on web. Public book URL opens in the system browser.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Alert, ActivityIndicator,
  Linking,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, fontSize, font } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { useAuth } from "@/src/auth";

const STATUS_COLOURS: Record<string, string> = {
  pending: colors.brand,
  confirmed: "#10b981",
  declined: colors.muted,
  cancelled: "#a1a1aa",
};

export default function InstaScheduleMobile() {
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || (user?.role as any) === "super_admin";
  const [rows, setRows] = useState<any[]>([]);
  const [selected, setSelected] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [activeConfig, setActiveConfig] = useState<any | null>(null);

  const load = useCallback(async () => {
    if (!isAdmin) { setLoading(false); return; }
    try {
      const [r, c] = await Promise.all([
        api.get("/instaschedule/bookings?limit=100"),
        api.get("/instaschedule/configs"),
      ]);
      setRows(r.bookings || []);
      setActiveConfig((c.configs || []).find((cf: any) => cf.active) || null);
    } catch {
      // best-effort
    } finally { setLoading(false); }
  }, [isAdmin]);
  useEffect(() => { load(); }, [load]);

  const openPublic = () => {
    if (!activeConfig) return;
    const backend = (process.env.EXPO_PUBLIC_BACKEND_URL || "").replace(/\/$/, "");
    const url = `${backend.replace(/\/api$/, "")}/book/${activeConfig.slug}`;
    Linking.openURL(url).catch(() => Alert.alert("Couldn't open URL"));
  };

  const act = async (id: string, verb: "confirm" | "decline" | "cancel") => {
    setBusy(true);
    try {
      const body = verb === "decline" ? { reason: "" } : {};
      const r = await api.post(`/instaschedule/bookings/${id}/${verb}`, body);
      Alert.alert(verb.charAt(0).toUpperCase() + verb.slice(1),
                    verb === "confirm"
                      ? `Job #${r.job_id?.slice(0, 6)}…`
                      : "");
      setSelected(null); load();
    } catch (e: any) {
      Alert.alert(`${verb} failed`, e?.message || "");
    } finally { setBusy(false); }
  };

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <Header title="InstaSchedule" />
        <View style={styles.centerBox}>
          <Text style={styles.emptyTxt}>Admin-only screen.</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <Header title="InstaSchedule" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 120 }}>
        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} />
        ) : (
          <>
            {activeConfig && (
              <Pressable onPress={openPublic}
                          style={styles.publicCard}
                          testID="is-mobile-public-url">
                <Ionicons name="link-outline" size={16} color={colors.brand} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.publicLbl}>Public book URL</Text>
                  <Text style={styles.publicUrl} numberOfLines={1}>
                    /book/{activeConfig.slug}
                  </Text>
                </View>
                <Ionicons name="open-outline" size={16} color={colors.muted} />
              </Pressable>
            )}
            <Text style={styles.sectionTitle}>Bookings</Text>
            {rows.length === 0 && (
              <Text style={styles.emptyTxt}>No bookings yet.</Text>
            )}
            {rows.map((s) => (
              <Pressable key={s.id}
                          onPress={() => setSelected(s)}
                          style={[styles.subCard,
                            selected?.id === s.id && styles.subCardSelected]}
                          testID={`is-mobile-booking-${s.id}`}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.subName}>
                    {s.contact?.name || s.contact?.email || "(anon)"}
                  </Text>
                  <Text style={styles.subMeta}>
                    {s.requested_slot?.date} · {(s.requested_slot?.start_iso || "").slice(11, 16)}
                  </Text>
                </View>
                <View style={[styles.badge,
                  { backgroundColor: STATUS_COLOURS[s.status] || colors.muted }]}>
                  <Text style={styles.badgeTxt}>{s.status}</Text>
                </View>
              </Pressable>
            ))}
            {selected && (
              <View style={styles.detail} testID="is-mobile-detail">
                <Text style={styles.detailTitle}>
                  {selected.contact?.name || "(anon)"}
                </Text>
                <Text style={styles.detailMeta}>
                  {selected.contact?.email}
                </Text>
                <Text style={styles.detailMeta}>
                  {selected.contact?.phone}
                </Text>
                {selected.notes && (
                  <Text style={styles.detailNote}>"{selected.notes}"</Text>
                )}
                <View style={styles.breakRow}>
                  <Text style={styles.breakLbl}>
                    {selected.requested_slot?.date} ·{" "}
                    {(selected.requested_slot?.start_iso || "").slice(11, 16)}–
                    {(selected.requested_slot?.end_iso || "").slice(11, 16)}
                  </Text>
                </View>
                {selected.status === "pending" && (
                  <View style={styles.actionRow}>
                    <Pressable style={[styles.actionBtn, styles.convertBtn,
                                          busy && { opacity: 0.6 }]}
                                onPress={() => act(selected.id, "confirm")}
                                disabled={busy}
                                testID="is-mobile-confirm">
                      <Text style={styles.actionTxt}>Confirm</Text>
                    </Pressable>
                    <Pressable style={[styles.actionBtn, styles.dismissBtn,
                                          busy && { opacity: 0.6 }]}
                                onPress={() => act(selected.id, "decline")}
                                disabled={busy}
                                testID="is-mobile-decline">
                      <Text style={[styles.actionTxt,
                                       { color: colors.onSurface }]}>
                        Decline
                      </Text>
                    </Pressable>
                  </View>
                )}
                {selected.status === "confirmed" && (
                  <>
                    <Text style={styles.detailMeta}>
                      Job: {selected.computed_job_id?.slice(0, 8)}…
                    </Text>
                    <Pressable style={[styles.actionBtn, styles.dismissBtn,
                                          busy && { opacity: 0.6 }]}
                                onPress={() => act(selected.id, "cancel")}
                                disabled={busy}
                                testID="is-mobile-cancel">
                      <Text style={[styles.actionTxt,
                                       { color: colors.onSurface }]}>
                        Cancel booking + job
                      </Text>
                    </Pressable>
                  </>
                )}
              </View>
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  centerBox: { flex: 1, alignItems: "center", justifyContent: "center" },
  publicCard: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surface, borderColor: colors.border,
    borderWidth: 1, marginBottom: spacing.md,
  },
  publicLbl: { color: colors.muted, fontSize: fontSize.sm,
                 fontFamily: font.regular },
  publicUrl: { color: colors.onSurface, fontFamily: font.semibold },
  sectionTitle: {
    color: colors.onSurface, fontWeight: "700",
    fontFamily: font.bold, marginTop: spacing.sm,
    marginBottom: spacing.sm,
  },
  subCard: {
    flexDirection: "row", alignItems: "center",
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surface, borderColor: colors.border,
    borderWidth: 1, marginBottom: 6, gap: spacing.md,
  },
  subCardSelected: { borderColor: colors.brand },
  subName: { color: colors.onSurface, fontFamily: font.semibold },
  subMeta: { color: colors.muted, fontSize: fontSize.sm,
                fontFamily: font.regular, marginTop: 2 },
  badge: {
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6,
  },
  badgeTxt: {
    color: "#fff", fontSize: 10, fontFamily: font.semibold,
    textTransform: "uppercase",
  },
  detail: {
    marginTop: spacing.md, padding: spacing.md,
    borderRadius: radius.md, backgroundColor: colors.surface,
    borderColor: colors.border, borderWidth: 1,
  },
  detailTitle: {
    color: colors.onSurface, fontFamily: font.bold,
    fontWeight: "700", fontSize: fontSize.base,
  },
  detailMeta: {
    color: colors.muted, fontFamily: font.regular,
    fontSize: fontSize.sm, marginTop: 2,
  },
  detailNote: {
    color: colors.onSurface, fontStyle: "italic",
    marginVertical: 6, fontSize: fontSize.sm,
    fontFamily: font.regular,
  },
  breakRow: {
    flexDirection: "row", justifyContent: "space-between",
    paddingVertical: 4,
  },
  breakLbl: { color: colors.onSurface, fontSize: fontSize.sm,
                fontFamily: font.regular, flex: 1 },
  breakVal: { color: colors.onSurface, fontSize: fontSize.sm,
                fontFamily: font.semibold },
  totalRow: {
    flexDirection: "row", justifyContent: "space-between",
    marginTop: spacing.sm, paddingTop: spacing.sm,
    borderTopWidth: 1, borderTopColor: colors.border,
  },
  totalLbl: { fontFamily: font.bold, fontWeight: "700" },
  totalVal: { color: colors.brand, fontFamily: font.bold,
                fontWeight: "700" },
  actionRow: {
    flexDirection: "row", gap: 8, marginTop: spacing.md,
  },
  actionBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: spacing.md, paddingVertical: 8,
    borderRadius: 8, flex: 1, justifyContent: "center",
  },
  convertBtn: { backgroundColor: colors.brand },
  dismissBtn: {
    backgroundColor: colors.surface, borderWidth: 1,
    borderColor: colors.border,
  },
  actionTxt: {
    color: "#fff", fontFamily: font.bold, fontWeight: "700",
    fontSize: fontSize.sm,
  },
  emptyTxt: { color: colors.muted, fontSize: fontSize.sm,
                fontFamily: font.regular, textAlign: "center",
                marginTop: 20 },
});
