/**
 * Templates Library — Phase 3 (Mobile) · fill screen (schema-driven).
 * Mirrors web `TemplateFillPage.jsx` + offline draft support
 * (see `useTemplateDraft`).
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, KeyboardAvoidingView, Platform } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/auth";
import { useOnline } from "@/src/offline";
import { Header } from "@/src/components/widgets";
import { useToast } from "@/src/components/ToastProvider";
import { showConfirm } from "@/src/components/ConfirmModal";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import TemplateFieldRenderer from "@/src/components/templates/TemplateFieldRenderer";
import TemplateStatusPill from "@/src/components/templates/TemplateStatusPill";
import OfflineIndicator from "@/src/components/templates/OfflineIndicator";
import { CATEGORY_LABEL, duplicateInstance, deleteInstance, downloadPdf } from "@/src/api/templates";
import { clearSnapshot, removePending, clearInstanceBundle } from "@/src/utils/offlineTemplateDrafts";
import { useTemplateDraft, SaveState } from "./useTemplateDraft";

const MINE = "/(app)/templates?tab=mine" as any;

export function SaveIndicator({ state, lastSaved, error }: { state: SaveState; lastSaved: Date | null; error: string }) {
  if (state === "saving") {
    return <View style={styles.saveRow} testID="template-save-indicator"><ActivityIndicator size="small" color={colors.onSurfaceSecondary} /><Text style={styles.saveText}>Saving…</Text></View>;
  }
  if (state === "error") {
    return <View style={styles.saveRow} testID="template-save-indicator-error"><Ionicons name="alert-circle-outline" size={14} color={colors.error} /><Text style={[styles.saveText, { color: colors.error }]}>{error || "Save failed"}</Text></View>;
  }
  if (state === "saved" && lastSaved) {
    return <View style={styles.saveRow} testID="template-save-indicator-saved"><Ionicons name="checkmark-circle" size={14} color={colors.success} /><Text style={[styles.saveText, { color: colors.success }]}>Saved {lastSaved.toLocaleTimeString()}</Text></View>;
  }
  return null;
}

function Banner({ tone, icon, text, testID, onClose }: { tone: "ok" | "warn" | "err"; icon: any; text: string; testID: string; onClose?: () => void }) {
  const t = TONES[tone];
  return (
    <View style={[styles.banner, { backgroundColor: t.bg, borderColor: t.border }]} testID={testID}>
      <Ionicons name={icon} size={16} color={t.fg} />
      <Text style={[styles.bannerText, { color: t.fg }]}>{text}</Text>
      {onClose ? <TouchableOpacity onPress={onClose} hitSlop={10} testID={`${testID}-dismiss`}><Ionicons name="close" size={16} color={t.fg} /></TouchableOpacity> : null}
    </View>
  );
}
const TONES = {
  ok: { bg: "#DCFCE7", border: "#86EFAC", fg: "#166534" },
  warn: { bg: "#FEF9C3", border: "#FDE68A", fg: "#A16207" },
  err: { bg: "#FEE2E2", border: "#FCA5A5", fg: "#991B1B" },
};

function HeaderBtn({ icon, color, onPress, testID, label, busy }: any) {
  return (
    <TouchableOpacity onPress={onPress} style={styles.headerBtn} testID={testID} accessibilityLabel={label} disabled={busy}>
      {busy ? <ActivityIndicator size="small" color={color} /> : <Ionicons name={icon} size={21} color={color} />}
    </TouchableOpacity>
  );
}

export default function TemplateFillScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth() as any;
  const online = useOnline();
  const { showToast } = useToast();
  const d = useTemplateDraft(String(id), online);
  const [blocked, setBlocked] = useState("");
  const [pdfBusy, setPdfBusy] = useState(false);

  const isFinalized = d.instance?.status === "finalized";
  const userName = user?.full_name || user?.name || user?.email || "";
  const requireOnline = (what: string) => {
    if (online) return true;
    showToast(`${what} needs a connection.`, "info");
    return false;
  };

  const onFinalize = async () => {
    const gate = await d.canFinalize();
    if (!gate.ok) { setBlocked(gate.message || ""); showToast(gate.message || "Cannot finalize.", "error"); return; }
    setBlocked("");
    showConfirm({
      title: "Finalize this template?",
      message: "Once finalized, the form fields become read-only. You can still download a PDF or duplicate it to make edits.",
      confirmLabel: "Finalize",
      onConfirm: async () => {
        const r = await d.finalize();
        if (r.ok) showToast("Template finalized.", "success");
        else { setBlocked(r.reason === "error" ? "" : r.message || ""); showToast(r.message || "Could not finalize.", "error"); }
      },
    });
  };

  const onDuplicate = async () => {
    if (!requireOnline("Duplicating")) return;
    try {
      await d.flushSave();
      const dup = await duplicateInstance(String(id));
      router.replace(`/(app)/templates/${dup.id}` as any);
    } catch (e: any) { showToast(e.message || "Could not duplicate.", "error"); }
  };

  const onDelete = () => {
    if (!requireOnline("Deleting")) return;
    showConfirm({
      title: "Delete this template?",
      message: "This will permanently remove this instance.",
      confirmLabel: "Delete",
      confirmStyle: "destructive",
      onConfirm: async () => {
        try {
          await deleteInstance(String(id));
          await Promise.all([clearSnapshot(String(id)), removePending(String(id)), clearInstanceBundle(String(id))]);
          router.replace(MINE);
        } catch (e: any) { showToast(e.message || "Could not delete.", "error"); }
      },
    });
  };

  const onDownload = async () => {
    if (!requireOnline("Downloading a PDF")) return;
    setPdfBusy(true);
    try { await downloadPdf(String(id), d.instance?.title || d.instance?.template_code); }
    catch (e: any) { showToast(e.message || "Could not generate PDF.", "error"); }
    finally { setPdfBusy(false); }
  };

  if (d.loading || d.loadError) {
    return (
      <View style={styles.root} testID={d.loadError ? "template-fill-error" : "template-fill-loading"}>
        <Header title="Template" back />
        {d.loadError ? (
          <View style={styles.pad}><Banner tone="err" icon="alert-circle-outline" text={d.loadError} testID="template-fill-error-banner" /></View>
        ) : (
          <View style={styles.center}><ActivityIndicator size="large" color={colors.brand} /></View>
        )}
      </View>
    );
  }

  return (
    <View style={styles.root} testID="template-fill-page">
      <Header
        title={d.instance?.title || "Template"}
        back
        right={
          <View style={styles.headerActions}>
            {!isFinalized && <HeaderBtn icon="checkmark-circle-outline" color={colors.brand} label="Finalize" onPress={onFinalize} testID="template-fill-finalize-btn" />}
            <HeaderBtn icon="copy-outline" color={colors.onSurfaceSecondary} label="Duplicate" onPress={onDuplicate} testID="template-fill-duplicate-btn" />
            {isFinalized && <HeaderBtn icon="download-outline" color={colors.brand} label="Download PDF" onPress={onDownload} busy={pdfBusy} testID="template-fill-download-btn" />}
            <HeaderBtn icon="trash-outline" color={colors.error} label="Delete" onPress={onDelete} testID="template-fill-delete-btn" />
          </View>
        }
      />
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={styles.flex}>
        <ScrollView style={styles.flex} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <View style={styles.card} testID="template-fill-header">
            <AppTextInput
              value={d.instance?.title || ""}
              onChangeText={d.setTitle}
              editable={!isFinalized}
              style={[styles.titleInput, isFinalized && styles.titleReadonly]}
              placeholder="Untitled template"
              testID="template-fill-title-input"
            />
            <View style={styles.metaRow}>
              {d.definition?.category ? (
                <View style={styles.catBadge} testID="template-fill-category"><Text style={styles.catText}>{CATEGORY_LABEL[d.definition.category] || d.definition.category}</Text></View>
              ) : null}
              <TemplateStatusPill status={d.instance?.status} />
              <SaveIndicator state={d.saveState} lastSaved={d.lastSaved} error={d.saveError} />
              <OfflineIndicator online={online} hasPending={d.hasPending} testID="template-fill-offline-indicator" />
            </View>
          </View>

          {isFinalized && <Banner tone="ok" icon="lock-closed-outline" text="This template is finalized. Duplicate it to make further changes." testID="template-fill-finalized-banner" />}
          {d.loadedLocalEdits && !isFinalized && (
            <Banner tone="warn" icon="sync-outline" text="Loaded unsynced local edits — will sync when online." testID="template-fill-local-edits-banner" onClose={() => d.setLoadedLocalEdits(false)} />
          )}
          {d.fromCache && <Banner tone="warn" icon="cloud-offline-outline" text="Opened from this device's saved copy. Edits will sync when you're back online." testID="template-fill-cached-banner" />}
          {blocked ? <Banner tone="err" icon="cloud-offline-outline" text={blocked} testID="template-fill-finalize-blocked" onClose={() => setBlocked("")} /> : null}

          {(d.definition?.schema || []).map((section: any, si: number) => (
            <View key={`${section.title || ""}${si}`} style={styles.card} testID={`template-fill-section-${si}`}>
              {section.title ? <Text style={styles.sectionTitle}>{section.title}</Text> : null}
              {(section.fields || []).map((field: any, fi: number) => (
                <View key={`${field.key || ""}${fi}`} style={styles.fieldWrap}>
                  <TemplateFieldRenderer
                    field={field}
                    value={d.instance?.values?.[field.key]}
                    onChange={(v: any) => d.setValue(field.key, v)}
                    disabled={isFinalized}
                    currentUserName={userName}
                  />
                </View>
              ))}
            </View>
          ))}
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  flex: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  pad: { padding: spacing.lg },
  content: { padding: spacing.lg, paddingBottom: 80 },
  headerActions: { flexDirection: "row", alignItems: "center" },
  headerBtn: { width: 40, height: 44, alignItems: "center", justifyContent: "center" },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.md },
  titleInput: { fontSize: fontSize["2xl"], fontFamily: font.bold, borderBottomWidth: 1, borderBottomColor: colors.border, paddingBottom: 6, marginBottom: 10 },
  titleReadonly: { borderBottomColor: "transparent" },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  catBadge: { backgroundColor: colors.brandTertiary, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  catText: { fontSize: 10, fontFamily: font.bold, color: colors.onBrandTertiary, textTransform: "uppercase", letterSpacing: 0.5 },
  saveRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  saveText: { fontSize: 11, fontFamily: font.regular, color: colors.onSurfaceSecondary },
  banner: { flexDirection: "row", alignItems: "center", gap: 8, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 10, marginBottom: spacing.md },
  bannerText: { flex: 1, fontSize: fontSize.sm, fontFamily: font.regular },
  sectionTitle: { fontSize: fontSize.lg, fontFamily: font.bold, color: colors.onSurface, marginBottom: spacing.md },
  fieldWrap: { marginBottom: spacing.md },
});
