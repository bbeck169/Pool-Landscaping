/**
 * Business Settings — Admin-only.
 *
 * Company defaults + brand colours + logo upload/remove.
 * Routes:
 *   GET    /api/tenants/me/business-settings
 *   PATCH  /api/tenants/me/business-settings
 *   POST   /api/tenants/me/logo   (multipart)
 *   DELETE /api/tenants/me/logo
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity,
  ActivityIndicator, Alert, RefreshControl, Image, KeyboardAvoidingView,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";

import { useAuth } from "@/src/auth";
import { api_base } from "@/src/api";
import {
  getBusinessSettings,
  patchBusinessSettings,
  uploadLogo,
  deleteLogo,
  type BusinessSettingsStored,
} from "@/src/api/businessSettings";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { Header } from "@/src/components/widgets";

const HEX_RE = /^#[0-9a-fA-F]{6}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function toAbsolute(url: string | null | undefined): string | null {
  if (!url) return null;
  if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("data:")) return url;
  const base = api_base();
  const origin = base.endsWith("/api") ? base.slice(0, -4) : base;
  return `${origin}${url.startsWith("/") ? "" : "/"}${url}`;
}

export default function BusinessSettingsScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const allowed = role === "admin" || role === "super_admin";

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [logoBusy, setLogoBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [fields, setFields] = useState<Record<string, string>>({
    company_display_name: "",
    mailing_address: "",
    phone: "",
    website: "",
    email: "",
    brand_primary_hex: "",
    brand_secondary_hex: "",
    footer_note: "",
    tax_id: "",
  });
  const [effective, setEffective] = useState<Record<string, any>>({});
  const [logoUrl, setLogoUrl] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!allowed) { setLoading(false); return; }
    try {
      const r = await getBusinessSettings();
      const stored = r?.stored || {};
      setFields({
        company_display_name: stored.company_display_name || "",
        mailing_address: stored.mailing_address || "",
        phone: stored.phone || "",
        website: stored.website || "",
        email: stored.email || "",
        brand_primary_hex: stored.brand_primary_hex || "",
        brand_secondary_hex: stored.brand_secondary_hex || "",
        footer_note: stored.footer_note || "",
        tax_id: stored.tax_id || "",
      });
      setEffective(r?.effective || {});
      setLogoUrl(stored.logo_url || r?.effective?.logo_url || null);
      setDirty(false);
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Failed to load settings");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [allowed]);

  useEffect(() => { reload(); }, [reload]);

  // Validation
  const errs: Record<string, string> = {};
  if (fields.brand_primary_hex && !HEX_RE.test(fields.brand_primary_hex)) errs.brand_primary_hex = "Use #RRGGBB";
  if (fields.brand_secondary_hex && !HEX_RE.test(fields.brand_secondary_hex)) errs.brand_secondary_hex = "Use #RRGGBB";
  if (fields.email && !EMAIL_RE.test(fields.email)) errs.email = "Invalid email";
  const canSave = dirty && Object.keys(errs).length === 0 && !saving;

  const onChange = (key: string, value: string) => {
    setFields((f) => ({ ...f, [key]: value }));
    setDirty(true);
  };

  const onSave = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      const patch: Record<string, any> = {};
      for (const [k, v] of Object.entries(fields)) {
        patch[k] = v.trim() === "" ? null : v;
      }
      const r = await patchBusinessSettings(patch);
      setEffective(r?.effective || {});
      setDirty(false);
      Alert.alert("Saved ✅", "Business Settings saved.");
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const pickLogo = async () => {
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        Alert.alert("Permission required", "Allow photo library access to pick a logo.");
        return;
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        allowsEditing: true,
        quality: 0.9,
      });
      if (result.canceled || !result.assets?.[0]) return;

      const asset = result.assets[0];
      if (asset.fileSize && asset.fileSize > 2 * 1024 * 1024) {
        Alert.alert("Too large", "Logo must be under 2 MB.");
        return;
      }

      setLogoBusy(true);
      const fileName = asset.fileName || asset.uri.split("/").pop() || "logo.png";
      const mimeType = asset.mimeType || "image/png";
      const body = await uploadLogo(asset.uri, fileName, mimeType);
      setLogoUrl(body.logo_url);
      Alert.alert("Logo uploaded ✅");
    } catch (e: any) {
      Alert.alert("Upload failed", e?.message || "Could not upload logo.");
    } finally {
      setLogoBusy(false);
    }
  };

  const removeLogo = () => {
    Alert.alert("Remove logo?", "The app will revert to the default placeholder.", [
      { text: "Keep it", style: "cancel" },
      {
        text: "Remove",
        style: "destructive",
        onPress: async () => {
          setLogoBusy(true);
          try {
            await deleteLogo();
            setLogoUrl(null);
            Alert.alert("Logo removed ✅");
          } catch (e: any) {
            Alert.alert("Error", e?.message || "Remove failed.");
          } finally {
            setLogoBusy(false);
          }
        },
      },
    ]);
  };

  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="business-settings-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateTitle}>Not authorized</Text>
        <Text style={s.gateSub}>Business Settings are available to admins only.</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn}>
          <Text style={s.gateBtnText}>Go Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (loading) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="business-settings-loading">
        <ActivityIndicator size="large" color={colors.brand} />
      </View>
    );
  }

  const primaryPreview = fields.brand_primary_hex || effective.brand_primary_hex || "#0B4A6F";
  const secondaryPreview = fields.brand_secondary_hex || effective.brand_secondary_hex || "#F97316";

  return (
    <View style={s.root} testID="business-settings-page">
      <Header title="Business Settings" back subtitle="Company defaults + brand identity" />
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        <ScrollView
          contentContainerStyle={s.scroll}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); reload(); }}
              tintColor={colors.brand}
            />
          }
        >
          {/* ── Company Section ─── */}
          <View style={s.card} testID="business-settings-company-section">
            <Text style={s.sectionTitle}>Company</Text>
            <Field label="Display name" value={fields.company_display_name} onChangeText={(v) => onChange("company_display_name", v)} placeholder="Aquaterra Landscaping" testID="bs-company-display-name" />
            <Field label="Phone" value={fields.phone} onChangeText={(v) => onChange("phone", v)} placeholder="(555) 123-4567" testID="bs-phone" keyboardType="phone-pad" />
            <Field label="Mailing address" value={fields.mailing_address} onChangeText={(v) => onChange("mailing_address", v)} placeholder={"123 Main St\nAustin, TX 78701"} testID="bs-mailing-address" multiline />
            <Field label="Website" value={fields.website} onChangeText={(v) => onChange("website", v)} placeholder="aquaterra.com" testID="bs-website" />
            <Field label="Email" value={fields.email} onChangeText={(v) => onChange("email", v)} placeholder="hello@aquaterra.com" testID="bs-email" error={errs.email} keyboardType="email-address" />
            <Field label="Footer note" value={fields.footer_note} onChangeText={(v) => onChange("footer_note", v)} placeholder="Licensed & Insured — Lic #12345" testID="bs-footer-note" />
            <Field label="Tax ID (invoices only)" value={fields.tax_id} onChangeText={(v) => onChange("tax_id", v)} placeholder="EIN 12-3456789" testID="bs-tax-id" />
          </View>

          {/* ── Branding Section ─── */}
          <View style={s.card} testID="business-settings-branding-section">
            <Text style={s.sectionTitle}>Branding</Text>

            {/* Logo */}
            <Text style={s.fieldLabel}>Logo</Text>
            <View style={s.logoTile} testID="bs-logo-tile">
              {logoUrl ? (
                <Image
                  source={{ uri: toAbsolute(logoUrl)! }}
                  style={s.logoImg}
                  resizeMode="contain"
                  testID="bs-logo-preview"
                />
              ) : (
                <View style={s.logoEmpty} testID="bs-logo-empty">
                  <Ionicons name="image-outline" size={24} color={colors.muted} />
                  <Text style={s.logoEmptyText}>No logo uploaded</Text>
                </View>
              )}
            </View>
            <View style={s.logoActions}>
              <TouchableOpacity
                style={s.logoBtn}
                onPress={pickLogo}
                disabled={logoBusy}
                testID="bs-logo-upload-button"
              >
                {logoBusy ? (
                  <ActivityIndicator size="small" color={colors.brand} />
                ) : (
                  <Ionicons name="cloud-upload-outline" size={16} color={colors.brand} />
                )}
                <Text style={s.logoBtnText}>{logoBusy ? "Uploading…" : logoUrl ? "Replace" : "Upload"}</Text>
              </TouchableOpacity>
              {logoUrl ? (
                <TouchableOpacity
                  style={[s.logoBtn, s.logoRemoveBtn]}
                  onPress={removeLogo}
                  disabled={logoBusy}
                  testID="bs-logo-remove-button"
                >
                  <Ionicons name="trash-outline" size={16} color={colors.error} />
                  <Text style={[s.logoBtnText, { color: colors.error }]}>Remove</Text>
                </TouchableOpacity>
              ) : null}
            </View>
            <Text style={s.hint}>PNG / JPEG / WEBP / SVG · under 2 MB</Text>

            {/* Primary colour */}
            <ColorField
              label="Primary colour"
              value={fields.brand_primary_hex}
              onChangeText={(v) => onChange("brand_primary_hex", v)}
              placeholder="#0B4A6F"
              error={errs.brand_primary_hex}
              testID="bs-brand-primary"
            />

            {/* Secondary colour */}
            <ColorField
              label="Secondary colour"
              value={fields.brand_secondary_hex}
              onChangeText={(v) => onChange("brand_secondary_hex", v)}
              placeholder="#F97316"
              error={errs.brand_secondary_hex}
              testID="bs-brand-secondary"
            />
          </View>

          {/* ── Live Preview ─── */}
          <View style={s.card} testID="business-settings-live-preview">
            <Text style={s.sectionTitle}>Live preview</Text>
            <View style={s.previewWrap}>
              <View style={[s.previewHeader, { backgroundColor: primaryPreview }]} testID="bs-preview-header">
                <Text style={s.previewLabel}>ESTIMATE</Text>
                <Text style={s.previewCompany}>
                  {fields.company_display_name || effective.company_display_name || "Your Company"}
                </Text>
              </View>
              <View style={s.previewBody}>
                <TouchableOpacity
                  style={[s.previewCta, { backgroundColor: secondaryPreview }]}
                  testID="bs-preview-cta"
                >
                  <Text style={s.previewCtaText}>Approve Estimate</Text>
                </TouchableOpacity>
              </View>
            </View>
          </View>

          {/* ── Save Button ─── */}
          <TouchableOpacity
            style={[s.saveBtn, !canSave && s.saveBtnDisabled]}
            onPress={onSave}
            disabled={!canSave}
            testID="bs-save-button"
          >
            {saving ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Text style={s.saveBtnText}>Save changes</Text>
            )}
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

