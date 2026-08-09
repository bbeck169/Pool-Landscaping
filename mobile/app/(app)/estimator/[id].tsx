/**
 * Phase 21 · Mobile — Estimate detail: items + upsells + convert + PDF share.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Alert, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";

import { api, TOKEN_KEY } from "@/src/api";
import { storage } from "@/src/utils/storage";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL || "";

export default function EstimatorDetailMobile() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [e, setE] = useState<any>(null);
  const [busy, setBusy] = useState<string>("");

  const load = useCallback(async () => {
    const r = await api.get(`/estimator/estimates/${id}`);
    setE(r);
  }, [id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!e) return (
    <View style={styles.root}>
      <Header title="Estimate" />
      <ActivityIndicator color={colors.brand} style={{ marginTop: 30 }} />
    </View>
  );

  const convert = async () => {
    setBusy("convert");
    try {
      const r = await api.post(
        `/estimator/estimates/${id}/convert-to-quote`);
      Alert.alert("Converted",
                   `Quote #${(r.quote_id || "").slice(0, 8)} created.`);
      await load();
    } catch (err: any) {
      Alert.alert("Convert failed", err?.message || "Error");
    } finally { setBusy(""); }
  };

  const share = async () => {
    setBusy("share");
    try {
      const token = await storage.secureGet<string>(TOKEN_KEY, "");
      const url = `${BACKEND}/api/estimator/estimates/${id}/pdf.file`;
      const dest = `${FileSystem.cacheDirectory}estimate-${id.slice(0, 8)}.pdf`;
      const dl = await FileSystem.downloadAsync(url, dest, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const ok = await Sharing.isAvailableAsync();
      if (ok) {
        await Sharing.shareAsync(dl.uri, { mimeType: "application/pdf",
                                             dialogTitle: e.title });
      } else {
        Alert.alert("Downloaded", `Saved to ${dl.uri}`);
      }
    } catch (err: any) {
      Alert.alert("Share failed", err?.message || "Error");
    } finally { setBusy(""); }
  };

  const addUpsell = async (u: any) => {
    setBusy("addup");
    try {
      await api.post(`/estimator/estimates/${id}/add-line-item`, {
        description: u.title, quantity: 1, unit: "ea",
        unit_price: u.estimated_add_price || 0, category: "misc",
      });
      await load();
    } finally { setBusy(""); }
  };

  return (
    <View style={styles.root}>
      <Header title="Estimate" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 120 }}>
        <Text style={styles.h1} numberOfLines={2}>{e.title}</Text>
        <Text style={styles.meta}>
          {e.service_type} · {e.status}
          {e.mocked ? " · MOCKED" : ""}
        </Text>

        <View style={styles.totalsCard}>
          {[
            ["Subtotal", e.subtotal],
            [`Markup (${(e.markup_pct || 0).toFixed(1)}%)`, e.markup_amount],
            [`Tax (${(e.tax_rate_pct || 0).toFixed(1)}%)`, e.tax_amount],
          ].map(([l, v]) => (
            <View key={l as string} style={styles.totRow}>
              <Text style={styles.totLabel}>{l}</Text>
              <Text style={styles.totValue}>${((v as number) || 0).toFixed(2)}</Text>
            </View>
          ))}
          <View style={[styles.totRow, styles.totFinal]}>
            <Text style={styles.totFinalLabel}>Total</Text>
            <Text style={styles.totFinalValue}>
              ${(e.total || 0).toFixed(2)}
            </Text>
          </View>
        </View>

        <View style={styles.actionRow}>
          <Pressable style={styles.actionBtn}
                     onPress={share}
                     disabled={!!busy}
                     testID="est-share">
            {busy === "share" ? <ActivityIndicator color="#fff" size="small" /> : (
              <>
                <Ionicons name="share-outline" size={14} color="#fff" />
                <Text style={styles.actionText}>Share PDF</Text>
              </>
            )}
          </Pressable>
          <Pressable style={[styles.actionBtn,
                              e.status === "converted" && { opacity: 0.5 }]}
                     onPress={convert}
                     disabled={!!busy || e.status === "converted"}
                     testID="est-convert">
            {busy === "convert" ? <ActivityIndicator color="#fff" size="small" /> : (
              <>
                <Ionicons name="checkmark-circle-outline" size={14}
                           color="#fff" />
                <Text style={styles.actionText}>
                  {e.status === "converted" ? "Converted" : "Convert to Quote"}
                </Text>
              </>
            )}
          </Pressable>
        </View>

        <Text style={styles.sectionH}>Line items</Text>
        {(e.line_items || []).length === 0 ? (
          <Text style={styles.empty}>No line items.</Text>
        ) : (
          (e.line_items || []).map((li: any) => (
            <View key={li.id} style={styles.itemCard}
                  testID={`est-item-${li.id}`}>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.itemDesc}
                       numberOfLines={2}>{li.description}</Text>
                <Text style={styles.itemMeta}>
                  {li.quantity} {li.unit} × ${li.unit_price.toFixed(2)}
                </Text>
                <View style={[styles.srcPill,
                                { backgroundColor:
                                    li.unit_price_source === "tenant_rate"
                                    ? "#DCFCE7" : "#FEF3C7",
                                    marginTop: 4 }]}>
                  <Text style={[styles.srcText,
                                  { color:
                                      li.unit_price_source === "tenant_rate"
                                      ? "#166534" : "#92400E" }]}>
                    {li.unit_price_source === "tenant_rate"
                      ? "✓ Rate catalog"
                      : `AI estimate · ${(li.confidence * 100).toFixed(0)}%`}
                  </Text>
                </View>
              </View>
              <Text style={styles.itemTotal}>
                ${(li.extended_price || 0).toFixed(2)}
              </Text>
            </View>
          ))
        )}

        <Text style={styles.sectionH}>Suggested add-ons</Text>
        {(e.upsells || []).length === 0 ? (
          <Text style={styles.empty}>No upsells suggested.</Text>
        ) : (
          (e.upsells || []).map((u: any) => (
            <View key={u.id} style={styles.upsellCard}
                  testID={`est-upsell-${u.id}`}>
              <View style={styles.upsellHead}>
                <Text style={styles.upsellTitle}
                       numberOfLines={1}>{u.title}</Text>
                <Text style={styles.upsellPrice}>
                  +${(u.estimated_add_price || 0).toFixed(0)}
                </Text>
              </View>
              <Text style={styles.upsellDesc}
                     numberOfLines={3}>{u.description}</Text>
              <Pressable style={styles.upsellBtn}
                          disabled={!!busy}
                          onPress={() => addUpsell(u)}
                          testID={`est-add-upsell-${u.id}`}>
                <Ionicons name="add" size={12} color={colors.brand} />
                <Text style={styles.upsellBtnText}>Add to estimate</Text>
              </Pressable>
            </View>
          ))
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  h1: { fontFamily: font.bold, fontSize: fontSize.xl,
         color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm,
           color: colors.muted, marginTop: 4 },
  totalsCard: {
    marginTop: spacing.md, padding: spacing.md,
    backgroundColor: colors.surface, borderWidth: 1,
    borderColor: colors.border, borderRadius: radius.lg,
  },
  totRow: { flexDirection: "row", justifyContent: "space-between",
             paddingVertical: 3 },
  totLabel: { fontFamily: font.regular, fontSize: fontSize.sm,
               color: colors.muted },
  totValue: { fontFamily: font.regular, fontSize: fontSize.sm,
               color: colors.onSurface },
  totFinal: { borderTopWidth: 2, borderTopColor: colors.onSurface,
               marginTop: 6, paddingTop: 6 },
  totFinalLabel: { fontFamily: font.bold, fontSize: fontSize.lg,
                    color: colors.onSurface },
  totFinalValue: { fontFamily: font.bold, fontSize: fontSize.lg,
                    color: colors.onSurface },
  actionRow: { flexDirection: "row", gap: spacing.sm,
                marginTop: spacing.md },
  actionBtn: {
    flex: 1, flexDirection: "row", alignItems: "center",
    justifyContent: "center", gap: 6,
    backgroundColor: colors.brand, paddingVertical: 12,
    borderRadius: radius.md,
  },
  actionText: { fontFamily: font.bold, fontSize: fontSize.sm,
                 color: "#fff" },
  sectionH: { fontFamily: font.bold, fontSize: fontSize.lg,
               color: colors.onSurface, marginTop: spacing.xl,
               marginBottom: spacing.sm },
  empty: { fontFamily: font.regular, fontSize: fontSize.sm,
            color: colors.muted, padding: spacing.md,
            textAlign: "center" },
  itemCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    padding: spacing.md, backgroundColor: colors.surface,
    borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, marginBottom: spacing.sm,
  },
  itemDesc: { fontFamily: font.bold, fontSize: fontSize.sm,
               color: colors.onSurface },
  itemMeta: { fontFamily: font.regular, fontSize: fontSize.sm,
               color: colors.muted, marginTop: 2 },
  itemTotal: { fontFamily: font.bold, fontSize: fontSize.base,
                color: colors.onSurface },
  srcPill: { alignSelf: "flex-start",
              paddingHorizontal: 6, paddingVertical: 2,
              borderRadius: 999 },
  srcText: { fontFamily: font.bold, fontSize: 9 },
  upsellCard: {
    padding: spacing.md, backgroundColor: colors.surface,
    borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, marginBottom: spacing.sm,
  },
  upsellHead: { flexDirection: "row", justifyContent: "space-between",
                 alignItems: "center" },
  upsellTitle: { flex: 1, fontFamily: font.bold, fontSize: fontSize.base,
                  color: colors.onSurface },
  upsellPrice: { fontFamily: font.bold, fontSize: fontSize.base,
                  color: "#059669" },
  upsellDesc: { fontFamily: font.regular, fontSize: fontSize.sm,
                 color: colors.muted, marginTop: 4 },
  upsellBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    marginTop: spacing.sm, alignSelf: "flex-start",
    backgroundColor: colors.brandTertiary,
    paddingHorizontal: spacing.md, paddingVertical: 6,
    borderRadius: 999,
  },
  upsellBtnText: { fontFamily: font.bold, fontSize: fontSize.sm,
                    color: colors.brand },
});
