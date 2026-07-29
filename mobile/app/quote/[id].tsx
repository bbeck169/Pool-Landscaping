import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Alert, Share, Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import * as Linking from "expo-linking";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, StatusChip, PrimaryButton } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { exportInvoicePdf } from "@/src/utils/exportInvoicePdf";

export default function QuoteDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin" || user?.role === "manager";
  const insets = useSafeAreaInsets();
  const [q, setQ] = useState<any>(null);
  const [company, setCompany] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<any>(null);

  const load = useCallback(async () => {
    try {
      setQ(await api.get(`/quotes/${id}`));
      if (!company) api.get("/card").then((r) => setCompany(r.company)).catch(() => {});
    } finally {
      setLoading(false);
    }
  }, [id, company]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  // Customer: pay online via Stripe Checkout (in-app browser + polling)
  const payOnline = async () => {
    setBusy(true);
    try {
      const returnUrl = Linking.createURL("/payment-complete");
      const { url, session_id } = await api.post(`/payments/checkout/${id}`, {
        success_url: returnUrl,
        cancel_url: returnUrl,
      });
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const res = await api.get(`/payments/status/${session_id}`);
          if (res.status === "paid") {
            clearInterval(pollRef.current);
            pollRef.current = null;
            if (Platform.OS !== "web") WebBrowser.dismissBrowser();
            await load();
            Alert.alert("Payment received", "Thank you! Your invoice is now paid.");
          }
        } catch {}
      }, 3000);
      await WebBrowser.openBrowserAsync(url);
      // Final check in case the browser closed right after paying
      const res = await api.get(`/payments/status/${session_id}`);
      if (res.status === "paid") {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        await load();
      }
    } catch (e: any) {
      Alert.alert("Payment error", e?.message || "Could not start checkout.");
    } finally {
      setBusy(false);
    }
  };

  // Admin: generate a Stripe payment link to share with the customer
  const generateLink = async () => {
    setBusy(true);
    try {
      const { payment_url } = await api.post(`/payments/admin/generate-link/${id}`);
      await Share.share({ message: `Pay your invoice for ${q?.title}: ${payment_url}` });
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Could not create payment link.");
    } finally {
      setBusy(false);
    }
  };

  // Admin: record an offline/manual payment (cash, check, external card)
  const recordManual = async () => {
    Alert.alert("Record payment", "Mark this invoice as paid (manual/offline)?", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Mark Paid",
        onPress: async () => {
          setBusy(true);
          try {
            setQ(await api.post(`/quotes/${id}/pay`));
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  };

  // Admin: send a payment reminder (logged to the invoice's reminder history)
  const sendReminder = async () => {
    setBusy(true);
    try {
      await api.post(`/quotes/${id}/remind`);
      await load();
      Alert.alert("Reminder sent", "The customer was notified about this invoice.");
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Could not send reminder.");
    } finally {
      setBusy(false);
    }
  };

  const setStatus = async (status: string) => {
    setBusy(true);
    try {
      setQ(await api.put(`/quotes/${id}/status?status=${status}`));
    } finally {
      setBusy(false);
    }
  };

  // Customer: instant approve/decline of an online estimate
  const decide = async (decision: "approve" | "decline") => {
    setBusy(true);
    try {
      setQ(await api.post(`/quotes/${id}/decision?decision=${decision}`));
      Alert.alert(decision === "approve" ? "Estimate approved ✅" : "Estimate declined",
        decision === "approve" ? "Thanks! Our team will schedule your service shortly." : "No problem — we've let the team know.");
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Could not submit your decision.");
    } finally {
      setBusy(false);
    }
  };

  const exportPdf = async () => {
    try {
      await exportInvoicePdf(q, company);
    } catch (e: any) {
      Alert.alert("Export failed", e?.message || "Could not create the PDF.");
    }
  };

  if (loading) return <Loading testID="quote-detail-loading" />;
  if (!q) return null;

  const isInvoice = q.doc_type === "invoice";
  const isCustomer = user?.role === "customer";
  const paid = q.payment_status === "paid";
  const decided = ["accepted", "declined", "scheduled"].includes(q.status);

  return (
    <View style={styles.root}>
      <Header title={isInvoice ? "Invoice" : "Quote"} back right={<IconButton icon="share-outline" onPress={exportPdf} testID="quote-share-pdf" />} />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 140 }}>
        <View style={styles.headerCard}>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>{q.title}</Text>
            <Text style={styles.customer}>{q.customer_name}</Text>
          </View>
          <StatusChip status={paid ? "paid" : q.status} testID="quote-status-chip" />
        </View>

        <View style={styles.card}>
          <Text style={styles.cardLabel}>Line Items</Text>
          {q.line_items?.map((li: any, idx: number) => (
            <View key={idx} style={styles.lineItem}>
              <View style={{ flex: 1 }}>
                <Text style={styles.liDesc}>{li.description}</Text>
                <Text style={styles.liMeta}>{li.quantity} × {money(li.unit_price)}</Text>
              </View>
              <Text style={styles.liTotal}>{money(li.quantity * li.unit_price)}</Text>
            </View>
          ))}
          <View style={styles.totalsBox}>
            <TotalRow label="Subtotal" value={money(q.subtotal)} />
            <TotalRow label={`Tax (${q.tax_rate}%)`} value={money(q.tax)} />
            <TotalRow label="Total" value={money(q.total)} bold />
          </View>
        </View>

        <View style={styles.payStatus}>
          <Ionicons name={paid ? "checkmark-circle" : "time-outline"} size={20} color={paid ? colors.success : colors.warning} />
          <Text style={[styles.payStatusText, { color: paid ? colors.success : colors.onSurfaceSecondary }]}>
            {paid ? "Payment received" : "Payment pending"}
          </Text>
        </View>

        {/* PB1 · Internal Margin — admin/manager/super_admin ONLY.
            NEVER rendered for customer or technician roles. */}
        {isAdmin && isInvoice && q.line_items?.length ? (() => {
          const rows = q.line_items.map((li: any) => {
            const qty = Number(li.quantity || li.qty_hr || 1);
            const retail = Number(li.retail_price_snapshot ?? li.unit_price ?? 0);
            const wholesale = Number(li.wholesale_price_snapshot || 0);
            const labor = Number(li.labor_cost_snapshot || 0);
            return {
              description: li.description || li.name || "—",
              revenue: qty * retail,
              cogs: qty * wholesale,
              labor: qty * labor,
              profit: qty * (retail - wholesale - labor),
              wholesale_per: wholesale,
              labor_per: labor,
            };
          });
          const totRev = rows.reduce((s: number, r: any) => s + r.revenue, 0);
          const totCogs = rows.reduce((s: number, r: any) => s + r.cogs, 0);
          const totLabor = rows.reduce((s: number, r: any) => s + r.labor, 0);
          const totProfit = totRev - totCogs - totLabor;
          const margin = totRev > 0 ? (totProfit / totRev * 100).toFixed(1) : "0.0";
          return (
            <View style={styles.marginSection} testID="internal-margin-section">
              <Text style={styles.marginTitle}>
                Internal margin — not shown to customer
              </Text>
              <View style={styles.marginHdrRow}>
                <Text style={[styles.marginHdrCell, { flex: 2 }]}>Line</Text>
                <Text style={[styles.marginHdrCell, styles.marginRt]}>W/u</Text>
                <Text style={[styles.marginHdrCell, styles.marginRt]}>L/u</Text>
                <Text style={[styles.marginHdrCell, styles.marginRt]}>Rev</Text>
                <Text style={[styles.marginHdrCell, styles.marginRt]}>COGS</Text>
                <Text style={[styles.marginHdrCell, styles.marginRt]}>Profit</Text>
              </View>
              {rows.map((r: any, i: number) => (
                <View key={i} style={styles.marginDataRow} testID={`internal-margin-line-${i}`}>
                  <Text style={[styles.marginDataCell, { flex: 2 }]} numberOfLines={1}>
                    {r.description}
                  </Text>
                  <Text style={[styles.marginDataCell, styles.marginRt]}>{money(r.wholesale_per)}</Text>
                  <Text style={[styles.marginDataCell, styles.marginRt]}>{money(r.labor_per)}</Text>
                  <Text style={[styles.marginDataCell, styles.marginRt]}>{money(r.revenue)}</Text>
                  <Text style={[styles.marginDataCell, styles.marginRt, { color: "#B45309" }]}>
                    {money(r.cogs)}
                  </Text>
                  <Text style={[styles.marginDataCell, styles.marginRt, { fontFamily: font.semibold }]}>
                    {money(r.profit)}
                  </Text>
                </View>
              ))}
              <View style={styles.marginTotRow} testID="internal-margin-totals">
                <Text style={[styles.marginTotCell, { flex: 2 }]}>Totals</Text>
                <Text style={[styles.marginTotCell, styles.marginRt]} />
                <Text style={[styles.marginTotCell, styles.marginRt]} />
                <Text style={[styles.marginTotCell, styles.marginRt]}>{money(totRev)}</Text>
                <Text style={[styles.marginTotCell, styles.marginRt, { color: "#B45309" }]}>
                  {money(totCogs)}
                </Text>
                <Text style={[styles.marginTotCell, styles.marginRt]}>
                  {money(totProfit)} ({margin}%)
                </Text>
              </View>
            </View>
          );
        })() : null}

        {isAdmin && isInvoice && q.reminders?.length ? (
          <View style={styles.historyCard} testID="reminder-history">
            <Text style={styles.cardLabel}>Reminder History</Text>
            {[...q.reminders].reverse().map((r: any, idx: number) => (
              <View key={idx} style={styles.historyRow}>
                <Ionicons name="notifications-outline" size={16} color={colors.brand} />
                <Text style={styles.historyText}>
                  Reminder sent {fmtWhen(r.at)}{r.by ? ` by ${r.by}` : ""}
                </Text>
              </View>
            ))}
          </View>
        ) : null}
      </ScrollView>

      <View style={[styles.footer, { paddingBottom: insets.bottom + spacing.md }]}>
        {isInvoice && !paid ? (
          isAdmin ? (
            <View style={{ gap: spacing.sm }}>
              <PrimaryButton title="Send Payment Link" icon="link-outline" onPress={generateLink} loading={busy} testID="generate-link-button" />
              <View style={{ flexDirection: "row", gap: spacing.sm }}>
                <View style={{ flex: 1 }}>
                  <PrimaryButton title={q.reminders?.length ? "Remind Again" : "Send Reminder"} icon="notifications-outline" variant="outline" onPress={sendReminder} loading={busy} testID="send-reminder-button" />
                </View>
                <View style={{ flex: 1 }}>
                  <PrimaryButton title="Mark Paid" icon="cash-outline" variant="success" onPress={recordManual} loading={busy} testID="record-manual-button" />
                </View>
              </View>
            </View>
          ) : (
            <PrimaryButton title="Pay Now" icon="card-outline" onPress={payOnline} loading={busy} testID="pay-invoice-button" />
          )
        ) : isAdmin && !isInvoice && q.status === "draft" ? (
          <PrimaryButton title="Send Quote" icon="send-outline" onPress={() => setStatus("sent")} loading={busy} testID="send-quote-button" />
        ) : isAdmin && !isInvoice && q.status === "sent" ? (
          <PrimaryButton title="Mark Accepted" icon="checkmark-done" variant="success" onPress={() => setStatus("accepted")} loading={busy} testID="accept-quote-button" />
        ) : isCustomer && !isInvoice && !decided ? (
          <View style={{ flexDirection: "row", gap: spacing.sm }}>
            <View style={{ flex: 1 }}>
              <PrimaryButton title="Decline" icon="close" variant="outline" onPress={() => decide("decline")} loading={busy} testID="estimate-detail-decline" />
            </View>
            <View style={{ flex: 1 }}>
              <PrimaryButton title="Approve" icon="checkmark" variant="success" onPress={() => decide("approve")} loading={busy} testID="estimate-detail-approve" />
            </View>
          </View>
        ) : q.status === "declined" ? (
          <View style={styles.doneBanner}>
            <Ionicons name="close-circle" size={20} color={colors.error} />
            <Text style={[styles.doneText, { color: colors.error }]}>Estimate declined</Text>
          </View>
        ) : (
          <View style={styles.doneBanner}>
            <Ionicons name="checkmark-circle" size={20} color={colors.success} />
            <Text style={styles.doneText}>{paid ? "Paid" : "Completed"}</Text>
          </View>
        )}
      </View>
    </View>
  );
}

