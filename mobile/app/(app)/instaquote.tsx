/**
 * QuoteIQ Q4 · Mobile — InstaQuote submissions list (admin only).
 *
 * Read + convert/dismiss flow. Deep-edit of the config stays on web.
 * Public quote URL is opened in the system browser via `Linking`.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Alert, ActivityIndicator,
  Linking,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { useToast } from "@/src/components/ToastProvider";
import { colors, spacing, radius, fontSize, font } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { useAuth } from "@/src/auth";

function fmt$(cents: number) {
  return `$${(Number(cents || 0) / 100).toFixed(2)}`;
}

const STATUS_COLOURS: Record<string, string> = {
  new: colors.brand,
  converted: "#10b981",
  dismissed: colors.muted,
  contacted: "#f59e0b",
};

export default function InstaQuoteMobile() {
  const { showToast } = useToast();
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || (user?.role as any) === "super_admin";
  const [subs, setSubs] = useState<any[]>([]);
  const [selected, setSelected] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [activeConfig, setActiveConfig] = useState<any | null>(null);

  const load = useCallback(async () => {
    if (!isAdmin) { setLoading(false); return; }
    try {
      const [subsResp, cfgResp] = await Promise.all([
        api.get("/instaquote/submissions?limit=100"),
        api.get("/instaquote/configs"),
      ]);
      setSubs(subsResp.submissions || []);
      const active = (cfgResp.configs || []).find((c: any) => c.active);
      setActiveConfig(active || null);
    } catch {
      // swallow — mobile is best-effort here.
    } finally {
      setLoading(false);
    }
  }, [isAdmin]);
  useEffect(() => { load(); }, [load]);

  const openPublicUrl = () => {
    if (!activeConfig) return;
    const backend = (process.env.EXPO_PUBLIC_BACKEND_URL || "").replace(/\/$/, "");
    const url = `${backend.replace(/\/api$/, "")}/quote/${activeConfig.slug}`;
    Linking.openURL(url).catch(() => Alert.alert("Couldn't open URL"));
  };

  const convert = async (id: string) => {
    setBusy(true);
    try {
      const r = await api.post(`/instaquote/submissions/${id}/convert`);
      showToast(`Converted — Deal #${r.deal_id?.slice(0, 6)}…`);
      setSelected(null);
      load();
    } catch (e: any) {
      showToast(e?.message || "Convert failed.", "error");
    } finally {
      setBusy(false);
    }
  };

  const dismiss = async (id: string) => {
    setBusy(true);
    try {
      await api.post(`/instaquote/submissions/${id}/dismiss`, { note: "" });
      showToast("Dismissed");
      setSelected(null);
      load();
    } catch (e: any) {
      Alert.alert("Dismiss failed", e?.message || "");
    } finally {
      setBusy(false);
    }
  };

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <Header title="InstaQuote" />
        <View style={styles.centerBox}>
          <Text style={styles.emptyTxt}>Admin-only screen.</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <Header title="InstaQuote" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 120 }}>
        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} />
        ) : (
          <>
            {activeConfig && (
              <Pressable onPress={openPublicUrl}
                          style={styles.publicCard}
                          testID="iq-mobile-public-url">
                <Ionicons name="link-outline" size={16} color={colors.brand} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.publicLbl}>Public quote URL</Text>
                  <Text style={styles.publicUrl} numberOfLines={1}>
                    /quote/{activeConfig.slug}
                  </Text>
                </View>
                <Ionicons name="open-outline" size={16} color={colors.muted} />
              </Pressable>
            )}

            <Text style={styles.sectionTitle}>Submissions</Text>
            {subs.length === 0 && (
              <Text style={styles.emptyTxt}>No submissions yet.</Text>
            )}
            {subs.map((s) => (
              <Pressable key={s.id}
                          onPress={() => setSelected(s)}
                          style={[styles.subCard,
                            selected?.id === s.id && styles.subCardSelected]}
                          testID={`iq-mobile-sub-${s.id}`}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.subName}>
                    {s.contact?.name || s.contact?.email || "(anon)"}
                  </Text>
                  <Text style={styles.subMeta}>
                    {fmt$(s.computed_total_cents)} · {s.submitted_at?.slice(0, 16)}
                  </Text>
                </View>
                <View style={[styles.badge,
                  { backgroundColor: STATUS_COLOURS[s.status] || colors.muted }]}>
                  <Text style={styles.badgeTxt}>{s.status}</Text>
                </View>
              </Pressable>
            ))}

            {selected && (
              <View style={styles.detail} testID="iq-mobile-detail">
                <Text style={styles.detailTitle}>
                  {selected.contact?.name || "(anon)"}
                </Text>
                <Text style={styles.detailMeta}>
                  {selected.contact?.email}
                </Text>
                <Text style={styles.detailMeta}>
                  {selected.contact?.phone}
                </Text>
                {selected.contact?.notes && (
                  <Text style={styles.detailNote}>
                    &quot;{selected.contact.notes}&quot;
                  </Text>
                )}
                {(selected.computed_breakdown_json || []).map((b: any, i: number) => (
                  <View key={i} style={styles.breakRow}>
                    <Text style={styles.breakLbl}>
                      {b.service_name} × {b.qty} · {b.frequency_label}
                    </Text>
                    <Text style={styles.breakVal}>
                      {fmt$(b.line_total_cents)}
                    </Text>
                  </View>
                ))}
                <View style={styles.totalRow}>
                  <Text style={styles.totalLbl}>Total</Text>
                  <Text style={styles.totalVal}>
                    {fmt$(selected.computed_total_cents)}
                  </Text>
                </View>
                {selected.status === "new" && (
                  <View style={styles.actionRow}>
                    <Pressable style={[styles.actionBtn, styles.convertBtn,
                                          busy && { opacity: 0.6 }]}
                                onPress={() => convert(selected.id)}
                                disabled={busy}
                                testID="iq-mobile-convert">
                      <Ionicons name="checkmark-circle-outline"
                                  size={16} color="#fff" />
                      <Text style={styles.actionTxt}>Convert</Text>
                    </Pressable>
                    <Pressable style={[styles.actionBtn, styles.dismissBtn,
                                          busy && { opacity: 0.6 }]}
                                onPress={() => dismiss(selected.id)}
                                disabled={busy}
                                testID="iq-mobile-dismiss">
                      <Ionicons name="close-circle-outline"
                                  size={16} color={colors.onSurface} />
                      <Text style={[styles.actionTxt,
                                       { color: colors.onSurface }]}>
                        Dismiss
                      </Text>
                    </Pressable>
                  </View>
                )}
                {selected.status === "converted" && (
                  <Text style={styles.detailMeta}>
                    Deal: {selected.converted_deal_id?.slice(0, 8)}…
                  </Text>
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
