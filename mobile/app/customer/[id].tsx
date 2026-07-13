import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Linking, TextInput, Platform, Alert } from "react-native";
import * as ImagePicker from "expo-image-picker";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, JobCard } from "@/src/components/widgets";

export default function CustomerDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user, startImpersonation } = useAuth();
  const router = useRouter();
  const [c, setC] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [loginSheet, setLoginSheet] = useState(false);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPw, setLoginPw] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginErr, setLoginErr] = useState("");
  const [docs, setDocs] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const [impersonating, setImpersonating] = useState(false);
  const [confirmImp, setConfirmImp] = useState(false);
  const [requesting, setRequesting] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.get(`/customers/${id}`);
      setC(data);
      setLoginEmail(data.email || "");
      api.get(`/documents?customer_id=${id}`).then(setDocs).catch(() => {});
    } finally {
      setLoading(false);
    }
  }, [id]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const createLogin = async () => {
    const pw = loginPw;
    const strong = pw.length >= 8 && /[A-Z]/.test(pw) && /[a-z]/.test(pw) && /[0-9]/.test(pw);
    if (!loginEmail.trim() || !strong) {
      setLoginErr("Enter an email and a password with 8+ chars, an uppercase, a lowercase and a number.");
      return;
    }
    setLoginBusy(true);
    setLoginErr("");
    try {
      await api.post(`/customers/${id}/create-login`, { email: loginEmail.trim().toLowerCase(), password: loginPw });
      setLoginSheet(false);
      setLoginPw("");
      load();
    } catch (e: any) {
      setLoginErr(e.message || "Failed to create login");
    } finally {
      setLoginBusy(false);
    }
  };

  if (loading) return <Loading testID="customer-detail-loading" />;
  if (!c) return null;

  const isAdmin = user?.role === "admin";

  const loginAsCustomer = () => setConfirmImp(true);

  const doImpersonate = async () => {
    setImpersonating(true);
    try {
      await startImpersonation(id as string);
      setConfirmImp(false);
      router.replace("/portal/home");
    } catch (e: any) {
      Alert.alert("Couldn't switch", e.message || "Please try again.");
    } finally {
      setImpersonating(false);
    }
  };

  const requestCard = async () => {
    setRequesting(true);
    try {
      await api.post(`/payments/request-method/${id}`, {});
      Alert.alert("Request sent ✅", `${c.name} was asked to add a card/bank on file.`);
    } catch (e: any) {
      Alert.alert("Failed", e.message || "Please try again.");
    } finally {
      setRequesting(false);
    }
  };

  const shareDocument = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return;
    const res = await ImagePicker.launchImageLibraryAsync({ base64: true, quality: 0.6 });
    if (res.canceled || !res.assets?.[0]?.base64) return;
    setUploading(true);
    try {
      const asset = res.assets[0];
      const name = (asset.fileName as string) || `Document ${new Date().toISOString().slice(0, 10)}`;
      const created = await api.post(`/documents`, {
        customer_id: id,
        name,
        type: "photo",
        data: `data:image/jpeg;base64,${asset.base64}`,
      });
      setDocs((prev) => [created, ...prev]);
    } catch {}
    finally { setUploading(false); }
  };

  const removeDoc = async (did: string) => {
    setDocs((prev) => prev.filter((d) => d.id !== did));
    await api.del(`/documents/${did}`).catch(() => {});
  };

  return (
    <View style={styles.root}>
      <Header
        title={c.name}
        back
        right={
          <Pressable onPress={() => router.push(`/customer/new?id=${id}`)} testID="edit-customer-button" hitSlop={8}>
            <Ionicons name="create-outline" size={24} color={colors.brand} />
          </Pressable>
        }
      />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}>
        <View style={styles.card}>
          <ContactRow icon="call-outline" value={c.phone} onPress={() => c.phone && Linking.openURL(`tel:${c.phone}`)} />
          <ContactRow icon="mail-outline" value={c.email} onPress={() => c.email && Linking.openURL(`mailto:${c.email}`)} />
          <ContactRow icon="location-outline" value={c.address} />
          <ContactRow icon="card-outline" value={c.billing_address ? `Billing: ${c.billing_address}` : ""} />
        </View>

        {isAdmin && c.has_login ? (
          <Pressable style={styles.impersonateBtn} onPress={loginAsCustomer} disabled={impersonating} testID="impersonate-customer-button">
            <Ionicons name="eye-outline" size={18} color="#fff" />
            <Text style={styles.impersonateText}>{impersonating ? "Switching…" : "View as customer"}</Text>
          </Pressable>
        ) : null}

        {isAdmin ? (
          <View style={styles.pmCard} testID="customer-payment-method">
            <View style={styles.pmIcon}>
              <Ionicons name={c.default_payment_method_id ? "card" : "card-outline"} size={18} color={colors.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.pmLabel}>Payment method on file</Text>
              <Text style={styles.pmValue}>
                {c.default_payment_method_id
                  ? `${c.pm_brand || "Card"} ••${c.pm_last4 || "----"}`
                  : "No card or bank on file"}
              </Text>
            </View>
            {!c.default_payment_method_id ? (
              <Pressable style={styles.pmRequest} onPress={requestCard} disabled={requesting} testID="request-card-button">
                <Text style={styles.pmRequestText}>{requesting ? "…" : "Request"}</Text>
              </Pressable>
            ) : (
              <Ionicons name="checkmark-circle" size={20} color={colors.success} />
            )}
          </View>
        ) : null}

        {isAdmin ? (
          c.has_login ? (
            <View style={styles.loginBadge} testID="customer-has-login">
              <Ionicons name="checkmark-circle" size={18} color={colors.success} />
              <Text style={styles.loginBadgeText}>Customer login active ({c.email})</Text>
            </View>
          ) : (
            <Pressable style={styles.createLoginBtn} onPress={() => setLoginSheet(true)} testID="create-login-button">
              <Ionicons name="key-outline" size={18} color={colors.brand} />
              <Text style={styles.createLoginText}>Create customer login</Text>
            </Pressable>
          )
        ) : null}

        {c.notes ? (
          <View style={styles.notesBox}>
            <Text style={styles.notesLabel}>Notes</Text>
            <Text style={styles.notes}>{c.notes}</Text>
          </View>
        ) : null}

        {isAdmin ? (
          <>
            <View style={styles.docHeader}>
              <Text style={styles.sectionTitle}>Documents ({docs.length})</Text>
              <Pressable style={styles.shareBtn} onPress={shareDocument} disabled={uploading} testID="share-document-button">
                <Ionicons name="cloud-upload-outline" size={16} color={colors.brand} />
                <Text style={styles.shareText}>{uploading ? "Uploading…" : "Share"}</Text>
              </Pressable>
            </View>
            {docs.length ? (
              docs.map((d) => (
                <View key={d.id} style={styles.docRow} testID={`customer-doc-${d.id}`}>
                  <Ionicons name="document-outline" size={18} color={colors.brand} />
                  <Text style={styles.docName} numberOfLines={1}>{d.name}</Text>
                  <Pressable onPress={() => removeDoc(d.id)} hitSlop={8} testID={`delete-doc-${d.id}`}>
                    <Ionicons name="trash-outline" size={18} color={colors.muted} />
                  </Pressable>
                </View>
              ))
            ) : (
              <Text style={styles.empty}>No documents shared yet.</Text>
            )}
          </>
        ) : null}

        <Text style={styles.sectionTitle}>Job History ({c.jobs?.length || 0})</Text>
        {c.jobs?.length ? (
          c.jobs.map((j: any) => <JobCard key={j.id} job={j} testID={`customer-job-${j.id}`} />)
        ) : (
          <Text style={styles.empty}>No jobs yet for this customer.</Text>
        )}
      </ScrollView>

      <Sheet visible={confirmImp} onClose={() => setConfirmImp(false)} title="View as customer" testID="impersonate-confirm-sheet">
        <Text style={styles.sheetHint}>
          You'll be switched into {c.name}'s portal to see exactly what they see (services, invoices, documents). An orange banner will let you return to admin anytime. Payments and card changes are disabled while viewing.
        </Text>
        <View style={{ height: spacing.md }} />
        <PrimaryButton title="View as customer" icon="eye-outline" onPress={doImpersonate} loading={impersonating} testID="impersonate-confirm-button" />
      </Sheet>

      <Sheet visible={loginSheet} onClose={() => setLoginSheet(false)} title="Create Customer Login" testID="create-login-sheet">
        <Text style={styles.sheetHint}>The customer will use these credentials to view their jobs and pay invoices.</Text>
        <Text style={styles.inputLabel}>Email</Text>
        <TextInput
          testID="login-email-field"
          style={styles.input}
          value={loginEmail}
          onChangeText={setLoginEmail}
          placeholder="customer@email.com"
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          keyboardType="email-address"
        />
        <Text style={styles.inputLabel}>Temporary Password</Text>
        <TextInput
          testID="login-password-field"
          style={styles.input}
          value={loginPw}
          onChangeText={setLoginPw}
          placeholder="8+ chars, upper, lower & number"
          placeholderTextColor={colors.muted}
          secureTextEntry
        />
        {loginErr ? <Text style={styles.error}>{loginErr}</Text> : null}
        <View style={{ height: spacing.md }} />
        <PrimaryButton title="Create Login" onPress={createLogin} loading={loginBusy} testID="submit-create-login" />
      </Sheet>
    </View>
  );
}

