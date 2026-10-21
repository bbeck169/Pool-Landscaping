/**
 * Multi-Contact Editor — admin-only inline editor for customer.emails[]
 * and customer.mobiles[]. Mirrors web CustomerMultiContactEditor.jsx.
 *
 * Caps: 4 emails, 4 mobiles. Client-side duplicate detection + email
 * format validation. Save posts full arrays via:
 *   PATCH /api/customers/{cid}/emails  { emails }
 *   PATCH /api/customers/{cid}/mobiles { mobiles }
 */
import React, { useState } from "react";
import {
  View, Text, Pressable, Switch, StyleSheet, Alert,
  ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { useToast } from "@/src/components/ToastProvider";

const MAX_ENTRIES = 4;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_RE = /^\+?[0-9]{7,15}$/;

type EmailRow = { address: string; label: string; notifications_enabled: boolean };
type MobileRow = { number_e164: string; label: string; notifications_enabled: boolean };

function blankEmail(): EmailRow {
  return { address: "", label: "primary", notifications_enabled: true };
}
function blankMobile(): MobileRow {
  return { number_e164: "", label: "primary", notifications_enabled: true };
}

function hasDupes(rows: any[], key: string): boolean {
  const seen = new Set<string>();
  for (const r of rows) {
    const k = String(r?.[key] || "").trim().toLowerCase();
    if (!k) continue;
    if (seen.has(k)) return true;
    seen.add(k);
  }
  return false;
}

type Props = {
  customerId: string;
  initialEmails?: any[];
  initialMobiles?: any[];
  onSaved?: () => void;
};

export default function CustomerMultiContactEditor({
  customerId, initialEmails, initialMobiles, onSaved,
}: Props) {
  const { showToast } = useToast(); // TD-96-mobile-toast-sweep (undefined since 4a8d04429)
  const [emails, setEmails] = useState<EmailRow[]>(
    () => (Array.isArray(initialEmails) ? initialEmails.slice(0, MAX_ENTRIES).map((e: any) => ({
      address: e.address || "", label: e.label || "", notifications_enabled: e.notifications_enabled !== false,
    })) : []),
  );
  const [mobiles, setMobiles] = useState<MobileRow[]>(
    () => (Array.isArray(initialMobiles) ? initialMobiles.slice(0, MAX_ENTRIES).map((m: any) => ({
      number_e164: m.number_e164 || "", label: m.label || "", notifications_enabled: m.notifications_enabled !== false,
    })) : []),
  );
  const [saving, setSaving] = useState(false);

  const emailDupes = hasDupes(emails, "address");
  const mobileDupes = hasDupes(mobiles, "number_e164");
  const dupes = emailDupes || mobileDupes;

  const hasInvalidEmail = emails.some(
    (e) => e.address.trim() !== "" && !EMAIL_RE.test(e.address.trim()),
  );
  const hasInvalidPhone = mobiles.some(
    (m) => m.number_e164.trim() !== "" && !PHONE_RE.test(m.number_e164.trim()),
  );

  const canSave = !saving && !dupes && !hasInvalidEmail && !hasInvalidPhone;

  const saveContacts = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      await api.patch(`/customers/${customerId}/emails`, { emails });
      await api.patch(`/customers/${customerId}/mobiles`, { mobiles });
      showToast("Contacts updated.");
      onSaved?.();
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Please try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={s.container} testID="customer-multi-contact-editor">
      {/* ── Emails ── */}
      <SectionEditor
        title="Emails"
        testPrefix="customer-email"
        rows={emails}
        setRows={setEmails}
        addressField="address"
        placeholder="name@example.com"
        keyboardType="email-address"
        hasDupes={emailDupes}
        dupeLabel="address"
      />

      {/* ── Mobiles ── */}
      <SectionEditor
        title="Mobiles"
        testPrefix="customer-mobile"
        rows={mobiles}
        setRows={setMobiles}
        addressField="number_e164"
        placeholder="+15551234567"
        keyboardType="phone-pad"
        hasDupes={mobileDupes}
        dupeLabel="number"
      />

      {/* Validation hints */}
      {hasInvalidEmail && (
        <Text style={s.errorHint} testID="email-validation-error">
          Invalid email format — check highlighted rows.
        </Text>
      )}
      {hasInvalidPhone && (
        <Text style={s.errorHint} testID="phone-validation-error">
          Invalid phone format — use E.164 (e.g. +15551234567).
        </Text>
      )}

      {/* Save */}
      <Pressable
        style={[s.saveBtn, !canSave && { opacity: 0.5 }]}
        onPress={saveContacts}
        disabled={!canSave}
        testID="customer-contacts-save-btn"
      >
        {saving ? (
          <ActivityIndicator size="small" color="#fff" />
        ) : (
          <Text style={s.saveBtnText}>Save contacts</Text>
        )}
      </Pressable>
    </View>
  );
}

