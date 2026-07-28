/**
 * F2f · Staff "My Profile" screen — mobile mirror of MyProfilePage.jsx.
 *
 * - Fetches /api/auth/me on mount
 * - Shows current photo via AuthedImage (or initial badge fallback)
 * - FileUpload for new photo (purpose=staff_profile_photo)
 * - PATCH /api/users/me with profile_photo_url on upload
 * - Remove photo button
 * - Identity card (name, email, role)
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Alert,
  ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { FileUpload } from "@/src/components/files/FileUpload";
import { AuthedImage } from "@/src/components/files/AuthedImage";
import type { FileRecord } from "@/src/api/files";

function buildStaffPhotoUrl(fileId: string): string {
  if (!fileId) return "";
  return `/api/files/${fileId}/download`;
}

function InitialBadge({ name, size = 96 }: { name?: string; size?: number }) {
  const initial = String(name || "?").trim().slice(0, 1).toUpperCase();
  return (
    <View
      style={[styles.initialBadge, { width: size, height: size, borderRadius: size / 2 }]}
      testID="profile-initial-badge"
    >
      {initial ? (
        <Text style={[styles.initialText, { fontSize: size / 2.5 }]}>{initial}</Text>
      ) : (
        <Ionicons name="person-outline" size={size / 2} color={colors.muted} />
      )}
    </View>
  );
}

export default function ProfileScreen() {
  const { user: ctxUser } = useAuth();
  const [me, setMe] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/auth/me")
      .then((data) => { setMe(data); setLoading(false); })
      .catch(() => { setMe(ctxUser || null); setLoading(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patch = async (fields: Record<string, any>) => {
    setSaving(true);
    try {
      const res = await api.patch("/users/me", fields);
      setMe(res.user || { ...me, ...fields });
      Alert.alert("Success", "Profile updated.");
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Update failed.");
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
    patch({ profile_photo_url: buildStaffPhotoUrl(id) });
  };

  const onRemove = () => patch({ profile_photo_url: null });

  if (loading) {
    return (
      <View style={styles.root}>
        <Header title="My Profile" back />
        <View style={styles.center} testID="profile-loading">
          <ActivityIndicator size="large" color={colors.brand} />
        </View>
      </View>
    );
  }

  const photoUrl = me?.profile_photo_url || "";
  const fileIdMatch = photoUrl.match(/^\/api\/files\/([^/?#]+)\/download/);
  const fileId = fileIdMatch ? fileIdMatch[1] : null;

  return (
    <View style={styles.root}>
      <Header title="My Profile" back />
      <ScrollView contentContainerStyle={styles.scroll} testID="my-profile-page">
        <Text style={styles.subtitle}>
          Update your display photo and basic info. Changes are visible to your team.
        </Text>

        {/* Photo Card */}
        <View style={styles.card} testID="profile-photo-card">
          <Text style={styles.cardLabel}>PROFILE PHOTO</Text>
          <View style={styles.photoRow}>
            <View testID="profile-current-photo">
              {fileId ? (
                <AuthedImage
                  fileId={fileId}
                  size={96}
                  style={styles.avatar}
                />
              ) : (
                <InitialBadge name={me?.name || me?.email} size={96} />
              )}
            </View>
            <View style={styles.uploadCol}>
              <FileUpload
                purpose="staff_profile_photo"
                linkedEntityType="user"
                linkedEntityId={me?.id}
                accept="image/png,image/jpeg,image/webp"
                multiple={false}
                maxFiles={1}
                onUploaded={onUploaded}
                buttonLabel="Upload Photo"
                disabled={saving}
              />
              <Text style={styles.hint}>
                Recommended: 400×400px square, under 5 MB.
              </Text>
              {photoUrl ? (
                <Pressable
                  onPress={onRemove}
                  disabled={saving}
                  testID="profile-remove-photo"
                  style={styles.removeBtn}
                >
                  <Ionicons name="trash-outline" size={14} color={colors.error} />
                  <Text style={styles.removeText}>Remove photo</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
        </View>

        {/* Identity Card */}
        <View style={styles.card} testID="profile-identity-card">
          <Text style={styles.cardLabel}>IDENTITY</Text>
          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Name</Text>
            <Text style={styles.infoValue} testID="profile-name">{me?.name || "—"}</Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Email</Text>
            <Text style={styles.infoValue} testID="profile-email">{me?.email || "—"}</Text>
          </View>
          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Role</Text>
            <Text style={styles.infoValue} testID="profile-role">{me?.role || "—"}</Text>
          </View>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  scroll: { padding: spacing.lg, paddingBottom: spacing["3xl"] },
  subtitle: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginBottom: spacing.lg,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.lg,
  },
  cardLabel: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: colors.muted,
    letterSpacing: 1,
    marginBottom: spacing.md,
  },
  photoRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.lg,
  },
  avatar: { borderRadius: 48 },
  uploadCol: { flex: 1 },
  hint: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: spacing.sm,
  },
  removeBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginTop: spacing.md,
  },
  removeText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.error,
  },
  initialBadge: {
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center",
    justifyContent: "center",
  },
  initialText: {
    fontFamily: font.bold,
    color: colors.muted,
  },
  infoRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  infoLabel: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
  },
  infoValue: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
});
