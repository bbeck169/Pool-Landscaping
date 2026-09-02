/**
 * PaymentMethodRow — renders a single card or ACH bank account.
 *
 * Card:  VISA •••• 4242  Exp 12/26  [Default]  [Remove]
 * ACH:   Chase •••• 6789  [Unverified]          [Remove]
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

type Props = {
  pm: {
    id: string;
    provider_payment_method_id: string;
    type: "card" | "us_bank_account";
    brand?: string;
    bank_name?: string;
    last4: string;
    exp_month?: number;
    exp_year?: number;
    verification_status?: string;
    is_default: boolean;
  };
  onRemove: (id: string) => void;
  onSetDefault?: (id: string) => void;
  disabled?: boolean;
  settingDefault?: boolean;
};

function VerificationChip({ status }: { status?: string }) {
  if (!status) return null;
  const cfg: Record<string, { bg: string; fg: string; label: string }> = {
    verified:   { bg: "#DCFCE7", fg: "#166534", label: "Verified" },
    unverified: { bg: "#FEF3C7", fg: "#854D0E", label: "Unverified" },
    pending:    { bg: "#DBEAFE", fg: "#1E40AF", label: "Pending" },
    failed:     { bg: "#FEE2E2", fg: "#991B1B", label: "Failed" },
  };
  const c = cfg[status] || cfg.pending;
  return (
    <View style={[s.chip, { backgroundColor: c.bg }]} testID="pm-verification-chip">
      <Text style={[s.chipText, { color: c.fg }]}>{c.label}</Text>
    </View>
  );
}

export default function PaymentMethodRow({ pm, onRemove, onSetDefault, disabled, settingDefault }: Props) {
  const isCard = pm.type === "card";
  const label = isCard
    ? (pm.brand || "Card").toUpperCase()
    : pm.bank_name || "Bank account";
  const icon = isCard ? "card-outline" : "business-outline";
  const sub = isCard && pm.exp_month && pm.exp_year
    ? `Exp ${String(pm.exp_month).padStart(2, "0")}/${String(pm.exp_year).slice(-2)}`
    : !isCard
    ? "ACH bank account"
    : "";

  return (
    <View style={s.row} testID={`pm-row-${pm.provider_payment_method_id}`}>
      <View style={[s.iconWrap, { backgroundColor: isCard ? "#EFF6FF" : "#F0FDF4" }]}>
        <Ionicons name={icon} size={20} color={isCard ? "#2563EB" : "#16A34A"} />
      </View>
      <View style={s.info}>
        <View style={s.nameRow}>
          <Text style={s.label} testID={`pm-label-${pm.provider_payment_method_id}`}>
            {label} •••• {pm.last4}
          </Text>
          {pm.is_default && (
            <View style={s.defaultChip} testID="pm-default-chip">
              <Text style={s.defaultChipText}>Default</Text>
            </View>
          )}
        </View>
        <View style={s.metaRow}>
          {sub ? <Text style={s.sub}>{sub}</Text> : null}
          {!isCard && <VerificationChip status={pm.verification_status} />}
        </View>
      </View>
      <View style={s.actions}>
        {!pm.is_default && onSetDefault && (
          <Pressable
            onPress={() => onSetDefault(pm.provider_payment_method_id)}
            disabled={disabled || settingDefault}
            hitSlop={8}
            style={[s.setDefaultBtn, (disabled || settingDefault) && { opacity: 0.4 }]}
            testID={`pm-set-default-${pm.provider_payment_method_id}`}
            accessibilityLabel="Set as default payment method"
            accessibilityRole="button"
          >
            <Ionicons name="star-outline" size={14} color="#1E40AF" />
            <Text style={s.setDefaultText}>
              {settingDefault ? "Setting…" : "Set default"}
            </Text>
          </Pressable>
        )}
        <Pressable
          onPress={() => onRemove(pm.provider_payment_method_id)}
          disabled={disabled}
          hitSlop={8}
          style={[s.removeBtn, disabled && { opacity: 0.4 }]}
          testID={`pm-remove-${pm.provider_payment_method_id}`}
          accessibilityLabel="Remove payment method"
          accessibilityRole="button"
        >
          <Ionicons name="trash-outline" size={18} color={colors.error} />
        </Pressable>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  iconWrap: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  info: { flex: 1 },
  nameRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    flexWrap: "wrap",
  },
  label: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginTop: 2,
    flexWrap: "wrap",
  },
  sub: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  chip: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
  },
  chipText: {
    fontFamily: font.semibold,
    fontSize: 10,
    textTransform: "uppercase",
  },
  defaultChip: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
    backgroundColor: "#DBEAFE",
  },
  defaultChipText: {
    fontFamily: font.semibold,
    fontSize: 10,
    color: "#1E40AF",
    textTransform: "uppercase",
  },
  removeBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: "#FEE2E2",
    alignItems: "center",
    justifyContent: "center",
  },
  actions: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  setDefaultBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: "#EFF6FF",
  },
  setDefaultText: {
    fontFamily: font.semibold,
    fontSize: 11,
    color: "#1E40AF",
  },
});
