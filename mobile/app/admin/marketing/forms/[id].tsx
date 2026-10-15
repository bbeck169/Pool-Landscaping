/**
 * Marketing Form detail — Preview | Versions | Settings (all read-only).
 * Version revert is intentionally NOT available on mobile (touch-safety);
 * admins get "Open on desktop to revert" + a copy-link. TD-48.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, KeyboardAvoidingView, Platform } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as Clipboard from "expo-clipboard";

import { Header } from "@/src/components/widgets";
import CommsAdminGate, { MARKETING_FORMS_ROLES } from "@/src/components/comms/CommsAdminGate";
import FormSchemaPreview from "@/src/components/forms/FormSchemaPreview";
import { useToast } from "@/src/components/ToastProvider";
import { getForm, listFormVersions, type FormVersion, type MarketingForm } from "@/src/api/marketingForms";
import { colors, font, fontSize, radius, spacing } from "@/src/theme";

type Tab = "preview" | "versions" | "settings";
const ACTION_STYLE: Record<string, { bg: string; fg: string }> = {
  create: { bg: "#DBEAFE", fg: "#1E40AF" },
  update: { bg: "#E0F2FE", fg: "#075985" },
  revert: { bg: "#FEF3C7", fg: "#92400E" },
};
export const desktopFormsUrl = () => `${process.env.EXPO_PUBLIC_BACKEND_URL || ""}/admin/marketing/forms`;

export default function MarketingFormDetailScreen() {
  return (
    <CommsAdminGate title="Form" roles={MARKETING_FORMS_ROLES}>
      <FormDetailBody />
    </CommsAdminGate>
  );
}

function Versions({ fid }: { fid: string }) {
  const { showToast } = useToast();
  const [rows, setRows] = useState<FormVersion[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    listFormVersions(fid).then(setRows).catch((e) => { setErr(e?.message || "Couldn't load versions."); setRows([]); });
  }, [fid]);
  const copy = async () => {
    await Clipboard.setStringAsync(desktopFormsUrl());
    showToast("Desktop link copied", "success");
  };
  if (rows === null) return <ActivityIndicator color={colors.brand} testID="form-versions-loader" />;
  return (
    <View testID="form-versions">
      <View style={s.note}>
        <Text style={s.noteText}>Open on desktop to revert a version.</Text>
        <Pressable onPress={copy} style={s.copyBtn} testID="form-versions-copy-link"><Text style={s.copyText}>Copy link</Text></Pressable>
      </View>
      {err ? <Text style={s.err}>{err}</Text> : null}
      {!rows.length && !err ? <Text style={s.muted} testID="form-versions-empty">No saved versions yet.</Text> : null}
      {rows.map((v) => {
        const st = ACTION_STYLE[v.action || ""] || { bg: "#F3F4F6", fg: "#374151" };
        return (
          <View key={v.id || v.version} style={s.vRow} testID={`form-version-${v.version}`}>
            <Text style={s.vNum}>v{v.version}</Text>
            <View style={[s.badge, { backgroundColor: st.bg }]} testID={`form-version-action-${v.version}`}>
              <Text style={[s.badgeText, { color: st.fg }]}>{(v.action || "saved").toUpperCase()}</Text>
            </View>
            <Text style={s.vAt} numberOfLines={1}>{v.at ? new Date(v.at).toLocaleString() : "—"}</Text>
          </View>
        );
      })}
    </View>
  );
}

function Settings({ f }: { f: MarketingForm }) {
  const rows: [string, string][] = [
    ["Status", f.active !== false ? "Active" : "Inactive"],
    ["Slug", f.slug || "—"],
    ["Submit button", f.submit_button_label || "Submit"],
    ["Success message", f.success_message || "—"],
    ["Admin bell on submit", f.notify_admin_bell ? "On" : "Off"],
    ["Submit routing", f.submit_config?.mode || f.submit_config?.destination || "Default"],
    ["Submissions", String(f.submission_count || 0)],
  ];
  return (
    <View testID="form-settings">
      {rows.map(([k, v]) => (
        <View key={k} style={s.sRow}><Text style={s.sKey}>{k}</Text><Text style={s.sVal}>{v}</Text></View>
      ))}
    </View>
  );
}

function FormDetailBody() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [form, setForm] = useState<MarketingForm | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("preview");
  const load = useCallback(() => {
    getForm(String(id)).then(setForm).catch((e) => setErr(e?.message || "Couldn't load form."));
  }, [id]);
  useEffect(() => { load(); }, [load]);

  return (
    <View style={s.root} testID="marketing-form-detail">
      <Header
        title={form?.name || "Form"}
        subtitle={form?.slug ? `/${form.slug}` : undefined}
        back
        right={
          <Pressable onPress={() => router.push({ pathname: "/admin/marketing/forms/submissions", params: { fid: String(id) } } as any)} hitSlop={8} testID="marketing-form-submissions-btn">
            <Text style={s.link}>Submissions</Text>
          </Pressable>
        }
      />
      <View style={s.tabs}>
        {(["preview", "versions", "settings"] as Tab[]).map((t) => (
          <Pressable key={t} onPress={() => setTab(t)} style={[s.tab, tab === t && s.tabOn]} testID={`marketing-form-tab-${t}`}>
            <Text style={[s.tabText, tab === t && s.tabTextOn]}>{t[0].toUpperCase() + t.slice(1)}</Text>
          </Pressable>
        ))}
      </View>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView contentContainerStyle={{ padding: spacing.lg }} keyboardShouldPersistTaps="handled">
          {err ? <Text style={s.err} testID="marketing-form-error">{err}</Text> : !form ? (
            <ActivityIndicator color={colors.brand} testID="marketing-form-loader" />
          ) : tab === "preview" ? (
            <FormSchemaPreview fields={form.fields || []} submitLabel={form.submit_button_label} />
          ) : tab === "versions" ? (
            <Versions fid={form.id} />
          ) : (
            <Settings f={form} />
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  link: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  tabs: { flexDirection: "row", gap: 6, paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  tab: { flex: 1, minHeight: 38, alignItems: "center", justifyContent: "center", borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border },
  tabOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  tabText: { fontFamily: font.semibold, fontSize: 13, color: colors.onSurface },
  tabTextOn: { color: "#fff" },
  note: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm, backgroundColor: "#F1F5F9", borderRadius: radius.sm, padding: spacing.sm, marginBottom: spacing.md },
  noteText: { flex: 1, fontFamily: font.medium, fontSize: 12, color: colors.onSurface },
  copyBtn: { minHeight: 36, paddingHorizontal: 12, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, justifyContent: "center", backgroundColor: colors.surface },
  copyText: { fontFamily: font.semibold, fontSize: 12, color: colors.onSurface },
  vRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border },
  vNum: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface, minWidth: 36 },
  badge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 4 },
  badgeText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.4 },
  vAt: { flex: 1, textAlign: "right", fontFamily: font.regular, fontSize: 12, color: colors.muted },
  sRow: { flexDirection: "row", justifyContent: "space-between", gap: spacing.md, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border },
  sKey: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  sVal: { flex: 1, textAlign: "right", fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  err: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error },
  muted: { fontFamily: font.regular, fontSize: 12, color: colors.muted },
});
