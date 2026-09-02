/**
 * PaymentMethodTiles — Phase J2 / I5 parity.
 *
 * Polished card + ACH on-file tiles for the mobile customer profile.
 * Green on-file tile with white bold text (web Wave C pattern),
 * dark-red empty state.
 *
 * Features:
 * - Two subsections: Credit/Debit Cards + Bank Accounts
 * - Delete: typed-confirm modal (typed last4, case-sensitive)
 * - Add/Edit: reuses existing SetupIntent mobile flow (navigates to payment-methods screen)
 * - J1 Set-default chevron button on non-default cards
 * - J1 Expires-soon amber chip (and 30-day dark-red variant)
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator,
  Alert, Modal, TextInput, KeyboardAvoidingView, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useStripeConfig } from "@/src/config/stripe";
import { StripeUnconfiguredBanner } from "@/src/lib/stripeConfig";

/* ── Types ──────────────────────────────────────────────────── */
type PM = {
  id: string;
  provider_payment_method_id: string;
  type: string;
  brand?: string;
  bank_name?: string;
  last4: string;
  exp_month?: number;
  exp_year?: number;
  is_default: boolean;
  account_holder_type?: string;
};

/* ── Shared primitives ──────────────────────────────────────── */
const _TILE_BG = colors.success;
const _TILE_BORDER = "#15803D";
const _PILL_BG = "#15803D";
const _FIELD_BG = "rgba(0,0,0,0.18)";
const _FIELD_BORDER = "rgba(255,255,255,0.35)";

function LockedField({ label, value, testID: tid }: { label: string; value: string; testID: string }) {
  return (
    <View style={pf.wrap} testID={tid}>
      <Text style={pf.label}>{label}</Text>
      <View style={pf.box}>
        <Ionicons name="lock-closed" size={10} color="#fff" />
        <Text style={pf.value} numberOfLines={1}>{value}</Text>
      </View>
    </View>
  );
}
const pf = StyleSheet.create({
  wrap: { flex: 1, minWidth: 100 },
  label: { fontFamily: font.bold, fontSize: 10, color: "#fff", textTransform: "uppercase", letterSpacing: 0.8, marginBottom: 4 },
  box: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: _FIELD_BG, borderWidth: 1, borderColor: _FIELD_BORDER, borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 8 },
  value: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff", flex: 1 },
});

function ActionBtn({ label, icon, tone, onPress, disabled, testID: tid }: {
  label: string; icon: string; tone?: "danger"; onPress: () => void; disabled?: boolean; testID: string;
}) {
  const isDanger = tone === "danger";
  return (
    <Pressable
      style={[ab.btn, isDanger && ab.danger, disabled && ab.disabled]}
      onPress={disabled ? undefined : onPress}
      testID={tid}
    >
      <Ionicons name={icon as any} size={12} color={isDanger ? "#991B1B" : colors.onSurface} />
      <Text style={[ab.text, isDanger && ab.dangerText]}>{label}</Text>
    </Pressable>
  );
}
const ab = StyleSheet.create({
  btn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.md, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  danger: { backgroundColor: "#FEE2E2", borderColor: "#FCA5A5" },
  disabled: { opacity: 0.5 },
  text: { fontFamily: font.semibold, fontSize: 11, color: colors.onSurface },
  dangerText: { color: "#991B1B" },
});

