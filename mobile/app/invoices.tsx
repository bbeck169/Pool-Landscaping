import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { writeCache, readCache } from "@/src/services/readCache";
import { colors, spacing, radius, font, fontSize, money, statusMeta } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { Loading, EmptyState, StatusChip, Sheet, PrimaryButton } from "@/src/components/ui";
import { Header, FilterRow } from "@/src/components/widgets";
import { useBulkSelect, BulkCheckbox, BulkActionBar } from "@/src/components/bulk-select/BulkSelectToolkit";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import AppTextInput from "@/src/components/ui/AppTextInput";

Object.assign(statusMeta, {
  pending: { label: "Pending", bg: "#FEF9C3", fg: "#A16207" },
  overdue: { label: "Past Due", bg: "#FEE2E2", fg: "#DC2626" },
  partial: { label: "Partial", bg: "#FFEDD5", fg: "#C2410C" },
});

const FILTERS = [
  // Phase K40 · Feb-2026 — "All" is now the default. "Outstanding"
  // stays as a legacy pass-through chip; both bypass the boolean
  // field filter (see filter loop in ``load``).
  { key: "all", label: "All" },
  { key: "outstanding", label: "Outstanding" },
  { key: "pending", label: "Pending" },
  { key: "past_due", label: "Past Due" },
  { key: "partial", label: "Partial" },
  { key: "charge_failed", label: "Failed" },
];

