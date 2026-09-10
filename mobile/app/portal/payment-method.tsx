/**
 * Portal · Payment Method screen.
 *
 * Feb-2026 Deployment Fix — the previous implementation POSTed to the
 * ``/api/payments/method`` and ``/api/payments/setup-session``
 * endpoints, both of which were deleted server-side during the web
 * refactor. On a live AAB the old code would 404 on mount + on tap.
 * This rewrite mirrors the web portal fix (see
 * ``frontend/src/pages/portal/PortalPages.jsx`` ·
 * ``PortalPaymentMethod``):
 *
 *   • Load     ``GET /api/customer-portal/payment-methods`` on focus.
 *   • Preflight ``POST /api/payments/stripe/setup-intent`` on tap so
 *     the customer sees an inline error before the in-app browser
 *     opens (validates auth + Stripe wiring). The returned
 *     ``client_secret`` is discarded on mobile because the mobile
 *     app does NOT ship ``@stripe/stripe-react-native`` — the actual
 *     Elements form still runs in the web portal.
 *   • Confirmation happens by opening the WEB portal's
 *     ``/portal/payment-method`` page in ``expo-web-browser``, which
 *     already runs the correct SetupIntent + attach flow. Same
 *     hosted-web pattern the tech-facing ``payments/methods.tsx``
 *     already uses (grepped, verified).
 *   • On browser close, we refetch the methods list so the summary
 *     flips from "No card" → the saved brand+last4 without a full
 *     screen reload.
 *
 * No new dependencies. No URL constructed via ``/undefined``.
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as WebBrowser from "expo-web-browser";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading, PrimaryButton, Card } from "@/src/components/ui";
import { StripeUnconfiguredNotice } from "@/src/lib/stripeConfig";


type Pm = {
  provider_payment_method_id?: string;
  brand?: string;
  last4?: string;
  exp_month?: number;
  exp_year?: number;
  is_default?: boolean;
  type?: string;
};

type MethodsResponse = {
  methods?: Pm[];
  stripe_configured?: boolean;
};


/** Resolve the base URL for the WEB portal. Falls back to the API
 *  host when ``EXPO_PUBLIC_WEB_BASE_URL`` isn't set (the current
 *  deploy uses the same domain for web + API). Trailing slash is
 *  stripped so ``${base}/portal/payment-method`` is well-formed and
 *  never contains ``//`` or ``/undefined``. */
function _webPortalBase(): string {
  const explicit = (process.env.EXPO_PUBLIC_WEB_BASE_URL || "").replace(/\/$/, "");
  if (explicit) return explicit;
  const api = (process.env.EXPO_PUBLIC_BACKEND_URL || "").replace(/\/$/, "");
  return api;
}


function _formatMethodLabel(pm: Pm | null): string {
  if (!pm) return "No payment method on file";
  const brand = (pm.brand || "").toUpperCase();
  const last4 = pm.last4 || "";
  if (brand && last4) return `${brand} · •••• ${last4}`;
  if (last4) return `•••• ${last4}`;
  if (brand) return brand;
  return "Card on file";
}


