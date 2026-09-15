/** Phase 17A · Mobile — Rank Heatmap: form + table view (graph is desktop-only). */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { AdminOnlyGate, DesktopHint, BrandPill, CenterLoader } from "./_shared";
import AppTextInput from "@/src/components/ui/AppTextInput";

export default function RankHeatmapMobile() {
  return (
    <AdminOnlyGate title="Rank Heatmap">
      <Inner />
    </AdminOnlyGate>
  );
}

function Inner() {
  const [keyword, setKeyword] = useState("");
  const [lat, setLat] = useState("33.5");
  const [lng, setLng] = useState("-112.2");
  const [grid, setGrid] = useState("5");
  const [radiusMi, setRadiusMi] = useState("5");
  const [busy, setBusy] = useState(false);
  const [rows, setRows] = useState<any[]>([]);
  const [heatmap, setHeatmap] = useState<any>(null);

  const load = async () => {
    try {
      const r = await api.get("/seo/rank-heatmaps");
      setRows(Array.isArray(r) ? r : (r.items || []));
    } catch { /* ignore */ }
  };
  useEffect(() => { load(); }, []);

  const start = async () => {
    if (!keyword.trim()) {
      Alert.alert("Missing keyword", "Enter a keyword to track.");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post("/seo/rank-heatmaps", {
        keyword,
        center_lat: parseFloat(lat), center_lng: parseFloat(lng),
        grid_size: parseInt(grid) || 5,
        radius_miles: parseFloat(radiusMi),
      });
      // poll for completion
      const poll = async () => {
        const g = await api.get(`/seo/rank-heatmaps/${r.heatmap_id}`);
        setHeatmap(g);
        if (["queued", "running"].includes(g.status)) {
          setTimeout(poll, 3500);
        } else {
          setBusy(false);
          await load();
        }
      };
      await poll();
    } catch (e: any) {
      Alert.alert("Failed", e?.message || "Error");
      setBusy(false);
    }
  };

  return (
    <View style={styles.root}>
      <Header title="Rank Heatmap" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 60 }}>
        <DesktopHint text="Map overlay is best viewed on desktop. Mobile shows a compact table view." />

        <Text style={styles.label}>Keyword</Text>
        <AppTextInput style={styles.input} value={keyword}
                    autoCapitalize="none"
                    onChangeText={setKeyword}
                    testID="heatmap-keyword" />
        <View style={{ flexDirection: "row", gap: spacing.md }}>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Latitude</Text>
            <AppTextInput style={styles.input} value={lat}
                        keyboardType="numbers-and-punctuation"
                        onChangeText={setLat}
                        testID="heatmap-lat" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Longitude</Text>
            <AppTextInput style={styles.input} value={lng}
                        keyboardType="numbers-and-punctuation"
                        onChangeText={setLng}
                        testID="heatmap-lng" />
          </View>
        </View>
        <View style={{ flexDirection: "row", gap: spacing.md }}>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Grid (per side)</Text>
            <AppTextInput style={styles.input} value={grid}
                        keyboardType="number-pad"
                        onChangeText={setGrid}
                        testID="heatmap-grid" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Radius (mi)</Text>
            <AppTextInput style={styles.input} value={radiusMi}
                        keyboardType="numbers-and-punctuation"
                        onChangeText={setRadiusMi}
                        testID="heatmap-radius" />
          </View>
        </View>

        <Pressable style={[styles.submit, busy && { opacity: 0.6 }]}
                    disabled={busy} onPress={start}
                    testID="heatmap-start">
          <Ionicons name="search-outline" size={16} color="#fff" />
          <Text style={styles.submitText}>
            {busy ? "Scanning…" : "Run scan"}
          </Text>
        </Pressable>

        {busy && <CenterLoader />}

        {heatmap && (
          <View style={{ marginTop: spacing.xl }}>
            <View style={styles.summaryCard}>
              <Text style={styles.summaryTitle}>
                “{heatmap.keyword}”
              </Text>
              <View style={{ flexDirection: "row",
                              gap: spacing.md, marginTop: spacing.sm,
                              alignItems: "center", flexWrap: "wrap" }}>
                <BrandPill text={heatmap.status}
                            tone={heatmap.status === "done" ? "green" :
                                   heatmap.status === "failed" ? "red" : "amber"} />
                {heatmap.mocked && <BrandPill text="MOCKED" tone="amber" />}
                <Text style={styles.summaryText}>
                  Avg rank: {heatmap.avg_rank ?? "—"} · Top-3:{" "}
                  {heatmap.top_position_count ?? 0}
                </Text>
              </View>
            </View>

            <View style={styles.tableHeader}>
              <Text style={[styles.th, { flex: 1 }]}>Lat</Text>
              <Text style={[styles.th, { flex: 1 }]}>Lng</Text>
              <Text style={[styles.th, { width: 50, textAlign: "right" }]}>
                Rank
              </Text>
              <Text style={[styles.th, { flex: 2 }]}>Top URL</Text>
            </View>
            {(heatmap.points || []).map((p: any, i: number) => (
              <View key={i} style={styles.tableRow}>
                <Text style={[styles.td, { flex: 1 }]}>
                  {(p.lat ?? 0).toFixed(3)}
                </Text>
                <Text style={[styles.td, { flex: 1 }]}>
                  {(p.lng ?? 0).toFixed(3)}
                </Text>
                <Text style={[styles.td, { width: 50, textAlign: "right",
                                            fontFamily: font.bold }]}>
                  {p.rank ?? "—"}
                </Text>
                <Text style={[styles.td, { flex: 2, color: colors.brand }]}
                       numberOfLines={1}>
                  {p.top_url || "—"}
                </Text>
              </View>
            ))}
          </View>
        )}

        {rows.length > 0 && !heatmap && (
          <View style={{ marginTop: spacing.xl }}>
            <Text style={styles.subtitle}>Recent heatmaps</Text>
            {rows.slice(0, 20).map((r) => (
              <Pressable key={r.id}
                          style={styles.pastRow}
                          onPress={() => setHeatmap(r)}>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.pastKw} numberOfLines={1}>
                    {r.keyword}
                  </Text>
                  <Text style={styles.pastMeta}>
                    Avg: {r.avg_rank ?? "—"} · {r.status}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={18}
                           color={colors.muted} />
              </Pressable>
            ))}
          </View>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm,
            color: colors.muted, marginTop: spacing.sm,
            marginBottom: spacing.xs },
  input: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    padding: spacing.md, fontFamily: font.regular,
    fontSize: fontSize.base, color: colors.onSurface,
    borderWidth: 1, borderColor: colors.border,
  },
  submit: {
    marginTop: spacing.lg, backgroundColor: colors.brand,
    borderRadius: radius.md, padding: spacing.md,
    alignItems: "center", flexDirection: "row",
    justifyContent: "center", gap: spacing.sm,
  },
  submitText: { fontFamily: font.bold, fontSize: fontSize.lg,
                 color: "#fff" },
  summaryCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.md,
  },
  summaryTitle: { fontFamily: font.bold, fontSize: fontSize.lg,
                   color: colors.onSurface },
  summaryText: { fontFamily: font.regular, fontSize: fontSize.sm,
                  color: colors.muted },
  tableHeader: {
    flexDirection: "row", padding: spacing.sm,
    backgroundColor: colors.brand,
    borderTopLeftRadius: radius.sm, borderTopRightRadius: radius.sm,
  },
  th: { fontFamily: font.bold, fontSize: 10, color: "#fff",
         textTransform: "uppercase" },
  tableRow: {
    flexDirection: "row", padding: spacing.sm,
    backgroundColor: colors.surface, borderBottomWidth: 1,
    borderColor: colors.border,
  },
  td: { fontFamily: font.regular, fontSize: fontSize.sm,
         color: colors.onSurface },
  subtitle: { fontFamily: font.bold, fontSize: fontSize.lg,
               color: colors.onSurface, marginBottom: spacing.sm },
  pastRow: {
    flexDirection: "row", alignItems: "center", padding: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  pastKw: { fontFamily: font.bold, fontSize: fontSize.base,
             color: colors.onSurface },
  pastMeta: { fontFamily: font.regular, fontSize: fontSize.sm,
               color: colors.muted, marginTop: 2 },
});
