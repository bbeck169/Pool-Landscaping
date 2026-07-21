/**
 * MultiContact — read-only phone + email list for tech view (A4).
 */
import React from "react";
import { View, Text, StyleSheet, TouchableOpacity, Linking } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type MobileEntry = { number_e164?: string; label?: string; is_primary?: boolean; sms_ok?: boolean; id?: string };
type EmailEntry = { address?: string; label?: string; is_primary?: boolean; marketing_ok?: boolean; id?: string };
type Props = { mobiles?: (string | MobileEntry)[]; emails?: (string | EmailEntry)[] };

const mobileDisplay = (m: string | MobileEntry): { phone: string; label: string } => {
  if (typeof m === "string") return { phone: m, label: "" };
  return { phone: m.number_e164 || "", label: m.label || "" };
};

const emailDisplay = (e: string | EmailEntry): { addr: string; label: string } => {
  if (typeof e === "string") return { addr: e, label: "" };
  return { addr: e.address || "", label: e.label || "" };
};

export default function MultiContact({ mobiles, emails }: Props) {
  const hasMobiles = mobiles && mobiles.length > 0;
  const hasEmails = emails && emails.length > 0;
  if (!hasMobiles && !hasEmails) return null;

  return (
    <View style={styles.container}>
      {hasMobiles && (
        <View testID="customer-mobiles-list">
          <Text style={styles.label}>Phone Numbers</Text>
          {mobiles!.map((m, i) => {
            const { phone, label } = mobileDisplay(m);
            if (!phone) return null;
            return (
              <TouchableOpacity
                key={i}
                style={styles.row}
                onPress={() => Linking.openURL(`tel:${phone}`)}
                activeOpacity={0.7}
              >
                <View style={styles.icon}>
                  <Ionicons name="call-outline" size={16} color={colors.brand} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.value}>{phone}</Text>
                  {label ? <Text style={styles.sublabel}>{label}</Text> : null}
                </View>
                <Ionicons name="chevron-forward" size={14} color={colors.muted} />
              </TouchableOpacity>
            );
          })}
        </View>
      )}
      {hasEmails && (
        <View testID="customer-emails-list">
          <Text style={[styles.label, hasMobiles ? { marginTop: spacing.md } : {}]}>
            Email Addresses
          </Text>
          {emails!.map((e, i) => {
            const { addr, label } = emailDisplay(e);
            if (!addr) return null;
            return (
              <TouchableOpacity
                key={i}
                style={styles.row}
                onPress={() => Linking.openURL(`mailto:${addr}`)}
                activeOpacity={0.7}
              >
                <View style={styles.icon}>
                  <Ionicons name="mail-outline" size={16} color={colors.brand} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.value}>{addr}</Text>
                  {label ? <Text style={styles.sublabel}>{label}</Text> : null}
                </View>
                <Ionicons name="chevron-forward" size={14} color={colors.muted} />
              </TouchableOpacity>
            );
          })}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { marginTop: spacing.md },
  label: { fontFamily: font.bold, fontSize: 11, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: spacing.xs },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.xs },
  icon: { width: 32, height: 32, borderRadius: radius.sm, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  value: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  sublabel: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 1 },
});