function ExpiryChip({ expMonth, expYear, rowId }: { expMonth?: number; expYear?: number; rowId: string }) {
  if (!expMonth || !expYear) return null;
  const now = new Date();
  const thisY = now.getFullYear();
  const thisM = now.getMonth() + 1;
  let chip: { label: string; bg: string; fg: string } | null = null;
  if (expYear < thisY || (expYear === thisY && expMonth < thisM)) {
    chip = { label: "Expired", bg: "#FEE2E2", fg: "#991B1B" };
  } else if (expYear === thisY && expMonth === thisM) {
    chip = { label: "Expires this month", bg: "#FEE2E2", fg: "#991B1B" };
  } else if (expYear <= thisY + 1) {
    chip = { label: "Expires soon", bg: "#FEF3C7", fg: "#92400E" };
  }
  if (!chip) return null;
  return (
    <View style={[ec.pill, { backgroundColor: chip.bg }]} testID={`payment-tile-card-expiry-chip-${rowId}`}>
      <Text style={[ec.text, { color: chip.fg }]}>{chip.label}</Text>
    </View>
  );
}
const ec = StyleSheet.create({
  pill: { position: "absolute", top: 10, right: 10, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  text: { fontFamily: font.bold, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 },
});

/* ── Card Tile ──────────────────────────────────────────────── */
function CardTile({ row, onEdit, onDelete, onSetDefault, defaultBusy }: {
  row: PM; onEdit: (r: PM) => void; onDelete: (r: PM) => void;
  onSetDefault: (r: PM) => void; defaultBusy: boolean;
}) {
  const brand = (row.brand || "card").toUpperCase();
  const last4 = row.last4 || "••••";
  const exp = (row.exp_month && row.exp_year)
    ? `${String(row.exp_month).padStart(2, "0")} / ${row.exp_year}` : "—";
  return (
    <View style={ct.card} testID={`payment-tile-card-${row.id}`}>
      <ExpiryChip expMonth={row.exp_month} expYear={row.exp_year} rowId={row.id} />
      <View style={ct.pillRow}>
        <View style={ct.pill}>
          <Ionicons name="card" size={12} color="#fff" />
          <Text style={ct.pillText}>{brand} on file{row.is_default ? " · default" : ""}</Text>
        </View>
      </View>
      <View style={ct.fieldsRow}>
        <LockedField label="Card number" value={`•••• •••• •••• ${last4}`} testID={`payment-tile-card-number-${row.id}`} />
        <LockedField label="Expires" value={exp} testID={`payment-tile-card-exp-${row.id}`} />
      </View>
      <View style={ct.actionsRow}>
        <ActionBtn label="Edit" icon="pencil-outline" onPress={() => onEdit(row)} testID={`payment-tile-card-edit-${row.id}`} />
        {!row.is_default ? (
          <ActionBtn label={defaultBusy ? "Setting…" : "Set default"} icon="star-outline" onPress={() => onSetDefault(row)} disabled={defaultBusy} testID={`payment-tile-card-set-default-${row.id}`} />
        ) : null}
        <ActionBtn label="Delete" icon="trash-outline" tone="danger" onPress={() => onDelete(row)} testID={`payment-tile-card-delete-${row.id}`} />
      </View>
    </View>
  );
}
const ct = StyleSheet.create({
  card: { borderRadius: radius.lg, padding: spacing.md, backgroundColor: _TILE_BG, borderWidth: 2, borderColor: _TILE_BORDER, gap: spacing.sm },
  pillRow: { marginBottom: 2 },
  pill: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: _PILL_BG, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4, alignSelf: "flex-start" },
  pillText: { fontFamily: font.bold, fontSize: 10, color: "#fff", textTransform: "uppercase", letterSpacing: 0.5 },
  fieldsRow: { flexDirection: "row", gap: spacing.sm },
  actionsRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: 4 },
});

/* ── Bank Tile ──────────────────────────────────────────────── */
function BankTile({ row, onEdit, onDelete, onSetDefault, defaultBusy }: {
  row: PM; onEdit: (r: PM) => void; onDelete: (r: PM) => void;
  onSetDefault: (r: PM) => void; defaultBusy: boolean;
}) {
  const last4 = row.last4 || "••••";
  const bank = row.bank_name || "Bank";
  const acct = row.account_holder_type
    ? row.account_holder_type[0].toUpperCase() + row.account_holder_type.slice(1) : "Account";
  return (
    <View style={ct.card} testID={`payment-tile-bank-${row.id}`}>
      <View style={ct.pillRow}>
        <View style={ct.pill}>
          <Ionicons name="business" size={12} color="#fff" />
          <Text style={ct.pillText}>Bank account on file{row.is_default ? " · default" : ""}</Text>
        </View>
      </View>
      <View style={ct.fieldsRow}>
        <LockedField label="Account" value={`•••• ${last4}`} testID={`payment-tile-bank-number-${row.id}`} />
        <LockedField label="Bank" value={bank} testID={`payment-tile-bank-name-${row.id}`} />
        <LockedField label="Type" value={acct} testID={`payment-tile-bank-type-${row.id}`} />
      </View>
      <View style={ct.actionsRow}>
        <ActionBtn label="Edit" icon="pencil-outline" onPress={() => onEdit(row)} testID={`payment-tile-bank-edit-${row.id}`} />
        {!row.is_default ? (
          <ActionBtn label={defaultBusy ? "Setting…" : "Set default"} icon="star-outline" onPress={() => onSetDefault(row)} disabled={defaultBusy} testID={`payment-tile-bank-set-default-${row.id}`} />
        ) : null}
        <ActionBtn label="Delete" icon="trash-outline" tone="danger" onPress={() => onDelete(row)} testID={`payment-tile-bank-delete-${row.id}`} />
      </View>
    </View>
  );
}

