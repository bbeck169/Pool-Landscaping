/**
 * Invoice Detail Viewer + Stripe Pay Now.
 *
 * Fetches GET /api/invoices/{id}/full (authenticated).
 * Renders company header, bill-to, line items, totals, notes, payment stub.
 * Pay Now opens a WebView with Stripe.js PaymentElement.
 *
 * pk_live is fetched from GET /api/config/public at runtime — never hardcoded.
 * Server-authoritative amount — displays amount_cents from create-intent response.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity, TextInput,
  ActivityIndicator, Alert, Linking, Modal, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import { WebView } from "react-native-webview";

import { useAuth } from "@/src/auth";
import { useStripeConfig } from "@/src/config/stripe";
import { getInvoiceFull, type InvoiceFull } from "@/src/api/invoices";
import { createPaymentIntent } from "@/src/api/payments";
import { InvoiceAttachments } from "@/src/components/files";
import InvoiceViewHistory from "@/src/components/invoices/InvoiceViewHistory";
import { StripeUnconfiguredNotice } from "@/src/lib/stripeConfig";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

const fmt = (n: number | undefined) => "$" + (n || 0).toFixed(2);

export default function InvoiceDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const stripe = useStripeConfig();

  const [data, setData] = useState<InvoiceFull | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [payOpen, setPayOpen] = useState(false);
  const [payHtml, setPayHtml] = useState("");
  const [payLoading, setPayLoading] = useState(false);
  // Promo code state (Phase 13B)
  const [promoExpanded, setPromoExpanded] = useState(false);
  const [promoCode, setPromoCode] = useState("");
  const [promoApplied, setPromoApplied] = useState<any>(null);
  const [promoError, setPromoError] = useState("");
  const [promoLoading, setPromoLoading] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError("");
    try {
      const inv = await getInvoiceFull(id);
      setData(inv);
    } catch (e: any) {
      setError(e?.message || "Failed to load invoice");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const startPayment = async () => {
    if (!id || !stripe.pk) {
      Alert.alert("Error", "Payments not configured.");
      return;
    }
    setPayLoading(true);
    try {
      const pi = await createPaymentIntent(id, "authenticated", undefined, promoApplied?.promo_code_id);
      if (!pi.client_secret) throw new Error("Could not create payment intent.");
      const html = buildStripeHtml(stripe.pk, pi.client_secret, pi.amount_cents, pi.currency);
      setPayHtml(html);
      setPayOpen(true);
    } catch (e: any) {
      Alert.alert("Payment Error", e?.message || "Failed to start payment.");
    } finally {
      setPayLoading(false);
    }
  };

  const applyPromo = async () => {
    const code = promoCode.trim().toUpperCase();
    if (!code) return;
    setPromoLoading(true);
    setPromoError("");
    try {
      const res = await api.post("/promo-codes/validate", { code, invoice_id: id });
      if (res.valid) {
        setPromoApplied({ ...res, code });
        setPromoError("");
      } else {
        setPromoError(res.reason === "not_found" ? "Invalid promo code" : res.reason === "expired" ? "This code has expired" : res.reason === "already_used" ? "This code has already been used" : res.reason || "Invalid code");
        setPromoApplied(null);
      }
    } catch (e: any) {
      setPromoError(e?.message || "Failed to validate code");
    } finally {
      setPromoLoading(false);
    }
  };

  const removePromo = () => {
    setPromoApplied(null);
    setPromoCode("");
    setPromoError("");
  };

  const handlePayMessage = (event: any) => {
    try {
      const msg = JSON.parse(event.nativeEvent.data);
      if (msg.type === "payment_success") {
        setPayOpen(false);
        Alert.alert("Payment Received", `A receipt is on the way to ${data?.bill_to?.name || "you"}.`);
        load();
      } else if (msg.type === "payment_error") {
        Alert.alert("Payment Failed", msg.message || "Please try again.");
      }
    } catch {}
  };

  if (loading) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]}>
        <ActivityIndicator size="large" color={colors.brand} />
      </View>
    );
  }

  if (error || !data) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]}>
        <Ionicons name="alert-circle" size={32} color={colors.error} />
        <Text style={s.errorText}>{error || "Invoice not found"}</Text>
        <TouchableOpacity onPress={() => router.back()} style={s.backBtn}>
          <Text style={s.backBtnText}>Go Back</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const { company, bill_to, property_address, header, line_items, totals, notes, is_due_on_receipt, payment_status } = data;
  const canPay = (payment_status || "").toLowerCase() !== "paid" && (totals?.total_due || 0) > 0;

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      {/* Header bar */}
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12} testID="invoice-back-btn">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Invoice</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={s.scroll} showsVerticalScrollIndicator={false}>
        {/* Status + amount */}
        <View style={s.card} testID="invoice-header-card">
          <View style={s.statusRow}>
            <View style={[s.statusPill, { backgroundColor: payment_status === "paid" ? "#DCFCE7" : "#FEF9C3" }]}>
              <Text style={[s.statusText, { color: payment_status === "paid" ? "#166534" : "#A16207" }]}>
                {(payment_status || "unpaid").toUpperCase()}
              </Text>
            </View>
            {is_due_on_receipt && <Text style={s.duePill}>Due on Receipt</Text>}
          </View>
          <Text style={s.invoiceNum} testID="invoice-number">
            Invoice #{header.invoice_number}
          </Text>
          <Text style={s.invoiceDate}>{header.invoice_date}</Text>
          <View style={s.amountRow}>
            <Text style={s.totalDue} testID="invoice-total-due">{fmt(totals.total_due)}</Text>
            <Text style={s.totalLabel}>Balance Due</Text>
          </View>
          <View style={s.metaRow}>
            <View style={s.metaItem}>
              <Text style={s.metaLabel}>Subtotal</Text>
              <Text style={s.metaValue}>{fmt(totals.subtotal)}</Text>
            </View>
            <View style={s.metaItem}>
              <Text style={s.metaLabel}>This Invoice</Text>
              <Text style={s.metaValue}>{fmt(totals.this_invoice)}</Text>
            </View>
            <View style={s.metaItem}>
              <Text style={s.metaLabel}>Paid</Text>
              <Text style={s.metaValue}>{fmt(totals.amount_paid)}</Text>
            </View>
            {(data as any).credits_applied_cents > 0 ? (
              <View style={s.metaItem} testID="invoice-credit-applied">
                <Text style={[s.metaLabel, { color: "#166534" }]}>Credit Applied</Text>
                <Text style={[s.metaValue, { color: "#166534" }]}>
                  −{fmt(((data as any).credits_applied_cents || 0) / 100)}
                </Text>
              </View>
            ) : null}
          </View>
        </View>

        {/* Promo Code Section (Phase 13B) */}
        {canPay && (
          <View style={s.promoWrap} testID="promo-code-section">
            <TouchableOpacity
              style={s.promoToggle}
              onPress={() => setPromoExpanded(!promoExpanded)}
              testID="promo-toggle"
            >
              <Ionicons name="pricetag-outline" size={14} color={colors.brand} />
              <Text style={s.promoToggleText}>Have a promo code?</Text>
              <Ionicons name={promoExpanded ? "chevron-up" : "chevron-down"} size={16} color={colors.muted} />
            </TouchableOpacity>
            {promoExpanded && (
              <View style={s.promoBody}>
                {promoApplied ? (
                  <View style={s.promoAppliedRow}>
                    <View style={[s.promoAppliedPill, { backgroundColor: promoApplied.apply_to === "account_credit" ? "#DBEAFE" : "#DCFCE7" }]}>
                      <Ionicons name="checkmark-circle" size={14} color={promoApplied.apply_to === "account_credit" ? "#1D4ED8" : "#166534"} />
                      <Text style={[s.promoAppliedText, { color: promoApplied.apply_to === "account_credit" ? "#1D4ED8" : "#166534" }]}>
                        {promoApplied.apply_to === "account_credit"
                          ? `${promoApplied.code}: +$${((promoApplied.amount_cents || 0) / 100).toFixed(2)} credit after payment`
                          : `${promoApplied.code}: -$${((promoApplied.discount_cents || promoApplied.amount_cents || 0) / 100).toFixed(2)}`}
                      </Text>
                    </View>
                    <TouchableOpacity onPress={removePromo} testID="promo-remove">
                      <Ionicons name="close-circle" size={20} color={colors.muted} />
                    </TouchableOpacity>
                  </View>
                ) : (
                  <View style={s.promoInputRow}>
                    <TextInput
                      style={s.promoInput}
                      value={promoCode}
                      onChangeText={setPromoCode}
                      placeholder="Enter code"
                      placeholderTextColor={colors.muted}
                      autoCapitalize="characters"
                      testID="promo-input"
                    />
                    <TouchableOpacity
                      style={[s.promoApplyBtn, (!promoCode.trim() || promoLoading) && { opacity: 0.4 }]}
                      onPress={applyPromo}
                      disabled={!promoCode.trim() || promoLoading}
                      testID="promo-apply"
                    >
                      <Text style={s.promoApplyText}>{promoLoading ? "…" : "Apply"}</Text>
                    </TouchableOpacity>
                  </View>
                )}
                {promoError ? <Text style={s.promoErrorText} testID="promo-error">{promoError}</Text> : null}
              </View>
            )}
          </View>
        )}

        {/* Pay Now */}
        {canPay && !stripe.stripeConfigured && (
          <StripeUnconfiguredNotice
            testID="invoice-stripe-unconfigured"
            message="Online payments are not available. Contact support to enable Stripe payments."
          />
        )}
        {canPay && stripe.stripeConfigured && (
          <TouchableOpacity
            style={s.payBtn}
            onPress={startPayment}
            disabled={payLoading || stripe.loading}
            testID="invoice-pay-now-btn"
          >
            {payLoading ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <>
                <Ionicons name="card" size={18} color="#fff" />
                <Text style={s.payBtnText}>Pay Now — {fmt(totals.total_due)}</Text>
              </>
            )}
          </TouchableOpacity>
        )}

        {/* Company info */}
        <View style={s.card}>
          <Text style={s.sectionLabel}>FROM</Text>
          <Text style={s.companyName}>{company.name}</Text>
          {company.address ? <Text style={s.muted}>{company.address}</Text> : null}
          {company.phone ? (
            <TouchableOpacity onPress={() => Linking.openURL(`tel:${company.phone}`)}>
              <Text style={[s.muted, { color: colors.brand }]}>{company.phone}</Text>
            </TouchableOpacity>
          ) : null}
        </View>

        {/* Bill To */}
        <View style={s.card}>
          <Text style={s.sectionLabel}>BILL TO</Text>
          <Text style={s.billName}>{bill_to.name || "—"}</Text>
          {bill_to.address ? <Text style={s.muted}>{bill_to.address}</Text> : null}
          {property_address ? (
            <Text style={[s.muted, { marginTop: 4 }]}>
              <Text style={{ fontFamily: font.semibold }}>Property: </Text>{property_address}
            </Text>
          ) : null}
        </View>

        {/* Credit info */}
        {(header.credit_available ?? 0) > 0 && (
          <View style={s.creditCard}>
            <Ionicons name="gift" size={16} color="#166534" />
            <Text style={s.creditText}>Credit Available: {fmt(header.credit_available)}</Text>
          </View>
        )}

        {/* Line Items */}
        <View style={s.card} testID="invoice-line-items">
          <Text style={s.sectionLabel}>LINE ITEMS</Text>
          {line_items.length === 0 ? (
            <Text style={s.muted}>No line items</Text>
          ) : (
            line_items.map((li, i) => (
              <View
                key={i}
                style={[s.lineRow, li.is_late_fee && s.lineRowLateFee]}
                testID={`invoice-line-item-${i}`}
              >
                <View style={{ flex: 1 }}>
                  <Text style={s.lineDesc}>{li.description}</Text>
                  {li.is_late_fee && (
                    <View style={s.lateFeePill}>
                      <Text style={s.lateFeeText}>LATE FEE</Text>
                    </View>
                  )}
                </View>
                <View style={s.lineRight}>
                  <Text style={s.lineQty}>{li.qty_hr || 1} × {fmt(li.cost_rate)}</Text>
                  <Text style={s.lineTotal}>{fmt(li.total)}</Text>
                </View>
              </View>
            ))
          )}
        </View>

        {/* Notes */}
        {notes ? (
          <View style={s.card} testID="invoice-notes">
            <Text style={s.sectionLabel}>NOTES</Text>
            <Text style={s.notesText}>{notes}</Text>
          </View>
        ) : null}

        {/* PB1 · Internal Margin section — admin/manager/super_admin ONLY.
            NEVER rendered for customer or technician roles. */}
        {(user?.role === "admin" || user?.role === "super_admin" ||
          user?.role === "manager") ? (() => {
            const rows = line_items || [];
            const perLine = rows.map((li: any) => {
              const q = Number(li.qty_hr || li.quantity || 1);
              const retail = Number(li.retail_price_snapshot ?? li.cost_rate ?? li.unit_price ?? 0);
              const wholesale = Number(li.wholesale_price_snapshot || 0);
              const labor = Number(li.labor_cost_snapshot || 0);
              return {
                description: li.description,
                revenue: q * retail,
                cogs: q * wholesale,
                labor: q * labor,
                profit: q * (retail - wholesale - labor),
                wholesale_per_unit: wholesale,
                labor_per_unit: labor,
              };
            });
            const totRev = perLine.reduce((acc: number, r: any) => acc + r.revenue, 0);
            const totCogs = perLine.reduce((acc: number, r: any) => acc + r.cogs, 0);
            const totLabor = perLine.reduce((acc: number, r: any) => acc + r.labor, 0);
            const totProfit = totRev - totCogs - totLabor;
            const margin = totRev > 0
              ? (totProfit / totRev * 100).toFixed(1)
              : "0.0";
            return (
              <View style={s.marginSection} testID="internal-margin-section">
                <Text style={s.marginTitle}>
                  Internal margin — not shown to customer
                </Text>
                {/* Header */}
                <View style={s.marginHeaderRow}>
                  <Text style={[s.marginHdr, { flex: 2 }]}>Line</Text>
                  <Text style={[s.marginHdr, s.marginRight]}>W/u</Text>
                  <Text style={[s.marginHdr, s.marginRight]}>L/u</Text>
                  <Text style={[s.marginHdr, s.marginRight]}>Rev</Text>
                  <Text style={[s.marginHdr, s.marginRight]}>COGS</Text>
                  <Text style={[s.marginHdr, s.marginRight]}>Profit</Text>
                </View>
                {perLine.map((r: any, i: number) => (
                  <View key={i} style={s.marginRow} testID={`internal-margin-line-${i}`}>
                    <Text style={[s.marginCell, { flex: 2 }]} numberOfLines={1}>
                      {r.description}
                    </Text>
                    <Text style={[s.marginCell, s.marginRight]}>{fmt(r.wholesale_per_unit)}</Text>
                    <Text style={[s.marginCell, s.marginRight]}>{fmt(r.labor_per_unit)}</Text>
                    <Text style={[s.marginCell, s.marginRight]}>{fmt(r.revenue)}</Text>
                    <Text style={[s.marginCell, s.marginRight, { color: "#B45309" }]}>
                      {fmt(r.cogs)}
                    </Text>
                    <Text style={[s.marginCell, s.marginRight, { fontFamily: font.semibold }]}>
                      {fmt(r.profit)}
                    </Text>
                  </View>
                ))}
                <View style={s.marginTotalsRow} testID="internal-margin-totals">
                  <Text style={[s.marginTotalCell, { flex: 2 }]}>Totals</Text>
                  <Text style={[s.marginTotalCell, s.marginRight]}></Text>
                  <Text style={[s.marginTotalCell, s.marginRight]}></Text>
                  <Text style={[s.marginTotalCell, s.marginRight]}>{fmt(totRev)}</Text>
                  <Text style={[s.marginTotalCell, s.marginRight, { color: "#B45309" }]}>
                    {fmt(totCogs)}
                  </Text>
                  <Text style={[s.marginTotalCell, s.marginRight]}>
                    {fmt(totProfit)} ({margin}%)
                  </Text>
                </View>
              </View>
            );
          })() : null}

        {/* F2b — Attachments */}
        <InvoiceAttachments docId={id!} isInvoice={true} user={user} />

        {/* Phase K47 · Feb-2026 — Invoice view history (admin only,
            self-hides on 403 for customer/technician callers). */}
        <InvoiceViewHistory invoiceId={id!} />
      </ScrollView>

      {/* Payment WebView Modal */}
      <Modal visible={payOpen} animationType="slide" testID="invoice-pay-modal">
        <View style={[s.payModalRoot, { paddingTop: insets.top }]}>
          <View style={s.payModalHeader}>
            <TouchableOpacity onPress={() => setPayOpen(false)} testID="invoice-pay-close">
              <Ionicons name="close" size={24} color={colors.onSurface} />
            </TouchableOpacity>
            <Text style={s.payModalTitle}>Pay Invoice</Text>
            <Ionicons name="shield-checkmark" size={20} color={colors.success} />
          </View>
          {payHtml ? (
            <WebView
              source={{ html: payHtml }}
              style={{ flex: 1 }}
              onMessage={handlePayMessage}
              javaScriptEnabled
              domStorageEnabled
              originWhitelist={["*"]}
            />
          ) : (
            <ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} />
          )}
        </View>
      </Modal>
    </View>
  );
}

