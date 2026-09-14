/**
 * Phase 12C · Tenant Settings — admin/manager only.
 * GET  /api/tenants/mine/settings
 * PATCH /api/tenants/mine/settings
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, Switch, Alert, RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import BreadcrumbBar from "@/src/components/nav/BreadcrumbBar";
import TenantIndustryBadges from "@/src/components/tenant/TenantIndustryBadges";

const TIMEZONES = [
  { value: "America/New_York", label: "Eastern", short: "ET" },
  { value: "America/Chicago", label: "Central", short: "CT" },
  { value: "America/Denver", label: "Mountain", short: "MT" },
  { value: "America/Phoenix", label: "Arizona", short: "AZ" },
  { value: "America/Los_Angeles", label: "Pacific", short: "PT" },
];

function relativeTime(iso: string) {
  if (!iso) return "";
  const d = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(d / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default function TenantSettingsScreen() {
  const insets = useSafeAreaInsets();
  const { showToast } = useToast();
  const router = useRouter();
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const allowed = role === "admin" || role === "super_admin";

  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!allowed) { setLoading(false); return; }
    try {
      const res = await api.get("/tenants/mine/settings");
      setData(res);
    } catch {} finally { setLoading(false); setRefreshing(false); }
  }, [allowed]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const saveSetting = async (patch: Record<string, any>) => {
    setSaving(true);
    try {
      const updated = await api.patch("/tenants/mine/settings", patch);
      setData(updated);
      showToast("Saved");
    } catch (e: any) {
      Alert.alert("Failed", e.message || "Update failed");
    } finally {
      setSaving(false);
    }
  };

  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="tenant-settings-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateTitle}>Not authorized</Text>
        <Text style={s.gateSub}>Settings are available to admins only.</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}>
          <Text style={s.gateBtnText}>Go Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (loading) {
    return <View style={[s.center, { paddingTop: insets.top + 60 }]}><ActivityIndicator size="large" color={colors.brand} /></View>;
  }

  const tz = data?.timezone || "America/Phoenix";
  const nextSyncDay = "Thu 02:00";
  const tzLabel = TIMEZONES.find((t) => t.value === tz)?.label || tz;

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Tenant Settings</Text>
        <View style={{ width: 22 }} />
      </View>
      <BreadcrumbBar title="Tenant Settings" />

      {/* Industry badges — Phase D */}
      <View style={s.badgeRow}>
        <TenantIndustryBadges max={4} />
      </View>

      <ScrollView
        contentContainerStyle={s.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />}
      >
        {/* Timezone */}
        <View style={s.card} testID="settings-timezone">
          <Text style={s.sectionLabel}>TIMEZONE</Text>
          <View style={s.tzGrid}>
            {TIMEZONES.map((t) => (
              <TouchableOpacity
                key={t.value}
                style={[s.tzChip, tz === t.value && s.tzChipActive]}
                onPress={() => saveSetting({ timezone: t.value })}
                disabled={saving}
                testID={`tz-${t.short}`}
              >
                <Text style={[s.tzLabel, tz === t.value && s.tzLabelActive]}>{t.short}</Text>
                <Text style={[s.tzSub, tz === t.value && s.tzSubActive]}>{t.label}</Text>
              </TouchableOpacity>
            ))}
          </View>
          <Text style={s.syncNote} testID="next-sync-label">
            Next scheduled sync: {nextSyncDay} · {tzLabel}
          </Text>
        </View>

        {/* Card on file default */}
        <View style={s.card} testID="settings-card-default">
          <View style={s.switchRow}>
            <View style={{ flex: 1 }}>
              <Text style={s.switchLabel}>Require card on file by default</Text>
              <Text style={s.switchDesc}>New customers will be required to add a card on file.</Text>
            </View>
            <Switch
              testID="card-default-toggle"
              value={!!data?.require_card_on_file_default}
              onValueChange={(val) => saveSetting({ require_card_on_file_default: val })}
              trackColor={{ false: "#9CA3AF", true: "#16A34A" }}
              thumbColor="#ffffff"
              ios_backgroundColor="#9CA3AF"
              disabled={saving}
            />
          </View>
        </View>

        {/* Auto-send card link */}
        <View style={s.card} testID="settings-auto-send">
          <View style={s.switchRow}>
            <View style={{ flex: 1 }}>
              <Text style={s.switchLabel}>Auto-send add-card link on creation</Text>
              <Text style={s.switchDesc}>Automatically send the add-card email + SMS when a new customer is created.</Text>
            </View>
            <Switch
              testID="auto-send-toggle"
              value={!!data?.auto_send_card_add_on_create}
              onValueChange={(val) => saveSetting({ auto_send_card_add_on_create: val })}
              trackColor={{ false: "#9CA3AF", true: "#16A34A" }}
              thumbColor="#ffffff"
              ios_backgroundColor="#9CA3AF"
              disabled={saving}
            />
          </View>
        </View>

        {/* Last changed */}
        {data?.settings_updated_at && (
          <Text style={s.lastChanged} testID="settings-last-changed">
            Last changed {relativeTime(data.settings_updated_at)}
            {data.settings_updated_by ? ` by ${data.settings_updated_by}` : ""}
          </Text>
        )}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F8FAFC" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  gateTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 12 },
  gateSub: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 4, textAlign: "center" },
  gateBtn: { marginTop: 20, paddingHorizontal: 24, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.brand },
  gateBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  navBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  navTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  badgeRow: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  scroll: { padding: spacing.lg, paddingBottom: 40 },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  sectionLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 1, textTransform: "uppercase", marginBottom: spacing.sm },
  tzGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  tzChip: { alignItems: "center", paddingHorizontal: 14, paddingVertical: 10, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, minWidth: 64 },
  tzChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  tzLabel: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  tzLabelActive: { color: "#fff" },
  tzSub: { fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 1 },
  tzSubActive: { color: "rgba(255,255,255,0.8)" },
  syncNote: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: spacing.md, fontStyle: "italic" },
  switchRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  switchLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  switchDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2, maxWidth: "90%" },
  lastChanged: { fontFamily: font.regular, fontSize: 11, color: colors.muted, textAlign: "center", marginTop: spacing.sm },
});