export default function Invoices() {
  const router = useRouter();
  const { showToast } = useToast();
  const [data, setData] = useState<any>({ summary: null, invoices: [] });
  const [filter, setFilter] = useState("all");
  const params = useLocalSearchParams<{ customer_id?: string }>();
  const [custFilter, setCustFilter] = useState<string | null>(
    params.customer_id ? String(params.customer_id) : null,
  );
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [payFor, setPayFor] = useState<any>(null);
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectMode, setSelectMode] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await api.get("/invoices/overview");
      setData(d);
      writeCache("invoices:overview", d).catch(() => {});
    } catch {
      const cached = await readCache<any>("invoices:overview");
      setData(cached ?? { summary: null, invoices: [] });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Phase K40 · Feb-2026 — treat both ``"all"`` (the K40 default) and
  // ``"outstanding"`` (legacy shortcut) as "no filter" pass-through.
  // Any other value maps to a boolean field on the invoice row
  // (``pending``, ``paid``, ``overdue`` …).
  const invoices = (data.invoices || []).filter((i: any) =>
    (filter === "all" || filter === "outstanding" ? true : i[filter]) &&
    // TD-79 — `/invoices?customer_id=<cid>` (customer Overview "View all").
    // `/invoices/overview` has no customer param, so filter client-side.
    (!custFilter || i.customer_id === custFilter),
  );
  const visibleIds = invoices.map((i: any) => i.id);
  const bulk = useBulkSelect(visibleIds);
  const exitSelectMode = () => { setSelectMode(false); bulk.clear(); };

  const bulkMarkPaid = async () => {
    Alert.alert(`Mark ${bulk.count} invoice${bulk.count !== 1 ? "s" : ""} as paid?`, "", [
      { text: "Cancel", style: "cancel" },
      { text: "Confirm", onPress: async () => {
        try {
          await api.post("/invoices/bulk-mark-paid", { ids: [...bulk.selected] });
          showToast(`${bulk.count} invoice${bulk.count !== 1 ? "s" : ""} marked as paid.`);
          exitSelectMode(); load();
        } catch (e: any) { Alert.alert("Error", e?.message || "Failed"); }
      }},
    ]);
  };

  // Phase K38 · Feb-2026 — Bulk Charge ACH on File. Mirrors the web
  // confirmation flow: shows the verbatim 3–5 business day settlement
  // warning, then submits the ACH bulk endpoint (dry_run=false).
  const [bulkAchBusy, setBulkAchBusy] = useState(false);
  const bulkChargeAch = () => {
    const ids = [...bulk.selected];
    if (!ids.length || bulkAchBusy) return;
    const key = `ach-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    Alert.alert(
      `Charge ACH for ${ids.length} invoice${ids.length !== 1 ? "s" : ""}?`,
      // K38 · Feb-2026 — verbatim test-fixture anchor. DO NOT paraphrase.
      "ACH payments take 3\u20135 business days to settle. Charges may still fail after submission (NSF, closed account, or incorrect routing). Failed charges will revert the invoice to Unpaid.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Submit ACH",
          onPress: async () => {
            setBulkAchBusy(true);
            try {
              const res = await api.post("/invoices/bulk-charge-ach-on-file", {
                invoice_ids: ids,
                dry_run: false,
                idempotency_key: key,
              });
              const s = (res && res.summary) || {};
              const initiated = s.initiated || 0;
              const skipped = s.skipped || 0;
              const failed = s.failed || 0;
              Alert.alert(
                "ACH submissions sent",
                `${initiated} initiated · ${skipped} skipped · ${failed} failed`,
              );
              exitSelectMode();
              load();
            } catch (e: any) {
              Alert.alert("ACH bulk charge failed", e?.message || "Failed");
            } finally {
              setBulkAchBusy(false);
            }
          },
        },
      ],
    );
  };

  const openPay = (inv: any) => {
    setPayFor(inv);
    setAmount(String(inv.balance));
  };

  const recordPayment = async () => {
    const amt = parseFloat(amount);
    if (!amt || amt <= 0) return Alert.alert("Invalid amount", "Enter an amount greater than zero.");
    setBusy(true);
    try {
      await api.post(`/quotes/${payFor.id}/record-payment`, { amount: amt });
      setPayFor(null);
      await load();
      showToast("Payment recorded");
    } catch (e: any) {
      Alert.alert("Failed", e.message);
    } finally {
      setBusy(false);
    }
  };

  const [chargingId, setChargingId] = useState<string | null>(null);
  const chargeOnFile = (inv: any) => {
    Alert.alert(
      "Charge card on file?",
      `Charge ${inv.pm_label} for the ${money(inv.balance)} balance on "${inv.title}"?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Charge",
          onPress: async () => {
            setChargingId(inv.id);
            try {
              const r = await api.post(`/payments/charge-on-file/${inv.id}`, {});
              await load();
              if (r.status === "succeeded") showToast(`${inv.pm_label} charged ${money(r.amount)}.`);
              else if (r.status === "processing") Alert.alert("ACH processing ⏳", "The bank payment is processing and will settle in a few days.");
              else if (r.status === "requires_action") Alert.alert("Action needed", "The customer must authenticate this payment in their portal.");
              else Alert.alert("Status", r.status);
            } catch (e: any) {
              Alert.alert("Charge failed", e.message);
            } finally {
              setChargingId(null);
            }
          },
        },
      ]
    );
  };

  const requestMethod = async (inv: any) => {
    try {
      await api.post(`/payments/request-method/${inv.customer_id}`, {});
      showToast(`${formatCustomerName(inv)} was asked to add a card/bank on file.`);
    } catch (e: any) {
      Alert.alert("Failed", e.message);
    }
  };

  const [remindingId, setRemindingId] = useState<string | null>(null);
  const sendReminder = async (inv: any) => {
    setRemindingId(inv.id);
    try {
      const r = await api.post(`/quotes/${inv.id}/send-reminder`, {});
      await load();
      Alert.alert(
        "Reminder sent ✅",
        `${formatCustomerName(inv)} was notified in-app${r.email_sent ? " and by email" : ""}.` +
          (r.email_sent ? "" : "\n(Email/SMS delivery not configured — logged only.)")
      );
    } catch (e: any) {
      Alert.alert("Failed", e.message);
    } finally {
      setRemindingId(null);
    }
  };

  const s = data.summary;
  const stat = (key: string) => (s ? s[key] : { count: 0, amount: 0 });

  const chipFor = (inv: any) => (inv.past_due ? "overdue" : inv.partial ? "partial" : "pending");
  const dueLabel = (inv: any) => {
    if (!inv.due_date) return "No due date";
    try {
      const d = new Date(inv.due_date + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
      return inv.past_due ? `Overdue · was due ${d}` : `Due ${d}`;
    } catch { return inv.due_date; }
  };

  return (
    <View style={styles.root}>
      <Header title="Invoices" back subtitle="Accounts receivable" />

      {s ? (
        <View style={styles.summaryRow}>
          <SummaryCard label="Pending" data={stat("pending")} color="#A16207" active={filter === "pending"} onPress={() => setFilter("pending")} testID="inv-sum-pending" />
          <SummaryCard label="Past Due" data={stat("past_due")} color="#DC2626" active={filter === "past_due"} onPress={() => setFilter("past_due")} testID="inv-sum-pastdue" />
          <SummaryCard label="Partial" data={stat("partial")} color="#C2410C" active={filter === "partial"} onPress={() => setFilter("partial")} testID="inv-sum-partial" />
        </View>
      ) : null}

      <FilterRow options={FILTERS} value={filter} onChange={setFilter} testID="invoices-filter" />

      {custFilter ? (
        <View style={styles.custChip} testID="invoices-customer-filter-chip">
          <Ionicons name="person-outline" size={14} color={colors.brand} />
          <Text style={styles.custChipText} numberOfLines={1}>
            {(() => {
              const first = (data.invoices || []).find((i: any) => i.customer_id === custFilter);
              return first ? `Customer: ${formatCustomerName(first)}` : "Customer filter";
            })()}
          </Text>
          <Pressable
            onPress={() => setCustFilter(null)}
            hitSlop={12}
            accessibilityLabel="Clear customer filter"
            testID="invoices-customer-filter-clear"
          >
            <Ionicons name="close-circle" size={18} color={colors.muted} />
          </Pressable>
        </View>
      ) : null}

      {s && s.failed && s.failed.count > 0 ? (
        <Pressable style={styles.failBanner} onPress={() => setFilter("charge_failed")} testID="invoices-fail-banner">
          <Ionicons name="alert-circle" size={18} color="#fff" />
          <Text style={styles.failBannerText}>
            {s.failed.count} auto-charge{s.failed.count > 1 ? "s" : ""} failed · {money(s.failed.amount)} needs attention
          </Text>
          <Ionicons name="chevron-forward" size={16} color="#fff" />
        </Pressable>
      ) : null}

      {loading ? (
        <Loading testID="invoices-loading" />
      ) : invoices.length === 0 ? (
        <EmptyState icon="checkmark-done-circle-outline" title="All clear" subtitle="No invoices in this bucket." testID="invoices-empty" />
      ) : (
        <FlatList
          testID="invoices-list"
          data={invoices}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <View style={[styles.card, bulk.selected.has(item.id) && { borderColor: colors.brand, backgroundColor: colors.brandTertiary }]} testID={`invoice-${item.id}`}>
              <Pressable
                onPress={() => selectMode ? bulk.toggleOne(item.id) : router.push(`/quote/${item.id}`)}
                onLongPress={() => { if (!selectMode) { setSelectMode(true); bulk.toggleOne(item.id); } }}
              >
                <View style={styles.topRow}>
                  {selectMode ? <BulkCheckbox checked={bulk.selected.has(item.id)} onPress={() => bulk.toggleOne(item.id)} /> : null}
                  <Text style={[styles.title, { flex: 1 }]} numberOfLines={1}>{item.title}</Text>
                  <StatusChip status={chipFor(item)} />
                </View>
                <Text style={styles.customer}>{formatCustomerName(item)}</Text>
                <Text style={[styles.due, item.past_due && { color: colors.error }]}>{dueLabel(item)}</Text>
                {/* Phase K47 · Feb-2026 — "Viewed Nd ago" indicator.
                    Reads the denormalised aggregate fields off the
                    invoice doc; if the overview endpoint hasn't
                    been backfilled with these fields yet the pill
                    simply doesn't render (graceful). */}
                {item.first_viewed_at ? (
                  <View style={styles.viewedRow} testID={`invoice-viewed-${item.id}`}>
                    <Ionicons name="eye-outline" size={12} color={colors.onSurfaceSecondary} />
                    <Text style={styles.viewedText}>
                      Viewed {(() => {
                        const iso = item.last_viewed_at || item.first_viewed_at;
                        const ts = Date.parse(iso);
                        if (Number.isNaN(ts)) return "recently";
                        const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
                        if (diffSec < 60) return `${diffSec}s ago`;
                        const m = Math.floor(diffSec / 60);
                        if (m < 60) return `${m}m ago`;
                        const h = Math.floor(m / 60);
                        if (h < 24) return `${h}h ago`;
                        const d = Math.floor(h / 24);
                        if (d < 30) return `${d}d ago`;
                        return `${Math.floor(d / 30)}mo ago`;
                      })()}
                      {item.view_count > 1 ? ` · ${item.view_count}×` : ""}
                    </Text>
                  </View>
                ) : null}
                <View style={styles.amountRow}>
                  <View>
                    <Text style={styles.balanceLabel}>Balance due</Text>
                    <Text style={styles.balance}>{money(item.balance)}</Text>
                  </View>
                  <Text style={styles.total}>of {money(item.total)}{item.amount_paid > 0 ? ` · paid ${money(item.amount_paid)}` : ""}</Text>
                </View>
              </Pressable>
              {item.charge_failed ? (
                <View style={styles.failStrip} testID={`invoice-failed-${item.id}`}>
                  <Ionicons name="warning" size={15} color="#B91C1C" />
                  <Text style={styles.failStripText}>Auto-charge failed{item.charge_error ? ` — ${item.charge_error}` : ""}</Text>
                </View>
              ) : null}
              {item.processing ? (
                <View style={styles.processing}>
                  <Ionicons name="hourglass-outline" size={15} color="#C2410C" />
                  <Text style={styles.processingText}>ACH payment processing…</Text>
                </View>
              ) : item.has_payment_method ? (
                <Pressable style={styles.chargeBtn} onPress={() => chargeOnFile(item)} disabled={chargingId === item.id} testID={`invoice-charge-${item.id}`}>
                  <Ionicons name={chargingId === item.id ? "hourglass-outline" : "flash"} size={16} color="#fff" />
                  <Text style={styles.chargeText}>Charge {item.pm_label}</Text>
                </Pressable>
              ) : (
                <Pressable style={styles.requestBtn} onPress={() => requestMethod(item)} testID={`invoice-request-${item.id}`}>
                  <Ionicons name="card-outline" size={16} color={colors.warning} />
                  <Text style={styles.requestText}>No card on file — request one</Text>
                </Pressable>
              )}
              <View style={styles.actionRow}>
                <Pressable style={[styles.payBtn, { flex: 1 }]} onPress={() => openPay(item)} testID={`invoice-pay-${item.id}`}>
                  <Ionicons name="cash-outline" size={16} color="#fff" />
                  <Text style={styles.payText}>Record Payment</Text>
                </Pressable>
                <Pressable style={[styles.remindBtn, item.past_due && styles.remindBtnUrgent]} onPress={() => sendReminder(item)} disabled={remindingId === item.id} testID={`invoice-remind-${item.id}`}>
                  <Ionicons name={remindingId === item.id ? "hourglass-outline" : "notifications-outline"} size={16} color={item.past_due ? "#fff" : colors.brand} />
                  <Text style={[styles.remindText, item.past_due && { color: "#fff" }]}>Remind</Text>
                </Pressable>
              </View>
              {item.reminder_count > 0 ? (
                <Text style={styles.remindMeta}>Reminded {item.reminder_count}× · last {new Date(item.last_reminder_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</Text>
              ) : null}
            </View>
          )}
        />
      )}

      <Sheet visible={!!payFor} onClose={() => setPayFor(null)} title="Record Payment" testID="invoice-pay-sheet">
        {payFor ? (
          <>
            <Text style={styles.paySub}>{payFor.title} · {formatCustomerName(payFor)}</Text>
            <Text style={styles.paySub}>Balance due: {money(payFor.balance)}</Text>
            <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>AMOUNT RECEIVED ($)</Text>
            <AppTextInput style={styles.input} value={amount} onChangeText={setAmount} keyboardType="decimal-pad" placeholderTextColor={colors.muted} testID="invoice-pay-amount" />
            <Text style={styles.hint}>Enter a partial amount to mark the invoice partially paid, or the full balance to close it.</Text>
            <View style={{ height: spacing.md }} />
            <PrimaryButton title="Save Payment" icon="checkmark" loading={busy} onPress={recordPayment} testID="invoice-pay-confirm" />
          </>
        ) : null}
      </Sheet>
      <BulkActionBar
        count={bulk.count}
        onClear={exitSelectMode}
        actions={[
          { key: "bulk-mark-paid-invoices", label: "Mark Paid", icon: "checkmark-circle-outline", tone: "primary", onPress: bulkMarkPaid },
          { key: "bulk-charge-ach-invoices", label: "Charge ACH", icon: "business-outline", tone: "primary", onPress: bulkChargeAch },
        ]}
      />
    </View>
  );
}

