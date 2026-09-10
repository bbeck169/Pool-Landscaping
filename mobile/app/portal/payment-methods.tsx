/**
 * Task 5 — Portal Payment Methods (full list).
 *
 * Lists saved cards from `GET /customer-portal/payment-methods`.
 * Actions: Set default (PATCH), Remove (DELETE with confirm).
 * Empty state guides customer to save a card during next payment.
 *
 * Mirrors web `PortalPaymentMethods.jsx`.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity,
  RefreshControl, Modal, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading } from "@/src/components/ui";

type SavedCard = {
  provider_payment_method_id?: string;
  id?: string;
  brand?: string;
  last4?: string;
  exp_month?: number;
  exp_year?: number;
  default?: boolean;
  is_default?: boolean;
  type?: string;
};

export default function PortalPaymentMethodsScreen() {
  const [cards, setCards] = useState<SavedCard[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState("");
  const [confirmRemoveId, setConfirmRemoveId] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await api.get("/customer-portal/payment-methods");
      const methods: SavedCard[] = (res?.methods || []).filter(
        (m: any) => m.type === "card",
      );
      setCards(methods);
    } catch {
      setCards([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const keyFor = (c: SavedCard) => c.provider_payment_method_id || c.id || "";
  const isDefault = (c: SavedCard) => Boolean(c.default || c.is_default);

  const setDefault = async (pmId: string) => {
    setBusy(`default:${pmId}`);
    try {
      await api.patch(
        `/customer-portal/payment-methods/${encodeURIComponent(pmId)}/set-default`,
        { is_default: true },
      );
      load();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Failed to set default.");
    } finally {
      setBusy("");
    }
  };

  const doRemove = async (pmId: string) => {
    setBusy(`remove:${pmId}`);
    try {
      await api.del(`/customer-portal/payment-methods/${encodeURIComponent(pmId)}`);
      setConfirmRemoveId("");
      load();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Failed to remove card.");
    } finally {
      setBusy("");
    }
  };

  if (loading) {
    return (
      <View style={s.root}>
        <Header title="Payment Methods" subtitle="Manage your saved cards" back />
        <Loading testID="portal-payment-methods-loading" />
      </View>
    );
  }

  return (
    <View style={s.root} testID="portal-payment-methods-page">
      <Header title="Payment Methods" subtitle="Manage your saved cards" back />

      {(cards || []).length === 0 ? (
        <View style={s.emptyWrap} testID="portal-pm-empty-state">
          <Ionicons name="card-outline" size={48} color={colors.muted} />
          <Text style={s.emptyTitle}>No cards on file</Text>
          <Text style={s.emptyBody}>
            Cards are saved automatically when you pay an invoice (if you leave the box checked).
          </Text>
        </View>
      ) : (
        <FlatList
          testID="portal-pm-list"
          data={cards}
          keyExtractor={(c) => keyFor(c)}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: 40 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item: c }) => {
            const key = keyFor(c);
            const def = isDefault(c);
            return (
              <View style={s.cardRow} testID={`portal-pm-row-${key}`}>
                <View style={s.cardIcon}>
                  <Ionicons name="card" size={20} color={colors.brand} />
                </View>
                <View style={{ flex: 1 }}>
                  <View style={s.cardLabelRow}>
                    <Text style={s.cardBrand}>
                      {(c.brand || "Card").toUpperCase()} ···· {c.last4 || "????"}
                    </Text>
                    {def && (
                      <View style={s.defaultChip} testID={`portal-pm-default-chip-${key}`}>
                        <Text style={s.defaultChipText}>Default</Text>
                      </View>
                    )}
                  </View>
                  {c.exp_month && c.exp_year ? (
                    <Text style={s.cardExpiry}>
                      Expires {String(c.exp_month).padStart(2, "0")}/{String(c.exp_year).slice(-2)}
                    </Text>
                  ) : null}
                </View>
                <View style={s.actions}>
                  {!def && (
                    <TouchableOpacity
                      onPress={() => setDefault(key)}
                      disabled={busy === `default:${key}`}
                      style={s.actionBtn}
                      testID={`customer-pm-set-default-${key}`}
                    >
                      <Ionicons name="star-outline" size={14} color={colors.brand} />
                      <Text style={s.actionText}>Default</Text>
                    </TouchableOpacity>
                  )}
                  <TouchableOpacity
                    onPress={() => setConfirmRemoveId(key)}
                    disabled={busy === `remove:${key}`}
                    style={[s.actionBtn, s.removeBtn]}
                    testID={`customer-pm-remove-${key}`}
                  >
                    <Ionicons name="trash-outline" size={14} color="#DC2626" />
                    <Text style={[s.actionText, { color: "#DC2626" }]}>Remove</Text>
                  </TouchableOpacity>
                </View>
              </View>
            );
          }}
        />
      )}

      {/* Remove confirm dialog */}
      <Modal visible={!!confirmRemoveId} transparent animationType="fade" testID="portal-pm-remove-confirm-dialog">
        <View style={s.overlay}>
          <View style={s.dialog}>
            <Text style={s.dialogTitle}>Remove this card?</Text>
            <Text style={s.dialogBody}>
              This will detach the card from your account. You can always save a new one during your next invoice payment.
            </Text>
            <View style={s.dialogActions}>
              <TouchableOpacity
                onPress={() => setConfirmRemoveId("")}
                style={s.dialogCancel}
                testID="portal-pm-remove-cancel"
              >
                <Text style={s.dialogCancelText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => doRemove(confirmRemoveId)}
                disabled={busy.startsWith("remove:")}
                style={s.dialogConfirm}
                testID="portal-pm-remove-confirm"
              >
                <Text style={s.dialogConfirmText}>
                  {busy.startsWith("remove:") ? "Removing…" : "Remove card"}
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  emptyWrap: { flex: 1, alignItems: "center", justifyContent: "center", padding: 32 },
  emptyTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginTop: 16 },
  emptyBody: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 8, textAlign: "center", lineHeight: 20 },
  cardRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  cardIcon: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.brand + "14", alignItems: "center", justifyContent: "center" },
  cardLabelRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  cardBrand: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  defaultChip: { backgroundColor: "#DCFCE7", paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  defaultChipText: { fontFamily: font.bold, fontSize: 10, color: "#166534" },
  cardExpiry: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  actions: { flexDirection: "column", gap: 6, alignItems: "flex-end" },
  actionBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border },
  removeBtn: { borderColor: "#FCA5A5" },
  actionText: { fontFamily: font.semibold, fontSize: 11, color: colors.brand },
  overlay: { flex: 1, backgroundColor: "rgba(15,23,42,0.5)", justifyContent: "center", padding: 20 },
  dialog: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl },
  dialogTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  dialogBody: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 8, lineHeight: 20 },
  dialogActions: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, marginTop: spacing.lg },
  dialogCancel: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border },
  dialogCancelText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.muted },
  dialogConfirm: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.sm, backgroundColor: "#DC2626" },
  dialogConfirmText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
});
