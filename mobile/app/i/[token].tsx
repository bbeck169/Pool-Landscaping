/**
 * Task 3 — Invoice Magic Link bypass (public, no auth).
 *
 * Deep-link route: `/i/:token`
 *
 * Decodes the magic-link JWT client-side to extract `invoice_id`,
 * fetches the invoice via `/api/invoices/{iid}/full-magic?token=...`,
 * and renders a read-only invoice view with a Pay Now CTA that opens
 * the Stripe Checkout URL in the system browser.
 *
 * Does NOT embed Stripe in a WebView — pay opens via Linking.openURL.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity,
  ActivityIndicator, Linking, Switch,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

/* ── JWT decode (payload only, no verification) ────────────── */
function decodeJwtPayload(token: string): Record<string, any> | null {
  if (!token || typeof token !== "string") return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    let payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    while (payload.length % 4) payload += "=";
    const json = global.atob
      ? global.atob(payload)
      : Buffer.from(payload, "base64").toString("utf-8");
    return JSON.parse(json);
  } catch {
    return null;
  }
}

const fmt = (n: number | undefined) => "$" + (n || 0).toFixed(2);

type InvoiceData = {
  company: { name: string; address?: string; phone?: string; website?: string };
  bill_to: { name: string; address?: string };
  property_address?: string;
  header: {
    invoice_number: string;
    invoice_date: string;
    credit_available?: number;
    outstanding_balance?: number;
  };
  line_items: { description: string; cost_rate?: number; qty_hr?: number; total?: number }[];
  totals: { subtotal: number; this_invoice: number; amount_paid: number; total_due: number };
  notes: string;
  is_due_on_receipt?: boolean;
  payment_status?: string;
};

