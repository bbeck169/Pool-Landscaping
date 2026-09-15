/** Phase 17A · Mobile — Site Auditor list. */
import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, Modal, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from 'expo-router';

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { AdminOnlyGate, ScoreChip, BrandPill, CenterLoader } from "./_shared";
import AppTextInput from "@/src/components/ui/AppTextInput";

const STATUS_TONE: Record<string, "brand" | "green" | "amber" | "red" | "grey"> = {
  queued: "amber", running: "brand", done: "green",
  failed: "red", cancelled: "grey",
};

export default function SeoAuditsMobile() {
  return (
    <AdminOnlyGate title="Site Auditor">
      <Inner />
    </AdminOnlyGate>
  );
}

function Inner() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [url, setUrl] = useState("https://");
  const [depth, setDepth] = useState("3");
  const [maxPages, setMaxPages] = useState("50");
  const [starting, setStarting] = useState(false);

  const load = async () => {
    try {
      const r = await api.get("/seo/audits");
      setRows(Array.isArray(r) ? r : (r.items || []));
    } finally { setLoading(false); }
  };
  useFocusEffect(useCallback(() => { load(); }, []));

  useEffect(() => {
    if (!rows.some((r) => ["queued", "running"].includes(r.status))) return;
    const t = setInterval(load, 4500);
    return () => clearInterval(t);
  }, [rows]);

  const start = async () => {
    setStarting(true);
    try {
      await api.post("/seo/audits", {
        url, depth: parseInt(depth) || 3,
        max_pages: parseInt(maxPages) || 50,
      });
      setShowNew(false); setUrl("https://");
      await load();
    } catch (e: any) {
      Alert.alert("Failed to start audit", e?.message || "Error");
    } finally { setStarting(false); }
  };

  return (
    <View style={styles.root}>
      <Header title="Site Auditor" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 120 }}>
        {loading ? <CenterLoader /> : rows.length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="search-outline" size={28} color={colors.muted} />
            <Text style={styles.emptyTitle}>No audits yet</Text>
            <Text style={styles.emptyBody}>
              Tap the + button to crawl and score your first site.
            </Text>
          </View>
        ) : (
          rows.map((r) => (
            <Pressable key={r.id}
                       style={styles.card}
                       testID={`seo-audit-row-${r.id}`}
                       onPress={() => router.push(
                         `/admin/seo/audits/${r.id}` as any)}>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.cardUrl} numberOfLines={1}>{r.url}</Text>
                <View style={styles.cardMeta}>
                  <BrandPill text={r.status}
                              tone={STATUS_TONE[r.status] || "grey"} />
                  <Text style={styles.cardMetaText}>
                    {r.summary?.pages_crawled ?? "—"} pages ·{" "}
                    {r.summary?.issues_total ?? "—"} issues
                  </Text>
                </View>
              </View>
              <ScoreChip value={r.summary?.scores?.overall} />
              <Ionicons name="chevron-forward" size={18} color={colors.muted} />
            </Pressable>
          ))
        )}
      </ScrollView>

      <Pressable style={styles.fab}
                 testID="seo-audits-new-btn"
                 onPress={() => setShowNew(true)}>
        <Ionicons name="add" size={26} color="#fff" />
      </Pressable>

      <Modal visible={showNew} transparent animationType="slide"
             onRequestClose={() => setShowNew(false)}>
        <Pressable style={styles.modalBg}
                   onPress={() => setShowNew(false)}>
          <Pressable style={styles.modal} onPress={(e) => e.stopPropagation()}>
            <Text style={styles.modalTitle}>New audit</Text>
            <Text style={styles.label}>URL</Text>
            <AppTextInput style={styles.input} value={url}
                        autoCapitalize="none" autoCorrect={false}
                        onChangeText={setUrl}
                        testID="seo-audits-new-url" />
            <View style={{ flexDirection: "row", gap: spacing.md }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Depth</Text>
                <AppTextInput style={styles.input} value={depth}
                            onChangeText={setDepth} keyboardType="number-pad"
                            testID="seo-audits-new-depth" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Max pages</Text>
                <AppTextInput style={styles.input} value={maxPages}
                            onChangeText={setMaxPages}
                            keyboardType="number-pad"
                            testID="seo-audits-new-max" />
              </View>
            </View>
            <Pressable style={[styles.submit,
                                starting && { opacity: 0.6 }]}
                       disabled={starting}
                       onPress={start}
                       testID="seo-audits-new-submit">
              <Text style={styles.submitText}>
                {starting ? "Starting…" : "Run audit"}
              </Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  empty: { padding: spacing["2xl"], alignItems: "center", gap: spacing.sm },
  emptyTitle: { fontFamily: font.bold, fontSize: fontSize.lg,
                 color: colors.onSurface, marginTop: spacing.sm },
  emptyBody: { fontFamily: font.regular, fontSize: fontSize.base,
                color: colors.muted, textAlign: "center" },
  card: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  cardUrl: { fontFamily: font.bold, fontSize: fontSize.base,
              color: colors.onSurface },
  cardMeta: { flexDirection: "row", gap: spacing.sm,
               alignItems: "center", marginTop: 4 },
  cardMetaText: { fontFamily: font.regular, fontSize: fontSize.sm,
                   color: colors.muted },
  fab: {
    position: "absolute", right: spacing.lg, bottom: spacing.xl,
    width: 56, height: 56, borderRadius: 28,
    backgroundColor: colors.brand,
    alignItems: "center", justifyContent: "center",
    shadowColor: "#000", shadowOpacity: 0.2, shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 }, elevation: 4,
  },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)",
              justifyContent: "flex-end" },
  modal: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
    padding: spacing.lg, gap: spacing.sm,
  },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.xl,
                 color: colors.onSurface, marginBottom: spacing.md },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm,
            color: colors.muted, marginTop: spacing.sm },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, padding: spacing.md,
    fontFamily: font.regular, fontSize: fontSize.base,
    color: colors.onSurface, borderWidth: 1, borderColor: colors.border,
  },
  submit: {
    marginTop: spacing.lg, backgroundColor: colors.brand,
    borderRadius: radius.md, padding: spacing.md,
    alignItems: "center",
  },
  submitText: { fontFamily: font.bold, fontSize: fontSize.lg,
                 color: "#fff" },
});