function ContactRow({ icon, value, onPress }: { icon: any; value?: string; onPress?: () => void }) {
  if (!value) return null;
  return (
    <Pressable style={styles.contactRow} onPress={onPress} disabled={!onPress}>
      <View style={styles.contactIcon}>
        <Ionicons name={icon} size={18} color={colors.brand} />
      </View>
      <Text style={styles.contactValue}>{value}</Text>
      {onPress ? <Ionicons name="chevron-forward" size={16} color={colors.muted} /> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  contactRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.divider },
  contactIcon: { width: 36, height: 36, borderRadius: radius.sm, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  contactValue: { flex: 1, fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  notesBox: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginTop: spacing.md },
  notesLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: 4 },
  notes: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, lineHeight: 20 },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: spacing.xl, marginBottom: spacing.md },
  empty: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  loginBadge: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: "#DCFCE7", borderRadius: radius.md, padding: spacing.md, marginTop: spacing.md },
  loginBadgeText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.success, flex: 1 },
  createLoginBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, backgroundColor: colors.brandTertiary, borderRadius: radius.md, padding: spacing.md, marginTop: spacing.md },
  createLoginText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  sheetHint: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, marginBottom: spacing.md },
  inputLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: spacing.xs, marginTop: spacing.sm },
  input: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, height: 50, fontFamily: font.regular, fontSize: fontSize.lg, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  error: { color: colors.error, fontFamily: font.medium, fontSize: fontSize.base, marginTop: spacing.sm },
  docHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.xl, marginBottom: spacing.md },
  shareBtn: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: colors.brandTertiary, paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill },
  shareText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  docRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  docName: { flex: 1, fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  impersonateBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, backgroundColor: "#EA580C", borderRadius: radius.md, height: 48, marginTop: spacing.md },
  impersonateText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  pmCard: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginTop: spacing.md },
  pmIcon: { width: 36, height: 36, borderRadius: radius.sm, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  pmLabel: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  pmValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 1 },
  pmRequest: { backgroundColor: colors.brandTertiary, paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill },
  pmRequestText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
});
