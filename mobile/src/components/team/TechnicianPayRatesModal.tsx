/**
 * Phase 19 · Technician pay-rates edit sheet (mobile parity with web
 * Phase 10 · 04f1f3749 ``TechnicianPayRatesModal.jsx``).
 *
 * Opened from the Team roster kebab ("Edit pay rates"). Two decimal
 * inputs — hourly rate + per-pool-job flat rate — built on the shared
 * ``DecimalInput`` primitive (chemistry-decimals fix).
 *
 * Wire contract (same as web):
 *   PATCH /api/users/{id}  { "hourly_rate": "25.50", "per_pool_rate": "10.00" }
 * Values are 2-place decimal STRINGS (lossless Decimal parse on the
 * server); blank → null (labor-cost compute treats null as zero).
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, ActivityIndicator,
  KeyboardAvoidingView, Platform,
} from "react-native";

import { api } from "@/src/api";
import DecimalInput from "@/src/components/common/DecimalInput";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export function rateToNumber(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number.parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

export function formatRate(v: number | null | undefined): string | null {
  if (v == null || !Number.isFinite(v)) return null;
  return v.toFixed(2);
}

type Props = {
  target: any;
  onClose: () => void;
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
};

function RateField({ label, help, value, onChange, testID, disabled }: {
  label: string; help: string; value: number | null; onChange: (n: number | null) => void;
  testID: string; disabled: boolean;
}) {
  return (
    <View style={s.field}>
      <Text style={s.label}>{label}</Text>
      <DecimalInput
        value={value}
        onChangeValue={onChange}
        placeholder="e.g. 25.50"
        editable={!disabled}
        style={s.input}
        testID={testID}
        accessibilityLabel={label}
      />
      <Text style={s.help}>{help}</Text>
    </View>
  );
}

export default function TechnicianPayRatesModal({ target, onClose, onSaved, onError }: Props) {
  const [hourly, setHourly] = useState<number | null>(null);
  const [perPool, setPerPool] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!target) return;
    setHourly(rateToNumber(target.hourly_rate));
    setPerPool(rateToNumber(target.per_pool_rate));
    setBusy(false);
  }, [target?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!target) return null;
  const who = target.name || target.email;

  const submit = async () => {
    setBusy(true);
    try {
      await api.patch(`/users/${target.id}`, {
        hourly_rate: formatRate(hourly),
        per_pool_rate: formatRate(perPool),
      });
      onSaved(`Pay rates saved for ${who}`);
    } catch (e: any) {
      onError(e?.message || "Failed to save pay rates");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={s.overlay}>
        <View style={s.sheet} testID="tech-pay-rates-modal">
          <Text style={s.title}>Pay rates — {who}</Text>
          <Text style={s.help}>
            Combined labor cost = hours × hourly rate + completed pool jobs × per-pool rate.
            Either field can be left blank; blank is treated as zero.
          </Text>
          <RateField
            label="Hourly rate ($/hr)"
            help="Paid per hour of timecard activity (clock-in / clock-out punches)."
            value={hourly} onChange={setHourly} disabled={busy}
            testID="tech-pay-rate-hourly-input"
          />
          <RateField
            label="Per pool job rate ($)"
            help="Flat amount paid per completed pool service job."
            value={perPool} onChange={setPerPool} disabled={busy}
            testID="tech-pay-rate-per-pool-input"
          />
          <View style={s.actions}>
            <Pressable style={[s.btn, s.btnGhost]} onPress={onClose} disabled={busy} testID="tech-pay-rates-cancel">
              <Text style={s.btnGhostText}>Cancel</Text>
            </Pressable>
            <Pressable style={[s.btn, s.btnPrimary, busy && { opacity: 0.6 }]} onPress={submit}
                       disabled={busy} testID="tech-pay-rates-save">
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={s.btnPrimaryText}>Save</Text>}
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const s = StyleSheet.create({
  overlay: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.5)" },
  sheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
    padding: spacing.lg, paddingBottom: spacing.xl, gap: spacing.sm,
  },
  title: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  field: { marginTop: spacing.sm, gap: 4 },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, minHeight: 44, fontSize: fontSize.base,
  },
  help: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  actions: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, marginTop: spacing.md },
  btn: { minHeight: 44, minWidth: 96, paddingHorizontal: spacing.lg, borderRadius: radius.md,
         alignItems: "center", justifyContent: "center" },
  btnGhost: { borderWidth: 1, borderColor: colors.border },
  btnGhostText: { fontFamily: font.semibold, color: colors.onSurface },
  btnPrimary: { backgroundColor: colors.brand },
  btnPrimaryText: { fontFamily: font.semibold, color: "#fff" },
});
