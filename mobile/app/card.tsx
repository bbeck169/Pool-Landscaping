import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Linking, Share, Platform, Alert, TextInput } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import * as Clipboard from "expo-clipboard";
import * as Sharing from "expo-sharing";
import * as FileSystem from "expo-file-system/legacy";
import * as ImagePicker from "expo-image-picker";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, brandGradient } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Sheet, PrimaryButton } from "@/src/components/ui";

// Static fallback so the screen never renders blank while /card loads.
const FALLBACK_COMPANY = {
  name: "Pool & Landscaping of Vistancia",
  region: "Peoria & Vistancia, Arizona",
  tagline: "Your trusted local pool & landscaping pros in Vistancia.",
  contact_name: "Brian",
  phone: "602-887-4400",
  email: "brian@plofv.com",
  website: "https://www.poolandlandscapingofvistancia.com/",
  google_review: "https://share.google/TMIyxRkwapL0PlnWV",
};

export default function BusinessCard() {
  const [company, setCompany] = useState<any>(FALLBACK_COMPANY);
  const [personal, setPersonal] = useState<any>(null);
  const [canEditCompany, setCanEditCompany] = useState(false);
  const [canEditPersonal, setCanEditPersonal] = useState(false);
  const [mode, setMode] = useState<"company" | "personal">("company");

  const [editOpen, setEditOpen] = useState(false);
  const [form, setForm] = useState<any>({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await api.get("/card");
      setCompany(d.company || FALLBACK_COMPANY);
      setPersonal(d.personal || null);
      setCanEditCompany(!!d.can_edit_company);
      setCanEditPersonal(!!d.can_edit_personal);
      if (d.personal) setMode("personal"); // techs default to their own card (door-to-door)
    } catch {}
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const showingPersonal = mode === "personal" && personal;
  const title = showingPersonal ? personal.name : company.name;
  const subtitle = showingPersonal ? personal.title : company.region;
  const phone = showingPersonal ? personal.phone : company.phone;
  const email = showingPersonal ? personal.email : company.email;

  const vcard =
    `BEGIN:VCARD\nVERSION:3.0\nN:;${title};;;\nFN:${title}\nORG:${company.name}\n` +
    `TITLE:${showingPersonal ? personal.title : company.contact_name}\n` +
    `TEL;TYPE=WORK,VOICE:${phone}\nEMAIL;TYPE=WORK:${email}\nURL:${company.website}\n` +
    `ADR;TYPE=WORK:;;;${company.region};;;\nNOTE:${company.tagline}\nEND:VCARD`;
  const qr = `https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${encodeURIComponent(vcard)}`;

  const saveContact = async () => {
    try {
      if (Platform.OS === "web" || !(await Sharing.isAvailableAsync())) {
        await Clipboard.setStringAsync(vcard);
        Alert.alert("Contact copied", "The contact details were copied to your clipboard.");
        return;
      }
      const uri = `${FileSystem.cacheDirectory}${title.replace(/\s+/g, "_")}.vcf`;
      await FileSystem.writeAsStringAsync(uri, vcard);
      await Sharing.shareAsync(uri, { mimeType: "text/vcard", UTI: "public.vcard", dialogTitle: "Save to Contacts" });
    } catch (e: any) {
      Alert.alert("Could not save contact", e.message);
    }
  };

  const shareCard = () =>
    Share.share({ message: `${title} — ${subtitle}\n${company.name}\n📞 ${phone}\n✉️ ${email}\n🌐 ${company.website}` });

  const openEdit = () => {
    setForm(showingPersonal ? { ...personal } : { ...company });
    setEditOpen(true);
  };

  const saveEdit = async () => {
    setSaving(true);
    try {
      if (showingPersonal) {
        await api.put("/card/personal", { name: form.name, title: form.title, phone: form.phone, email: form.email });
      } else {
        await api.put("/card/company", form);
      }
      setEditOpen(false);
      await load();
    } catch (e: any) {
      Alert.alert("Save failed", e.message);
    } finally {
      setSaving(false);
    }
  };

  const canEdit = showingPersonal ? canEditPersonal : canEditCompany;

  const pickLogo = async () => {
    const perm = await ImagePicker.getMediaLibraryPermissionsAsync();
    let status = perm.status;
    if (status !== "granted") {
      if (!perm.canAskAgain) {
        Alert.alert("Photo access needed", "Allow photo access to upload your company logo.", [
          { text: "Cancel", style: "cancel" },
          { text: "Open Settings", onPress: () => Linking.openSettings() },
        ]);
        return;
      }
      status = (await ImagePicker.requestMediaLibraryPermissionsAsync()).status;
      if (status !== "granted") return;
    }
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.6, base64: true, allowsEditing: true, aspect: [1, 1] });
    if (!res.canceled && res.assets?.[0]?.base64) {
      setForm((f: any) => ({ ...f, logo: `data:image/jpeg;base64,${res.assets[0].base64}` }));
    }
  };
  const editFields = showingPersonal
    ? [["name", "Name"], ["title", "Title"], ["phone", "Phone"], ["email", "Email"]]
    : [["name", "Company name"], ["region", "Region"], ["tagline", "Tagline"], ["contact_name", "Contact name"], ["phone", "Phone"], ["email", "Email"], ["website", "Website"], ["google_review", "Google review link"]];

  const actions = [
    { icon: "call", label: "Call", onPress: () => Linking.openURL(`tel:${phone}`) },
    { icon: "mail", label: "Email", onPress: () => Linking.openURL(`mailto:${email}`) },
    { icon: "globe-outline", label: "Website", onPress: () => Linking.openURL(company.website) },
    { icon: "logo-google", label: "Review", onPress: () => Linking.openURL(company.google_review) },
  ];

  const initials = (title || "?").split(" ").map((w: string) => w[0]).slice(0, 2).join("").toUpperCase();

  return (
    <View style={styles.root}>
      <Header
        title="Business Card"
        back
        right={<Pressable onPress={shareCard} hitSlop={8} testID="card-share"><Ionicons name="share-outline" size={24} color={colors.brand} /></Pressable>}
      />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}>
        {personal ? (
          <View style={styles.toggle}>
            {(["personal", "company"] as const).map((m) => (
              <Pressable key={m} onPress={() => setMode(m)} style={[styles.toggleBtn, mode === m && styles.toggleBtnActive]} testID={`card-mode-${m}`}>
                <Text style={[styles.toggleText, { color: mode === m ? "#fff" : colors.onSurfaceSecondary }]}>{m === "personal" ? "My Card" : "Company"}</Text>
              </Pressable>
            ))}
          </View>
        ) : null}

        <View style={styles.card}>
          <LinearGradient colors={brandGradient} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.hero}>
            <View style={styles.logo}>
              {showingPersonal ? <Text style={styles.logoText}>{initials}</Text> : company.logo ? <Image source={{ uri: company.logo }} style={styles.heroLogo} contentFit="cover" /> : <Ionicons name="water" size={34} color="#fff" />}
            </View>
            <Text style={styles.name}>{title}</Text>
            <Text style={styles.region}>{subtitle}</Text>
            {showingPersonal ? <Text style={styles.orgLine}>{company.name}</Text> : null}
          </LinearGradient>

          <View style={styles.body}>
            <Text style={styles.tagline}>{company.tagline}</Text>

            <View style={styles.actionsRow}>
              {actions.map((a) => (
                <Pressable key={a.label} style={styles.action} onPress={a.onPress} testID={`card-${a.label.toLowerCase()}`}>
                  <View style={styles.actionIcon}><Ionicons name={a.icon as any} size={22} color={colors.brand} /></View>
                  <Text style={styles.actionLabel}>{a.label}</Text>
                </Pressable>
              ))}
            </View>

            <Pressable style={styles.saveBtn} onPress={saveContact} testID="card-save">
              <Ionicons name="person-add-outline" size={20} color="#fff" />
              <Text style={styles.saveText}>Save to Contacts</Text>
            </Pressable>

            {canEdit ? (
              <Pressable style={styles.editBtn} onPress={openEdit} testID="card-edit">
                <Ionicons name="create-outline" size={18} color={colors.brand} />
                <Text style={styles.editText}>Edit {showingPersonal ? "my card" : "company card"}</Text>
              </Pressable>
            ) : null}

            <View style={styles.qrWrap}>
              <Image source={{ uri: qr }} style={styles.qr} contentFit="contain" />
              <Text style={styles.qrHint}>Scan or tap (NFC) to save this contact</Text>
            </View>
          </View>
        </View>
      </ScrollView>

      <Sheet visible={editOpen} onClose={() => setEditOpen(false)} title={showingPersonal ? "Edit my card" : "Edit company card"} testID="card-edit-sheet">
        {!showingPersonal ? (
          <View style={{ alignItems: "center", marginBottom: spacing.md }}>
            {form.logo ? (
              <Image source={{ uri: form.logo }} style={styles.logoPreview} contentFit="cover" />
            ) : (
              <View style={[styles.logoPreview, styles.logoPlaceholder]}><Ionicons name="image-outline" size={28} color={colors.muted} /></View>
            )}
            <Pressable style={styles.logoUploadBtn} onPress={pickLogo} testID="card-upload-logo">
              <Ionicons name="cloud-upload-outline" size={16} color={colors.brand} />
              <Text style={styles.logoUploadText}>{form.logo ? "Change logo" : "Upload logo"}</Text>
            </Pressable>
          </View>
        ) : null}
        {editFields.map(([k, lbl]) => (
          <View key={k} style={{ marginBottom: spacing.sm }}>
            <Text style={styles.inputLabel}>{lbl}</Text>
            <TextInput
              style={styles.input}
              value={form[k] || ""}
              onChangeText={(v) => setForm((f: any) => ({ ...f, [k]: v }))}
              autoCapitalize={["email", "website", "google_review"].includes(k) ? "none" : "sentences"}
              placeholderTextColor={colors.muted}
              testID={`card-field-${k}`}
            />
          </View>
        ))}
        <View style={{ height: spacing.sm }} />
        <PrimaryButton title="Save" icon="save-outline" loading={saving} onPress={saveEdit} testID="card-save-edit" />
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  toggle: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.lg },
  toggleBtn: { flex: 1, height: 40, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  toggleBtnActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  toggleText: { fontFamily: font.semibold, fontSize: fontSize.base },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, overflow: "hidden", borderWidth: 1, borderColor: colors.border },
  hero: { alignItems: "center", paddingVertical: spacing["2xl"], paddingHorizontal: spacing.lg },
  logo: { width: 72, height: 72, borderRadius: 36, backgroundColor: "rgba(255,255,255,0.2)", alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: "rgba(255,255,255,0.5)" },
  logoText: { fontFamily: font.bold, fontSize: 26, color: "#fff" },
  heroLogo: { width: 72, height: 72, borderRadius: 36 },
  logoPreview: { width: 88, height: 88, borderRadius: 12, marginBottom: spacing.sm },
  logoPlaceholder: { backgroundColor: colors.surfaceSecondary, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.border },
  logoUploadBtn: { flexDirection: "row", alignItems: "center", gap: 6 },
  logoUploadText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  name: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: "#fff", marginTop: spacing.md, textAlign: "center" },
  region: { fontFamily: font.medium, fontSize: fontSize.base, color: "rgba(255,255,255,0.9)", marginTop: 4 },
  orgLine: { fontFamily: font.regular, fontSize: fontSize.sm, color: "rgba(255,255,255,0.85)", marginTop: 2 },
  body: { padding: spacing.lg },
  tagline: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center", lineHeight: 20 },
  actionsRow: { flexDirection: "row", justifyContent: "space-around", marginTop: spacing.xl },
  action: { alignItems: "center", gap: 6 },
  actionIcon: { width: 52, height: 52, borderRadius: 26, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  actionLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  saveBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, backgroundColor: colors.brand, height: 52, borderRadius: radius.md, marginTop: spacing.xl },
  saveText: { fontFamily: font.semibold, fontSize: fontSize.lg, color: "#fff" },
  editBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: spacing.md },
  editText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  qrWrap: { alignItems: "center", marginTop: spacing.xl },
  qr: { width: 200, height: 200, borderRadius: radius.md },
  qrHint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: spacing.md, textAlign: "center" },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs, textTransform: "uppercase" },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
});
