import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Alert, Share, Platform,
  Modal, Pressable, FlatList, ActivityIndicator } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import * as Linking from "expo-linking";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useStripeConfig } from "@/src/config/stripe";
import { useToast } from "@/src/components/ToastProvider";
import { writeCache, readCache } from "@/src/services/readCache";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, StatusChip, PrimaryButton } from "@/src/components/ui";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import { Header, IconButton } from "@/src/components/widgets";
import { exportInvoicePdf } from "@/src/utils/exportInvoicePdf";
import { StripeUnconfiguredNotice } from "@/src/lib/stripeConfig";
import { useBusinessSettings } from "@/src/hooks/useBusinessSettings";
import SendToCustomerSheet from "@/src/components/quotes/SendToCustomerSheet";
import { mapApiError, errorKindIcon } from "@/src/utils/mapApiError";
import ConvertToInvoiceButton from "@/src/components/quotes/ConvertToInvoiceButton";
import { RecipientTypeBadge } from "@/src/components/quotes/QuoteRecipientPicker";
import {
  canUserDeclineOrReopenQuote,
  shouldShowDeclineButton,
  shouldShowReopenButton,
  shouldHideConvertWhenDeclined,
} from "@/src/utils/quoteLifecycle";
import AppTextInput from "@/src/components/ui/AppTextInput";