export default function PaymentMethod() {
  const router = useRouter();
  const [pm, setPm] = useState<Pm | null>(null);
  const [stripeConfigured, setStripeConfigured] = useState<boolean>(true);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r: MethodsResponse = await api.get("/customer-portal/payment-methods");
      const list = Array.isArray(r?.methods) ? r.methods : [];
      const chosen = list.find((m) => m?.is_default) || list[0] || null;
      setPm(chosen);
      setStripeConfigured(r?.stripe_configured !== false);
    } catch {
      setPm(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const addMethod = async () => {
    setBusy(true);
    try {
      // 1) Preflight — this both validates the customer's auth + the
      //    server-side Stripe wiring, and surfaces a clear error
      //    before we hand off to the in-app browser. On success the
      //    ``client_secret`` is discarded (see file header for why).
      await api.post("/payments/stripe/setup-intent", {});

      // 2) Open the WEB portal's add-card page in an in-app browser
      //    session. The web page runs the actual Elements form and
      //    the ``/payments/stripe/attach`` call. We open the same
      //    URL as ``return_url`` so the session closes cleanly on
      //    completion regardless of navigation.
      const base = _webPortalBase();
      if (!base) {
        Alert.alert(
          "Web portal not configured",
          "Set EXPO_PUBLIC_WEB_BASE_URL (or EXPO_PUBLIC_BACKEND_URL) to the customer portal host.",
        );
        return;
      }
      const target = `${base}/portal/payment-method`;
      await WebBrowser.openAuthSessionAsync(target, target);

      // 3) Refresh so the summary flips from "No card" → brand+last4
      //    without a full-screen reload.
      await load();
    } catch (e: any) {
      Alert.alert("Couldn't start add-card", e?.message || "Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.root}>
        <Header title="Payment Method" back />
        <Loading />
      </View>
    );
  }

  const has = !!pm;

  return (
    <View style={styles.root}>
      <Header title="Payment Method" back subtitle="Card or bank (ACH) on file" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg }}>
        {!has ? (
          <View style={styles.banner} testID="pm-empty-banner">
            <Ionicons name="alert-circle" size={20} color="#B45309" />
            <Text style={styles.bannerText}>
              A payment method on file is required so we can process your service
              payments automatically.
            </Text>
          </View>
        ) : null}

        <Card style={styles.methodCard}>
          <View
            style={[
              styles.iconWrap,
              { backgroundColor: has ? "#DCFCE7" : colors.surfaceSecondary },
            ]}
          >
            <Ionicons
              name={pm?.type === "ach" ? "business-outline" : "card-outline"}
              size={26}
              color={has ? colors.success : colors.muted}
            />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.methodTitle} testID="pm-summary-label">
              {_formatMethodLabel(pm)}
            </Text>
            <Text style={styles.methodSub}>
              {has
                ? pm?.exp_month && pm?.exp_year
                  ? `Exp ${String(pm.exp_month).padStart(2, "0")}/${String(pm.exp_year).slice(-2)}${pm.is_default ? " · Default" : ""}`
                  : "Saved securely"
                : "Add a card or bank account to continue"}
            </Text>
          </View>
          {has ? (
            <Ionicons name="checkmark-circle" size={22} color={colors.success} />
          ) : null}
        </Card>

        <View style={{ height: spacing.lg }} />
        {stripeConfigured === false ? (
          <StripeUnconfiguredNotice
            testID="pm-stripe-unconfigured"
            message="Payments are not currently configured on this account. Please contact us to set up billing."
          />
        ) : (
          <PrimaryButton
            title={has ? "Update payment method" : "Add card or bank (ACH)"}
            icon="lock-closed"
            loading={busy}
            onPress={addMethod}
            testID="add-payment-method"
          />
        )}
        <Text style={styles.secure}>
          🔒 Payments are handled securely. We never store your card or bank details.
        </Text>

        {/* Task 5 — Link to full saved cards list */}
        <TouchableOpacity
          onPress={() => router.push("/portal/payment-methods")}
          style={styles.viewAllBtn}
          testID="portal-view-all-cards-btn"
        >
          <Ionicons name="list-outline" size={16} color={colors.brand} />
          <Text style={styles.viewAllText}>View all saved cards</Text>
          <Ionicons name="chevron-forward" size={16} color={colors.muted} />
        </TouchableOpacity>
      </ScrollView>
    </View>
  );
}


const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  banner: {
    flexDirection: "row",
    gap: spacing.sm,
    alignItems: "flex-start",
    backgroundColor: "#FFFBEB",
    borderWidth: 1,
    borderColor: "#FDE68A",
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.lg,
  },
  bannerText: {
    flex: 1,
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#92400E",
    lineHeight: 19,
  },
  methodCard: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  iconWrap: {
    width: 48,
    height: 48,
    borderRadius: 24,
    alignItems: "center",
    justifyContent: "center",
  },
  methodTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  methodSub: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 2,
  },
  notice: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#B45309",
    textAlign: "center",
    marginTop: spacing.sm,
  },
  secure: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
    marginTop: spacing.lg,
    lineHeight: 18,
  },
  viewAllBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: spacing.lg,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  viewAllText: {
    flex: 1,
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.brand,
  },
});
