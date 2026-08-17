import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Linking, TextInput, Platform, Alert, Switch, TouchableOpacity, Modal, KeyboardAvoidingView } from "react-native";
import * as ImagePicker from "expo-image-picker";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, JobCard } from "@/src/components/widgets";
import CustomerEquipmentLibrary from "@/src/components/customers/CustomerEquipmentLibrary";
import MultiContact from "@/src/components/customers/MultiContact";
import CustomerTasks from "@/src/components/customers/CustomerTasks";
import ServiceNotes from "@/src/components/customers/ServiceNotes";
import SendCreateSheet from "@/src/components/customers/SendCreateSheet";
import CustomerTagsSection from "@/src/components/customers/CustomerTagsSection";
import DemoAccountToggle from "@/src/components/comms/DemoAccountToggle";

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
  const [actionSheetOpen, setActionSheetOpen] = useState(false);
  const [noteComposerOpen, setNoteComposerOpen] = useState(false);
  // Feb-2026 MP2 UI — read-only property list. Editing lives on
  // web-only (per the ship brief); mobile admins get visibility.
  const [properties, setProperties] = useState<any[]>([]);
  // Credits state (Phase 13B)
  const [creditsData, setCreditsData] = useState<any>({ balance_cents: 0, ledger: [] });
  const [showAllLedger, setShowAllLedger] = useState(false);
  const [adjustOpen, setAdjustOpen] = useState(false);
  const [adjAmount, setAdjAmount] = useState("");
  const [adjReason, setAdjReason] = useState("");
  const [adjError, setAdjError] = useState("");
  const [adjBusy, setAdjBusy] = useState(false);

  const loadCredits = useCallback(async () => {
    try {
      const res = await api.get(`/customers/${id}/credits`);
      setCreditsData(res || { balance_cents: 0, ledger: [] });
    } catch {}
  }, [id]);

  const load = useCallback(async () => {
    try {
      const data = await api.get(`/customers/${id}`);
      setC(data);
      setLoginEmail(data.email || "");
      api.get(`/documents?customer_id=${id}`).then(setDocs).catch(() => {});
      api.get(`/customers/${id}/properties`)
        .then((rows) => setProperties(rows || []))
        .catch(() => setProperties([]));
      loadCredits();
    } finally {
      setLoading(false);
    }
  }, [id, loadCredits]);

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

  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const isActive = c.is_active !== false;

  // Phase 56.2 — mobile activation toggle. Reuses the shared
  // PATCH /customers/{id}/activation endpoint so the Phase 34f auto-
  // cancel cascade and Phase 55 notifications behave identically on
  // web and native.
  const toggleActivation = () => {
    const nextActive = !isActive;
    const confirmTitle = nextActive ? "Reactivate customer?" : "Mark customer inactive?";
    const confirmBody = nextActive
      ? `Reactivate ${c.name}? Their jobs will need to be re-scheduled manually.`
      : `Marking ${c.name} inactive will auto-cancel their scheduled jobs. Continue?`;
    Alert.alert(confirmTitle, confirmBody, [
      { text: "Cancel", style: "cancel" },
      {
        text: nextActive ? "Reactivate" : "Mark inactive",
        style: nextActive ? "default" : "destructive",
        onPress: async () => {
          // Optimistic flip.
          setC((prev: any) => ({ ...prev, is_active: nextActive }));
          try {
            const updated = await api.patch(`/customers/${id}/activation`, { is_active: nextActive });
            setC(updated);
          } catch (e: any) {
            setC((prev: any) => ({ ...prev, is_active: !nextActive }));
            Alert.alert("Update failed", e.message || "Please try again.");
          }
        },
      },
    ]);
  };

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
      await api.post(`/customers/${id}/send-card-add-link`, {});
      Alert.alert("Link sent ✅", `${c.name} will receive an email + SMS to add a card.`);
    } catch (e: any) {
      Alert.alert("Failed", e.message || "Please try again.");
    } finally {
      setRequesting(false);
    }
  };

  const submitAdjust = async () => {
    setAdjBusy(true);
    setAdjError("");
    try {
      const deltaCents = Math.round(parseFloat(adjAmount) * 100);
      if (isNaN(deltaCents) || deltaCents === 0) { setAdjError("Enter a valid amount."); setAdjBusy(false); return; }
      await api.post(`/customers/${id}/credits/adjust`, { delta_cents: deltaCents, reason: adjReason.trim() });
      setAdjustOpen(false);
      setAdjAmount("");
      setAdjReason("");
      Alert.alert("Adjusted ✅", `Credit balance updated.`);
      loadCredits();
      load();
    } catch (e: any) {
      const msg = e?.message || "";
      if (msg.includes("INSUFFICIENT_BALANCE")) {
        setAdjError("Insufficient balance — cannot go negative.");
      } else {
        setAdjError(msg || "Adjustment failed.");
      }
    } finally {
      setAdjBusy(false);
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
        {c.is_vip ? (
          <View style={styles.vipBadge} testID="vip-badge">
            <Ionicons name="star" size={14} color="#92400E" />
            <Text style={styles.vipBadgeText}>VIP</Text>
          </View>
        ) : null}
        {/* Phase 56.2 — status pill + (admin-only) toggle switch. Non-admins see the pill only. */}
        <View
          style={[styles.statusPill, isActive ? styles.statusPillActive : styles.statusPillInactive]}
          testID="customer-status-pill"
        >
          <Text style={[styles.statusPillText, isActive ? styles.statusPillTextActive : styles.statusPillTextInactive]}>
            {isActive ? "Active" : "Inactive"}
          </Text>
          {isAdmin ? (
            <Switch
              testID="customer-active-toggle"
              value={isActive}
              onValueChange={toggleActivation}
              trackColor={{ false: "#9CA3AF", true: "#16A34A" }}
              thumbColor="#ffffff"
              ios_backgroundColor="#9CA3AF"
              style={{ marginLeft: 6, transform: [{ scaleX: 0.85 }, { scaleY: 0.85 }] }}
            />
          ) : null}
        </View>
        {/* Legacy inactive badge retained (invisible) for prior tests referencing this testID. */}
        {!isActive ? (
          <View style={{ height: 0, opacity: 0 }} testID="customer-inactive-badge" />
        ) : null}
        <View style={styles.card}>
          <ContactRow icon="call-outline" value={c.phone} onPress={() => c.phone && Linking.openURL(`tel:${c.phone}`)} />
          <ContactRow icon="mail-outline" value={c.email} onPress={() => c.email && Linking.openURL(`mailto:${c.email}`)} />
          <ContactRow icon="location-outline" value={c.address} />
          <ContactRow icon="card-outline" value={c.billing_address ? `Billing: ${c.billing_address}` : ""} />
          {/* Phase 34d — always render (with placeholder when null) so it has
              the same visual weight as phone/email. */}
          <View style={styles.contactRow} testID="customer-pool-gallons-display">
            <View style={styles.contactIcon}>
              <Ionicons name="water-outline" size={18} color={colors.brand} />
            </View>
            <Text style={styles.contactValue}>
              {c.pool_gallons != null
                ? `Pool: ${Number(c.pool_gallons).toLocaleString()} gal`
                : "Pool: — (not set)"}
            </Text>
          </View>
        </View>

        {/* A4. Multi-contact viewer (read-only for tech) */}
        <MultiContact mobiles={c.mobiles} emails={c.emails} />

        {isAdmin && c.has_login ? (
          <Pressable style={styles.impersonateBtn} onPress={loginAsCustomer} disabled={impersonating} testID="impersonate-customer-button">
            <Ionicons name="eye-outline" size={18} color="#fff" />
            <Text style={styles.impersonateText}>{impersonating ? "Switching…" : "View as customer"}</Text>
          </Pressable>
        ) : null}

        {isAdmin ? (
          <View style={styles.pmCard} testID="customer-payment-method">
            <View style={styles.pmIcon}>
              <Ionicons name={c.has_card_on_file ? "card" : "card-outline"} size={18} color={colors.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.pmLabel}>Card on file</Text>
              {c.has_card_on_file ? (
                <Text style={[styles.pmValue, { color: "#166534" }]}>
                  {c.card_brand || c.pm_brand || "Card"} •••• {c.card_last4 || c.pm_last4 || "----"}
                  {c.card_exp_month && c.card_exp_year ? ` (${c.card_exp_month}/${String(c.card_exp_year).slice(-2)})` : ""}
                </Text>
              ) : c.effective_require_card_on_file ? (
                <Text style={[styles.pmValue, { color: "#A16207" }]}>No card — required</Text>
              ) : (
                <Text style={[styles.pmValue, { color: colors.muted }]}>No card — not required</Text>
              )}
            </View>
            {c.has_card_on_file ? (
              <Ionicons name="checkmark-circle" size={20} color={colors.success} />
            ) : c.effective_require_card_on_file ? (
              <Pressable style={styles.pmRequest} onPress={requestCard} disabled={requesting} testID="request-card-button">
                <Text style={styles.pmRequestText}>{requesting ? "…" : "Send Link"}</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}

        {/* Card required override (Phase 12 tri-state) */}
        {isAdmin ? (
          <View style={styles.cardRequiredCard} testID="card-required-override">
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <Text style={styles.pmLabel}>Card on file required?</Text>
              <Switch
                testID="card-required-toggle"
                value={c.require_card_on_file_override === true || (c.require_card_on_file_override === null && c.effective_require_card_on_file)}
                onValueChange={async (val) => {
                  try {
                    const updated = await api.patch(`/customers/${id}`, { require_card_on_file_override: val });
                    setC(updated);
                  } catch (e: any) { Alert.alert("Failed", e.message || "Update failed"); }
                }}
                trackColor={{ false: "#9CA3AF", true: "#16A34A" }}
                thumbColor="#ffffff"
                ios_backgroundColor="#9CA3AF"
                style={{ transform: [{ scaleX: 0.85 }, { scaleY: 0.85 }] }}
              />
            </View>
            {c.require_card_on_file_override != null && (
              <Pressable
                style={styles.resetDefaultBtn}
                onPress={async () => {
                  try {
                    const updated = await api.patch(`/customers/${id}`, { require_card_on_file_override: null });
                    setC(updated);
                  } catch (e: any) { Alert.alert("Failed", e.message || "Update failed"); }
                }}
                testID="reset-card-default"
              >
                <Text style={styles.resetDefaultText}>Reset to tenant default</Text>
              </Pressable>
            )}
          </View>
        ) : null}

        {/* Credits section (Phase 10 / Phase 13B) */}
        {isAdmin ? (
          <View style={styles.creditsSection} testID="customer-credits-section">
            <View style={styles.creditsSectionHeader}>
              <View style={{ flex: 1 }}>
                <Text style={styles.creditsLabel}>CREDIT BALANCE</Text>
                <Text style={styles.creditsAmount} testID="customer-credits-balance">
                  ${((creditsData?.balance_cents ?? c.credits_balance_cents ?? 0) / 100).toFixed(2)}
                </Text>
              </View>
              <TouchableOpacity
                style={styles.adjustBtn}
                onPress={() => setAdjustOpen(true)}
                testID="credits-adjust-btn"
              >
                <Ionicons name="add-circle-outline" size={14} color={colors.brand} />
                <Text style={styles.adjustBtnText}>Adjust</Text>
              </TouchableOpacity>
            </View>
            {(creditsData?.ledger || []).length > 0 ? (
              <View style={styles.ledgerList}>
                {creditsData.ledger.slice(0, showAllLedger ? 50 : 5).map((entry: any) => {
                  const isPositive = entry.delta_cents > 0;
                  return (
                    <View key={entry.id} style={styles.ledgerRow} testID={`ledger-${entry.id}`}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.ledgerSource}>
                          {entry.source === "manual" ? "Manual" : entry.source === "referral" ? "Referral" : entry.source === "redeemed" ? "Redeemed" : entry.source === "revert" ? "Revert" : entry.source || "—"}
                        </Text>
                        {entry.reason || entry.note ? <Text style={styles.ledgerNote} numberOfLines={1}>{entry.reason || entry.note}</Text> : null}
                        {entry.actor_email ? <Text style={styles.ledgerActor}>{entry.actor_email}</Text> : null}
                      </View>
                      <View style={{ alignItems: "flex-end" }}>
                        <Text style={[styles.ledgerDelta, { color: isPositive ? "#166534" : "#DC2626" }]}>
                          {isPositive ? "+" : ""}${(entry.delta_cents / 100).toFixed(2)}
                        </Text>
                        <Text style={styles.ledgerDate}>{new Date(entry.created_at).toLocaleDateString()}</Text>
                      </View>
                    </View>
                  );
                })}
                {creditsData.ledger.length > 5 && !showAllLedger && (
                  <TouchableOpacity onPress={() => setShowAllLedger(true)} testID="ledger-load-more">
                    <Text style={styles.loadMoreText}>Show all ({creditsData.ledger.length})</Text>
                  </TouchableOpacity>
                )}
              </View>
            ) : (
              <Text style={styles.ledgerEmpty}>No credit transactions yet</Text>
            )}
          </View>
        ) : null}

        {/* Adjust balance modal */}
        <Modal visible={adjustOpen} transparent animationType="fade" testID="adjust-credits-modal">
          <KeyboardAvoidingView style={styles.adjOverlay} behavior={Platform.OS === "ios" ? "padding" : "height"}>
            <View style={styles.adjCard}>
              <Text style={styles.adjTitle}>Adjust Credit Balance</Text>
              <Text style={styles.adjCurrent}>Current: ${((creditsData?.balance_cents ?? c.credits_balance_cents ?? 0) / 100).toFixed(2)}</Text>
              <TextInput
                style={styles.adjInput}
                value={adjAmount}
                onChangeText={setAdjAmount}
                placeholder="Amount in dollars (e.g. 25 or -10)"
                placeholderTextColor={colors.muted}
                keyboardType="numeric"
                testID="adjust-amount-input"
              />
              <TextInput
                style={[styles.adjInput, { minHeight: 60 }]}
                value={adjReason}
                onChangeText={setAdjReason}
                placeholder="Reason (min 5 characters)"
                placeholderTextColor={colors.muted}
                multiline
                testID="adjust-reason-input"
              />
              {adjAmount && adjReason.length >= 5 ? (
                <Text style={styles.adjPreview}>
                  Balance will change from ${((creditsData?.balance_cents ?? 0) / 100).toFixed(2)} to ${(((creditsData?.balance_cents ?? 0) + Math.round(parseFloat(adjAmount || "0") * 100)) / 100).toFixed(2)}
                </Text>
              ) : null}
              {adjError ? <Text style={styles.adjError}>{adjError}</Text> : null}
              <View style={styles.adjBtns}>
                <TouchableOpacity style={styles.adjCancel} onPress={() => { setAdjustOpen(false); setAdjAmount(""); setAdjReason(""); setAdjError(""); }} testID="adjust-cancel">
                  <Text style={styles.adjCancelText}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.adjSave, (!adjAmount || adjReason.length < 5) && { opacity: 0.4 }]}
                  onPress={submitAdjust}
                  disabled={adjBusy || !adjAmount || adjReason.length < 5}
                  testID="adjust-save"
                >
                  <Text style={styles.adjSaveText}>{adjBusy ? "Saving…" : "Save"}</Text>
                </TouchableOpacity>
              </View>
            </View>
          </KeyboardAvoidingView>
        </Modal>

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

        {/* Feb-2026 MP2 UI — read-only property list for mobile admins.
            Editing surfaces exist on web only per the ship brief. */}
        <Text style={styles.sectionTitle}>
          Properties ({properties.filter((p: any) => p.active !== false).length})
        </Text>
        {properties.filter((p: any) => p.active !== false).length === 0 ? (
          <Text style={styles.empty}>No properties yet.</Text>
        ) : (
          properties.filter((p: any) => p.active !== false).map((p: any) => (
            <View
              key={p.id}
              style={{
                marginBottom: spacing.sm,
                padding: spacing.md,
                borderRadius: radius.md,
                backgroundColor: colors.surface,
                borderWidth: 1,
                borderColor: colors.border,
              }}
              testID={`mobile-property-${p.id}`}
            >
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                <Ionicons name="home-outline" size={16} color={colors.brand} />
                <Text style={{ fontFamily: font.bold, color: colors.onSurface, fontSize: fontSize.md }}>
                  {p.label}
                </Text>
                {p.sort_order === 0 ? (
                  <View
                    style={{
                      paddingHorizontal: 6,
                      paddingVertical: 1,
                      borderRadius: 999,
                      backgroundColor: colors.brand,
                    }}
                  >
                    <Text style={{ color: "#fff", fontSize: 10, fontWeight: "700" }}>Primary</Text>
                  </View>
                ) : null}
              </View>
              <Text style={{ marginTop: 4, color: colors.onSurfaceSecondary, fontSize: fontSize.sm }}>
                {[p.address?.line1, p.address?.city, p.address?.state, p.address?.postal_code]
                  .filter(Boolean).join(", ")}
              </Text>
              {(p.service_types || []).length ? (
                <Text style={{ marginTop: 4, color: colors.onSurfaceSecondary, fontSize: fontSize.xs }}>
                  {(p.service_types || []).join(" · ")}
                </Text>
              ) : null}
              {p.pool_size_gallons ? (
                <Text style={{ marginTop: 2, color: colors.onSurfaceSecondary, fontSize: fontSize.xs }}>
                  Pool: {p.pool_size_gallons.toLocaleString()} gal
                </Text>
              ) : null}
            </View>
          ))
        )}

        {/* Phase 56.11-mobile — Equipment photo library section. */}
        <Text style={styles.sectionTitle}>Equipment</Text>
        <CustomerEquipmentLibrary customerId={id as string} />

        {/* Task 1 · Feb-2026 — Customer Tags section. Chip render +
            tap-to-add bottom sheet + inline "Create new: <query>". */}
        <CustomerTagsSection
          customerId={id as string}
          value={c.tags || []}
          onChange={(nextTags) => setC((prev: any) => (prev ? { ...prev, tags: nextTags } : prev))}
        />

        {/* Task 1 · Feb-2026 — Outbound-comms Demo whitelist toggle
            with hard-confirm modal. Same contract as web. */}
        <View style={{ marginHorizontal: 16, marginBottom: 12,
                        flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Text style={{ fontSize: 12, color: "#71717A" }}>Comms:</Text>
          <DemoAccountToggle
            recordType="customer"
            recordId={id as string}
            isDemo={!!c.is_demo_account}
            recordLabel={c.name || "this customer"}
            onChange={(next) => setC((prev: any) => (prev ? { ...prev, is_demo_account: next } : prev))}
          />
        </View>

        {/* A5. Tasks tab */}
        <CustomerTasks customerId={id as string} />

        {/* A8. Service notes */}
        <ServiceNotes customerId={id as string} />

        <Text style={styles.sectionTitle}>Job History ({c.jobs?.length || 0})</Text>
        {c.jobs?.length ? (
          c.jobs.map((j: any) => <JobCard key={j.id} job={j} testID={`customer-job-${j.id}`} />)
        ) : (
          <Text style={styles.empty}>No jobs yet for this customer.</Text>
        )}
      </ScrollView>

      <Sheet visible={confirmImp} onClose={() => setConfirmImp(false)} title="View as customer" testID="impersonate-confirm-sheet">
        <Text style={styles.sheetHint}>
          You&apos;ll be switched into {c.name}&apos;s portal to see exactly what they see (services, invoices, documents). An orange banner will let you return to admin anytime. Payments and card changes are disabled while viewing.
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

      {/* A6. Send-Create action sheet + FAB */}
      <TouchableOpacity
        testID="send-create-fab"
        style={styles.fab}
        onPress={() => setActionSheetOpen(true)}
        activeOpacity={0.8}
      >
        <Ionicons name="add" size={26} color="#fff" />
      </TouchableOpacity>
      <SendCreateSheet
        visible={actionSheetOpen}
        onClose={() => setActionSheetOpen(false)}
        customerId={id as string}
        onAddNote={() => setNoteComposerOpen(true)}
      />
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
  cardRequiredCard: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginTop: spacing.sm },
  resetDefaultBtn: { marginTop: 6 },
  resetDefaultText: { fontFamily: font.medium, fontSize: 11, color: colors.brand, textDecorationLine: "underline" },
  creditsBanner: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#DCFCE7", borderRadius: radius.md, padding: spacing.md, marginTop: spacing.sm, borderWidth: 1, borderColor: "#BBF7D0" },
  creditsText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#166534" },
  // Credits section styles (Phase 13B)
  creditsSection: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginTop: spacing.md, borderWidth: 1, borderColor: colors.border },
  creditsSectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  creditsLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 1, textTransform: "uppercase" },
  creditsAmount: { fontFamily: font.bold, fontSize: 28, color: "#166534", marginTop: 2 },
  adjustBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md, borderWidth: 1, borderColor: colors.brand },
  adjustBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  ledgerList: { marginTop: spacing.md, gap: 1 },
  ledgerRow: { flexDirection: "row", alignItems: "center", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  ledgerSource: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, textTransform: "capitalize" },
  ledgerNote: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 1 },
  ledgerActor: { fontFamily: font.regular, fontSize: 10, color: colors.muted, fontStyle: "italic" },
  ledgerDelta: { fontFamily: font.bold, fontSize: fontSize.base },
  ledgerDate: { fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 1 },
  ledgerEmpty: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: spacing.sm },
  loadMoreText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand, textAlign: "center", paddingTop: 8 },
  // Adjust modal
  adjOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "center", padding: 24 },
  adjCard: { backgroundColor: "#fff", borderRadius: radius.lg, padding: spacing.xl },
  adjTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  adjCurrent: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2, marginBottom: spacing.md },
  adjInput: { backgroundColor: "#F8FAFC", borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  adjPreview: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand, marginBottom: spacing.sm },
  adjError: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#DC2626", marginBottom: spacing.sm },
  adjBtns: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, marginTop: spacing.sm },
  adjCancel: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  adjCancelText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  adjSave: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md, backgroundColor: colors.brand },
  adjSaveText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  vipBadge: {
    flexDirection: "row", alignItems: "center", alignSelf: "flex-start",
    gap: 4, backgroundColor: "#FEF3C7", borderColor: "#F59E0B", borderWidth: 1,
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill,
    marginBottom: spacing.md,
  },
  vipBadgeText: {
    fontFamily: font.bold, fontSize: fontSize.xs, color: "#92400E",
    letterSpacing: 1, textTransform: "uppercase",
  },
  inactiveBadge: {
    alignSelf: "flex-start",
    backgroundColor: "#E5E7EB", borderColor: "#9CA3AF", borderWidth: 1,
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill,
    marginBottom: spacing.md,
  },
  inactiveBadgeText: {
    fontFamily: font.bold, fontSize: fontSize.xs, color: "#4B5563",
    letterSpacing: 1, textTransform: "uppercase",
  },
  statusPill: {
    flexDirection: "row", alignItems: "center", alignSelf: "flex-start",
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill,
    marginBottom: spacing.md, borderWidth: 1,
  },
  statusPillActive: { backgroundColor: "#DCFCE7", borderColor: "#86EFAC" },
  statusPillInactive: { backgroundColor: "#E5E7EB", borderColor: "#9CA3AF" },
  statusPillText: {
    fontFamily: font.bold, fontSize: fontSize.xs,
    letterSpacing: 1, textTransform: "uppercase",
  },
  statusPillTextActive: { color: "#166534" },
  statusPillTextInactive: { color: "#4B5563" },
  fab: {
    position: "absolute", bottom: 24, right: 20,
    width: 52, height: 52, borderRadius: 26,
    backgroundColor: colors.brand,
    alignItems: "center", justifyContent: "center",
    elevation: 6,
    shadowColor: "#000", shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.25, shadowRadius: 4,
    zIndex: 40,
  },
});
