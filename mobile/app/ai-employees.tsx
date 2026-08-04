/**
 * AI Employees list — with F2e persona avatar upload modal.
 *
 * Each row shows a camera icon overlay. On press, a modal opens with:
 *   - Current avatar preview
 *   - FileUpload (purpose=persona_avatar)
 *   - "Reset to default" button
 * On upload: PATCH /api/ai-employees/{eid} with avatar_url
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, RefreshControl, Pressable,
  Modal, Alert, ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { FileUpload } from "@/src/components/files/FileUpload";
import { AuthedImage } from "@/src/components/files/AuthedImage";
import type { FileRecord } from "@/src/api/files";
import AIAvatar from "@/src/components/ai/AIAvatar";

function buildPersonaAvatarUrl(fileId: string): string {
  if (!fileId) return "";
  return `/api/files/${fileId}/download`;
}

function defaultPersonaAvatarUrl(personaKey: string): string {
  if (!personaKey) return "";
  return `/avatars/personas/${personaKey}.jpg`;
}

/** Extract fileId from avatar_url of shape /api/files/{id}/download */
function extractFileId(avatarUrl?: string): string | null {
  if (!avatarUrl) return null;
  const m = avatarUrl.match(/^\/api\/files\/([^/?#]+)\/download/);
  return m ? m[1] : null;
}

/**
 * Phase 50.1 · Feb-2026 — resolve an ``avatar_url`` (either a signed
 * upload path like ``/api/files/{id}/download`` or a default seed
 * path like ``/avatars/personas/{key}.jpg``) into a fully-qualified
 * URL the React-Native ``<Image>`` loader can fetch. Returns
 * ``undefined`` when the input is null / empty so the ``<AIAvatar>``
 * component falls back to a Lottie-only render.
 */
function resolveAvatarSrc(avatarUrl?: string, fileId?: string | null): string | undefined {
  const host = (process.env.EXPO_PUBLIC_BACKEND_URL || "").replace(/\/$/, "");
  if (fileId) return `${host}/api/files/${fileId}/download`;
  if (!avatarUrl) return undefined;
  if (/^https?:\/\//i.test(avatarUrl)) return avatarUrl;
  return `${host}${avatarUrl.startsWith("/") ? "" : "/"}${avatarUrl}`;
}

export default function AIEmployees() {
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // F2e: avatar upload modal target
  const [avatarTarget, setAvatarTarget] = useState<any | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems(await api.get("/ai-employees"));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // ─── F2e: PATCH avatar_url ───
  const patchAvatar = async (eid: string, avatar_url: string) => {
    setSaving(true);
    try {
      await api.patch(`/ai-employees/${eid}`, { avatar_url });
      // Optimistic update in the list
      setItems((prev) =>
        prev.map((r) => (r.id === eid ? { ...r, avatar_url } : r)),
      );
      Alert.alert("Success", "Avatar updated.");
      setAvatarTarget(null);
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Failed to update avatar.");
    } finally {
      setSaving(false);
    }
  };

  const onUploaded = (payload: FileRecord) => {
    const id = payload?.id || (payload as any)?.file_id;
    if (!id) {
      Alert.alert("Error", "Upload succeeded but no file id returned.");
      return;
    }
    if (!avatarTarget) return;
    const eid = avatarTarget.id || avatarTarget.employee_id || avatarTarget.eid || avatarTarget.key;
    patchAvatar(eid, buildPersonaAvatarUrl(id));
  };

  const onReset = () => {
    if (!avatarTarget) return;
    const eid = avatarTarget.id || avatarTarget.employee_id || avatarTarget.eid || avatarTarget.key;
    const key = avatarTarget.key;
    patchAvatar(eid, defaultPersonaAvatarUrl(key));
  };

  return (
    <View style={styles.root}>
      <Header title="AI Employees" back subtitle="Your always-on AI team" />
      {loading ? (
        <Loading testID="ai-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="sparkles-outline" title="No AI employees" testID="ai-empty" />
      ) : (
        <FlatList
          testID="ai-employees-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); load(); }}
            />
          }
          renderItem={({ item }) => {
            const fileId = extractFileId(item.avatar_url);
            return (
              <Pressable
                style={styles.card}
                onPress={() =>
                  router.push({
                    pathname: "/ai-chat/[id]",
                    params: { id: item.id, name: item.name, role: item.role },
                  })
                }
                testID={`ai-employee-${item.id}`}
              >
                {/* Phase 50 · Feb-2026 — animated Lottie avatar replaces
                    the flat brand-color circle. When the persona has a
                    custom uploaded ``avatar_url``, ``<AIAvatar>`` layers
                    the image on top of the idle Lottie loop.
                    Phase 50.1 · avatar_url resolver — prepends the
                    backend host for app-relative paths (``/avatars/...``,
                    ``/api/files/...``) so both default seed images and
                    uploaded files render on the native app. Falls back
                    to Lottie-only when ``avatar_url`` is null / empty. */}
                <View>
                  <AIAvatar
                    size={52}
                    src={resolveAvatarSrc(item.avatar_url, fileId)}
                    testID={`ai-lottie-avatar-${item.key || item.id}`}
                  />
                  <Pressable
                    style={styles.cameraOverlay}
                    onPress={() => setAvatarTarget(item)}
                    hitSlop={6}
                    testID={`persona-avatar-upload-${item.key || item.id}`}
                  >
                    <Ionicons name="camera" size={10} color={colors.onSurface} />
                  </Pressable>
                </View>

                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Text style={styles.name}>{item.name}</Text>
                    <View style={styles.aiBadge}>
                      <Ionicons name="sparkles" size={10} color={colors.brand} />
                      <Text style={styles.aiBadgeText}>AI</Text>
                    </View>
                  </View>
                  <Text style={styles.role}>{item.role}</Text>
                  <Text style={styles.tagline}>{item.tagline}</Text>
                </View>
                <Ionicons name="chevron-forward" size={20} color={colors.muted} />
              </Pressable>
            );
          }}
        />
      )}

      {/* F2e: Avatar upload modal */}
      <Modal
        visible={!!avatarTarget}
        transparent
        animationType="slide"
        onRequestClose={() => setAvatarTarget(null)}
        testID="persona-avatar-upload-modal"
      >
        <Pressable
          style={styles.modalOverlay}
          onPress={() => setAvatarTarget(null)}
        >
          <Pressable
            style={styles.modalContent}
            onPress={() => {}}
          >
            <ScrollView>
              {/* Header */}
              <View style={styles.modalHeader}>
                <View style={styles.modalHeaderLeft}>
                  {avatarTarget && extractFileId(avatarTarget.avatar_url) ? (
                    <AuthedImage
                      fileId={extractFileId(avatarTarget.avatar_url)!}
                      size={56}
                      style={{ borderRadius: 28 }}
                    />
                  ) : (
                    <View style={[styles.avatar, { width: 56, height: 56, borderRadius: 28 }]}>
                      <Ionicons
                        name={avatarTarget?.icon as any || "sparkles"}
                        size={24}
                        color="#fff"
                      />
                    </View>
                  )}
                  <View style={{ flex: 1 }}>
                    <Text style={styles.modalTitle}>
                      {avatarTarget?.name || "Persona"}
                    </Text>
                    <Text style={styles.modalSubtitle}>
                      Upload a new avatar image
                    </Text>
                  </View>
                </View>
                <Pressable
                  onPress={() => setAvatarTarget(null)}
                  hitSlop={8}
                  testID="persona-avatar-close"
                >
                  <Ionicons name="close" size={22} color={colors.muted} />
                </Pressable>
              </View>

              {/* Upload area */}
              <FileUpload
                purpose="persona_avatar"
                linkedEntityType="persona"
                linkedEntityId={avatarTarget?.key}
                accept="image/png,image/jpeg,image/webp"
                multiple={false}
                maxFiles={1}
                onUploaded={onUploaded}
                buttonLabel="Upload Avatar"
                disabled={saving}
              />

              <Text style={styles.modalHint}>
                Recommended: 200×200px square, under 5 MB.
              </Text>

              {/* Footer */}
              <View style={styles.modalFooter}>
                <Pressable
                  onPress={onReset}
                  disabled={saving}
                  testID="persona-avatar-reset"
                  style={styles.resetBtn}
                >
                  <Text style={styles.resetText}>Reset to default</Text>
                </Pressable>
                <Pressable
                  onPress={() => setAvatarTarget(null)}
                  style={styles.closeBtn}
                  testID="persona-avatar-close-btn"
                >
                  <Text style={styles.closeBtnText}>Close</Text>
                </Pressable>
              </View>
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
  },
  avatar: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: colors.brand,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarImg: { borderRadius: 26 },
  cameraOverlay: {
    position: "absolute",
    bottom: -2,
    right: -2,
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    elevation: 2,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.1,
    shadowRadius: 2,
  },
  name: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  aiBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 2,
    backgroundColor: colors.brandTertiary,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: radius.pill,
  },
  aiBadgeText: { fontFamily: font.bold, fontSize: 9, color: colors.brand },
  role: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.brand,
    marginTop: 1,
  },
  tagline: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 2,
  },
  // Modal styles
  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(15,23,42,0.55)",
    justifyContent: "flex-end",
  },
  modalContent: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    padding: spacing.lg,
    maxHeight: "80%",
  },
  modalHeader: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    marginBottom: spacing.lg,
  },
  modalHeaderLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    flex: 1,
  },
  modalTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
  },
  modalSubtitle: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 2,
  },
  modalHint: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: spacing.sm,
  },
  modalFooter: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: spacing.xl,
    paddingBottom: spacing.lg,
  },
  resetBtn: { padding: spacing.sm },
  resetText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  closeBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
  },
  closeBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
});