/* ── Section Editor (reusable for emails + mobiles) ── */
function SectionEditor({
  title, testPrefix, rows, setRows, addressField, placeholder,
  keyboardType, hasDupes: dupes, dupeLabel,
}: {
  title: string;
  testPrefix: string;
  rows: any[];
  setRows: (r: any[]) => void;
  addressField: string;
  placeholder: string;
  keyboardType: "email-address" | "phone-pad";
  hasDupes: boolean;
  dupeLabel: string;
}) {
  const atCap = rows.length >= MAX_ENTRIES;
  return (
    <View style={s.section} testID={`${testPrefix}-editor`}>
      <View style={s.sectionHeader}>
        <Text style={s.sectionTitle}>{title}</Text>
        <Text style={s.sectionCount}>{rows.length} of {MAX_ENTRIES}</Text>
      </View>

      {rows.map((row, i) => (
        <View key={i} style={s.row} testID={`${testPrefix}-row-${i}`}>
          <AppTextInput
            style={s.addrInput}
            value={row[addressField] || ""}
            onChangeText={(v) => {
              const next = [...rows];
              next[i] = { ...next[i], [addressField]: v };
              setRows(next);
            }}
            placeholder={placeholder}
            placeholderTextColor={colors.muted}
            keyboardType={keyboardType}
            autoCapitalize="none"
            testID={`${testPrefix}-input-${i}`}
          />
          <AppTextInput
            style={s.labelInput}
            value={row.label || ""}
            onChangeText={(v) => {
              const next = [...rows];
              next[i] = { ...next[i], label: v };
              setRows(next);
            }}
            placeholder="Label"
            placeholderTextColor={colors.muted}
            testID={`${testPrefix}-label-${i}`}
          />
          <View style={s.notifyCol}>
            <Switch
              value={row.notifications_enabled !== false}
              onValueChange={(v) => {
                const next = [...rows];
                next[i] = { ...next[i], notifications_enabled: v };
                setRows(next);
              }}
              trackColor={{ false: "#9CA3AF", true: "#16A34A" }}
              thumbColor="#fff"
              style={{ transform: [{ scaleX: 0.7 }, { scaleY: 0.7 }] }}
              testID={`${testPrefix}-notifications-${i}`}
            />
            <Text style={s.notifyLabel}>notify</Text>
          </View>
          <Pressable
            onPress={() => setRows(rows.filter((_, j) => j !== i))}
            style={s.deleteBtn}
            testID={`${testPrefix}-delete-${i}`}
          >
            <Ionicons name="close-circle" size={20} color="#DC2626" />
          </Pressable>
        </View>
      ))}

      <Pressable
        style={[s.addBtn, atCap && s.addBtnDisabled]}
        onPress={() => {
          if (atCap) return;
          setRows([
            ...rows,
            addressField === "address" ? blankEmail() : blankMobile(),
          ]);
        }}
        disabled={atCap}
        testID={`${testPrefix}-add-btn`}
      >
        <Ionicons name="add-circle-outline" size={16} color={atCap ? colors.muted : "#fff"} />
        <Text style={[s.addBtnText, atCap && { color: colors.muted }]}>
          Add {addressField === "address" ? "email" : "mobile"}
        </Text>
      </Pressable>

      {dupes && (
        <Text style={s.dupeError} testID={`${testPrefix}-dupe-error`}>
          Duplicate {dupeLabel} — remove or edit.
        </Text>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  container: { marginTop: spacing.md },
  section: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.sm,
  },
  sectionTitle: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  sectionCount: { fontFamily: font.regular, fontSize: 10, color: colors.muted },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: spacing.sm,
  },
  addrInput: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 8,
    paddingVertical: 8,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  labelInput: {
    width: 80,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 8,
    paddingVertical: 8,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  notifyCol: { alignItems: "center" },
  notifyLabel: { fontFamily: font.regular, fontSize: 9, color: colors.muted, marginTop: -4 },
  deleteBtn: { padding: 4 },
  addBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    alignSelf: "flex-start",
    backgroundColor: colors.brand,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: radius.sm,
    marginTop: spacing.xs,
  },
  addBtnDisabled: { backgroundColor: colors.surfaceTertiary },
  addBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  dupeError: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#B91C1C",
    marginTop: spacing.xs,
  },
  errorHint: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#B91C1C",
    marginBottom: spacing.sm,
  },
  saveBtn: {
    backgroundColor: "#059669",
    borderRadius: radius.md,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: spacing.xs,
  },
  saveBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
});