export default function QuoteDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const { stripeConfigured } = useStripeConfig();
  const router = useRouter();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin" || user?.role === "manager";
  const canDuplicate = user?.role === "admin" || user?.role === "super_admin";
  const insets = useSafeAreaInsets();
  const { showToast } = useToast();

  // Theme refresh — tenant branding
  const { branding } = useBusinessSettings();
  const [q, setQ] = useState<any>(null);
  const [company, setCompany] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [rawLoadError, setRawLoadError] = useState<unknown>(null);
  const pollRef = useRef<any>(null);

  // ── Phase 3: Decline/Reopen lifecycle state ─────────────────
  const [lifecycleBusy, setLifecycleBusy] = useState(false);
  const canLifecycle = canUserDeclineOrReopenQuote(user?.role);

  // ── Duplicate Quote state ──────────────────────────────────
  const [dupOpen, setDupOpen] = useState(false);

  // ── Send to Customer state ─────────────────────────────────
  const [sendOpen, setSendOpen] = useState(false);
  const [dupCustomers, setDupCustomers] = useState<any[]>([]);
  const [dupCustomer, setDupCustomer] = useState<any>(null);
  const [dupProperties, setDupProperties] = useState<any[]>([]);
  const [dupProperty, setDupProperty] = useState<any>(null);
  const [dupSearch, setDupSearch] = useState("");
  const [dupBusy, setDupBusy] = useState(false);
  const [dupError, setDupError] = useState("");
  const [dupCustLoading, setDupCustLoading] = useState(false);
  const [dupPropLoading, setDupPropLoading] = useState(false);
  const [dupPickingCustomer, setDupPickingCustomer] = useState(false);

  const load = useCallback(async () => {
    setLoadError("");
    setRawLoadError(null);
    try {
      const data = await api.get(`/quotes/${id}`);
      setQ(data);
      writeCache(`quote:${id}`, data).catch(() => {});
      if (!company) api.get("/card").then((r) => setCompany(r.company)).catch(() => {});
    } catch (e) {
      const cached = await readCache<any>(`quote:${id}`);
      if (cached) {
        setQ(cached);
      } else {
        setQ(null);
        setRawLoadError(e);
        setLoadError("Couldn't load quote.");
      }
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
            showToast("Payment received — thank you!");
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

  // Admin: request a direct Stripe Checkout Session URL to share with
  // the customer.
  //
  // Phase 47d · Feb-2026 — swapped from the mythical
  // ``/payments/admin/generate-link/{id}`` endpoint (which returned 404
  // — never existed in the backend) to the Phase-47 Stripe-direct
  // ``POST /invoices/{id}/request-payment-link`` route. Same response
  // shape (``{payment_url, checkout_session_id, ...}``) so the Share
  // sheet handoff is unchanged. Web + mobile now share the same code
  // path; no Lumino / Zapier round-trip.
  const generateLink = async () => {
    setBusy(true);
    try {
      const { payment_url } = await api.post(
        `/invoices/${id}/request-payment-link`,
      );
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
      showToast("Reminder sent — the customer was notified.");
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
      showToast(
        decision === "approve"
          ? "Estimate approved — our team will schedule your service shortly."
          : "Estimate declined — we've let the team know.",
        "success",
      );
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

  // ── Duplicate Quote logic ──────────────────────────────────
  const openDuplicate = async () => {
    setDupOpen(true);
    setDupError("");
    setDupSearch("");
    setDupPickingCustomer(false);
    // Pre-select source customer
    const srcCust = q.customer_id
      ? { id: q.customer_id, name: formatCustomerName(q) }
      : null;
    setDupCustomer(srcCust);
    setDupProperty(null);
    setDupProperties([]);
    // Fetch customers
    setDupCustLoading(true);
    try {
      const custs = await api.get("/customers");
      setDupCustomers(Array.isArray(custs) ? custs : custs?.items || []);
    } catch {
      setDupCustomers([]);
    } finally {
      setDupCustLoading(false);
    }
    // Fetch properties for source customer
    if (srcCust?.id) loadDupProperties(srcCust.id);
  };

  const loadDupProperties = async (cid: string) => {
    setDupPropLoading(true);
    setDupProperty(null);
    setDupProperties([]);
    try {
      const props = await api.get(`/customers/${cid}/properties`);
      const active = (Array.isArray(props) ? props : props?.items || []).filter(
        (p: any) => p.active !== false,
      );
      setDupProperties(active);
      if (active.length > 0) setDupProperty(active[0]);
    } catch {
      setDupProperties([]);
    } finally {
      setDupPropLoading(false);
    }
  };

  const selectDupCustomer = (c: any) => {
    setDupCustomer(c);
    setDupPickingCustomer(false);
    setDupSearch("");
    setDupError("");
    loadDupProperties(c.id);
  };

  const submitDuplicate = async () => {
    if (!dupCustomer?.id) {
      setDupError("Select a customer.");
      return;
    }
    setDupBusy(true);
    setDupError("");
    try {
      const body: any = { customer_id: dupCustomer.id };
      if (dupProperty?.id) body.property_id = dupProperty.id;
      const res = await api.post(`/quotes/${id}/duplicate`, body);
      setDupOpen(false);
      const num = res.quote_number || res.quote_id?.slice(0, 8) || "new";
      showToast(`Quote duplicated as draft #${num}.`);
      router.push(`/quote/${res.quote_id}` as any);
    } catch (e: any) {
      setDupError(e?.message || "Duplicate failed.");
    } finally {
      setDupBusy(false);
    }
  };

  const closeDuplicate = () => {
    setDupOpen(false);
    setDupError("");
  };

  // ── Phase 3: Decline handler ────────────────────────────────
  const handleDeclineQuote = () => {
    if (lifecycleBusy) return;
    Alert.alert(
      "Decline Quote",
      "Decline this quote? You can reopen it later.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Decline",
          style: "destructive",
          onPress: async () => {
            setLifecycleBusy(true);
            try {
              await api.post(`/quotes/${id}/decline`, {});
              showToast("Quote declined", "success");
              await load();
            } catch (e: any) {
              const code = e?.detail?.code;
              if (code === "already_declined") {
                showToast("Already declined", "info");
                await load();
              } else if (code === "already_converted") {
                const invId = e?.detail?.invoice_id;
                showToast(
                  `Already converted to invoice${invId ? ` ${invId}` : ""}`,
                  "info",
                );
                await load();
              } else {
                showToast(e?.message || "Decline failed", "error");
              }
            } finally {
              setLifecycleBusy(false);
            }
          },
        },
      ],
    );
  };

  // ── Phase 3: Reopen handler ─────────────────────────────────
  const handleReopenQuote = () => {
    if (lifecycleBusy) return;
    Alert.alert(
      "Reopen Quote",
      "Reopen this quote?",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Reopen",
          onPress: async () => {
            setLifecycleBusy(true);
            try {
              await api.post(`/quotes/${id}/reopen`, {});
              showToast("Quote reopened", "success");
              await load();
            } catch (e: any) {
              const code = e?.detail?.code;
              if (code === "not_declined") {
                showToast("Not currently declined", "info");
                await load();
              } else {
                showToast(e?.message || "Reopen failed", "error");
              }
            } finally {
              setLifecycleBusy(false);
            }
          },
        },
      ],
    );
  };

  if (loading) return <Loading testID="quote-detail-loading" />;
  if (!q && loadError) {
    const mapped = rawLoadError ? mapApiError(rawLoadError) : null;
    const icon = mapped ? errorKindIcon(mapped.kind) : "alert-circle-outline";
    return (
      <View style={styles.root} testID="quote-detail-error">
        <Header title="Quote" back />
        <View style={{ flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg }}>
          <Ionicons name={icon as any} size={48} color={colors.muted} />
          <Text style={{ fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginTop: spacing.md, textAlign: "center" }} testID="quote-detail-error-title">
            {mapped?.title || loadError}
          </Text>
          {mapped && mapped.message !== mapped.title && (
            <Text style={{ fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: spacing.sm, textAlign: "center" }} testID="quote-detail-error-message">
              {mapped.message}
            </Text>
          )}
          <Pressable
            style={{ marginTop: spacing.lg, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, backgroundColor: colors.brand, borderRadius: radius.md }}
            onPress={load}
            testID="quote-detail-retry-btn"
          >
            <Text style={{ fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" }}>Retry</Text>
          </Pressable>
        </View>
      </View>
    );
  }
  if (!q) return null;

  const isInvoice = q.doc_type === "invoice";
  const isCustomer = user?.role === "customer";
  const paid = q.payment_status === "paid";
  const decided = ["accepted", "declined", "scheduled"].includes(q.status);
  const brandPrimary = branding?.brand_primary_hex || "#0B4A6F";

  return (
    <View style={styles.root}>
      <Header
        title={isInvoice ? "Invoice" : "Quote"}
        back
        right={
          <View style={{ flexDirection: "row", gap: 8 }}>
            {canDuplicate && !isInvoice ? (
              <IconButton icon="copy-outline" onPress={openDuplicate} testID="duplicate-quote-btn" />
            ) : null}
            {isAdmin && !isInvoice ? (
              <IconButton icon="send-outline" onPress={() => setSendOpen(true)} testID="send-to-customer-btn" />
            ) : null}
            <IconButton icon="share-outline" onPress={exportPdf} testID="quote-share-pdf" />
          </View>
        }
      />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 140 }}>
        {/* Branded header band (Theme Refresh) */}
        <View style={[styles.brandBand, { backgroundColor: brandPrimary }]} testID="doc-branded-header-band">
          <View>
            <Text style={styles.brandBandLabel}>{isInvoice ? "INVOICE" : "QUOTE"}</Text>
            <Text style={styles.brandBandCompany}>
              {branding?.company_display_name || company?.name || q.tenant_name || ""}
            </Text>
          </View>
        </View>

        <View style={styles.headerCard}>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>{q.title}</Text>
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: 2 }}>
              <Text style={styles.customer}>{formatCustomerName(q)}</Text>
              {/* Phase 2 B2 — recipient-type badge (Customer/Lead) */}
              <RecipientTypeBadge
                type={q.recipient_type === "lead" ? "lead" : "customer"}
                testID="quote-recipient-type-badge"
              />
            </View>
          </View>
          <StatusChip status={paid ? "paid" : q.status} testID="quote-status-chip" />
        </View>

        {/* Phase 2 B2 — Lead-recipient invoice notice */}
        {isInvoice && q.recipient_type === "lead" ? (
          <View style={styles.leadInvoiceNotice} testID="invoice-lead-recipient-notice">
            <Text style={styles.leadInvoiceNoticeText}>
              Lead-recipient invoice — card-on-file autopay unavailable. Use 'Send hosted checkout' to collect payment.
            </Text>
          </View>
        ) : null}

        <View style={styles.card}>
          <Text style={styles.cardLabel}>Line Items</Text>
          {q.line_items?.map((li: any, idx: number) => (
            <View key={idx} style={styles.lineCard} testID={`quote-line-item-${idx}`}>
              <Text style={styles.liDesc}>{li.description}</Text>
              <Text style={styles.liMeta}>{li.quantity} × {money(li.unit_price)}</Text>
              <View style={styles.lineCardSubtotalRow}>
                <Text style={styles.lineCardSubtotalLabel}>Subtotal</Text>
                <Text style={styles.liTotal}>{money(li.quantity * li.unit_price)}</Text>
              </View>
            </View>
          ))}
          <View style={styles.totalsBox}>
            <TotalRow label="Subtotal" value={money(q.subtotal)} />
            <TotalRow label={`Tax (${q.tax_rate}%)`} value={money(q.tax)} />
            <TotalRow label="Total" value={money(q.total)} bold />
            {q.has_declined_lines ? (
              <View style={styles.dualTotalBox} testID="quote-invoice-effective-total">
                <View style={styles.totalRow}>
                  <Text style={styles.dualTotalLabel}>Subtotal (incl. declined)</Text>
                  <Text style={styles.dualTotalValue}>{money(q.original_total ?? q.total)}</Text>
                </View>
                <View style={styles.totalRow}>
                  <Text style={styles.dualTotalEffLabel}>Effective (excl. declined)</Text>
                  <Text style={styles.dualTotalEffValue} testID="quote-invoice-effective-total-value">{money(q.adjusted_total ?? q.total)}</Text>
                </View>
              </View>
            ) : null}
          </View>
        </View>

        <View style={styles.payStatus}>
          <Ionicons name={paid ? "checkmark-circle" : "time-outline"} size={20} color={paid ? colors.success : colors.warning} />
          <Text style={[styles.payStatusText, { color: paid ? colors.success : colors.onSurfaceSecondary }]}>
            {paid ? "Payment received" : "Payment pending"}
          </Text>
        </View>

        {/* Convert to Invoice — admin/owner/manager only, quote docs only.
            Phase 3: HIDDEN when status === "declined" (mirrors backend guard). */}
        {!isInvoice && q.id && !shouldHideConvertWhenDeclined(q.status) ? (
          <View style={{ marginBottom: spacing.md }}>
            <ConvertToInvoiceButton
              docType="quote"
              docId={q.id}
              convertedInvoiceId={q.converted_invoice_id}
              userRole={user?.role}
              onConverted={() => load()}
            />
          </View>
        ) : null}

        {/* Phase 3: Decline button — visible on open quotes, role-gated */}
        {shouldShowDeclineButton({
          isInvoice,
          docStatus: q.status,
          convertedInvoiceId: q.converted_invoice_id,
          canDecline: canLifecycle,
        }) ? (
          <Pressable
            testID="qd-decline-quote"
            style={styles.declineBtn}
            onPress={handleDeclineQuote}
            disabled={lifecycleBusy}
          >
            <Ionicons name="close-circle-outline" size={18} color="#B91C1C" />
            <Text style={styles.declineBtnText}>Decline</Text>
          </Pressable>
        ) : null}

        {/* Phase 3: Reopen button — visible on declined quotes, role-gated */}
        {shouldShowReopenButton({
          isInvoice,
          docStatus: q.status,
          canReopen: canLifecycle,
        }) ? (
          <Pressable
            testID="qd-reopen-quote"
            style={styles.reopenBtn}
            onPress={handleReopenQuote}
            disabled={lifecycleBusy}
          >
            <Ionicons name="refresh-outline" size={18} color={colors.brand} />
            <Text style={styles.reopenBtnText}>Reopen</Text>
          </Pressable>
        ) : null}

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
              <ScrollView horizontal showsHorizontalScrollIndicator={true} style={{ marginHorizontal: -spacing.md }} contentContainerStyle={{ paddingHorizontal: spacing.md, minWidth: 480 }}>
                <View style={{ flex: 1 }}>
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
              </ScrollView>
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

        {/* Branded footer band (Theme Refresh) */}
        {branding?.footer_note ? (
          <View style={[styles.brandFooter, { backgroundColor: brandPrimary }]} testID="doc-branded-footer-band">
            <Text style={styles.brandFooterText}>{branding.footer_note}</Text>
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
          ) : !stripeConfigured ? (
            <StripeUnconfiguredNotice
              testID="quote-stripe-unconfigured"
              message="Online payments are not available. Contact support to enable Stripe."
            />
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

      {/* ── Send to Customer Sheet ──────────────────── */}
      <SendToCustomerSheet
        visible={sendOpen}
        quoteId={id as string}
        primaryEmail={q?.customer_email || q?.customer?.email}
        onClose={() => setSendOpen(false)}
        onSent={load}
      />

      {/* ── Duplicate Quote Modal ────────────────────────── */}
      <Modal visible={dupOpen} transparent animationType="fade" onRequestClose={closeDuplicate} testID="duplicate-quote-modal">
        <Pressable style={styles.dupOverlay} onPress={closeDuplicate} />
        <View style={styles.dupSheet} testID="duplicate-quote-sheet">
          <View style={styles.dupHeader}>
            <Text style={styles.dupTitle}>Duplicate Quote</Text>
            <Pressable onPress={closeDuplicate} hitSlop={10} testID="duplicate-quote-close">
              <Ionicons name="close" size={24} color={colors.onSurfaceSecondary} />
            </Pressable>
          </View>

          {/* Customer picker */}
          {dupPickingCustomer ? (
            <View style={styles.dupPickerArea} testID="duplicate-customer-picker">
              <AppTextInput
                style={styles.dupSearchInput}
                value={dupSearch}
                onChangeText={setDupSearch}
                placeholder="Search customers…"
                placeholderTextColor={colors.muted}
                autoFocus
                testID="duplicate-customer-search"
              />
              {dupCustLoading ? (
                <ActivityIndicator size="small" color={colors.brand} style={{ marginTop: 16 }} />
              ) : (
                <FlatList
                  data={dupCustomers.filter((c: any) =>
                    !dupSearch || (c.name || "").toLowerCase().includes(dupSearch.toLowerCase()),
                  )}
                  keyExtractor={(c: any) => c.id}
                  style={{ maxHeight: 220 }}
                  keyboardShouldPersistTaps="handled"
                  renderItem={({ item: c }) => (
                    <Pressable
                      style={styles.dupCustRow}
                      onPress={() => selectDupCustomer(c)}
                      testID={`duplicate-pick-customer-${c.id}`}
                    >
                      <Text style={styles.dupCustRowText}>{c.name}</Text>
                      {dupCustomer?.id === c.id ? (
                        <Ionicons name="checkmark" size={18} color={colors.brand} />
                      ) : null}
                    </Pressable>
                  )}
                  ListEmptyComponent={
                    <Text style={styles.dupEmptyText}>No customers found.</Text>
                  }
                />
              )}
            </View>
          ) : (
            <>
              {/* Selected customer display */}
              <Text style={styles.dupLabel}>Customer</Text>
              <Pressable
                style={styles.dupSelector}
                onPress={() => setDupPickingCustomer(true)}
                testID="duplicate-customer-selector"
              >
                <Text style={[styles.dupSelectorText, !dupCustomer && { color: colors.muted }]}>
                  {dupCustomer?.name || "Select customer"}
                </Text>
                <Ionicons name="chevron-down" size={18} color={colors.muted} />
              </Pressable>

              {/* Property picker */}
              <Text style={styles.dupLabel}>Property</Text>
              {dupPropLoading ? (
                <ActivityIndicator size="small" color={colors.brand} style={{ marginVertical: 8 }} testID="duplicate-property-loading" />
              ) : dupProperties.length === 0 ? (
                <Text style={styles.dupHint} testID="duplicate-no-properties">
                  {dupCustomer ? "This customer has no active properties." : "Select a customer first."}
                </Text>
              ) : (
                <View>
                  {dupProperties.map((p: any) => (
                    <Pressable
                      key={p.id}
                      style={[
                        styles.dupPropRow,
                        dupProperty?.id === p.id && styles.dupPropRowActive,
                      ]}
                      onPress={() => setDupProperty(p)}
                      testID={`duplicate-pick-property-${p.id}`}
                    >
                      <Ionicons
                        name={dupProperty?.id === p.id ? "radio-button-on" : "radio-button-off"}
                        size={18}
                        color={dupProperty?.id === p.id ? colors.brand : colors.muted}
                      />
                      <Text style={styles.dupPropRowText}>
                        {typeof p.address === "string"
                          ? p.address
                          : p.address?.line1
                            ? [p.address.line1, p.address.city, p.address.state].filter(Boolean).join(", ")
                            : p.name || p.id?.slice(0, 8)}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              )}

              {/* Error */}
              {dupError ? (
                <Text style={styles.dupError} testID="duplicate-quote-error">{dupError}</Text>
              ) : null}

              {/* Actions */}
              <View style={styles.dupActions}>
                <Pressable style={styles.dupCancelBtn} onPress={closeDuplicate} testID="duplicate-quote-cancel">
                  <Text style={styles.dupCancelText}>Cancel</Text>
                </Pressable>
                <Pressable
                  style={[styles.dupSubmitBtn, dupBusy && { opacity: 0.6 }]}
                  onPress={submitDuplicate}
                  disabled={dupBusy}
                  testID="duplicate-quote-submit"
                >
                  {dupBusy ? (
                    <ActivityIndicator size="small" color="#fff" />
                  ) : (
                    <>
                      <Ionicons name="copy-outline" size={16} color="#fff" />
                      <Text style={styles.dupSubmitText}>Duplicate</Text>
                    </>
                  )}
                </Pressable>
              </View>
            </>
          )}
        </View>
      </Modal>
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
  lineCard: { backgroundColor: "#F8FAFC", borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm },
  liDesc: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.onSurface },
  liMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  liTotal: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  lineCardSubtotalRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  lineCardSubtotalLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  totalsBox: { marginTop: spacing.md, gap: spacing.xs },
  dualTotalBox: {
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    gap: spacing.xs,
  },
  dualTotalLabel: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  dualTotalValue: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  dualTotalEffLabel: { fontFamily: font.bold, fontSize: fontSize.base, color: "#B45309" },
  dualTotalEffValue: { fontFamily: font.bold, fontSize: fontSize.base, color: "#B45309" },
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
  // Theme Refresh — branded header/footer bands
  brandBand: { borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md },
  brandBandLabel: { fontFamily: font.semibold, fontSize: 11, color: "rgba(255,255,255,0.8)", textTransform: "uppercase" as const, letterSpacing: 0.5 },
  brandBandCompany: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#fff", marginTop: 4 },
  brandFooter: { borderRadius: radius.md, paddingVertical: spacing.md, paddingHorizontal: spacing.lg, marginTop: spacing.md, marginBottom: spacing.md },
  brandFooterText: { fontFamily: font.regular, fontSize: fontSize.sm, color: "#fff", textAlign: "center" as const },
  // ── Duplicate Quote modal styles ───────────────────────────
  dupOverlay: {
    position: "absolute" as const, top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: "rgba(15,23,42,0.45)",
  },
  dupSheet: {
    position: "absolute" as const, bottom: 0, left: 0, right: 0,
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: 40,
    maxHeight: "80%" as any,
  },
  dupHeader: {
    flexDirection: "row" as const, alignItems: "center" as const,
    justifyContent: "space-between" as const, marginBottom: spacing.lg,
  },
  dupTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  dupLabel: {
    fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary,
    marginBottom: spacing.xs, marginTop: spacing.md,
    textTransform: "uppercase" as const, letterSpacing: 0.5,
  },
  dupSelector: {
    flexDirection: "row" as const, alignItems: "center" as const,
    justifyContent: "space-between" as const,
    backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48,
  },
  dupSelectorText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  dupPickerArea: { marginBottom: spacing.md },
  dupSearchInput: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, height: 44,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
  },
  dupCustRow: {
    flexDirection: "row" as const, alignItems: "center" as const,
    justifyContent: "space-between" as const,
    paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  dupCustRowText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  dupEmptyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" as const, marginTop: spacing.lg },
  dupPropRow: {
    flexDirection: "row" as const, alignItems: "center" as const, gap: spacing.sm,
    paddingVertical: 10, paddingHorizontal: spacing.sm,
    borderRadius: radius.sm, marginVertical: 2,
  },
  dupPropRowActive: { backgroundColor: "#EFF6FF" },
  dupPropRowText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, flex: 1 },
  dupHint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginVertical: spacing.sm, fontStyle: "italic" as const },
  dupError: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error, marginTop: spacing.sm },
  dupActions: {
    flexDirection: "row" as const, justifyContent: "flex-end" as const,
    gap: spacing.sm, marginTop: spacing.xl,
  },
  dupCancelBtn: {
    paddingHorizontal: 20, paddingVertical: 12, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
  },
  dupCancelText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurfaceSecondary },
  dupSubmitBtn: {
    flexDirection: "row" as const, alignItems: "center" as const, gap: 6,
    paddingHorizontal: 20, paddingVertical: 12, borderRadius: radius.md,
    backgroundColor: colors.brand,
  },
  dupSubmitText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  // Phase 2 B2 — Lead-recipient invoice notice
  leadInvoiceNotice: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    marginBottom: spacing.md,
  },
  leadInvoiceNoticeText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurfaceSecondary,
  },
  // Phase 3: Decline / Reopen buttons on detail
  declineBtn: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    justifyContent: "center" as const,
    gap: 8,
    backgroundColor: "#FEE2E2",
    borderRadius: radius.md,
    paddingVertical: 12,
    paddingHorizontal: 20,
    minHeight: 48,
    marginBottom: spacing.md,
  },
  declineBtnText: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: "#B91C1C",
  },
  reopenBtn: {
    flexDirection: "row" as const,
    alignItems: "center" as const,
    justifyContent: "center" as const,
    gap: 8,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    paddingVertical: 12,
    paddingHorizontal: 20,
    minHeight: 48,
    marginBottom: spacing.md,
  },
  reopenBtnText: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: colors.brand,
  },
});
