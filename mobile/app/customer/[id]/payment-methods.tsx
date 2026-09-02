/**
 * Customer · Payment Methods screen (admin surface).
 *
 * Mirrors web's payment methods panel:
 *   A. Saved methods list (cards + ACH bank accounts)
 *   B. Add card — opens Stripe PaymentSheet (card-only SetupIntent)
 *   C. Add ACH  — opens Stripe PaymentSheet (us_bank_account SetupIntent)
 *   D. Remove   — confirm modal → DELETE endpoint → refresh list
 *
 * Online-only. Offline shows a banner + disabled buttons.
 *
 * NOTE: PaymentSheet requires a native build (EAS Build / expo run).
 * On web preview, the SDK calls are safely wrapped — add buttons
 * will show a "native build required" alert.
 */
import React, { useCallback, useState, useEffect } from "react";
import {
  View, Text, StyleSheet, ScrollView, Alert,
  RefreshControl,
} from "react-native";
import { useLocalSearchParams, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import {
  createSetupIntent,
  attachPaymentMethod,
  listPaymentMethods,
  removePaymentMethod,
} from "@/src/api/stripe";
import type { PaymentMethodRow as PMType } from "@/src/api/stripe";
import { useStripeConfig } from "@/src/config/stripe";
import { useOnline } from "@/src/offline";
import { showConfirm } from "@/src/components/ConfirmModal";
import { Header } from "@/src/components/widgets";
import { PrimaryButton, EmptyState } from "@/src/components/ui";
import PaymentMethodRow from "@/src/components/stripe/PaymentMethodRow";
import { StripeProvider, initPaymentSheet, presentPaymentSheet } from "@/src/lib/stripeSdk";
import { StripeUnconfiguredNotice } from "@/src/lib/stripeConfig";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

/* ── Helpers ──────────────────────────────────────────────────── */

function OfflineBanner() {
  return (
    <View style={s.offlineBanner} testID="pm-offline-banner">
      <Ionicons name="cloud-offline" size={16} color="#92400E" />
      <Text style={s.offlineText}>
        {"You're offline — payment methods require a connection"}
      </Text>
    </View>
  );
}

function AchNote() {
  return (
    <View style={s.achNote} testID="pm-ach-note">
      <Ionicons name="information-circle-outline" size={16} color="#0369A1" />
      <Text style={s.achNoteText}>
        {"You'll receive an email from Stripe with two small deposits in 2-3 business days. Verify them to enable payments from this bank."}
      </Text>
    </View>
  );
}

/* ── Skeleton list ────────────────────────────────────────────── */
function Skeleton() {
  return (
    <View style={s.skeletonRow}>
      <View style={s.skeletonCircle} />
      <View style={{ flex: 1, gap: 6 }}>
        <View style={[s.skeletonBar, { width: "60%" }]} />
        <View style={[s.skeletonBar, { width: "40%" }]} />
      </View>
    </View>
  );
}

/* ── Main Screen ──────────────────────────────────────────────── */
export default function PaymentMethodsScreen() {
  const { id: customerId } = useLocalSearchParams<{ id: string }>();
  const online = useOnline();
  const { pk, stripeConfigured } = useStripeConfig();

  const [methods, setMethods] = useState<PMType[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addingCard, setAddingCard] = useState(false);
  const [addingAch, setAddingAch] = useState(false);
  const [hasAch, setHasAch] = useState(false);
  const [customerName, setCustomerName] = useState("");
  const [settingDefaultId, setSettingDefaultId] = useState<string | null>(null);

  /* ── Load ──────────────────────────────────────────────── */
  const load = useCallback(async () => {
    if (!customerId) return;
    try {
      const list = await listPaymentMethods(customerId);
      const normalized = Array.isArray(list) ? list : [];
      setMethods(normalized);
      setHasAch(normalized.some((m) => m.type === "us_bank_account"));
    } catch {
      setMethods([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [customerId]);

  const loadCustomerName = useCallback(async () => {
    if (!customerId) return;
    try {
      const c: any = await api.get(`/customers/${customerId}`);
      setCustomerName(c?.name || c?.full_name || "Customer");
    } catch {
      setCustomerName("Customer");
    }
  }, [customerId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));
  useEffect(() => { loadCustomerName(); }, [loadCustomerName]);

  const onRefresh = () => { setRefreshing(true); load(); };

  /* ── Add card ──────────────────────────────────────────── */
  const addCard = async () => {
    if (!online) return;
    setAddingCard(true);
    try {
      const si = await createSetupIntent(customerId);
      const { error: initError } = await initPaymentSheet({
        setupIntentClientSecret: si.client_secret,
        merchantDisplayName: customerName || "Payment",
        allowsDelayedPaymentMethods: false,
        style: "alwaysDark",
      });
      if (initError) {
        if (initError.code === "UnsupportedPlatform") {
          Alert.alert("Native build required", initError.message);
        } else {
          Alert.alert("Setup error", initError.message);
        }
        return;
      }
      const { error: sheetError } = await presentPaymentSheet();
      if (sheetError) {
        if (sheetError.code === "Canceled") return;
        Alert.alert("Payment error", sheetError.message);
        return;
      }
      await load();
    } catch (e: any) {
      Alert.alert("Failed", e?.message || "Could not add card. Please try again.");
    } finally {
      setAddingCard(false);
    }
  };

  /* ── Add ACH ───────────────────────────────────────────── */
  const addAch = async () => {
    if (!online) return;
    setAddingAch(true);
    try {
      const si = await createSetupIntent(customerId, ["us_bank_account"]);
      const { error: initError } = await initPaymentSheet({
        setupIntentClientSecret: si.client_secret,
        merchantDisplayName: customerName || "Payment",
        allowsDelayedPaymentMethods: true,
        style: "alwaysDark",
      });
      if (initError) {
        if (initError.code === "UnsupportedPlatform") {
          Alert.alert("Native build required", initError.message);
        } else {
          Alert.alert("Setup error", initError.message);
        }
        return;
      }
      const { error: sheetError } = await presentPaymentSheet();
      if (sheetError) {
        if (sheetError.code === "Canceled") return;
        Alert.alert("Payment error", sheetError.message);
        return;
      }
      await load();
    } catch (e: any) {
      Alert.alert("Failed", e?.message || "Could not add bank account. Please try again.");
    } finally {
      setAddingAch(false);
    }
  };

  /* ── Set default ────────────────────────────────────────── */
  const onSetDefault = async (pmId: string) => {
    if (!online) return;
    setSettingDefaultId(pmId);
    try {
      await api.post(`/payments/stripe/payment-methods/${pmId}/set-default`, {});
      await load();
    } catch (e: any) {
      Alert.alert("Failed", e?.message || "Could not set default. Please try again.");
    } finally {
      setSettingDefaultId(null);
    }
  };

  /* ── Remove ────────────────────────────────────────────── */
  const onRemove = (pmId: string) => {
    if (!online) return;
    const target = methods.find((m) => m.provider_payment_method_id === pmId);
    const label = target
      ? `${(target.brand || target.bank_name || target.type).toUpperCase()} •••• ${target.last4}`
      : "this payment method";

    showConfirm({
      title: "Remove payment method?",
      message: `${label} will be removed permanently.`,
      confirmLabel: "Remove",
      confirmStyle: "destructive",
      onConfirm: async () => {
        try {
          await removePaymentMethod(pmId);
          await load();
        } catch (e: any) {
          Alert.alert("Failed", e?.message || "Could not remove. Please try again.");
        }
      },
    });
  };

  /* ── Render ────────────────────────────────────────────── */
  const content = loading ? (
    <View style={s.skeletonList} testID="pm-loading">
      <Skeleton />
      <Skeleton />
    </View>
  ) : methods.length === 0 ? (
    <EmptyState
      icon="card-outline"
      title="No payment methods"
      subtitle="Add a card or bank account to enable automatic payments."
      testID="pm-empty-state"
    />
  ) : (
    <View style={s.methodList} testID="pm-method-list">
      {methods.map((m) => (
        <PaymentMethodRow
          key={m.provider_payment_method_id}
          pm={m}
          onRemove={onRemove}
          onSetDefault={stripeConfigured ? onSetDefault : undefined}
          disabled={!online}
          settingDefault={settingDefaultId === m.provider_payment_method_id}
        />
      ))}
    </View>
  );

  return (
    <StripeProvider
      publishableKey={pk || "pk_stub"}
    >
      {renderScreen()}
    </StripeProvider>
  );

  function renderScreen() {
    return (
      <View style={s.root} testID="payment-methods-screen">
        <Header
          title="Payment Methods"
          back
          subtitle={customerName || "Manage cards & bank accounts"}
        />
        {!online && <OfflineBanner />}
        <ScrollView
          style={s.scroll}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
        >
          {content}

          {/* K23 — Stripe-not-configured fallback */}
          {!stripeConfigured && (
            <StripeUnconfiguredNotice
              testID="pm-stripe-unconfigured-notice"
              message="Stripe is not configured for this account. Card and bank account actions are unavailable until an administrator enables Stripe."
            />
          )}

          {hasAch && <AchNote />}

          <View style={s.btnRow}>
            <PrimaryButton
              title={addingCard ? "Opening…" : "Add card"}
              icon="card-outline"
              onPress={addCard}
              loading={addingCard}
              disabled={!online || addingCard || addingAch || !stripeConfigured}
              testID="pm-add-card-btn"
            />
            <PrimaryButton
              title={addingAch ? "Opening…" : "Add bank (ACH)"}
              icon="business-outline"
              onPress={addAch}
              loading={addingAch}
              disabled={!online || addingCard || addingAch || !stripeConfigured}
              testID="pm-add-ach-btn"
            />
          </View>

          <Text style={s.secureText}>
            {"🔒 Payments handled securely by Stripe. We never see your full card or bank details."}
          </Text>
        </ScrollView>
      </View>
    );
  }
}

/* ── Styles ───────────────────────────────────────────────────── */
const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  scroll: { flex: 1 },
  scrollContent: { padding: spacing.lg, paddingBottom: spacing["2xl"] },
  offlineBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: "#FEF3C7",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
  },
  offlineText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#92400E",
    flex: 1,
  },
  methodList: { gap: spacing.sm },
  skeletonList: { gap: spacing.sm },
  skeletonRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  skeletonCircle: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.surfaceTertiary,
  },
  skeletonBar: {
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.surfaceTertiary,
  },
  btnRow: {
    gap: spacing.sm,
    marginTop: spacing.lg,
  },
  achNote: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    marginTop: spacing.md,
    backgroundColor: "#EFF6FF",
    borderRadius: radius.md,
    padding: spacing.md,
  },
  achNoteText: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#0369A1",
    lineHeight: 20,
  },
  secureText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
    marginTop: spacing.lg,
    lineHeight: 18,
  },
});