export default function MagicInvoiceScreen() {
  const { token } = useLocalSearchParams<{ token: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const payload = decodeJwtPayload(token || "");
  const invoiceId = payload?.invoice_id || "";

  const [data, setData] = useState<InvoiceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [payLoading, setPayLoading] = useState(false);
  const [saveCard, setSaveCard] = useState(false);

  const load = useCallback(async () => {
    if (!invoiceId || !token) return;
    setLoading(true);
    setError("");
    try {
      const res = await api.get(
        `/invoices/${invoiceId}/full-magic?token=${encodeURIComponent(token)}&src=link`,
      );
      setData(res);
    } catch (e: any) {
      setError(e?.message || "Failed to load invoice.");
    } finally {
      setLoading(false);
    }
  }, [invoiceId, token]);

  useEffect(() => { load(); }, [load]);

  const handlePayNow = async () => {
    if (!invoiceId || !token) return;
    setPayLoading(true);
    try {
      const res = await api.post(
        `/invoices/${invoiceId}/request-payment-link-magic?token=${encodeURIComponent(token)}`,
        { save_card: saveCard },
      );
      const url = res?.url || res?.checkout_url || res?.session_url;
      if (url) {
        await Linking.openURL(url);
      } else {
        setError("Could not generate payment link. Please try again.");
      }
    } catch (e: any) {
      if (e?.status === 409) {
        setError("This invoice has already been paid.");
        load();
      } else {
        setError(e?.message || "Failed to start payment.");
      }
    } finally {
      setPayLoading(false);
    }
  };

  /* ── Invalid token ────────────────────────────────────────── */
  if (!token || !invoiceId) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="public-invoice-magic-invalid-token">
        <Ionicons name="alert-circle" size={36} color="#DC2626" />
        <Text style={s.errorTitle}>Link Invalid</Text>
        <Text style={s.errorBody}>
          This invoice link is missing or malformed — please request a fresh one from the business that sent it.
        </Text>
      </View>
    );
  }

  /* ── Loading ──────────────────────────────────────────────── */
  if (loading) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="magic-invoice-loading">
        <ActivityIndicator size="large" color={colors.brand} />
        <Text style={s.loadingText}>Loading invoice…</Text>
      </View>
    );
  }

  /* ── Error ────────────────────────────────────────────────── */
  if (error && !data) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="magic-invoice-error">
        <Ionicons name="alert-circle" size={32} color={colors.error} />
        <Text style={s.errorText}>{error}</Text>
        <TouchableOpacity onPress={load} style={s.retryBtn} testID="magic-invoice-retry">
          <Text style={s.retryBtnText}>Retry</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (!data) return null;

  const { company, bill_to, property_address, header, line_items, totals, notes, is_due_on_receipt, payment_status } = data;
  const canPay = (payment_status || "").toLowerCase() !== "paid" && (totals?.total_due || 0) > 0;

  return (
    <View style={[s.root, { paddingTop: insets.top }]} testID="public-invoice-magic-root">
      {/* Nav bar */}
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.canGoBack() ? router.back() : null} hitSlop={12} testID="magic-invoice-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Invoice</Text>
        <View style={{ width: 22 }} />
      </View>

      {/* Error banner */}
      {error ? (
        <View style={s.errorBanner}>
          <Text style={s.errorBannerText}>{error}</Text>
        </View>
      ) : null}

      <ScrollView contentContainerStyle={s.scroll} showsVerticalScrollIndicator={false}>
        {/* Status + amount */}
        <View style={s.card} testID="magic-invoice-header-card">
          <View style={s.statusRow}>
            <View style={[s.statusPill, { backgroundColor: payment_status === "paid" ? "#DCFCE7" : "#FEF9C3" }]}>
              <Text style={[s.statusText, { color: payment_status === "paid" ? "#166534" : "#A16207" }]}>
                {(payment_status || "unpaid").toUpperCase()}
              </Text>
            </View>
            {is_due_on_receipt && <Text style={s.duePill}>Due on Receipt</Text>}
          </View>
          <Text style={s.invoiceNum} testID="magic-invoice-number">
            Invoice #{header.invoice_number}
          </Text>
          <Text style={s.invoiceDate}>{header.invoice_date}</Text>
          <View style={s.amountRow}>
            <Text style={s.totalDue} testID="magic-invoice-total-due">{fmt(totals.total_due)}</Text>
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
          </View>
        </View>

        {/* Pay Now */}
        {canPay && (
          <>
            {/* Task 5 — save card checkbox */}
            <View style={s.saveCardRow} testID="magic-invoice-save-card-row">
              <Switch
                value={saveCard}
                onValueChange={setSaveCard}
                trackColor={{ false: "#D1D5DB", true: "#86EFAC" }}
                thumbColor={saveCard ? "#059669" : "#9CA3AF"}
                testID="magic-invoice-save-card-switch"
              />
              <Text style={s.saveCardLabel}>Save this card for future payments</Text>
            </View>
            <TouchableOpacity
              style={s.payBtn}
              onPress={handlePayNow}
              disabled={payLoading}
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
          </>
        )}

        {/* Company */}
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
        <View style={s.card} testID="magic-invoice-bill-to">
          <Text style={s.sectionLabel}>BILL TO</Text>
          <Text style={s.billName}>{bill_to.name || "—"}</Text>
          {bill_to.address ? <Text style={s.muted}>{bill_to.address}</Text> : null}
          {property_address ? (
            <Text style={[s.muted, { marginTop: 4 }]}>
              <Text style={{ fontFamily: font.semibold }}>Property: </Text>{property_address}
            </Text>
          ) : null}
        </View>

        {/* Line Items */}
        <View style={s.card} testID="magic-invoice-line-items">
          <Text style={s.sectionLabel}>LINE ITEMS</Text>
          {line_items.length === 0 ? (
            <Text style={s.muted}>No line items</Text>
          ) : (
            line_items.map((li, i) => (
              <View key={i} style={s.lineRow} testID={`magic-invoice-line-item-${i}`}>
                <View style={{ flex: 1 }}>
                  <Text style={s.lineDesc}>{li.description}</Text>
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
          <View style={s.card} testID="magic-invoice-notes">
            <Text style={s.sectionLabel}>NOTES</Text>
            <Text style={s.notesText}>{notes}</Text>
          </View>
        ) : null}

        {/* Payment stub */}
        <View style={s.card} testID="magic-invoice-payment-stub">
          <View style={s.stubRow}>
            <Text style={s.stubLabel}>Customer</Text>
            <Text style={s.stubValue}>{bill_to.name}</Text>
          </View>
          <View style={s.stubRow}>
            <Text style={s.stubLabel}>Invoice #</Text>
            <Text style={s.stubValue}>{header.invoice_number}</Text>
          </View>
          <View style={s.stubRow}>
            <Text style={s.stubLabel}>Outstanding Balance</Text>
            <Text style={s.stubValue}>{fmt(header.outstanding_balance)}</Text>
          </View>
          <View style={[s.stubRow, { borderBottomWidth: 0 }]}>
            <Text style={[s.stubLabel, { fontFamily: font.bold }]}>Total Due</Text>
            <Text style={[s.stubValue, { fontFamily: font.bold, color: colors.brand }]}>{fmt(totals.total_due)}</Text>
          </View>
        </View>

        {/* Sticky pay bar at bottom of scroll for mobile */}
        {canPay && (
          <TouchableOpacity
            style={s.stickyPayBar}
            onPress={handlePayNow}
            disabled={payLoading}
            testID="magic-invoice-mobile-pay-btn"
          >
            {payLoading ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <>
                <Ionicons name="card" size={18} color="#fff" />
                <Text style={s.stickyPayText}>Pay {fmt(totals.total_due)}</Text>
              </>
            )}
          </TouchableOpacity>
        )}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F8FAFC" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, padding: 24 },
  loadingText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: 12 },
  errorTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: "#991B1B", marginTop: 12 },
  errorBody: { fontFamily: font.regular, fontSize: fontSize.base, color: "#6B7280", marginTop: 8, textAlign: "center", lineHeight: 22, paddingHorizontal: 20 },
  errorText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.error, marginTop: 8, textAlign: "center" },
  retryBtn: { marginTop: 16, paddingHorizontal: 24, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.brand },
  retryBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  navBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  navTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  errorBanner: { backgroundColor: "#FEF2F2", borderBottomWidth: 1, borderBottomColor: "#FCA5A5", paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  errorBannerText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#991B1B" },
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
  totalDue: { fontFamily: font.bold, fontSize: 28, color: colors.brand },
  totalLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  metaRow: { flexDirection: "row", justifyContent: "space-between", marginTop: spacing.lg, paddingTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.border },
  metaItem: { alignItems: "center" },
  metaLabel: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  metaValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2 },
  saveCardRow: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border },
  saveCardLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface, flex: 1 },
  payBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: "#059669", paddingVertical: 16, borderRadius: radius.md, marginBottom: spacing.md },
  payBtnText: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#fff" },
  companyName: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  billName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  muted: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  lineRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border },
  lineDesc: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, flex: 1 },
  lineRight: { alignItems: "flex-end", marginLeft: 12 },
  lineQty: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  lineTotal: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2 },
  notesText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 22 },
  stubRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.border },
  stubLabel: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  stubValue: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  stickyPayBar: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: "#059669", paddingVertical: 16, borderRadius: radius.md, marginTop: spacing.md },
  stickyPayText: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#fff" },
});
