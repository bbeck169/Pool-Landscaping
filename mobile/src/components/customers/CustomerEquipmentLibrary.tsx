/**
 * Phase 56.11-mobile — Customer Equipment Photo Library (mobile).
 *
 * Native mirror of `frontend/src/components/customers/CustomerEquipmentLibrary.jsx`.
 * Renders one collapsible section per equipment type from the
 * backend enum (11 types). Each section shows a 2×2 grid of up to
 * `photo_cap` (4) thumbnails; empty slots render a dashed
 * "+ Add photo" placeholder that disappears at the cap. Tapping a
 * thumbnail opens a native modal (`Sheet`) with caption + tags +
 * uploader + upload date. Admin / super_admin get a Delete button
 * in the lightbox; techs never do (defensive — the router returns
 * 403 either way).
 *
 * Upload flow reuses the same `expo-image-picker` idiom the customer
 * detail screen already uses for `shareDocument` — no new picker
 * dependency. Optional caption + tag pill selector (default
 * `general`; the two other allowed values are `algae_before` and
 * `algae_after`, matching the Phase 56.10 hook). `algae_before`
 * thumbnails get a small red "ALGAE" badge for cross-surface parity
 * with the web card.
 *
 * State is intentionally component-local; the grouped fetch is the
 * source of truth and refreshes after every mutation.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  Image,
  Pressable,
  StyleSheet,
  TextInput,
  ActivityIndicator,
  Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { PrimaryButton, Sheet } from "@/src/components/ui";

type EquipmentPhoto = {
  id: string;
  photo_url: string;
  caption?: string | null;
  tags?: string[];
  uploaded_by_name?: string | null;
  uploaded_at?: string | null;
};

type GroupedResp = {
  types: string[];
  grouped: Record<string, EquipmentPhoto[]>;
  cap: number;
  allowed_tags?: string[];
};

const ALLOWED_TAGS = ["general", "algae_before", "algae_after"] as const;
type Tag = (typeof ALLOWED_TAGS)[number];

function slugify(t: string): string {
  return t.replace(/\s+/g, "-").toLowerCase();
}

function isAdmin(user: any): boolean {
  const r = (user?.role || "").toLowerCase();
  return r === "admin" || r === "super_admin";
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "";
  return String(iso).slice(0, 10);
}

// ─── section — one per equipment type ───────────────────────────────────
function EquipmentSection({
  customerId,
  type,
  photos,
  cap,
  currentUser,
  onChange,
}: {
  customerId: string;
  type: string;
  photos: EquipmentPhoto[];
  cap: number;
  currentUser: any;
  onChange: () => Promise<void> | void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [lightbox, setLightbox] = useState<EquipmentPhoto | null>(null);
  const [uploadSheet, setUploadSheet] = useState<null | {
    dataUrl: string;
    caption: string;
    tag: Tag;
  }>(null);
  const [saving, setSaving] = useState(false);
  const slug = slugify(type);
  const remaining = Math.max(0, cap - photos.length);
  const canDelete = isAdmin(currentUser);

  // ── pick + open upload sheet ────────────────────────────────────────
  const pickPhoto = useCallback(async () => {
    setErr("");
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      setErr("Photo library permission is required.");
      return;
    }
    const res = await ImagePicker.launchImageLibraryAsync({
      base64: true,
      quality: 0.6,
    });
    if (res.canceled || !res.assets?.[0]?.base64) return;
    const asset = res.assets[0];
    setUploadSheet({
      dataUrl: `data:image/jpeg;base64,${asset.base64}`,
      caption: "",
      tag: "general",
    });
  }, []);

  // ── submit upload ───────────────────────────────────────────────────
  const submitUpload = useCallback(async () => {
    if (!uploadSheet) return;
    setSaving(true);
    setErr("");
    try {
      await api.post(`/customers/${customerId}/equipment-photos`, {
        equipment_type: type,
        photo: uploadSheet.dataUrl,
        caption: uploadSheet.caption.trim() || undefined,
        tags: [uploadSheet.tag],
      });
      setUploadSheet(null);
      await onChange();
    } catch (e: any) {
      const msg: string = e?.message || "Upload failed";
      // Backend 400 mentions the cap → surface inline.
      setErr(msg);
    } finally {
      setSaving(false);
    }
  }, [uploadSheet, customerId, type, onChange]);

  // ── delete (admin only) ─────────────────────────────────────────────
  const handleDelete = useCallback(
    (photo: EquipmentPhoto) => {
      Alert.alert(
        "Delete photo?",
        "This permanently removes the photo from the customer's equipment library.",
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Delete",
            style: "destructive",
            onPress: async () => {
              try {
                await api.del(
                  `/customers/${customerId}/equipment-photos/${photo.id}`
                );
                setLightbox(null);
                await onChange();
              } catch (e: any) {
                const status = e?.status;
                if (status === 403) {
                  Alert.alert("Not authorized", "Only admins can delete equipment photos.");
                } else {
                  Alert.alert("Delete failed", e?.message || "Please try again.");
                }
              }
            },
          },
        ]
      );
    },
    [customerId, onChange]
  );

  return (
    <View
      style={styles.section}
      testID={`mobile-equipment-section-${slug}`}
    >
      {/* Section header (tap to expand). */}
      <Pressable
        onPress={() => setOpen((v) => !v)}
        style={styles.sectionHeader}
        testID={`mobile-equipment-section-toggle-${slug}`}
      >
        <View style={styles.headerLeft}>
          <Ionicons
            name={open ? "chevron-down" : "chevron-forward"}
            size={16}
            color={colors.muted}
          />
          <Text style={styles.headerTitle}>{type}</Text>
        </View>
        <Text style={styles.headerCount}>
          {photos.length} / {cap}
        </Text>
      </Pressable>

      {open ? (
        <View style={styles.sectionBody}>
          {err ? (
            <View
              style={styles.errBox}
              testID={`mobile-equipment-section-error-${slug}`}
            >
              <Ionicons name="alert-circle" size={12} color="#991B1B" />
              <Text style={styles.errText}>{err}</Text>
            </View>
          ) : null}

          {/* 2×2 grid: photos first, then a single add-tile if under cap. */}
          <View style={styles.grid}>
            {photos.map((p) => {
              const hasAlgae = (p.tags || []).includes("algae_before");
              return (
                <Pressable
                  key={p.id}
                  onPress={() => setLightbox(p)}
                  style={styles.tile}
                  testID={`mobile-equipment-thumbnail-${p.id}`}
                >
                  <Image
                    source={{ uri: p.photo_url }}
                    style={styles.thumb}
                    resizeMode="cover"
                  />
                  {hasAlgae ? (
                    <View style={styles.algaeBadge}>
                      <Text style={styles.algaeBadgeText}>ALGAE</Text>
                    </View>
                  ) : null}
                </Pressable>
              );
            })}

            {remaining > 0 ? (
              <Pressable
                onPress={pickPhoto}
                disabled={busy}
                style={[styles.addTile, busy ? { opacity: 0.6 } : null]}
                testID={`mobile-equipment-add-${slug}`}
              >
                <Ionicons name="camera" size={22} color={colors.muted} />
                <Text style={styles.addTileText}>
                  {busy ? "Uploading…" : "Add photo"}
                </Text>
              </Pressable>
            ) : null}
          </View>
        </View>
      ) : null}

      {/* Lightbox — full photo + caption + tags + uploader + delete. */}
      <Sheet
        visible={!!lightbox}
        onClose={() => setLightbox(null)}
        title={type}
        testID="mobile-equipment-lightbox"
      >
        {lightbox ? (
          <View style={{ gap: spacing.md }}>
            <Image
              source={{ uri: lightbox.photo_url }}
              style={styles.lightboxImg}
              resizeMode="contain"
            />
            {lightbox.caption ? (
              <Text style={styles.lightboxCaption}>{lightbox.caption}</Text>
            ) : null}
            <Text style={styles.lightboxMeta}>
              Uploaded by {lightbox.uploaded_by_name || "Unknown"}
              {lightbox.uploaded_at ? ` · ${fmtDate(lightbox.uploaded_at)}` : ""}
            </Text>
            {lightbox.tags && lightbox.tags.length > 0 ? (
              <View style={styles.tagRow}>
                {lightbox.tags.map((t) => (
                  <View key={t} style={styles.tagChip}>
                    <Text style={styles.tagChipText}>{t}</Text>
                  </View>
                ))}
              </View>
            ) : null}
            {canDelete ? (
              <Pressable
                onPress={() => handleDelete(lightbox)}
                style={styles.deleteBtn}
                testID="mobile-equipment-delete-btn"
              >
                <Ionicons name="trash-outline" size={16} color="#fff" />
                <Text style={styles.deleteBtnText}>Delete</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
      </Sheet>

      {/* Upload sheet — caption + tag selector before POST. */}
      <Sheet
        visible={!!uploadSheet}
        onClose={() => (saving ? null : setUploadSheet(null))}
        title={`Add ${type} photo`}
        testID={`mobile-equipment-upload-sheet-${slug}`}
      >
        {uploadSheet ? (
          <View style={{ gap: spacing.md }}>
            <Image
              source={{ uri: uploadSheet.dataUrl }}
              style={styles.previewImg}
              resizeMode="cover"
            />
            <Text style={styles.inputLabel}>Caption (optional)</Text>
            <TextInput
              value={uploadSheet.caption}
              onChangeText={(v) =>
                setUploadSheet((s) => (s ? { ...s, caption: v.slice(0, 120) } : s))
              }
              placeholder="Short note about this photo (max 120)"
              placeholderTextColor={colors.muted}
              style={styles.input}
              testID={`mobile-equipment-upload-caption-${slug}`}
            />
            <Text style={styles.inputLabel}>Tag</Text>
            <View style={styles.tagPickerRow}>
              {ALLOWED_TAGS.map((t) => {
                const active = uploadSheet.tag === t;
                return (
                  <Pressable
                    key={t}
                    onPress={() =>
                      setUploadSheet((s) => (s ? { ...s, tag: t } : s))
                    }
                    style={[
                      styles.tagPill,
                      active ? styles.tagPillActive : null,
                    ]}
                    testID={`mobile-equipment-upload-tag-${slug}-${t}`}
                  >
                    <Text
                      style={[
                        styles.tagPillText,
                        active ? styles.tagPillTextActive : null,
                      ]}
                    >
                      {t}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
            {err ? <Text style={styles.errTextInline}>{err}</Text> : null}
            <PrimaryButton
              title="Upload photo"
              icon="cloud-upload-outline"
              onPress={submitUpload}
              loading={saving}
              testID={`mobile-equipment-upload-submit-${slug}`}
            />
          </View>
        ) : null}
      </Sheet>
    </View>
  );
}

// ─── outer container ────────────────────────────────────────────────────
export default function CustomerEquipmentLibrary({
  customerId,
}: {
  customerId: string;
}) {
  const { user } = useAuth();
  const [state, setState] = useState<{
    types: string[];
    grouped: Record<string, EquipmentPhoto[]>;
    cap: number;
    loading: boolean;
    error: string;
  }>({ types: [], grouped: {}, cap: 4, loading: true, error: "" });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: "" }));
    try {
      const res: GroupedResp = await api.get(
        `/customers/${customerId}/equipment-photos`
      );
      setState({
        types: res.types || [],
        grouped: res.grouped || {},
        cap: res.cap || 4,
        loading: false,
        error: "",
      });
    } catch (e: any) {
      setState((s) => ({
        ...s,
        loading: false,
        error: e?.message || "Failed to load equipment photos.",
      }));
    }
  }, [customerId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <View testID="mobile-customer-equipment-library">
      <Text style={styles.legend}>
        Up to {state.cap} photos per equipment type. Techs upload; admins delete.
      </Text>
      {state.loading ? (
        <ActivityIndicator color={colors.brand} style={{ marginTop: spacing.md }} />
      ) : state.error ? (
        <Text style={styles.errText}>{state.error}</Text>
      ) : (
        state.types.map((t) => (
          <EquipmentSection
            key={t}
            customerId={customerId}
            type={t}
            photos={state.grouped[t] || []}
            cap={state.cap}
            currentUser={user}
            onChange={load}
          />
        ))
      )}
    </View>
  );
}

// ─── styles ─────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  legend: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginBottom: spacing.sm,
  },
  section: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    marginBottom: spacing.sm,
    overflow: "hidden",
  },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    backgroundColor: colors.surfaceSecondary,
  },
  headerLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flex: 1,
  },
  headerTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  headerCount: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  sectionBody: {
    padding: spacing.md,
  },
  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  tile: {
    width: "48%",
    aspectRatio: 1,
    borderRadius: radius.sm,
    overflow: "hidden",
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  thumb: {
    width: "100%",
    height: "100%",
  },
  algaeBadge: {
    position: "absolute",
    top: 4,
    left: 4,
    backgroundColor: "#B91C1C",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: radius.sm,
  },
  algaeBadgeText: {
    fontFamily: font.bold,
    fontSize: 10,
    color: "#fff",
  },
  addTile: {
    width: "48%",
    aspectRatio: 1,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 2,
    borderStyle: "dashed",
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  addTileText: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    padding: spacing.sm,
    marginBottom: spacing.sm,
    backgroundColor: "#FEE2E2",
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: "#FCA5A5",
  },
  errText: {
    fontFamily: font.regular,
    fontSize: 12,
    color: "#991B1B",
    flex: 1,
  },
  errTextInline: {
    fontFamily: font.regular,
    fontSize: 12,
    color: "#991B1B",
  },
  lightboxImg: {
    width: "100%",
    aspectRatio: 1,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceSecondary,
  },
  lightboxCaption: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  lightboxMeta: {
    fontFamily: font.regular,
    fontSize: 12,
    color: colors.muted,
  },
  tagRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  tagChip: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  tagChipText: {
    fontFamily: font.medium,
    fontSize: 11,
    color: colors.muted,
  },
  deleteBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    borderRadius: radius.md,
    backgroundColor: "#DC2626",
  },
  deleteBtnText: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#fff",
  },
  previewImg: {
    width: "100%",
    aspectRatio: 1,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceSecondary,
  },
  inputLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  tagPickerRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  tagPill: {
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1.5,
    borderColor: colors.border,
    backgroundColor: "transparent",
  },
  tagPillActive: {
    backgroundColor: colors.brandTertiary,
    borderColor: colors.brand,
  },
  tagPillText: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.muted,
    textTransform: "capitalize",
  },
  tagPillTextActive: {
    color: colors.brand,
  },
});
