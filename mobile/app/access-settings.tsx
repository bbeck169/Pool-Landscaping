import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, Switch } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

const MODULE_LABELS: Record<string, string> = {
  jobs: "Jobs", schedule: "Schedule", quotes: "Quotes & Invoices", customers: "Customers",
  payments: "Payments", reports: "Reports", dispatch: "Dispatch", marketing: "Marketing",
};
const ROLE_META: Record<string, { label: string; icon: any; note: string }> = {
  technician: { label: "Technician", icon: "construct", note: "Field crew — pricing always hidden" },
  customer: { label: "Customer", icon: "person", note: "Client portal access" },
};

export default function AccessSettings() {
  const [data, setData] = useState<any>({ modules: [], matrix: {} });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.get("/access-settings"));
    } catch {
      setData({ modules: [], matrix: {} });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const toggle = async (role: string, module: string, enabled: boolean) => {
    // optimistic update
    setData((d: any) => ({ ...d, matrix: { ...d.matrix, [role]: { ...d.matrix[role], [module]: enabled } } }));
    setSaving(`${role}-${module}`);
    try {
      const res = await api.put("/access-settings", { role, module, enabled });
      setData(res);
    } catch {
      load();
    } finally {
      setSaving(null);
    }
  };

  if (loading) {
    return (
      <View style={styles.root}>
        <Header title="Access Settings" back subtitle="Role permissions" />
        <Loading testID="access-loading" />
      </View>
    );
  }

  const roles = Object.keys(data.matrix || {});

  return (
    <View style={styles.root}>
      <Header title="Access Settings" back subtitle="Role permissions" />
      <ScrollView
        testID="access-scroll"
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <View style={styles.adminBanner}>
          <Ionicons name="shield-checkmark" size={18} color={colors.brand} />
          <Text style={styles.adminText}>Administrators always have full access.</Text>
        </View>

        {roles.map((role) => {
          const meta = ROLE_META[role] || { label: role, icon: "person", note: "" };
          return (
            <View key={role} style={styles.card} testID={`access-role-${role}`}>
              <View style={styles.roleHeader}>
                <View style={styles.roleIcon}>
                  <Ionicons name={meta.icon} size={18} color={colors.brand} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.roleLabel}>{meta.label}</Text>
                  {meta.note ? <Text style={styles.roleNote}>{meta.note}</Text> : null}
                </View>
              </View>
              {(data.modules || []).map((mod: string) => (
                <View key={mod} style={styles.permRow}>
                  <Text style={styles.permLabel}>{MODULE_LABELS[mod] || mod}</Text>
                  <Switch
                    value={!!data.matrix[role]?.[mod]}
                    onValueChange={(v) => toggle(role, mod, v)}
                    disabled={saving === `${role}-${mod}`}
                    trackColor={{ true: colors.brand, false: colors.surfaceTertiary }}
                    thumbColor="#fff"
                    testID={`access-${role}-${mod}`}
                  />
                </View>
              ))}
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  adminBanner: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.brandTertiary, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md },
  adminText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onBrandTertiary, flex: 1 },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  roleHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm },
  roleIcon: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  roleLabel: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  roleNote: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  permRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: colors.divider },
  permLabel: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
});