function buildStripeHtml(pk: string, clientSecret: string, amountCents: number, currency: string) {
  const amountLabel = (amountCents / 100).toFixed(2);
  const cur = (currency || "usd").toUpperCase();
  return `<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://js.stripe.com/v3/"></script>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 20px; margin: 0; background: #fff; }
  .amount { font-size: 16px; color: #475569; margin-bottom: 16px; }
  .amount b { color: #0F172A; }
  #payment-element { min-height: 200px; }
  .error { margin-top: 12px; padding: 10px 12px; border-radius: 8px; background: #FEF3C7; color: #92400E; font-size: 13px; display: none; }
  button { margin-top: 16px; width: 100%; padding: 14px; border-radius: 10px; background: #0F766E; color: white; font-weight: 600; font-size: 15px; border: none; cursor: pointer; }
  button:disabled { background: #94A3B8; cursor: wait; }
  .secured { margin-top: 10px; font-size: 11px; color: #64748B; text-align: center; }
</style>
</head><body>
<div class="amount">Amount due: <b>$${amountLabel} ${cur}</b></div>
<div id="payment-element"></div>
<div id="error-msg" class="error"></div>
<button id="submit-btn" disabled>Pay $${amountLabel}</button>
<div class="secured">Secured by Stripe. Card & ACH accepted.</div>
<script>
  const stripe = Stripe('${pk}');
  const elements = stripe.elements({ clientSecret: '${clientSecret}', appearance: { theme: 'stripe' } });
  const pe = elements.create('payment');
  pe.mount('#payment-element');
  pe.on('ready', function() { document.getElementById('submit-btn').disabled = false; });
  document.getElementById('submit-btn').addEventListener('click', async function() {
    this.disabled = true; this.textContent = 'Processing...';
    const { error, paymentIntent } = await stripe.confirmPayment({ elements, confirmParams: { return_url: 'https://example.com' }, redirect: 'if_required' });
    if (error) {
      document.getElementById('error-msg').style.display = 'block';
      document.getElementById('error-msg').textContent = error.message;
      this.disabled = false; this.textContent = 'Pay $${amountLabel}';
      window.ReactNativeWebView.postMessage(JSON.stringify({ type: 'payment_error', message: error.message }));
    } else if (paymentIntent && (paymentIntent.status === 'succeeded' || paymentIntent.status === 'processing')) {
      window.ReactNativeWebView.postMessage(JSON.stringify({ type: 'payment_success' }));
    }
  });
</script>
</body></html>`;
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, padding: 20 },
  errorText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.error, marginTop: 8, textAlign: "center" },
  backBtn: { marginTop: 16, paddingHorizontal: 20, paddingVertical: 10, borderRadius: radius.md, backgroundColor: colors.brand },
  backBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  navBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  navTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  scroll: { padding: spacing.lg, paddingBottom: 40 },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  sectionLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 1, marginBottom: spacing.sm },
  statusRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm },
  statusPill: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999 },
  statusText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.5 },
  duePill: { fontFamily: font.semibold, fontSize: 10, color: "#C2410C", backgroundColor: "#FFEDD5", paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  invoiceNum: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  invoiceDate: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  amountRow: { marginTop: spacing.md, alignItems: "flex-end" },
  totalDue: { fontFamily: font.bold, fontSize: fontSize["3xl"], color: colors.brand },
  totalLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  metaRow: { flexDirection: "row", justifyContent: "space-between", marginTop: spacing.lg, paddingTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.border },
  metaItem: { alignItems: "center" },
  metaLabel: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  metaValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2 },
  payBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: "#0F766E", paddingVertical: 16, borderRadius: radius.md, marginBottom: spacing.md },
  payBtnText: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#fff" },
  companyName: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  billName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  muted: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  creditCard: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#DCFCE7", borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md },
  creditText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#166534" },
  lineRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border },
  lineRowLateFee: { backgroundColor: "#FFF7ED" },
  lineDesc: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, flex: 1 },
  lateFeePill: { backgroundColor: "#FEE2E2", paddingHorizontal: 6, paddingVertical: 1, borderRadius: 4, marginTop: 4, alignSelf: "flex-start" },
  lateFeeText: { fontFamily: font.bold, fontSize: 9, color: "#B91C1C", letterSpacing: 0.5 },
  lineRight: { alignItems: "flex-end", marginLeft: 12 },
  lineQty: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  lineTotal: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2 },
  notesText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 22 },
  // PB1 · Internal Margin styles
  marginSection: {
    marginTop: spacing.md,
    marginBottom: spacing.md,
    borderRadius: radius.md,
    padding: spacing.md,
    backgroundColor: "#FEF3C7",
    borderWidth: 1,
    borderColor: "#FCD34D",
  },
  marginTitle: {
    fontFamily: font.bold,
    fontSize: 11,
    color: "#92400E",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
  },
  marginHeaderRow: {
    flexDirection: "row",
    paddingVertical: 4,
    borderBottomWidth: 1,
    borderBottomColor: "#FCD34D",
  },
  marginHdr: {
    flex: 1,
    fontFamily: font.bold,
    fontSize: 10,
    color: "#92400E",
    textTransform: "uppercase",
  },
  marginRight: { textAlign: "right" },
  marginRow: {
    flexDirection: "row",
    paddingVertical: 4,
    borderBottomWidth: 1,
    borderBottomColor: "#FDEAB0",
  },
  marginCell: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: 11,
    color: "#78350F",
  },
  marginTotalsRow: {
    flexDirection: "row",
    paddingVertical: 6,
    borderTopWidth: 1,
    borderTopColor: "#FCD34D",
    marginTop: 2,
  },
  marginTotalCell: {
    flex: 1,
    fontFamily: font.bold,
    fontSize: 11,
    color: "#78350F",
  },
  payModalRoot: { flex: 1, backgroundColor: colors.surface },
  payModalHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  payModalTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  // Promo code styles (Phase 13B)
  promoWrap: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md, overflow: "hidden" },
  promoToggle: { flexDirection: "row", alignItems: "center", gap: 6, padding: spacing.md },
  promoToggleText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  promoBody: { paddingHorizontal: spacing.md, paddingBottom: spacing.md },
  promoInputRow: { flexDirection: "row", gap: 8 },
  promoInput: { flex: 1, backgroundColor: "#F8FAFC", borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 12, height: 40, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  promoApplyBtn: { paddingHorizontal: 16, height: 40, justifyContent: "center", borderRadius: radius.md, backgroundColor: colors.brand },
  promoApplyText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  promoAppliedRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  promoAppliedPill: { flexDirection: "row", alignItems: "center", gap: 6, flex: 1, paddingHorizontal: 10, paddingVertical: 8, borderRadius: radius.md },
  promoAppliedText: { fontFamily: font.semibold, fontSize: fontSize.sm, flex: 1 },
  promoErrorText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#DC2626", marginTop: 6 },
});
