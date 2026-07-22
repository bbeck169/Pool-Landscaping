/**
 * Widget Configs — admin only.
 * AI Chat Widget: GET /api/instaquote/configs
 * Form Builder: GET /api/admin/forms
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type WidgetConfig = { id: string; slug?: string; headline?: string; subheadline?: string; brand_color?: string; collect_fields?: any[]; services?: any[] };
type FormConfig = { id: string; name?: string; fields?: any[]; active?: boolean; created_at?: string };

export default function WidgetsScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const allowed = role === "admin" || role === "super_admin";

  const [configs, setConfigs] = useState<WidgetConfig[]>([]);
  const [forms, setForms] = useState<FormConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!allowed) { setLoading(false); return; }
    try {
      const [cfgRes, frmRes] = await Promise.all([
        api.get("/instaquote/configs").catch(() => ({ configs: [] })),
        api.get("/admin/forms").catch(() => []),
      ]);
      setConfigs(cfgRes?.configs || []);
      setForms(Array.isArray(frmRes) ? frmRes : frmRes?.forms || []);
    } catch {} finally { setLoading(false); setRefreshing(false); }
  }, [allowed]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="widgets-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateText}>Not authorized</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}><Text style={s.gateBtnText}>Go Home</Text></TouchableOpacity>
      </View>
    );
  }

  if (loading) return <View style={[s.center, { paddingTop: insets.top + 60 }]}><ActivityIndicator size="large" color={colors.brand} /></View>;

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12}><Ionicons name="arrow-back" size={22} color={colors.onSurface} /></TouchableOpacity>
        <Text style={s.navTitle}>Widget Configs</Text>
        <View style={{ width: 22 }} />
      </View>
      <ScrollView
        contentContainerStyle={s.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />}
      >
        {/* AI Chat Widget configs */}
        <Text style={s.sectionHeader}>AI Chat Widgets</Text>
        {configs.length === 0 ? (
          <View style={s.emptyCard}><Text style={s.emptyText}>No chat widget configs</Text></View>
        ) : (
          configs.map((cfg) => (
            <TouchableOpacity
              key={cfg.id}
              style={s.card}
              onPress={() => setExpanded(expanded === cfg.id ? null : cfg.id)}
              testID={`widget-${cfg.id}`}
            >
              <View style={s.cardTop}>
                <View style={s.iconWrap}><Ionicons name="chatbubbles" size={18} color={colors.brand} /></View>
                <View style={{ flex: 1 }}>
                  <Text style={s.cardName}>{cfg.headline || cfg.slug || "Widget"}</Text>
                  {cfg.subheadline ? <Text style={s.cardDesc}>{cfg.subheadline}</Text> : null}
                </View>
                <Ionicons name={expanded === cfg.id ? "chevron-up" : "chevron-down"} size={18} color={colors.muted} />
              </View>
              {expanded === cfg.id && (
                <View style={s.detailWrap}>
                  <Text style={s.detailLabel}>Slug</Text>
                  <Text style={s.detailValue}>{cfg.slug || "—"}</Text>
                  <Text style={s.detailLabel}>Brand Color</Text>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                    <View style={{ width: 18, height: 18, borderRadius: 4, backgroundColor: cfg.brand_color || "#ccc" }} />
                    <Text style={s.detailValue}>{cfg.brand_color || "—"}</Text>
                  </View>
                  <Text style={s.detailLabel}>Services ({cfg.services?.length || 0})</Text>
                  {(cfg.services || []).slice(0, 5).map((svc: any, i: number) => (
                    <Text key={i} style={s.detailValue}>• {svc.name || svc.label || svc}</Text>
                  ))}
                  <Text style={s.detailLabel}>Collect Fields</Text>
                  {(cfg.collect_fields || []).map((f: any, i: number) => (
                    <Text key={i} style={s.detailValue}>• {f.label || f.name || f} {f.required ? "(required)" : ""}</Text>
                  ))}
                  <View style={s.secNote}>
                    <Ionicons name="shield-checkmark" size={13} color={colors.brand} />
                    <Text style={s.secNoteText}>Allowed origins managed by admin console for security.</Text>
                  </View>
                </View>
              )}
            </TouchableOpacity>
          ))
        )}

        {/* Form Builder */}
        <Text style={[s.sectionHeader, { marginTop: spacing.lg }]}>Form Builder</Text>
        {forms.length === 0 ? (
          <View style={s.emptyCard}><Text style={s.emptyText}>No forms configured</Text></View>
        ) : (
          forms.map((frm) => (
            <View key={frm.id} style={s.card} testID={`form-${frm.id}`}>
              <View style={s.cardTop}>
                <View style={[s.iconWrap, { backgroundColor: "#F3E8FF" }]}><Ionicons name="document-text" size={18} color="#7E22CE" /></View>
                <View style={{ flex: 1 }}>
                  <Text style={s.cardName}>{frm.name || "Form"}</Text>
                  <Text style={s.cardDesc}>{frm.fields?.length || 0} fields · {frm.active ? "Active" : "Inactive"}</Text>
                </View>
                <View style={[s.activeDot, { backgroundColor: frm.active ? colors.success : colors.muted }]} />
              </View>
              {frm.fields && frm.fields.length > 0 && (
                <View style={s.fieldsWrap}>
                  {frm.fields.slice(0, 6).map((f: any, i: number) => (
                    <Text key={i} style={s.fieldText}>• {f.label || f.name} ({f.type || "text"}){f.required ? " *" : ""}</Text>
                  ))}
                  {frm.fields.length > 6 && <Text style={s.moreText}>+{frm.fields.length - 6} more fields</Text>}
                </View>
              )}
              <Text style={s.readOnlyNote}>Read-only on mobile. Full editor on web.</Text>
            </View>
          ))
        )}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F8FAFC" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  gateText: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 12 },
  gateBtn: { marginTop: 20, paddingHorizontal: 24, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.brand },
  gateBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  navBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  navTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  scroll: { padding: spacing.lg, paddingBottom: 40 },
  sectionHeader: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: spacing.sm },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 12 },
  iconWrap: { width: 36, height: 36, borderRadius: 10, backgroundColor: "#F0F9FF", alignItems: "center", justifyContent: "center" },
  cardName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  cardDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  activeDot: { width: 8, height: 8, borderRadius: 4 },
  detailWrap: { marginTop: spacing.md, paddingTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.border },
  detailLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginTop: spacing.sm, marginBottom: 2 },
  detailValue: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  secNote: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#F0F9FF", padding: spacing.sm, borderRadius: radius.sm, marginTop: spacing.md },
  secNoteText: { fontFamily: font.regular, fontSize: 11, color: colors.brand, flex: 1 },
  fieldsWrap: { marginTop: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  fieldText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface, paddingVertical: 2 },
  moreText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand, marginTop: 4 },
  readOnlyNote: { fontFamily: font.regular, fontSize: 10, color: colors.brand, fontStyle: "italic", marginTop: spacing.sm },
  emptyCard: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.xl, alignItems: "center", borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted },
});
