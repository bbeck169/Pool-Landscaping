/** Phase 17C · Mobile — White-Label Reports: list, create, share PDF. */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  Modal, Alert, ActivityIndicator, Switch,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";
import { useFocusEffect } from "expo-router";

import { api, TOKEN_KEY } from "@/src/api";
import { storage } from "@/src/utils/storage";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { AdminOnlyGate, BrandPill, CenterLoader } from "./_shared";

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || "";

export default function ReportsMobile() {
  return (
    <AdminOnlyGate title="White-Label Reports">
      <Inner />
    </AdminOnlyGate>
  );
}

function Inner() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [audits, setAudits] = useState<any[]>([]);
  const [creating, setCreating] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);

  const [title, setTitle] = useState("SEO Report");
  const [brandName, setBrandName] = useState("");
  const [includeLlm, setIncludeLlm] = useState(true);
  const [pickedAudit, setPickedAudit] = useState<string>("");

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/seo/reports");
      setRows(r.items || []);
    } finally { setLoading(false); }
  };
  useFocusEffect(useCallback(() => { load(); }, []));

  const openNew = async () => {
    setShowNew(true);
    try {
      const a = await api.get("/seo/audits");
      setAudits(Array.isArray(a) ? a : (a.items || []));
    } catch { /* ignore */ }
  };

  const create = async () => {
    if (!title.trim()) {
      Alert.alert("Missing title", "Enter a report title.");
      return;
    }
    if (!pickedAudit && !includeLlm) {
      Alert.alert("Add a data source",
                   "Pick an audit or include LLM Visibility.");
      return;
    }
    setCreating(true);
    try {
      const payload: any = {
        title, brand_name: brandName,
        include_llm_visibility: includeLlm,
        range_days: 30,
      };
      if (pickedAudit) payload.audit_id = pickedAudit;
      await api.post("/seo/reports", payload, 120000);
      setShowNew(false);
      setTitle("SEO Report"); setBrandName(""); setPickedAudit("");
      await load();
    } catch (e: any) {
      Alert.alert("Failed", e?.message || "Error");
    } finally { setCreating(false); }
  };

  const shareReport = async (r: any) => {
    setDownloading(r.id);
    try {
      const token = await storage.secureGet<string>(TOKEN_KEY, "");
      const url = `${BACKEND}/api/seo/reports/${r.id}/download?format=pdf`;
      const dest = `${FileSystem.cacheDirectory}report-${r.id.slice(0, 8)}.pdf`;
      const dl = await FileSystem.downloadAsync(url, dest, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const isAvail = await Sharing.isAvailableAsync();
      if (!isAvail) {
        Alert.alert("Downloaded", `Saved to ${dl.uri}`);
        return;
      }
      await Sharing.shareAsync(dl.uri, {
        mimeType: "application/pdf",
        dialogTitle: r.title || "SEO Report",
      });
    } catch (e: any) {
      Alert.alert("Share failed", e?.message || "Error");
    } finally { setDownloading(null); }
  };

  return (
    <View style={styles.root}>
      <Header title="White-Label Reports" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 60 }}>
        <Pressable style={styles.newBtn} onPress={openNew}
                    testID="report-new-btn">
          <Ionicons name="add" size={16} color="#fff" />
          <Text style={styles.newBtnText}>New report</Text>
        </Pressable>

        {loading ? <CenterLoader /> : rows.length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="document-text-outline" size={28}
                       color={colors.muted} />
            <Text style={styles.emptyTitle}>No reports yet</Text>
            <Text style={styles.emptyBody}>
              Tap New report to generate your first branded snapshot.
            </Text>
          </View>
        ) : (
          rows.map((r) => (
            <View key={r.id} style={styles.card}
                  testID={`report-row-${r.id}`}>
              <View style={{
                width: 6, height: 44, borderRadius: 3,
                backgroundColor: r.brand_color || colors.brand,
              }} />
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.title} numberOfLines={1}>{r.title}</Text>
                <Text style={styles.meta}>
                  {r.brand_name} · {(r.created_at || "").slice(0, 10)}
                </Text>
                {r.last_sent_at && (
                  <BrandPill text={`Sent ${(r.last_sent_at || "").slice(0, 10)}`}
                              tone="green" />
                )}
              </View>
              <Pressable style={styles.shareBtn}
                          disabled={downloading === r.id}
                          onPress={() => shareReport(r)}
                          testID={`report-share-${r.id}`}>
                {downloading === r.id ? (
                  <ActivityIndicator color="#fff" size="small" />
                ) : (
                  <>
                    <Ionicons name="share-outline" size={14} color="#fff" />
                    <Text style={styles.shareBtnText}>Share</Text>
                  </>
                )}
              </Pressable>
            </View>
          ))
        )}
      </ScrollView>

      <Modal visible={showNew} transparent animationType="slide"
              onRequestClose={() => setShowNew(false)}>
        <Pressable style={styles.modalBg}
                    onPress={() => setShowNew(false)}>
          <Pressable style={styles.modal}
                      onPress={(e) => e.stopPropagation()}>
            <Text style={styles.modalTitle}>New report</Text>

            <Text style={styles.label}>Title</Text>
            <TextInput style={styles.input} value={title}
                        onChangeText={setTitle}
                        testID="report-new-title" />
            <Text style={styles.label}>Brand name (optional)</Text>
            <TextInput style={styles.input} value={brandName}
                        onChangeText={setBrandName}
                        testID="report-new-brand" />

            <Text style={styles.label}>Include audit</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}
                         style={{ marginBottom: spacing.md }}>
              <Pressable style={[styles.auditChip,
                                    !pickedAudit && styles.auditChipActive]}
                          onPress={() => setPickedAudit("")}>
                <Text style={[styles.auditChipText,
                                !pickedAudit && { color: "#fff" }]}>None</Text>
              </Pressable>
              {audits.slice(0, 20).map((a) => (
                <Pressable key={a.id}
                            style={[styles.auditChip,
                                     pickedAudit === a.id && styles.auditChipActive]}
                            onPress={() => setPickedAudit(a.id)}
                            testID={`report-new-audit-${a.id}`}>
                  <Text style={[styles.auditChipText,
                                  pickedAudit === a.id && { color: "#fff" }]}
                         numberOfLines={1}>{a.url}</Text>
                </Pressable>
              ))}
            </ScrollView>

            <View style={styles.switchRow}>
              <Text style={styles.switchLabel}>
                Include LLM Visibility (30d)
              </Text>
              <Switch value={includeLlm} onValueChange={setIncludeLlm}
                       trackColor={{ true: colors.brand, false: "#CBD5E1" }}
                       testID="report-new-llm" />
            </View>

            <Pressable style={[styles.submit,
                                creating && { opacity: 0.6 }]}
                        disabled={creating} onPress={create}
                        testID="report-new-submit">
              <Text style={styles.submitText}>
                {creating ? "Generating…" : "Generate report"}
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
  newBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brand, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: 10,
    alignSelf: "flex-start", marginBottom: spacing.md,
  },
  newBtnText: { fontFamily: font.bold, fontSize: fontSize.sm,
                 color: "#fff" },
  empty: { padding: spacing["2xl"], alignItems: "center",
            gap: spacing.sm },
  emptyTitle: { fontFamily: font.bold, fontSize: fontSize.lg,
                 color: colors.onSurface, marginTop: spacing.sm },
  emptyBody: { fontFamily: font.regular, fontSize: fontSize.base,
                color: colors.muted, textAlign: "center" },
  card: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.md, borderWidth: 1,
    borderColor: colors.border, marginBottom: spacing.sm,
  },
  title: { fontFamily: font.bold, fontSize: fontSize.base,
            color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm,
           color: colors.muted, marginTop: 2 },
  shareBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.brand, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: 8,
    minWidth: 80, justifyContent: "center",
  },
  shareBtnText: { fontFamily: font.bold, fontSize: fontSize.sm,
                   color: "#fff" },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)",
              justifyContent: "flex-end" },
  modal: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
    padding: spacing.lg, maxHeight: "90%",
  },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.xl,
                 color: colors.onSurface, marginBottom: spacing.md },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm,
            color: colors.muted, marginTop: spacing.sm,
            marginBottom: spacing.xs },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, padding: spacing.md,
    fontFamily: font.regular, fontSize: fontSize.base,
    color: colors.onSurface, borderWidth: 1,
    borderColor: colors.border,
  },
  auditChip: {
    paddingHorizontal: spacing.md, paddingVertical: 6,
    borderRadius: 999, marginRight: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border,
    maxWidth: 240,
  },
  auditChipActive: { backgroundColor: colors.brand,
                      borderColor: colors.brand },
  auditChipText: { fontFamily: font.semibold, fontSize: fontSize.sm,
                    color: colors.onSurface },
  switchRow: {
    flexDirection: "row", alignItems: "center",
    justifyContent: "space-between", marginTop: spacing.md,
    marginBottom: spacing.md,
  },
  switchLabel: { fontFamily: font.semibold, fontSize: fontSize.base,
                  color: colors.onSurface, flex: 1 },
  submit: {
    marginTop: spacing.md, backgroundColor: colors.brand,
    borderRadius: radius.md, padding: spacing.md,
    alignItems: "center",
  },
  submitText: { fontFamily: font.bold, fontSize: fontSize.lg,
                 color: "#fff" },
});
