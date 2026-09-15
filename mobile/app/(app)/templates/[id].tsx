/**
 * Templates Library — Phase 3 · Mobile Fill Page
 *
 * Schema-driven form with autosave + offline draft support.
 * Mirrors the web TemplateFillPage, plus:
 *   - Writes local snapshot BEFORE each PATCH
 *   - Queues failed PATCHes for replay on reconnect
 *   - Merges local-over-server on load when local is newer
 *   - Blocks Finalize when pending sync entries exist
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Linking } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api, ApiNetworkError, api_base } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useOnline } from "@/src/offline";
import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import TemplateFieldRenderer from "@/src/components/templates/TemplateFieldRenderer";
import TemplateStatusPill from "@/src/components/templates/TemplateStatusPill";
import { showConfirm } from "@/src/components/ConfirmModal";
import {
  writeSnapshot,
  clearSnapshot,
  enqueuePending,
  hasPendingForInstance,
  mergeLocalOverServer,
  removePending,
  flushPendingTemplateDrafts,
} from "@/src/utils/offlineTemplateDrafts";
import AppTextInput from "@/src/components/ui/AppTextInput";

const AUTOSAVE_DEBOUNCE_MS = 1000;
const AUTOSAVE_INTERVAL_MS = 15000;

const CATEGORY_LABEL: Record<string, string> = {
  pricing_money: "Pricing & Money",
  operations_checklists: "Ops & Checklists",
  chemicals_chemistry: "Chemistry",
  documents: "Documents",
};

export default function TemplateFillScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const online = useOnline();

  const [instance, setInstance] = useState<any>(null);
  const [definition, setDefinition] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saveState, setSaveState] = useState<
    "idle" | "saving" | "saved" | "error" | "offline_queued"
  >("idle");
  const [error, setError] = useState("");
  const [hasPending, setHasPending] = useState(false);
  const [loadedLocalEdits, setLoadedLocalEdits] = useState(false);

  const dirtyRef = useRef(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const instanceRef = useRef<any>(null);
  instanceRef.current = instance;

  const isFinalized = instance?.status === "finalized";
  const readOnly = isFinalized;

  const currentUserName = useMemo(() => {
    if (!user) return "";
    return user.name || user.email || "";
  }, [user]);

  // Check pending state
  const refreshPending = useCallback(async () => {
    if (!id) return;
    const pending = await hasPendingForInstance(id);
    setHasPending(pending);
  }, [id]);

  // Load instance + definition, with local merge
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setLoadedLocalEdits(false);
    try {
      const inst = await api.get(`/templates/instances/${id}`);
      // Merge local snapshot if newer
      const { merged, hadLocalEdits } = await mergeLocalOverServer(inst);
      setInstance(merged);
      instanceRef.current = merged;
      if (hadLocalEdits) {
        setLoadedLocalEdits(true);
        // Mark dirty so autosave pushes merged values
        dirtyRef.current = true;
      }
      const defn = await api.get(
        `/templates/definitions/${encodeURIComponent(inst.template_code)}`
      );
      setDefinition(defn);
      await refreshPending();
    } catch (e: any) {
      setError(e.message || "Failed to load template.");
    } finally {
      setLoading(false);
    }
  }, [id, refreshPending]);

  useEffect(() => {
    load();
  }, [load]);

  // Autosave — writes local snapshot BEFORE PATCH, queues on network failure
  const flushSave = useCallback(async () => {
    const inst = instanceRef.current;
    if (!inst || !dirtyRef.current || inst.status === "finalized") return;
    dirtyRef.current = false;
    setSaveState("saving");

    const title = inst.title || "";
    const values = inst.values || {};

    // 1. Write local snapshot FIRST (before network call)
    await writeSnapshot({
      instance_id: inst.id,
      title,
      values,
      dirty_since: new Date().toISOString(),
    });

    // 2. Attempt PATCH
    try {
      const updated = await api.patch(`/templates/instances/${inst.id}`, {
        title,
        values,
      });
      instanceRef.current = updated;
      setInstance((prev: any) => (prev ? { ...prev, ...updated } : updated));
      // 3. On success — clear snapshot + remove from pending queue
      await clearSnapshot(inst.id);
      await removePending(inst.id);
      setHasPending(false);
      setSaveState("saved");
    } catch (e: any) {
      if (e instanceof ApiNetworkError) {
        // 4. Network failure — enqueue for later replay
        console.log(`[TemplateFill] offline — queued ${inst.id}`);
        await enqueuePending({
          instance_id: inst.id,
          title,
          values,
          ts: new Date().toISOString(),
        });
        setHasPending(true);
        setSaveState("offline_queued");
      } else {
        setSaveState("error");
        setError(e.message || "Autosave failed.");
        dirtyRef.current = true;
      }
    }
  }, []);

  const scheduleSave = useCallback(() => {
    dirtyRef.current = true;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => flushSave(), AUTOSAVE_DEBOUNCE_MS);
  }, [flushSave]);

  // 15s safety net
  useEffect(() => {
    intervalRef.current = setInterval(() => {
      if (dirtyRef.current) flushSave();
    }, AUTOSAVE_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      // Flush on unmount
      flushSave();
    };
  }, [flushSave]);

  // Auto-flush pending queue when coming back online
  useEffect(() => {
    if (online && hasPending) {
      flushPendingTemplateDrafts().then(async (res) => {
        if (res.synced > 0) {
          console.log(`[TemplateFill] flushed ${res.synced} pending drafts`);
          await refreshPending();
          // Reload server state after successful sync
          load();
        }
      }).catch(() => {});
    }
  }, [online, hasPending, refreshPending, load]);

  // Value handlers
  const setValue = (key: string, val: any) => {
    if (readOnly) return;
    setInstance((prev: any) => ({
      ...prev,
      values: { ...(prev?.values || {}), [key]: val },
    }));
    scheduleSave();
  };

  const setTitle = (val: string) => {
    if (readOnly) return;
    setInstance((prev: any) => ({ ...prev, title: val }));
    scheduleSave();
  };

  // Actions
  const doFinalize = async () => {
    // Block finalize when pending sync entries exist
    const pending = await hasPendingForInstance(id!);
    if (pending) {
      Alert.alert(
        "Unsynced Changes",
        "You have unsynced changes. Reconnect to sync before finalizing.",
        [{ text: "OK" }]
      );
      return;
    }
    Alert.alert(
      "Finalize this template?",
      "Once finalized, the form fields become read-only. You can still download a PDF or duplicate it.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Finalize",
          onPress: async () => {
            try {
              await flushSave();
              const updated = await api.post(`/templates/instances/${id}/finalize`);
              setInstance(updated);
              // Clear local snapshot on finalize
              await clearSnapshot(id!);
            } catch (e: any) {
              Alert.alert("Error", e.message || "Could not finalize.");
            }
          },
        },
      ]
    );
  };

  const doDuplicate = async () => {
    try {
      await flushSave();
      const dup = await api.post(`/templates/instances/${id}/duplicate`);
      router.replace(`/(app)/templates/${dup.id}` as any);
    } catch (e: any) {
      Alert.alert("Error", e.message || "Could not duplicate.");
    }
  };

  const doDelete = () => {
    showConfirm({
      title: "Delete this template?",
      message: "This will permanently remove this instance.",
      confirmLabel: "Delete",
      confirmStyle: "destructive",
      onConfirm: async () => {
        try {
          await api.del(`/templates/instances/${id}`);
          router.back();
        } catch (e: any) {
          Alert.alert("Error", e.message || "Could not delete.");
        }
      },
    });
  };

  const doDownload = () => {
    const url = `${api_base()}/templates/instances/${id}/pdf`;
    Alert.alert("Download PDF", "PDF will open in your browser.", [
      { text: "Cancel", style: "cancel" },
      { text: "Open", onPress: () => Linking.openURL(url) },
    ]);
  };

  // Render
  if (loading) {
    return (
      <View style={styles.root} testID="template-fill-loading">
        <Header title="Template" back />
        <View style={styles.center}>
          <ActivityIndicator size="large" color={colors.brand} />
        </View>
      </View>
    );
  }

  if (error && !instance) {
    return (
      <View style={styles.root} testID="template-fill-error">
        <Header title="Template" back />
        <View style={styles.errorContainer}>
          <View style={styles.errorBox}>
            <Text style={styles.errorText}>{error}</Text>
          </View>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root} testID="template-fill-page">
      <Header
        title={instance?.title || "Template"}
        back
        right={
          <View style={styles.headerActions}>
            {/* Offline indicator in header */}
            {(hasPending || saveState === "offline_queued") && (
              <View style={styles.offlinePill} testID="template-fill-offline-indicator">
                <Ionicons name="cloud-offline-outline" size={14} color="#A16207" />
                <Text style={styles.offlinePillText}>Offline — will sync</Text>
              </View>
            )}
            {!isFinalized && (
              <TouchableOpacity
                onPress={doFinalize}
                style={styles.headerBtn}
                testID="template-fill-finalize-btn"
              >
                <Ionicons name="checkmark-circle-outline" size={20} color={colors.brand} />
              </TouchableOpacity>
            )}
            <TouchableOpacity
              onPress={doDuplicate}
              style={styles.headerBtn}
              testID="template-fill-duplicate-btn"
            >
              <Ionicons name="copy-outline" size={20} color={colors.onSurfaceSecondary} />
            </TouchableOpacity>
            <TouchableOpacity
              onPress={doDownload}
              style={styles.headerBtn}
              testID="template-fill-download-btn"
            >
              <Ionicons name="download-outline" size={20} color={colors.brand} />
            </TouchableOpacity>
            <TouchableOpacity
              onPress={doDelete}
              style={styles.headerBtn}
              testID="template-fill-delete-btn"
            >
              <Ionicons name="trash-outline" size={20} color={colors.error} />
            </TouchableOpacity>
          </View>
        }
      />

      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={{ flex: 1 }}
      >
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
        >
          {/* Header card */}
          <View style={styles.card} testID="template-fill-header">
            <AppTextInput
              value={instance?.title || ""}
              onChangeText={setTitle}
              editable={!readOnly}
              style={[styles.titleInput, readOnly && styles.titleInputReadonly]}
              placeholder="Untitled template"
              placeholderTextColor={colors.muted}
              testID="template-fill-title-input"
            />
            <View style={styles.metaRow}>
              {definition?.category && (
                <View style={styles.catBadge}>
                  <Text style={styles.catBadgeText}>
                    {CATEGORY_LABEL[definition.category] || definition.category}
                  </Text>
                </View>
              )}
              <TemplateStatusPill status={instance?.status} />
              <SaveIndicator state={saveState} error={error} />
            </View>
          </View>

          {/* Finalized banner */}
          {isFinalized && (
            <View style={styles.finalizedBanner} testID="template-fill-finalized-banner">
              <Ionicons name="lock-closed-outline" size={16} color="#166534" />
              <Text style={styles.finalizedText}>
                This template is finalized.{" "}
                <Text style={{ fontFamily: font.bold }}>Duplicate</Text> it to make
                further changes.
              </Text>
            </View>
          )}

          {/* Local-edits-merged toast */}
          {loadedLocalEdits && (
            <View style={styles.localEditsBanner} testID="template-fill-local-edits-banner">
              <Ionicons name="sync-outline" size={16} color="#A16207" />
              <Text style={styles.localEditsText}>
                Loaded unsynced local edits — will sync when online.
              </Text>
              <TouchableOpacity
                onPress={() => setLoadedLocalEdits(false)}
                hitSlop={8}
                testID="template-fill-local-edits-dismiss"
              >
                <Ionicons name="close" size={16} color="#A16207" />
              </TouchableOpacity>
            </View>
          )}

          {/* Schema sections */}
          {definition?.schema?.map((section: any, si: number) => (
            <View
              key={(section.title || "") + si}
              style={styles.card}
              testID={`template-fill-section-${si}`}
            >
              {section.title ? (
                <Text style={styles.sectionTitle}>{section.title}</Text>
              ) : null}
              {(section.fields || []).map((field: any, fi: number) => (
                <View key={(field.key || "") + fi} style={styles.fieldWrap}>
                  <TemplateFieldRenderer
                    field={field}
                    value={instance?.values?.[field.key]}
                    onChange={(v: any) => setValue(field.key, v)}
                    disabled={readOnly}
                    currentUserName={currentUserName}
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

function SaveIndicator({
  state,
  error,
}: {
  state: string;
  error: string;
}) {
  if (state === "saving") {
    return (
      <View style={styles.saveRow} testID="template-save-indicator">
        <ActivityIndicator size="small" color={colors.onSurfaceSecondary} />
        <Text style={styles.saveText}>Saving…</Text>
      </View>
    );
  }
  if (state === "offline_queued") {
    return (
      <View style={styles.saveRow} testID="template-save-indicator-offline">
        <Ionicons name="cloud-offline-outline" size={14} color="#A16207" />
        <Text style={[styles.saveText, { color: "#A16207" }]}>Saved locally</Text>
      </View>
    );
  }
  if (state === "error") {
    return (
      <View style={styles.saveRow} testID="template-save-indicator-error">
        <Ionicons name="alert-circle-outline" size={14} color={colors.error} />
        <Text style={[styles.saveText, { color: colors.error }]}>
          {error || "Save failed"}
        </Text>
      </View>
    );
  }
  if (state === "saved") {
    return (
      <View style={styles.saveRow} testID="template-save-indicator-saved">
        <Ionicons name="checkmark-circle" size={14} color={colors.success} />
        <Text style={[styles.saveText, { color: colors.success }]}>Saved</Text>
      </View>
    );
  }
  return null;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  errorContainer: { padding: spacing.lg },
  errorBox: {
    backgroundColor: "#FEE2E2",
    borderRadius: radius.sm,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  errorText: {
    fontSize: fontSize.sm,
    fontFamily: font.regular,
    color: colors.error,
  },
  headerActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  headerBtn: {
    padding: 6,
    borderRadius: radius.sm,
  },
  scroll: { flex: 1 },
  scrollContent: { padding: spacing.lg, paddingBottom: 60 },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  titleInput: {
    fontSize: fontSize["2xl"],
    fontFamily: font.bold,
    color: colors.onSurface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    paddingBottom: 6,
    marginBottom: 8,
  },
  titleInputReadonly: {
    borderBottomColor: "transparent",
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap",
  },
  catBadge: {
    backgroundColor: colors.brandTertiary,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
  },
  catBadgeText: {
    fontSize: 10,
    fontFamily: font.bold,
    color: colors.onBrandTertiary,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  saveRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  saveText: {
    fontSize: 11,
    fontFamily: font.regular,
    color: colors.onSurfaceSecondary,
  },
  finalizedBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "#DCFCE7",
    borderWidth: 1,
    borderColor: "#86EFAC",
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 10,
    marginBottom: spacing.md,
  },
  finalizedText: {
    fontSize: fontSize.sm,
    fontFamily: font.regular,
    color: "#166534",
    flex: 1,
  },
  sectionTitle: {
    fontSize: fontSize.lg,
    fontFamily: font.bold,
    color: colors.onSurface,
    marginBottom: spacing.md,
  },
  fieldWrap: {
    marginBottom: spacing.md,
  },
  offlinePill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#FEF9C3",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 999,
  },
  offlinePillText: {
    fontSize: 10,
    fontFamily: font.bold,
    color: "#A16207",
  },
  localEditsBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "#FEF9C3",
    borderWidth: 1,
    borderColor: "#FDE68A",
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 10,
    marginBottom: spacing.md,
  },
  localEditsText: {
    fontSize: fontSize.sm,
    fontFamily: font.regular,
    color: "#A16207",
    flex: 1,
  },
});
