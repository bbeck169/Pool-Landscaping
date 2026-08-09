/**
 * Phase 54f · Feb-2026 — Mobile Settings > Suppliers (view-only).
 *
 * Mirrors the web ``SupplierSettings.jsx`` in read-only form. Operators
 * on mobile can see:
 *
 *   * All five supplier cards
 *   * Whether credentials are saved (green "Connected" pill)
 *   * Current sync_frequency
 *   * Last sync status + timestamp
 *
 * Edit + sync-now stays on web to avoid a native module dep + keep
 * this MVP a pure display screen. Full parity ships in a follow-up
 * phase once operators actually need it.
 *
 * Role gate: super_admin + admin + manager (view-only for everyone
 * who reaches this screen; the settings nav already blocks tech +
 * customer at the parent tab level).
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

// Same slug set + labels as the mobile pricebook — kept local so the
// module remains fork-safe if someone changes the web copy.
const SUPPLIER_LABELS: Record<string, string> = {
  poolcorp:    "Pool360 (PoolCorp)",
  siteone:     "SiteOne",
  ewing:       "Ewing Irrigation",
  heritage:    "Heritage Pool Plus",
  epoolsupply: "ePoolSupply",
};

const SUPPLIER_SLUG_ORDER = ["poolcorp", "siteone", "ewing", "heritage", "epoolsupply"];

type SupplierRow = {
  id: string;
  slug: string;
  display_name: string;
  active?: boolean;
  sync_frequency?: string;
  last_sync_at?: string | null;
  last_sync_status?: string | null;
};

function formatDate(iso?: string | null) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); }
  catch { return iso; }
}

function StatusPill({ label, tone }: { label: string; tone: "success" | "neutral" | "danger" }) {
  const palette = {
    success: { bg: "#DCFCE7", fg: "#166534" },
    neutral: { bg: "#E5E7EB", fg: "#374151" },
    danger:  { bg: "#FEE2E2", fg: "#991B1B" },
  }[tone];
  return (
    <View style={[styles.pill, { backgroundColor: palette.bg }]}>
      <Text style={[styles.pillText, { color: palette.fg }]}>{label}</Text>
    </View>
  );
}

export default function SupplierSettingsMobile() {
  const [suppliers, setSuppliers] = useState<SupplierRow[]>([]);
  const [credsBySlug, setCredsBySlug] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await api.get("/suppliers");
      setSuppliers(list || []);
      // Fan out one credentials read per supplier — 5 wholesalers max.
      const map: Record<string, boolean> = {};
      await Promise.all((list || []).map(async (s: SupplierRow) => {
        try {
          const c = await api.get(`/suppliers/${s.slug}/credentials`);
          map[s.slug] = !!c?.has_credentials;
        } catch { map[s.slug] = false; }
      }));
      setCredsBySlug(map);
    } catch {
      setSuppliers([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const orderedSuppliers = [...suppliers].sort(
    (a, b) => SUPPLIER_SLUG_ORDER.indexOf(a.slug) -
              SUPPLIER_SLUG_ORDER.indexOf(b.slug));

  return (
    <View style={styles.root} testID="mobile-supplier-settings-screen">
      <Header title="Suppliers" back subtitle="Wholesale pricebook sources" />
      {loading ? (
        <Loading testID="mobile-suppliers-loading" />
      ) : orderedSuppliers.length === 0 ? (
        <EmptyState icon="server-outline" title="No suppliers"
                    subtitle="Nothing to show yet — reach out to support."
                    testID="mobile-suppliers-empty" />
      ) : (
        <FlatList
          testID="mobile-suppliers-list"
          data={orderedSuppliers}
          keyExtractor={(s) => s.slug}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing}
                              onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item: s }) => (
            <View style={styles.card} testID={`mobile-supplier-card-${s.slug}`}>
              <View style={styles.cardHeader}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardTitle}>
                    {SUPPLIER_LABELS[s.slug] || s.display_name}
                  </Text>
                  <Text style={styles.cardSub}>Slug: {s.slug}</Text>
                </View>
                {credsBySlug[s.slug]
                  ? <StatusPill label="Connected" tone="success" />
                  : <StatusPill label="Not connected" tone="neutral" />}
              </View>

              <View style={styles.rowLine}>
                <Ionicons name="time-outline" size={14} color={colors.muted} />
                <Text style={styles.metaLabel}>Frequency</Text>
                <Text style={styles.metaValue}
                      testID={`mobile-supplier-frequency-${s.slug}`}>
                  {s.sync_frequency || "daily"}
                </Text>
              </View>

              <View style={styles.rowLine}>
                <Ionicons name="sync-outline" size={14} color={colors.muted} />
                <Text style={styles.metaLabel}>Last sync</Text>
                <Text style={styles.metaValue}>{formatDate(s.last_sync_at)}</Text>
                {s.last_sync_status ? (
                  <StatusPill label={s.last_sync_status}
                              tone={s.last_sync_status === "success"
                                    ? "success" : s.last_sync_status === "error"
                                    ? "danger" : "neutral"} />
                ) : null}
              </View>

              <View style={styles.rowLine}>
                <Ionicons name="power-outline" size={14} color={colors.muted} />
                <Text style={styles.metaLabel}>Active</Text>
                <Text style={styles.metaValue}>{s.active === false ? "no" : "yes"}</Text>
              </View>

              <Text style={styles.readonlyNote}>
                Mobile is view-only. Manage credentials + trigger syncs from the web app.
              </Text>
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  card: { backgroundColor: colors.surface, borderRadius: radius.md,
          padding: spacing.md, borderWidth: 1, borderColor: colors.border,
          marginBottom: spacing.md },
  cardHeader: { flexDirection: "row", alignItems: "flex-start",
                gap: spacing.sm, marginBottom: spacing.sm },
  cardTitle: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface },
  cardSub: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  rowLine: { flexDirection: "row", alignItems: "center",
             gap: 6, marginTop: 6, flexWrap: "wrap" },
  metaLabel: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  metaValue: { fontFamily: font.bold, fontSize: fontSize.xs,
               color: colors.onSurface, marginLeft: "auto" },
  readonlyNote: { fontFamily: font.regular, fontSize: fontSize.xs,
                  color: colors.muted, marginTop: spacing.sm, fontStyle: "italic" },
  pill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  pillText: { fontFamily: font.bold, fontSize: 10 },
});
