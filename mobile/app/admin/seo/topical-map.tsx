/** Phase 17B · Mobile — Topical Map: seed form + collapsible pillar tree. */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { AdminOnlyGate, DesktopHint, BrandPill, CenterLoader } from "./_shared";

const INTENT_TONE: Record<string, "brand" | "green" | "amber" | "red" | "grey"> = {
  informational: "brand", commercial: "green",
  transactional: "amber", navigational: "red",
};

export default function TopicalMapMobile() {
  return (
    <AdminOnlyGate title="Topical Map">
      <Inner />
    </AdminOnlyGate>
  );
}

function Inner() {
  const [seed, setSeed] = useState("");
  const [context, setContext] = useState("");
  const [busy, setBusy] = useState(false);
  const [map, setMap] = useState<any>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const load = async () => {
    try {
      const r = await api.get("/seo/topical-maps");
      setRows(Array.isArray(r) ? r : (r.items || []));
    } catch { /* ignore */ }
  };
  useEffect(() => { load(); }, []);

  const generate = async () => {
    if (!seed.trim()) {
      Alert.alert("Missing seed keyword", "Enter a seed keyword first.");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post("/seo/topical-maps", {
        seed_keyword: seed,
        business_context: context,
      }, 90000);
      const m = await api.get(`/seo/topical-maps/${r.map_id}`);
      setMap(m);
      await load();
    } catch (e: any) {
      Alert.alert("Failed", e?.message || "Error");
    } finally { setBusy(false); }
  };

  const nodes: any[] = map?.tree?.nodes || [];
  const pillars = nodes.filter((n) => (n.level ?? 0) === 0 || !n.parent);
  const childrenOf = (parentId: string) =>
    nodes.filter((n) => n.parent === parentId);

  return (
    <View style={styles.root}>
      <Header title="Topical Map" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 60 }}>
        <DesktopHint text="Graph visualization is desktop-only. Mobile shows a collapsible tree list." />

        <Text style={styles.label}>Seed keyword</Text>
        <TextInput style={styles.input} value={seed}
                    onChangeText={setSeed}
                    autoCapitalize="none"
                    testID="topical-seed" />
        <Text style={styles.label}>Business context (optional)</Text>
        <TextInput style={[styles.input, { minHeight: 80,
                                            textAlignVertical: "top" }]}
                    multiline value={context}
                    onChangeText={setContext}
                    testID="topical-context" />

        <Pressable style={[styles.submit, busy && { opacity: 0.6 }]}
                    disabled={busy} onPress={generate}
                    testID="topical-generate">
          <Ionicons name="sparkles-outline" size={16} color="#fff" />
          <Text style={styles.submitText}>
            {busy ? "Generating…" : "Generate map"}
          </Text>
        </Pressable>

        {busy && <CenterLoader />}

        {map && (
          <View style={{ marginTop: spacing.xl }}>
            <Text style={styles.subtitle}>
              {nodes.length} nodes · seed “{map.seed_keyword}”
            </Text>
            {pillars.map((pillar) => {
              const isOpen = expanded[pillar.id] ?? true;
              const clusters = childrenOf(pillar.id);
              return (
                <View key={pillar.id} style={styles.pillarBlock}>
                  <Pressable
                    style={styles.pillarHead}
                    onPress={() => setExpanded({ ...expanded,
                                                    [pillar.id]: !isOpen })}
                    testID={`topical-pillar-${pillar.id}`}>
                    <Ionicons name={isOpen ? "chevron-down" : "chevron-forward"}
                                size={16} color={colors.brand} />
                    <Text style={styles.pillarTitle} numberOfLines={2}>
                      {pillar.title}
                    </Text>
                    <BrandPill text={pillar.intent || "info"}
                                tone={INTENT_TONE[pillar.intent] || "brand"} />
                  </Pressable>
                  {isOpen && clusters.map((cluster) => {
                    const supports = childrenOf(cluster.id);
                    return (
                      <View key={cluster.id} style={styles.clusterBlock}>
                        <View style={styles.clusterHead}>
                          <Text style={styles.clusterTitle}>{cluster.title}</Text>
                          <BrandPill text={cluster.intent || "info"}
                                      tone={INTENT_TONE[cluster.intent] || "brand"} />
                        </View>
                        {supports.map((sup) => (
                          <View key={sup.id} style={styles.supportRow}>
                            <View style={styles.supportDot} />
                            <Text style={styles.supportTitle}
                                   numberOfLines={2}>{sup.title}</Text>
                          </View>
                        ))}
                      </View>
                    );
                  })}
                </View>
              );
            })}
          </View>
        )}

        {rows.length > 0 && !map && (
          <View style={{ marginTop: spacing.xl }}>
            <Text style={styles.subtitle}>Recent maps</Text>
            {rows.slice(0, 20).map((r) => (
              <Pressable key={r.id} style={styles.pastRow}
                          onPress={async () => {
                            const m = await api.get(
                              `/seo/topical-maps/${r.id}`);
                            setMap(m);
                          }}>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.pastKw} numberOfLines={1}>
                    {r.seed_keyword}
                  </Text>
                  <Text style={styles.pastMeta}>
                    {(r.created_at || "").slice(0, 10)}
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
  subtitle: { fontFamily: font.bold, fontSize: fontSize.base,
               color: colors.onSurface, marginBottom: spacing.md },
  pillarBlock: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, marginBottom: spacing.md,
  },
  pillarHead: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
  },
  pillarTitle: { flex: 1, fontFamily: font.bold, fontSize: fontSize.base,
                  color: colors.onSurface },
  clusterBlock: {
    marginTop: spacing.md, marginLeft: 8, paddingLeft: 10,
    borderLeftWidth: 2, borderLeftColor: colors.brandTertiary,
  },
  clusterHead: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    marginBottom: 6,
  },
  clusterTitle: { flex: 1, fontFamily: font.semibold,
                   fontSize: fontSize.sm, color: colors.onSurface },
  supportRow: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    paddingLeft: 12, marginBottom: 4,
  },
  supportDot: {
    width: 5, height: 5, borderRadius: 2.5,
    backgroundColor: colors.muted, marginTop: 6,
  },
  supportTitle: { flex: 1, fontFamily: font.regular,
                   fontSize: fontSize.sm, color: colors.muted },
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
