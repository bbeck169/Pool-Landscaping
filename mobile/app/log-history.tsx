import React, { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading, EmptyState } from "@/src/components/ui";
import AppTextInput from "@/src/components/ui/AppTextInput";

const RATING_COLOR: Record<string, string> = {
  "Average": "#16A34A",
  "Below Average": "#D97706",
  "Above Average": "#D97706",
  "High": "#DC2626",
};

export default function LogHistoryReport() {
  const [customers, setCustomers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [loadingReport, setLoadingReport] = useState(false);

  const loadCustomers = useCallback(async () => {
    try {
      const c = await api.get("/customers");
      setCustomers(c);
    } catch {
      setCustomers([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { loadCustomers(); }, [loadCustomers]));

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return customers.slice(0, 30);
    return customers.filter((c) => (c.name || "").toLowerCase().includes(q) || (c.address || "").toLowerCase().includes(q)).slice(0, 30);
  }, [customers, query]);

  const selectCustomer = async (c: any) => {
    setSelected(c);
    setReport(null);
    setLoadingReport(true);
    try {
      const r = await api.get(`/reports/log-history?customer_id=${c.id}`);
      setReport(r);
    } catch {
      setReport({ entries: [], count: 0 });
    } finally {
      setLoadingReport(false);
    }
  };

  const reset = () => { setSelected(null); setReport(null); setQuery(""); };

  if (loading) return <Loading testID="loghistory-loading" />;

  return (
    <View style={styles.root}>
      <Header title="Log History" back subtitle="Water tests & chemical usage" />

      {!selected ? (
        <View style={{ flex: 1 }}>
          <View style={styles.searchWrap}>
            <Ionicons name="search" size={16} color={colors.muted} />
            <AppTextInput
              style={styles.searchInput}
              value={query}
              onChangeText={setQuery}
              placeholder="Search customer by name or address"
              placeholderTextColor={colors.muted}
              autoCorrect={false}
              testID="loghistory-search"
            />
          </View>
          <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }} keyboardShouldPersistTaps="handled">
            {filtered.length === 0 ? (
              <EmptyState icon="people-outline" title="No customers" subtitle="Try a different search." testID="loghistory-nocust" />
            ) : (
              filtered.map((c) => (
                <Pressable key={c.id} style={styles.custRow} onPress={() => selectCustomer(c)} testID={`loghistory-cust-${c.id}`}>
                  <View style={styles.avatar}><Text style={styles.avatarText}>{(c.name || "?").charAt(0).toUpperCase()}</Text></View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.custName} numberOfLines={1}>{c.name}</Text>
                    {c.address ? <Text style={styles.custMeta} numberOfLines={1}>{c.address}</Text> : null}
                  </View>
                  <Ionicons name="chevron-forward" size={18} color={colors.muted} />
                </Pressable>
              ))
            )}
          </ScrollView>
        </View>
      ) : (
        <View style={{ flex: 1 }}>
          <Pressable style={styles.selectedBar} onPress={reset} testID="loghistory-change">
            <View style={styles.avatar}><Text style={styles.avatarText}>{(selected.name || "?").charAt(0).toUpperCase()}</Text></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.custName} numberOfLines={1}>{selected.name}</Text>
              <Text style={styles.custMeta}>{report ? `${report.count} logged visit${report.count === 1 ? "" : "s"}` : "Loading…"}</Text>
            </View>
            <Text style={styles.changeLink}>Change</Text>
          </Pressable>

          {loadingReport ? (
            <Loading testID="loghistory-report-loading" />
          ) : (
            <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}>
              {report && report.entries.length === 0 ? (
                <EmptyState icon="flask-outline" title="No logs yet" subtitle="This customer has no recorded water tests or chemical usage." testID="loghistory-empty" />
              ) : (
                (report?.entries || []).map((e: any) => (
                  <View key={e.job_id} style={styles.card} testID={`loghistory-entry-${e.job_id}`}>
                    <View style={styles.cardHead}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.cardDate}>{e.date}</Text>
                        <Text style={styles.cardService} numberOfLines={1}>{e.service_type}{e.technician ? ` · ${e.technician}` : ""}</Text>
                      </View>
                      {e.status ? <Text style={styles.statusPill}>{e.status}</Text> : null}
                    </View>

                    {e.readings.length > 0 ? (
                      <View style={styles.section}>
                        <Text style={styles.sectionTitle}>💧 Water Test</Text>
                        {e.readings.map((r: any) => (
                          <View key={r.key} style={styles.dataRow}>
                            <Text style={styles.dataLabel}>{r.label}</Text>
                            <View style={styles.dataRight}>
                              <Text style={styles.dataValue}>{r.value}{r.unit ? ` ${r.unit}` : ""}</Text>
                              <Text style={[styles.rating, { color: RATING_COLOR[r.rating] || colors.muted }]}>{r.rating}</Text>
                            </View>
                          </View>
                        ))}
                      </View>
                    ) : null}

                    {e.chemicals.length > 0 ? (
                      <View style={styles.section}>
                        <Text style={styles.sectionTitle}>🧪 Chemicals Added</Text>
                        {e.chemicals.map((c: any, i: number) => (
                          <View key={`${c.name}-${i}`} style={styles.dataRow}>
                            <Text style={styles.dataLabel}>{c.name}</Text>
                            <Text style={styles.dataValue}>{c.amount}{c.unit ? ` ${c.unit}` : ""}</Text>
                          </View>
                        ))}
                      </View>
                    ) : null}
                  </View>
                ))
              )}
            </ScrollView>
          )}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  searchWrap: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, marginHorizontal: spacing.lg, marginTop: spacing.md },
  searchInput: { flex: 1, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  custRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  avatar: { width: 38, height: 38, borderRadius: 19, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
  custName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  custMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  selectedBar: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, padding: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  changeLink: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.md },
  cardHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm },
  cardDate: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  cardService: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  statusPill: { fontFamily: font.semibold, fontSize: 11, color: colors.onSurfaceSecondary, backgroundColor: colors.surfaceSecondary, paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.pill, textTransform: "capitalize", overflow: "hidden" },
  section: { marginTop: spacing.xs, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  sectionTitle: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  dataRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 5 },
  dataLabel: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, flex: 1 },
  dataRight: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  dataValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  rating: { fontFamily: font.medium, fontSize: fontSize.sm, minWidth: 96, textAlign: "right" },
});