/* ── Empty state ────────────────────────────────────────────── */
function EmptyState({ kind, onAdd, testID: tid }: { kind: "card" | "bank"; onAdd: () => void; testID: string }) {
  const isCard = kind === "card";
  return (
    <View style={es.box} testID={tid}>
      <View style={es.headRow}>
        <Ionicons name={isCard ? "card" : "business"} size={16} color={colors.onError} />
        <Text style={es.title}>
          {isCard ? "No Credit/Debit Card on File" : "No Bank Account on File"}
        </Text>
      </View>
      <Pressable style={es.addBtn} onPress={onAdd} testID={`${tid}-add`}>
        <Ionicons name="add-circle-outline" size={14} color={colors.onSurface} />
        <Text style={es.addText}>{isCard ? "Add a Credit/Debit Card" : "Add Bank Account"}</Text>
      </Pressable>
    </View>
  );
}
const es = StyleSheet.create({
  box: { borderRadius: radius.lg, padding: spacing.md, backgroundColor: colors.error, gap: spacing.sm },
  headRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  title: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff", flex: 1 },
  addBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.surface, borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 8, alignSelf: "flex-start" },
  addText: { fontFamily: font.semibold, fontSize: 12, color: colors.onSurface },
});

/* ── Typed confirm delete modal ─────────────────────────────── */
function TypedDeleteModal({ pending, onConfirm, onCancel, busy }: {
  pending: PM | null; onConfirm: () => void; onCancel: () => void; busy: boolean;
}) {
  const [typed, setTyped] = useState("");
  useEffect(() => { if (pending) setTyped(""); }, [pending]);
  const match = typed === (pending?.last4 || "");
  const isBank = pending?.type === "us_bank_account";
  return (
    <Modal visible={!!pending} transparent animationType="fade" onRequestClose={onCancel}>
      <KeyboardAvoidingView style={dm.overlay} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <View style={dm.card} testID="payment-tile-delete-confirm-modal">
          <Text style={dm.title}>{isBank ? "Delete bank account" : "Delete credit / debit card"}</Text>
          <Text style={dm.desc}>
            Type the last 4 (<Text style={dm.bold}>{pending?.last4}</Text>) to permanently remove this {isBank ? "bank account" : "card"}. This may cause future recurring charges to fail.
          </Text>
          <TextInput
            style={dm.input}
            value={typed}
            onChangeText={setTyped}
            placeholder="Last 4 digits"
            placeholderTextColor={colors.muted}
            keyboardType="number-pad"
            maxLength={4}
            testID="payment-tile-delete-confirm-input"
          />
          <View style={dm.btns}>
            <Pressable style={dm.cancel} onPress={onCancel} disabled={busy} testID="payment-tile-delete-confirm-cancel">
              <Text style={dm.cancelText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[dm.confirm, (!match || busy) && { opacity: 0.4 }]}
              onPress={match && !busy ? onConfirm : undefined}
              disabled={!match || busy}
              testID="payment-tile-delete-confirm-btn"
            >
              <Text style={dm.confirmText}>{busy ? "Removing…" : "Remove"}</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}
const dm = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", alignItems: "center", justifyContent: "center", padding: spacing.lg },
  card: { width: "100%", maxWidth: 380, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, gap: spacing.md },
  title: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  desc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, lineHeight: 20 },
  bold: { fontFamily: font.bold, color: colors.onSurface },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 10, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, textAlign: "center", letterSpacing: 4 },
  btns: { flexDirection: "row", gap: spacing.sm },
  cancel: { flex: 1, paddingVertical: 10, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, alignItems: "center" },
  cancelText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  confirm: { flex: 1, paddingVertical: 10, borderRadius: radius.md, backgroundColor: colors.error, alignItems: "center" },
  confirmText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});