function fmtWhen(iso?: string) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  } catch {
    return "";
  }
}

function TotalRow({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <View style={styles.totalRow}>
      <Text style={[styles.totalLabel, bold && { fontFamily: font.bold, color: colors.onSurface, fontSize: fontSize.lg }]}>{label}</Text>
      <Text style={[styles.totalValue, bold && { fontFamily: font.bold, fontSize: fontSize.xl }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  headerCard: { flexDirection: "row", alignItems: "flex-start", marginBottom: spacing.md },
  title: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface },
  customer: { fontFamily: font.regular, fontSize: fontSize.lg, color: colors.muted, marginTop: 2 },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border },
  cardLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.muted, marginBottom: spacing.md, textTransform: "uppercase", letterSpacing: 0.5 },
  lineItem: { flexDirection: "row", alignItems: "center", paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider },
  liDesc: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.onSurface },
  liMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  liTotal: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  totalsBox: { marginTop: spacing.md, gap: spacing.xs },
  totalRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  totalLabel: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  totalValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  payStatus: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.lg },
  payStatusText: { fontFamily: font.semibold, fontSize: fontSize.base },
  historyCard: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginTop: spacing.lg },
  historyRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xs },
  historyText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  footer: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border,
    paddingHorizontal: spacing.lg, paddingTop: spacing.md,
  },
  doneBanner: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, height: 52 },
  doneText: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.success },
  // PB1 · Internal Margin styles
  marginSection: {
    marginTop: spacing.lg,
    borderRadius: radius.lg,
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
  marginHdrRow: {
    flexDirection: "row" as const,
    paddingVertical: 4,
    borderBottomWidth: 1,
    borderBottomColor: "#FCD34D",
  },
  marginHdrCell: {
    flex: 1,
    fontFamily: font.bold,
    fontSize: 10,
    color: "#92400E",
    textTransform: "uppercase" as const,
  },
  marginRt: { textAlign: "right" as const },
  marginDataRow: {
    flexDirection: "row" as const,
    paddingVertical: 4,
    borderBottomWidth: 1,
    borderBottomColor: "#FDEAB0",
  },
  marginDataCell: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: 11,
    color: "#78350F",
  },
  marginTotRow: {
    flexDirection: "row" as const,
    paddingVertical: 6,
    borderTopWidth: 1,
    borderTopColor: "#FCD34D",
    marginTop: 2,
  },
  marginTotCell: {
    flex: 1,
    fontFamily: font.bold,
    fontSize: 11,
    color: "#78350F",
  },
});