// ── Field component ────────────────────────────────────────
function Field({
  label, value, onChangeText, placeholder, testID, error, multiline, keyboardType,
}: {
  label: string; value: string; onChangeText: (v: string) => void;
  placeholder?: string; testID: string; error?: string;
  multiline?: boolean; keyboardType?: any;
}) {
  return (
    <View style={s.fieldWrap}>
      <Text style={s.fieldLabel}>{label}</Text>
      <TextInput
        style={[s.fieldInput, multiline && { minHeight: 68, textAlignVertical: "top" }, error && { borderColor: colors.error }]}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.muted}
        multiline={multiline}
        keyboardType={keyboardType}
        testID={testID}
      />
      {error ? <Text style={s.fieldError} testID={`${testID}-error`}>{error}</Text> : null}
    </View>
  );
}

// ── ColorField component ────────────────────────────────────
function ColorField({
  label, value, onChangeText, placeholder, error, testID,
}: {
  label: string; value: string; onChangeText: (v: string) => void;
  placeholder: string; error?: string; testID: string;
}) {
  const display = (value && HEX_RE.test(value)) ? value : placeholder;
  return (
    <View style={s.fieldWrap} testID={`${testID}-field`}>
      <Text style={s.fieldLabel}>{label}</Text>
      <View style={s.colorRow}>
        <View style={[s.colorSwatch, { backgroundColor: display }]} testID={`${testID}-swatch`} />
        <TextInput
          style={[s.fieldInput, { flex: 1 }, error && { borderColor: colors.error }]}
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          testID={`${testID}-hex`}
        />
      </View>
      {error ? <Text style={s.fieldError} testID={`${testID}-error`}>{error}</Text> : null}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  gateTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 12 },
  gateSub: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 4, textAlign: "center" },
  gateBtn: { marginTop: 20, paddingHorizontal: 24, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.brand },
  gateBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  scroll: { padding: spacing.lg, paddingBottom: 60 },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: spacing.md },
  fieldWrap: { marginBottom: spacing.md },
  fieldLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.5 },
  fieldInput: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, paddingHorizontal: 12, paddingVertical: 10, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  fieldError: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error, marginTop: 2 },
  colorRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  colorSwatch: { width: 36, height: 36, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border },
  logoTile: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md, minHeight: 96, justifyContent: "center", alignItems: "center", marginBottom: spacing.sm },
  logoImg: { width: 160, height: 64 },
  logoEmpty: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  logoEmptyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  logoActions: { flexDirection: "row", gap: spacing.sm, marginBottom: 4 },
  logoBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border },
  logoRemoveBtn: { borderColor: "#FECACA" },
  logoBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  hint: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginBottom: spacing.md },
  previewWrap: { borderRadius: radius.md, overflow: "hidden", borderWidth: 1, borderColor: colors.border },
  previewHeader: { padding: spacing.lg },
  previewLabel: { fontFamily: font.semibold, fontSize: 11, color: "rgba(255,255,255,0.8)", textTransform: "uppercase", letterSpacing: 0.5 },
  previewCompany: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#fff", marginTop: 4 },
  previewBody: { padding: spacing.lg, backgroundColor: colors.surface },
  previewCta: { alignSelf: "flex-start", paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.sm },
  previewCtaText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  saveBtn: { backgroundColor: colors.brand, borderRadius: radius.md, paddingVertical: 14, alignItems: "center", marginTop: spacing.sm },
  saveBtnDisabled: { backgroundColor: "#94A3B8" },
  saveBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
});
