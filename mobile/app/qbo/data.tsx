// Phase 17 · Feb-2026 — QBO mobile data browser (Manager+; read-only).
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TextInput, Pressable, RefreshControl } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, EmptyState, Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

const TABS = [
  { key: "customers",       label: "Customers" },
  { key: "invoices",        label: "Invoices" },
  { key: "payments",        label: "Payments" },
  { key: "accounts",        label: "Accounts" },
  { key: "vendors",         label: "Vendors" },
  { key: "bills",           label: "Bills" },
  { key: "journal-entries", label: "Journal" },
];

function _summary(entity: string, row: any): string {
  const ex = row.extracted || {};
  return ex.display_name || ex.customer_name || ex.vendor_name
    || ex.doc_number || ex.name || row.qbo_id;
}

export default function QboData() {
  const [entity, setEntity] = useState("customers");
  const [rows, setRows] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (q) params.set("search", q);
      const j: any = await api.get(`/qbo/${entity}?${params.toString()}`);
      setRows(j?.items || []);
    } catch { setRows([]); }
    setLoading(false);
  }, [entity, q]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <RoleGate level="admin_plus">
      <View style={styles.container}>
        <Header title="QBO data browser" />
        <ScrollView horizontal showsHorizontalScrollIndicator={false}
                     contentContainerStyle={styles.tabsRow}>
          {TABS.map((t) => {
            const on = entity === t.key;
            return (
              <Pressable
                key={t.key}
                testID={`qbo-mobile-tab-${t.key}`}
                accessibilityLabel={`Entity ${t.label}`}
                onPress={() => setEntity(t.key)}
                style={[styles.tab, on && styles.tabOn]}
              >
                <Text style={[styles.tabText, on && styles.tabTextOn]}>{t.label}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
        <TextInput
          testID="qbo-mobile-search"
          value={q}
          onChangeText={setQ}
          placeholder="Search…"
          placeholderTextColor={colors.muted}
          style={styles.search}
        />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => {
            setRefreshing(true); await load(); setRefreshing(false);
          }} />}
        >
          {loading ? (
            <Loading />
          ) : rows.length === 0 ? (
            <EmptyState
              icon="cloud-download-outline"
              title="Nothing synced yet"
              subtitle="Run a sync from the QBO landing screen first."
              testID="qbo-mobile-data-empty"
            />
          ) : (
            rows.map((r) => (
              <Card key={r.qbo_id}>
                <Text style={styles.title} testID={`qbo-mobile-row-${r.qbo_id}`}>
                  {_summary(entity, r)}
                </Text>
                <Text style={styles.meta}>QBO ID: {r.qbo_id}</Text>
                {r.linked_crm_id ? (
                  <Text style={styles.linked}>
                    Linked to CRM · {r.linked_crm_entity_type} · {String(r.linked_crm_id).slice(0, 14)}…
                  </Text>
                ) : null}
                <Text style={styles.synced}>
                  Last synced {(r.last_synced_at || "").slice(0, 19)}
                </Text>
              </Card>
            ))
          )}
        </ScrollView>
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  tabsRow: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, gap: 6 },
  tab: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill,
         backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  tabOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  tabText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  tabTextOn: { color: "#FFFFFF" },
  search: {
    marginHorizontal: spacing.lg, marginBottom: spacing.sm,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base,
    color: colors.onSurface,
  },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  title: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4 },
  linked: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.success, marginTop: 4 },
  synced: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 4 },
});
