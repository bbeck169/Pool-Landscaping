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

export default function PortalProfile() {
  const { user, logout } = useAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [billing, setBilling] = useState("");
  const [avatar, setAvatar] = useState("");

  const load = useCallback(async () => {
    try {
      const me = await api.get("/me");
      setName(me.name || "");
      setPhone(me.phone || "");
      setAddress(me.address || "");
      setBilling(me.billing_address || "");
      setAvatar(me.avatar || "");
    } finally {
      setLoading(false);
    }
  }, []);

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
      await api.put("/me", { name, phone, address, billing_address: billing, avatar });
      setSaved(true);
    } catch {}
    finally { setSaving(false); }
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
        <PrimaryButton title="Save Changes" icon="checkmark" onPress={save} loading={saving} testID="portal-profile-save" />

        <Pressable style={styles.logout} onPress={logout} testID="portal-logout">
          <Ionicons name="log-out-outline" size={20} color={colors.error} />
          <Text style={styles.logoutText}>Sign out</Text>
        </Pressable>
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
});