/* ── Main component ─────────────────────────────────────────── */
export default function PaymentMethodTiles({
  customerId,
  variant = "admin",
  onChange,
}: {
  customerId: string;
  variant?: "admin" | "portal";
  onChange?: () => void;
}) {
  const router = useRouter();
  const { stripeConfigured } = useStripeConfig();
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [methods, setMethods] = useState<PM[]>([]);
  const [pending, setPending] = useState<PM | null>(null);
  const [busy, setBusy] = useState(false);
  const [defaultBusyId, setDefaultBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!customerId) return;
    setLoading(true);
    try {
      const r: any = await api.get(`/payments/stripe/payment-methods/${customerId}`);
      setMethods(r?.payment_methods || []);
      setErr("");
    } catch (e: any) {
      setErr(e?.message || "Couldn't load payment methods");
    } finally {
      setLoading(false);
    }
  }, [customerId]);
  useEffect(() => { load(); }, [load]);

  const cards = methods.filter((m) => (m.type || "card") === "card");
  const banks = methods.filter((m) => m.type === "us_bank_account");

  const navigateAddPM = () => router.push(`/customer/${customerId}/payment-methods` as any);

  const openEdit = (row: PM) => {
    Alert.alert(
      "Edit payment method",
      "Card/bank details are immutable on Stripe. Add a new one, then delete the old.",
      [{ text: "OK", onPress: navigateAddPM }],
    );
  };

  const openDelete = (row: PM) => setPending(row);
  const closeDelete = () => { if (!busy) setPending(null); };

  const confirmDelete = async () => {
    if (!pending) return;
    setBusy(true);
    try {
      await api.post(
        `/payments/stripe/payment-methods/${pending.provider_payment_method_id}/delete-typed`,
        { typed_last4: pending.last4 || "" },
      );
      const kind = pending.type === "us_bank_account" ? "Bank account" : "Card";
      Alert.alert("Removed", `${kind} ending in ${pending.last4} removed.`);
      setPending(null);
      await load();
      onChange?.();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Delete failed");
    } finally {
      setBusy(false);
    }
  };

  const onSetDefault = async (row: PM) => {
    if (!row?.provider_payment_method_id) return;
    setDefaultBusyId(row.id);
    try {
      await api.post(`/payments/stripe/payment-methods/${row.provider_payment_method_id}/set-default`, {});
      const kind = row.type === "us_bank_account" ? "Bank account" : "Card";
      Alert.alert("Done", `${kind} ending in ${row.last4} set as default.`);
      await load();
      onChange?.();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Set-default failed");
    } finally {
      setDefaultBusyId(null);
    }
  };

  if (loading) {
    return (
      <View style={s.loadWrap} testID="payment-method-tiles-loading">
        <ActivityIndicator size="small" color={colors.brand} />
        <Text style={s.loadText}>Loading payment methods…</Text>
      </View>
    );
  }

  return (
    <View style={s.root} testID={`payment-method-tiles-${variant}`}>
      {err ? (
        <View style={s.errBox} testID="payment-method-tiles-error">
          <Text style={s.errText}>{err}</Text>
        </View>
      ) : null}

      {/* K23 — Stripe-not-configured banner */}
      {!stripeConfigured && (
        <StripeUnconfiguredBanner testID="pm-tiles-stripe-unconfigured" />
      )}

      {/* Cards subsection */}
      <View testID="payment-method-tiles-cards-section">
        <View style={s.sectionHeader}>
          <View style={s.sectionTitleRow}>
            <Ionicons name="card" size={14} color={colors.onSurface} />
            <Text style={s.sectionTitle}>Credit / Debit Cards</Text>
          </View>
          {cards.length ? (
            <Pressable style={s.addMore} onPress={navigateAddPM} testID="payment-method-tiles-add-card">
              <Ionicons name="add" size={14} color={colors.onSurface} />
              <Text style={s.addMoreText}>Add</Text>
            </Pressable>
          ) : null}
        </View>
        {cards.length === 0 ? (
          <EmptyState kind="card" onAdd={navigateAddPM} testID="payment-method-tiles-card-empty" />
        ) : (
          <View style={s.listGap}>
            {cards.map((row) => (
              <CardTile key={row.id} row={row} onEdit={openEdit} onDelete={openDelete}
                onSetDefault={onSetDefault} defaultBusy={defaultBusyId === row.id} />
            ))}
          </View>
        )}
      </View>

      {/* Banks subsection */}
      <View testID="payment-method-tiles-banks-section">
        <View style={s.sectionHeader}>
          <View style={s.sectionTitleRow}>
            <Ionicons name="business" size={14} color={colors.onSurface} />
            <Text style={s.sectionTitle}>Bank Accounts</Text>
          </View>
          {banks.length ? (
            <Pressable style={s.addMore} onPress={navigateAddPM} testID="payment-method-tiles-add-bank">
              <Ionicons name="add" size={14} color={colors.onSurface} />
              <Text style={s.addMoreText}>Add</Text>
            </Pressable>
          ) : null}
        </View>
        {banks.length === 0 ? (
          <EmptyState kind="bank" onAdd={navigateAddPM} testID="payment-method-tiles-bank-empty" />
        ) : (
          <View style={s.listGap}>
            {banks.map((row) => (
              <BankTile key={row.id} row={row} onEdit={openEdit} onDelete={openDelete}
                onSetDefault={onSetDefault} defaultBusy={defaultBusyId === row.id} />
            ))}
          </View>
        )}
      </View>

      {/* Typed-confirm delete gate */}
      <TypedDeleteModal pending={pending} onConfirm={confirmDelete} onCancel={closeDelete} busy={busy} />
    </View>
  );
}

const s = StyleSheet.create({
  root: { gap: spacing.lg },
  loadWrap: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border },
  loadText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  errBox: { borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: "#FEE2E2" },
  errText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#991B1B" },
  sectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  sectionTitleRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  addMore: { flexDirection: "row", alignItems: "center", gap: 2, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  addMoreText: { fontFamily: font.semibold, fontSize: 12, color: colors.onSurface },
  listGap: { gap: spacing.sm },
});
