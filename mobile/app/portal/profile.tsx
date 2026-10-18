import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading, PrimaryButton } from "@/src/components/ui";
import { Field } from "@/app/customer/new";
// Feb-2026 · P11b — App Store consumer-account guideline blockers 3 + 4.
import DeleteAccountSection from "@/src/components/portal/DeleteAccountSection";
import * as Linking from "expo-linking";

export default function PortalProfile() {
  const { user, logout } = useAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [billing, setBilling] = useState("");
  const [avatar, setAvatar] = useState("");

  const load = useCallback(async () => {
    setLoadError(false);
    try {
      // Primary source: /auth/me always works for any authenticated user
      const authMe = await api.get("/auth/me");
      setName(authMe.name || "");
      setAvatar(authMe.avatar || "");

      // Try to get extended customer profile from /me (has phone, address, etc.)
      try {
        const me = await api.get("/me");
        if (me.name) setName(me.name);
        if (me.phone) setPhone(me.phone);
        if (me.address) setAddress(me.address);
        if (me.billing_address) setBilling(me.billing_address);
        if (me.avatar) setAvatar(me.avatar);
      } catch {
        // /api/me may 404 if customer record doesn't exist — that's OK,
        // we still have the auth data above.
        setLoadError(true);
      }
    } catch {
      // Even /auth/me failed — use whatever we have from the auth context
      setName(user?.name || user?.email || "");
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const pickAvatar = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return;
    const res = await ImagePicker.launchImageLibraryAsync({ base64: true, quality: 0.5, allowsEditing: true, aspect: [1, 1] });
    if (res.canceled || !res.assets?.[0]?.base64) return;
    setAvatar(`data:image/jpeg;base64,${res.assets[0].base64}`);
  };

  const save = async () => {
    setSaving(true);
    setSaved(false);
    try {
      // Phase 34: Use customer-portal profile PATCH endpoint (now shipped)
      await api.patch("/customer-portal/profile", { name, phone, address, billing_address: billing, avatar });
      setSaved(true);
    } catch {
      // Fallback to legacy PUT /me endpoint if portal patch fails
      try {
        await api.put("/me", { name, phone, address, billing_address: billing, avatar });
        setSaved(true);
      } catch {
        setSaved(false);
      }
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.root}>
        <Header title="My Profile" back />
        <Loading testID="portal-profile-loading" />
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <Header title="My Profile" back />
      <KeyboardAwareScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }} bottomOffset={24} keyboardShouldPersistTaps="handled">
        {loadError && (
          <View style={styles.errorBanner} testID="portal-profile-load-error">
            <Ionicons name="alert-circle-outline" size={16} color="#92400E" />
            <Text style={styles.errorText}>
              Some profile info could not be loaded. Pull to refresh or contact support.
            </Text>
          </View>
        )}

        <View style={styles.avatarWrap}>
          <Pressable onPress={pickAvatar} testID="portal-profile-avatar">
            {avatar ? (
              <Image source={{ uri: avatar }} style={styles.avatar} />
            ) : (
              <View style={[styles.avatar, styles.avatarFallback]}>
                <Text style={styles.avatarText}>{name?.charAt(0)?.toUpperCase() || "?"}</Text>
              </View>
            )}
            <View style={styles.cameraBadge}>
              <Ionicons name="camera" size={14} color="#fff" />
            </View>
          </Pressable>
          <Text style={styles.email}>{user?.email}</Text>
        </View>

        <Field label="Full Name" value={name} onChangeText={setName} placeholder="Your name" testID="portal-profile-name" />
        <Field label="Phone" value={phone} onChangeText={setPhone} placeholder="Cell phone" testID="portal-profile-phone" />
        <Field label="Service Address" value={address} onChangeText={setAddress} placeholder="Where we service" testID="portal-profile-address" />
        <Field label="Billing Address" value={billing} onChangeText={setBilling} placeholder="Where to send invoices" testID="portal-profile-billing" />

        {saved ? <Text style={styles.saved} testID="portal-profile-saved">✓ Profile saved</Text> : null}
        <View style={{ height: spacing.md }} />
        {/* TD-73 (web 73ac7cc3f) — Save = Call Now green #16A34A (`success`). */}
        <PrimaryButton title="Save Changes" icon="checkmark" onPress={save} loading={saving} variant="success" testID="portal-profile-save" />

        <Pressable style={styles.logout} onPress={logout} testID="portal-logout">
          <Ionicons name="log-out-outline" size={20} color={colors.error} />
          <Text style={styles.logoutText}>Sign out</Text>
        </Pressable>

        {/* Feb-2026 · P11b — Privacy Policy row (App Store item 4). */}
        <Pressable
          style={styles.privacyRow}
          onPress={() => {
            const webUrl = process.env.EXPO_PUBLIC_WEB_URL || "https://app.plofv.com";
            Linking.openURL(`${webUrl}/privacy-policy`).catch(() => {});
          }}
          testID="portal-profile-privacy-policy-link"
        >
          <Ionicons name="shield-checkmark-outline" size={16} color={colors.muted} />
          <Text style={styles.privacyText}>Privacy Policy</Text>
        </Pressable>

        {/* Feb-2026 · P11b — Delete-account danger section (App Store item 3). */}
        <DeleteAccountSection />
      </KeyboardAwareScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  avatarWrap: { alignItems: "center", marginBottom: spacing.lg },
  avatar: { width: 96, height: 96, borderRadius: 48, backgroundColor: colors.brandTertiary },
  avatarFallback: { alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: font.bold, fontSize: 36, color: colors.brand },
  cameraBadge: { position: "absolute", bottom: 0, right: 0, width: 30, height: 30, borderRadius: 15, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: colors.surface },
  email: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: spacing.sm },
  saved: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.success, marginTop: spacing.md, textAlign: "center" },
  logout: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, marginTop: spacing.xl, height: 52, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.error },
  logoutText: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.error },
  privacyRow: {
    marginTop: spacing.lg,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    paddingVertical: spacing.sm,
  },
  privacyText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.muted,
    textDecorationLine: "underline",
  },
  errorBanner: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    padding: spacing.md,
    backgroundColor: "#FEF3C7",
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: "#FDE68A",
    marginBottom: spacing.lg,
  },
  errorText: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#92400E",
  },
});
