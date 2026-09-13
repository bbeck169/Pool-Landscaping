/**
 * SubscriptionsSection — mobile parity for web SubscriptionsPanel.
 *
 * Mounted on Customer Detail beneath the payment-methods section.
 * Lists per-customer subscriptions with create / edit / cancel modals.
 * Online-only — shows offline banner + disabled actions when disconnected.
 */
import React, { useCallback, useState, useEffect } from "react";
import {
  View, Text, StyleSheet, Pressable, Modal, TextInput,
  Alert, Switch, ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import {
  listSubscriptions, listPrices, createSubscription,
  updateSubscription, cancelSubscription,
} from "@/src/api/subscriptions";
import type { SubRow, SubPrice } from "@/src/api/subscriptions";
import { listPaymentMethods } from "@/src/api/stripe";
import type { PaymentMethodRow as PMRow } from "@/src/api/stripe";
import { useOnline } from "@/src/offline";
import { useToast } from "@/src/components/ToastProvider";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

/* ═══════════ Helpers ═══════════ */

const STATUS_TONE: Record<string, { bg: string; fg: string }> = {
  active:              { bg: "#DCFCE7", fg: "#166534" },
  trialing:            { bg: "#DBEAFE", fg: "#1E40AF" },
  past_due:            { bg: "#FEF3C7", fg: "#854D0E" },
  unpaid:              { bg: "#FEF3C7", fg: "#854D0E" },
  canceled:            { bg: "#F3F4F6", fg: "#6B7280" },
  incomplete:          { bg: "#FEF3C7", fg: "#854D0E" },
  incomplete_expired:  { bg: "#F3F4F6", fg: "#6B7280" },
  paused:              { bg: "#F3F4F6", fg: "#6B7280" },
};

function StatusChip({ label }: { label: string }) {
  const t = STATUS_TONE[label] || { bg: "#F3F4F6", fg: "#6B7280" };
  return (
    <View style={[s.chip, { backgroundColor: t.bg }]}>
      <Text style={[s.chipText, { color: t.fg }]}>{label}</Text>
    </View>
  );
}

function fmtDate(iso?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric", month: "short", day: "numeric",
    });
  } catch { return "—"; }
}

function priceLabel(p: SubPrice): string {
  if (p.formatted_plan_label) return p.formatted_plan_label;
  const money = p.unit_amount != null
    ? `$${(p.unit_amount / 100).toFixed(2)}`
    : "";
  const interval = p.recurring?.interval || "";
  const suffix = interval ? `/${interval}` : "";
  return `${p.nickname || p.product_name || p.id} · ${money}${suffix}`;
}

function Skeleton() {
  return <View style={s.skeleton} />;
}

/* ═══════════ Sub Row ═══════════ */