function SummaryCard({ label, data, color, active, onPress, testID }: any) {
  return (
    <Pressable style={[styles.sumCard, active && { borderColor: color, borderWidth: 2 }]} onPress={onPress} testID={testID}>
      <Text style={[styles.sumCount, { color }]}>{data.count}</Text>
      <Text style={styles.sumLabel}>{label}</Text>
      <Text style={styles.sumAmount}>{money(data.amount)}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  summaryRow: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  sumCard: { flex: 1, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, alignItems: "center", gap: 2 },
  sumCount: { fontFamily: font.bold, fontSize: fontSize["2xl"] },
  sumLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  sumAmount: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md, gap: 4 },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: spacing.sm },
  title: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  customer: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  due: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 2 },
  viewedRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  viewedText: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.onSurfaceSecondary },
  amountRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-end", marginTop: spacing.sm },
  balanceLabel: { fontFamily: font.regular, fontSize: 11, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  balance: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  total: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  payBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.brand, height: 42, borderRadius: radius.md, marginTop: spacing.sm },
  payText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  actionRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  chargeBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.success, height: 44, borderRadius: radius.md, marginTop: spacing.md },
  chargeText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  requestBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 44, borderRadius: radius.md, marginTop: spacing.md, borderWidth: 1.5, borderColor: colors.warning, backgroundColor: "#FFFBEB" },
  requestText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#B45309" },
  processing: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 44, borderRadius: radius.md, marginTop: spacing.md, backgroundColor: "#FFEDD5" },
  processingText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#C2410C" },
  remindBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 42, paddingHorizontal: spacing.lg, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.brand, backgroundColor: colors.surface },
  remindBtnUrgent: { backgroundColor: colors.error, borderColor: colors.error },
  remindText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  remindMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 6 },
  paySub: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, marginTop: 2 },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 6, lineHeight: 18 },
  custChip: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm, alignSelf: "flex-start",
    marginHorizontal: spacing.lg, marginTop: spacing.sm, paddingHorizontal: spacing.md, minHeight: 36,
    borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  custChipText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface, maxWidth: 240 },
  failBanner: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.error, marginHorizontal: spacing.lg, marginTop: spacing.sm, paddingHorizontal: spacing.md, height: 44, borderRadius: radius.md },
  failBannerText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  failStrip: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#FEE2E2", borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 8, marginTop: spacing.md },
  failStripText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.sm, color: "#B91C1C" },
});