function SubRowItem({
  row, canWrite, onEdit, onCancel, disabled,
}: {
  row: SubRow; canWrite: boolean;
  onEdit: () => void; onCancel: () => void; disabled?: boolean;
}) {
  const sid = row.stripe_subscription_id;
  return (
    <View style={s.subRow} testID={`subscriptions-row-${sid}`}>
      <View style={s.subRowTop}>
        <View style={{ flex: 1 }}>
          {row.formatted_plan_label ? (
            <Text style={s.planLabel} testID={`subscriptions-row-${sid}-plan`}>
              {row.formatted_plan_label}
            </Text>
          ) : (
            <Text style={s.planFallback} testID={`subscriptions-row-${sid}-plan-fallback`}>
              {row.price_id}
              <Text style={s.resolving}> · resolving…</Text>
            </Text>
          )}
        </View>
        <StatusChip label={row.status || "unknown"} />
      </View>

      <View style={s.subMeta}>
        <Text style={s.metaText}>Qty {row.quantity ?? 1}</Text>
        <Text style={s.metaDot}>·</Text>
        <Text style={s.metaText}>Ends {fmtDate(row.current_period_end)}</Text>
        {row.cancel_at_period_end ? (
          <>
            <Text style={s.metaDot}>·</Text>
            <Text
              style={[s.metaText, { color: "#D97706", fontFamily: font.semibold }]}
              testID={`subscriptions-row-${sid}-autocancel`}
            >
              Ending {fmtDate(row.current_period_end)}
            </Text>
          </>
        ) : null}
      </View>

      {canWrite ? (
        <View style={s.subActions}>
          <Pressable
            style={[s.actionBtn, disabled && s.actionDisabled]}
            onPress={onEdit}
            disabled={disabled}
            testID={`subscriptions-row-${sid}-edit`}
            accessibilityLabel="Edit subscription"
            accessibilityRole="button"
          >
            <Ionicons name="pencil-outline" size={14} color={colors.brand} />
            <Text style={s.actionText}>Edit</Text>
          </Pressable>
          <Pressable
            style={[s.actionBtn, disabled && s.actionDisabled]}
            onPress={onCancel}
            disabled={disabled}
            testID={`subscriptions-row-${sid}-cancel`}
            accessibilityLabel="Cancel subscription"
            accessibilityRole="button"
          >
            <Ionicons name="close-circle-outline" size={14} color={colors.error} />
            <Text style={[s.actionText, { color: colors.error }]}>Cancel</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

/* ═══════════ Create Modal ═══════════ */

function CreateModal({
  customerId, visible, onClose, onDone,
}: {
  customerId: string; visible: boolean;
  onClose: () => void; onDone: (msg: string) => void;
}) {
  const [prices, setPrices] = useState<SubPrice[]>([]);
  const [pms, setPms] = useState<PMRow[]>([]);
  const [priceIdx, setPriceIdx] = useState(0);
  const [pmIdx, setPmIdx] = useState(-1); // -1 = default
  const [quantity, setQuantity] = useState("1");
  const [trialDays, setTrialDays] = useState("0");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [loadingForm, setLoadingForm] = useState(true);

  useEffect(() => {
    if (!visible) return;
    (async () => {
      setLoadingForm(true);
      try {
        const [priceRes, pmRes] = await Promise.all([
          listPrices(),
          listPaymentMethods(customerId).catch(() => []),
        ]);
        const priceRows = priceRes?.rows || [];
        setPrices(priceRows);
        const pmRows = Array.isArray(pmRes) ? pmRes : [];
        // Only show cards + verified ACH
        setPms(pmRows.filter((p: PMRow) =>
          p.type === "card" || (p.type === "us_bank_account" && p.verification_status === "verified"),
        ));
        setPriceIdx(0);
        setPmIdx(-1);
      } catch (e: any) {
        setErr(e?.message || "Failed to load form data");
      } finally {
        setLoadingForm(false);
      }
    })();
  }, [visible, customerId]);

  const selectedPrice = prices[priceIdx];
  const canSubmit = !!selectedPrice && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true); setErr("");
    try {
      await createSubscription({
        customer_id: customerId,
        price_id: selectedPrice.id,
        quantity: Number(quantity) || 1,
        payment_method_id: pmIdx >= 0 ? pms[pmIdx]?.provider_payment_method_id : null,
        trial_days: Number(trialDays) || 0,
      });
      onDone("Subscription created");
    } catch (e: any) {
      setErr(e?.message || "Create failed");
    } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={s.modalBg}>
        <View style={s.modalCard} testID="subscriptions-create-modal">
          <Text style={s.modalTitle}>Create subscription</Text>

          {loadingForm ? (
            <View style={s.modalBody}><Skeleton /><Skeleton /></View>
          ) : (
            <ScrollView style={s.modalBody} keyboardShouldPersistTaps="handled">
              {/* Price picker */}
              <Text style={s.fieldLabel}>Plan</Text>
              {prices.length === 0 ? (
                <View style={s.emptyPlans} testID="subscriptions-create-empty-plans">
                  <Text style={s.emptyPlansText}>
                    No recurring plans configured in Stripe. Add a recurring price in your Stripe Dashboard to enable subscriptions.
                  </Text>
                </View>
              ) : (
                <View testID="subscriptions-create-price">
                  {prices.map((p, i) => (
                    <Pressable
                      key={p.id}
                      style={[s.pickerRow, priceIdx === i && s.pickerRowActive]}
                      onPress={() => setPriceIdx(i)}
                      testID={`subscriptions-create-price-${p.id}`}
                    >
                      <View style={[s.radioOuter, priceIdx === i && s.radioOuterActive]}>
                        {priceIdx === i ? <View style={s.radioInner} /> : null}
                      </View>
                      <Text style={[s.pickerLabel, priceIdx === i && { color: colors.onSurface }]}>
                        {priceLabel(p)}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              )}

              {/* Quantity */}
              <Text style={[s.fieldLabel, { marginTop: spacing.md }]}>Quantity</Text>
              <TextInput
                style={s.input}
                keyboardType="number-pad"
                value={quantity}
                onChangeText={setQuantity}
                testID="subscriptions-create-quantity"
              />

              {/* Payment method picker */}
              <Text style={[s.fieldLabel, { marginTop: spacing.md }]}>Payment method</Text>
              <Pressable
                style={[s.pickerRow, pmIdx === -1 && s.pickerRowActive]}
                onPress={() => setPmIdx(-1)}
                testID="subscriptions-create-pm-default"
              >
                <View style={[s.radioOuter, pmIdx === -1 && s.radioOuterActive]}>
                  {pmIdx === -1 ? <View style={s.radioInner} /> : null}
                </View>
                <Text style={s.pickerLabel}>Use customer default</Text>
              </Pressable>
              {pms.map((pm, i) => (
                <Pressable
                  key={pm.provider_payment_method_id}
                  style={[s.pickerRow, pmIdx === i && s.pickerRowActive]}
                  onPress={() => setPmIdx(i)}
                  testID={`subscriptions-create-pm-${pm.provider_payment_method_id}`}
                >
                  <View style={[s.radioOuter, pmIdx === i && s.radioOuterActive]}>
                    {pmIdx === i ? <View style={s.radioInner} /> : null}
                  </View>
                  <Text style={s.pickerLabel}>
                    {pm.type === "card"
                      ? `${(pm.brand || "Card").toUpperCase()} •••• ${pm.last4}`
                      : `ACH ${pm.bank_name || ""} •••• ${pm.last4}`}
                  </Text>
                </Pressable>
              ))}

              {/* Trial days */}
              <Text style={[s.fieldLabel, { marginTop: spacing.md }]}>Trial days (optional)</Text>
              <TextInput
                style={s.input}
                keyboardType="number-pad"
                value={trialDays}
                onChangeText={setTrialDays}
                testID="subscriptions-create-trial"
              />

              {err ? <Text style={s.errText} testID="subscriptions-create-error">{err}</Text> : null}
            </ScrollView>
          )}

          <View style={s.modalFooter}>
            <Pressable style={s.ghostBtn} onPress={onClose} testID="subscriptions-create-cancel">
              <Text style={s.ghostBtnText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[s.primaryBtn, !canSubmit && s.btnDisabled]}
              onPress={submit}
              disabled={!canSubmit}
              testID="subscriptions-create-submit"
              accessibilityRole="button"
              accessibilityLabel="Create subscription"
            >
              <Text style={s.primaryBtnText}>{busy ? "Creating…" : "Create subscription"}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

/* ═══════════ Edit Modal ═══════════ */

function EditModal({
  row, visible, onClose, onDone,
}: {
  row: SubRow | null; visible: boolean;
  onClose: () => void; onDone: (msg: string) => void;
}) {
  const [quantity, setQuantity] = useState(String(row?.quantity ?? 1));
  const [cancelAtEnd, setCancelAtEnd] = useState(!!row?.cancel_at_period_end);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (row) {
      setQuantity(String(row.quantity ?? 1));
      setCancelAtEnd(!!row.cancel_at_period_end);
      setErr("");
    }
  }, [row]);

  const submit = async () => {
    if (!row) return;
    setBusy(true); setErr("");
    try {
      await updateSubscription(row.stripe_subscription_id, {
        quantity: Number(quantity) || 1,
        cancel_at_period_end: cancelAtEnd,
      });
      onDone("Subscription updated");
    } catch (e: any) {
      setErr(e?.message || "Update failed");
    } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={s.modalBg}>
        <View style={s.modalCard} testID="subscriptions-edit-modal">
          <Text style={s.modalTitle}>Edit subscription</Text>
          <View style={s.modalBody}>
            <Text style={s.fieldLabel}>Quantity</Text>
            <TextInput
              style={s.input}
              keyboardType="number-pad"
              value={quantity}
              onChangeText={setQuantity}
              testID="subscriptions-edit-quantity"
            />

            <View style={s.switchRow}>
              <Text style={s.switchLabel}>Cancel at end of billing period</Text>
              <Switch
                value={cancelAtEnd}
                onValueChange={setCancelAtEnd}
                trackColor={{ false: "#9CA3AF", true: colors.brand }}
                testID="subscriptions-edit-cancel-at-end"
              />
            </View>

            {err ? <Text style={s.errText} testID="subscriptions-edit-error">{err}</Text> : null}
          </View>
          <View style={s.modalFooter}>
            <Pressable style={s.ghostBtn} onPress={onClose} testID="subscriptions-edit-cancel">
              <Text style={s.ghostBtnText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[s.primaryBtn, busy && s.btnDisabled]}
              onPress={submit}
              disabled={busy}
              testID="subscriptions-edit-submit"
              accessibilityRole="button"
              accessibilityLabel="Save subscription changes"
            >
              <Text style={s.primaryBtnText}>{busy ? "Saving…" : "Save changes"}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

/* ═══════════ Cancel Modal ═══════════ */

function CancelModal({
  row, visible, onClose, onDone,
}: {
  row: SubRow | null; visible: boolean;
  onClose: () => void; onDone: (msg: string) => void;
}) {
  const [mode, setMode] = useState<"at_period_end" | "immediate">("at_period_end");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { setMode("at_period_end"); setErr(""); }, [row]);

  const submit = async () => {
    if (!row) return;
    setBusy(true); setErr("");
    try {
      await cancelSubscription(row.stripe_subscription_id, mode);
      onDone(mode === "immediate"
        ? "Subscription canceled immediately"
        : "Subscription set to cancel at period end");
    } catch (e: any) {
      setErr(e?.message || "Cancel failed");
    } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={s.modalBg}>
        <View style={s.modalCard} testID="subscriptions-cancel-modal">
          <Text style={s.modalTitle}>Cancel subscription</Text>
          <View style={s.modalBody}>
            <Text style={s.modalHint}>Choose when this subscription should stop billing.</Text>

            <Pressable
              style={[s.radioRow, mode === "at_period_end" && s.radioRowActive]}
              onPress={() => setMode("at_period_end")}
              testID="subscriptions-cancel-mode-period-end"
            >
              <View style={[s.radioOuter, mode === "at_period_end" && s.radioOuterActive]}>
                {mode === "at_period_end" ? <View style={s.radioInner} /> : null}
              </View>
              <View style={{ flex: 1 }}>
                <Text style={s.radioTitle}>Cancel at end of billing period (recommended)</Text>
                <Text style={s.radioDesc}>
                  The customer keeps access until the current period ends; no refund.
                </Text>
              </View>
            </Pressable>

            <Pressable
              style={[s.radioRow, mode === "immediate" && s.radioRowActive]}
              onPress={() => setMode("immediate")}
              testID="subscriptions-cancel-mode-immediate"
            >
              <View style={[s.radioOuter, mode === "immediate" && s.radioOuterActive]}>
                {mode === "immediate" ? <View style={s.radioInner} /> : null}
              </View>
              <View style={{ flex: 1 }}>
                <Text style={s.radioTitle}>Cancel immediately</Text>
                <Text style={s.radioDesc}>
                  Ends billing right now. Use Stripe dashboard if a refund is required.
                </Text>
              </View>
            </Pressable>

            {err ? <Text style={s.errText} testID="subscriptions-cancel-error">{err}</Text> : null}
          </View>
          <View style={s.modalFooter}>
            <Pressable style={s.ghostBtn} onPress={onClose} testID="subscriptions-cancel-close">
              <Text style={s.ghostBtnText}>Keep subscription</Text>
            </Pressable>
            <Pressable
              style={[s.dangerBtn, busy && s.btnDisabled]}
              onPress={submit}
              disabled={busy}
              testID="subscriptions-cancel-submit"
              accessibilityRole="button"
              accessibilityLabel="Cancel subscription"
            >
              <Text style={s.primaryBtnText}>
                {busy ? "Canceling…" : mode === "immediate" ? "Cancel immediately" : "Cancel at period end"}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

/* ═══════════ Main Export ═══════════ */

type Props = { customerId: string; canWrite?: boolean };

export default function SubscriptionsSection({ customerId, canWrite = true }: Props) {
  const { showToast } = useToast();
  const online = useOnline();
  const [rows, setRows] = useState<SubRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [editRow, setEditRow] = useState<SubRow | null>(null);
  const [cancelRow, setCancelRow] = useState<SubRow | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listSubscriptions(customerId);
      setRows(res?.rows || []);
      setTotal(res?.total || 0);
    } catch {
      setRows([]);
    } finally { setLoading(false); }
  }, [customerId]);

  useEffect(() => { load(); }, [load]);

  const onDone = async (msg: string) => {
    setCreateOpen(false);
    setEditRow(null);
    setCancelRow(null);
    showToast(msg);
    await load();
  };

  return (
    <View testID="subscriptions-panel">
      {/* Header row */}
      <View style={s.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={s.sectionTitle} testID="subscriptions-title">Subscriptions</Text>
          <Text style={s.sectionSub}>
            {total} subscription{total === 1 ? "" : "s"} on file.
          </Text>
        </View>
        <View style={s.headerBtns}>
          <Pressable style={s.refreshBtn} onPress={load} testID="subscriptions-refresh"
            accessibilityLabel="Refresh subscriptions" accessibilityRole="button">
            <Ionicons name="refresh-outline" size={16} color={colors.brand} />
          </Pressable>
          {canWrite ? (
            <Pressable
              style={[s.createBtn, !online && s.actionDisabled]}
              onPress={() => setCreateOpen(true)}
              disabled={!online}
              testID="subscriptions-create-btn"
              accessibilityLabel="Create subscription"
              accessibilityRole="button"
            >
              <Ionicons name="add" size={16} color="#fff" />
              <Text style={s.createBtnText}>Create</Text>
            </Pressable>
          ) : null}
        </View>
      </View>

      {/* Offline banner */}
      {!online ? (
        <View style={s.offlineBanner} testID="subscriptions-offline-banner">
          <Ionicons name="cloud-offline" size={14} color="#92400E" />
          <Text style={s.offlineText}>
            {"You're offline — subscription management requires a connection"}
          </Text>
        </View>
      ) : null}

      {/* List */}
      {loading ? (
        <View style={s.skeletonWrap} testID="subscriptions-loading">
          <Skeleton /><Skeleton />
        </View>
      ) : rows.length === 0 ? (
        <View style={s.emptyWrap} testID="subscriptions-empty">
          <Ionicons name="card-outline" size={28} color={colors.muted} />
          <Text style={s.emptyTitle}>No subscriptions yet</Text>
          <Text style={s.emptySub}>
            Create the first subscription to charge this customer on a recurring basis.
          </Text>
        </View>
      ) : (
        <View style={s.listWrap} testID="subscriptions-list">
          {rows.map((r) => (
            <SubRowItem
              key={r.stripe_subscription_id}
              row={r}
              canWrite={canWrite}
              onEdit={() => setEditRow(r)}
              onCancel={() => setCancelRow(r)}
              disabled={!online}
            />
          ))}
        </View>
      )}

      {/* Modals */}
      <CreateModal
        customerId={customerId}
        visible={createOpen}
        onClose={() => setCreateOpen(false)}
        onDone={onDone}
      />
      <EditModal
        row={editRow}
        visible={!!editRow}
        onClose={() => setEditRow(null)}
        onDone={onDone}
      />
      <CancelModal
        row={cancelRow}
        visible={!!cancelRow}
        onClose={() => setCancelRow(null)}
        onDone={onDone}
      />
    </View>
  );
}

/* ═══════════ Styles ═══════════ */

const s = StyleSheet.create({
  /* header */
  headerRow: {
    flexDirection: "row", alignItems: "flex-start",
    justifyContent: "space-between", marginBottom: spacing.md,
  },
  sectionTitle: {
    fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface,
  },
  sectionSub: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2,
  },
  headerBtns: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  refreshBtn: {
    width: 32, height: 32, borderRadius: 16,
    backgroundColor: colors.surfaceTertiary,
    alignItems: "center", justifyContent: "center",
  },
  createBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.brand, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: 7,
  },
  createBtnText: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff",
  },
  /* offline */
  offlineBanner: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: "#FEF3C7", borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    marginBottom: spacing.md,
  },
  offlineText: {
    fontFamily: font.medium, fontSize: fontSize.sm, color: "#92400E", flex: 1,
  },
  /* skeleton */
  skeletonWrap: { gap: spacing.sm },
  skeleton: {
    height: 56, borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
  },
  /* empty */
  emptyWrap: {
    alignItems: "center", paddingVertical: spacing.xl,
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, borderStyle: "dashed",
  },
  emptyTitle: {
    fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface,
    marginTop: spacing.sm,
  },
  emptySub: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
    marginTop: 4, textAlign: "center", paddingHorizontal: spacing.xl,
  },
  /* list + row */
  listWrap: { gap: spacing.sm },
  subRow: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, padding: spacing.md,
  },
  subRowTop: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
  },
  planLabel: {
    fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface,
  },
  planFallback: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
  },
  resolving: { fontStyle: "italic", color: colors.muted },
  subMeta: {
    flexDirection: "row", alignItems: "center", flexWrap: "wrap",
    gap: 4, marginTop: 4,
  },
  metaText: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
  },
  metaDot: { color: colors.muted, fontSize: 10 },
  subActions: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    marginTop: spacing.sm, paddingTop: spacing.sm,
    borderTopWidth: 1, borderTopColor: colors.border,
  },
  actionBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingVertical: 4, paddingHorizontal: 8, borderRadius: radius.sm,
  },
  actionDisabled: { opacity: 0.4 },
  actionText: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand,
  },
  /* chip */
  chip: {
    paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999,
  },
  chipText: {
    fontFamily: font.semibold, fontSize: 10, textTransform: "uppercase",
  },
  /* modals */
  modalBg: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "flex-end",
  },
  modalCard: {
    backgroundColor: colors.surface, borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg, paddingTop: spacing.lg,
    maxHeight: "80%",
  },
  modalTitle: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
    paddingHorizontal: spacing.lg,
  },
  modalHint: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
    marginBottom: spacing.md,
  },
  modalBody: {
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  modalFooter: {
    flexDirection: "row", alignItems: "center", justifyContent: "flex-end",
    gap: spacing.sm, paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md, borderTopWidth: 1, borderTopColor: colors.border,
  },
  ghostBtn: {
    paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: radius.md,
  },
  ghostBtnText: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface,
  },
  primaryBtn: {
    backgroundColor: colors.brand, borderRadius: radius.md,
    paddingHorizontal: spacing.lg, paddingVertical: 10,
  },
  dangerBtn: {
    backgroundColor: colors.error, borderRadius: radius.md,
    paddingHorizontal: spacing.lg, paddingVertical: 10,
  },
  primaryBtnText: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff",
  },
  btnDisabled: { opacity: 0.5 },
  /* form fields */
  fieldLabel: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface,
    marginBottom: 4,
  },
  input: {
    height: 42, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, paddingHorizontal: spacing.md,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
    backgroundColor: colors.surfaceSecondary,
  },
  pickerRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: 8, paddingHorizontal: spacing.sm,
    borderRadius: radius.md, marginBottom: 4,
  },
  pickerRowActive: { backgroundColor: "#EFF6FF" },
  pickerLabel: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, flex: 1,
  },
  radioOuter: {
    width: 18, height: 18, borderRadius: 9,
    borderWidth: 2, borderColor: "#9CA3AF",
    alignItems: "center", justifyContent: "center",
  },
  radioOuterActive: { borderColor: colors.brand },
  radioInner: {
    width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brand,
  },
  radioRow: {
    flexDirection: "row", alignItems: "flex-start", gap: spacing.sm,
    paddingVertical: spacing.sm, paddingHorizontal: spacing.sm,
    borderRadius: radius.md, marginBottom: spacing.sm,
    borderWidth: 1, borderColor: colors.border,
  },
  radioRowActive: { borderColor: colors.brand, backgroundColor: "#EFF6FF" },
  radioTitle: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface,
  },
  radioDesc: {
    fontFamily: font.regular, fontSize: 12, color: colors.muted,
    marginTop: 2, lineHeight: 16,
  },
  switchRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginTop: spacing.md, paddingVertical: spacing.sm,
  },
  switchLabel: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, flex: 1,
  },
  errText: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.error,
    marginTop: spacing.sm,
  },
  emptyPlans: {
    borderWidth: 1, borderStyle: "dashed", borderColor: colors.border,
    borderRadius: radius.md, padding: spacing.md,
  },
  emptyPlansText: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
  },
});
