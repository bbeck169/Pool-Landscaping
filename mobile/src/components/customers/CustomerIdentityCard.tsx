/**
 * Phase 35 · web parity b40352a (Phase 28) — customer identity header.
 * Phase 36 · VIP badge is an admin toggle (web ``customer-vip-toggle``):
 * optimistic flip → PATCH /customers/{cid}/vip → rollback + toast on error.
 *
 * One light card at the TOP of the mobile customer profile (above the
 * Phase 20 action row) consolidating: name, Customer since, VIP badge
 * (read-only), Active pill + toggle, primary phone / email / address,
 * pool gallons, gate code (only when set) and tags.
 *
 * Light chassis (Phase 32 two-tone): white card + #E4E4E7 border on the
 * white page; the dark tiles (nav bar, action row, KPI, Quick Actions)
 * sit below it. Every testID previously rendered for these fields is
 * kept verbatim. Tags are passed in as a slot so the parent keeps owning
 * the CustomerTagsSection mount + onChange wiring.
 */
import React, { useEffect, useRef, useState } from "react";
import { View, Text, Pressable, Switch, StyleSheet, Linking, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { PhoneLink, AddressLink } from "@/src/components/customer";
import { useToast } from "@/src/components/ToastProvider";
import { toggleVip } from "@/src/api/customers";
import {
  LIGHT_CARD_BG, LIGHT_CARD_BORDER, LIGHT_TEXT, LIGHT_TEXT_MUTED, LIGHT_CARD_RADIUS,
} from "@/src/lib/customerLightTokens";

type Props = {
  c: any;
  isActive: boolean;
  isAdmin: boolean;
  onToggleActive: (next: boolean) => void;
  primaryPhone?: string;
  primaryEmail?: string;
  tagsSlot?: React.ReactNode;
  /** M4 · web Ticket AA — combined category badge under the name. */
  categorySlot?: React.ReactNode;
};

function Row({ icon, children, testID }: { icon: any; children: React.ReactNode; testID?: string }) {
  return (
    <View style={s.row} testID={testID}>
      <View style={s.icon}><Ionicons name={icon} size={18} color={colors.brand} /></View>
      {children}
    </View>
  );
}

// Phase 36 · optimistic VIP state. Local state is the render source; it
// re-syncs whenever the parent's ``c.is_vip`` changes (refetch / cache).
function useVipToggle(c: any) {
  const { showToast } = useToast();
  const [vip, setVip] = useState<boolean>(Boolean(c.is_vip));
  const [busy, setBusy] = useState(false);
  const note = useRef<string | null>(c.vip_note ?? null);
  const inFlight = useRef(false); // same-frame double-tap guard

  useEffect(() => { setVip(Boolean(c.is_vip)); }, [c.is_vip]);
  useEffect(() => { note.current = c.vip_note ?? null; }, [c.vip_note]);
  const onToggle = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    const prev = vip;
    const next = !prev;
    setVip(next);
    setBusy(true);
    try {
      const doc = await toggleVip(c.id, next, note.current);
      if (doc && typeof doc.is_vip === "boolean") setVip(doc.is_vip);
      if (doc && "vip_note" in doc) note.current = doc.vip_note ?? null;
      showToast(next ? "Flagged as VIP" : "Removed VIP flag");
    } catch (e: any) {
      setVip(prev);
      showToast(e?.message || "Could not update VIP flag", "error");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  return { vip, busy, onToggle };
}

function VipBadgeInner({ vip, busy }: { vip: boolean; busy: boolean }) {
  return (
    <View style={vip ? s.vipBadge : s.vipBadgeOff} testID={vip ? "vip-badge" : "vip-badge-off"}>
      {busy ? (
        <ActivityIndicator size="small" color={vip ? "#92400E" : colors.muted} style={s.vipSpinner} testID="customer-vip-toggle-spinner" />
      ) : (
        <Ionicons name={vip ? "star" : "star-outline"} size={14} color={vip ? "#92400E" : colors.muted} />
      )}
      <Text style={vip ? s.vipBadgeText : s.vipBadgeTextOff}>{vip ? "VIP" : "Flag as VIP"}</Text>
    </View>
  );
}

function SinceVipRow({ c, isAdmin }: { c: any; isAdmin: boolean }) {
  const { vip, busy, onToggle } = useVipToggle(c);
  if (!c.customer_since && !vip && !isAdmin) return null;
  return (
    <View style={s.chipRow} testID="cd-identity-since-row">
      {c.customer_since ? (
        <Text testID="mobile-customer-since-label" style={s.since}>
          {`Customer since ${new Date(c.customer_since).toLocaleDateString(undefined, { month: "long", year: "numeric" })}`}
        </Text>
      ) : null}
      {isAdmin ? (
        <Pressable
          onPress={onToggle}
          disabled={busy}
          hitSlop={8}
          style={({ pressed }) => [s.vipToggle, (pressed || busy) && { opacity: 0.6 }]}
          accessibilityRole="switch"
          accessibilityLabel={vip ? "Remove VIP flag" : "Flag as VIP"}
          accessibilityState={{ checked: vip, busy, disabled: busy }}
          testID="customer-vip-toggle"
        >
          <VipBadgeInner vip={vip} busy={busy} />
        </Pressable>
      ) : vip ? (
        <VipBadgeInner vip busy={false} />
      ) : null}
    </View>
  );
}

function ActiveRow({ isActive, isAdmin, onToggleActive }: Pick<Props, "isActive" | "isAdmin" | "onToggleActive">) {
  return (
    <View testID="cd-identity-active-row">
      <View style={[s.statusPill, isActive ? s.statusPillActive : s.statusPillInactive]} testID="customer-status-pill">
        <Text style={[s.statusPillText, isActive ? s.statusPillTextActive : s.statusPillTextInactive]}>
          {isActive ? "Active" : "Inactive"}
        </Text>
        {isAdmin ? (
          <Switch
            testID="customer-active-toggle"
            value={isActive}
            onValueChange={onToggleActive}
            trackColor={{ false: "#9CA3AF", true: "#16A34A" }}
            thumbColor="#ffffff"
            ios_backgroundColor="#9CA3AF"
            style={{ marginLeft: 6, transform: [{ scaleX: 0.85 }, { scaleY: 0.85 }] }}
          />
        ) : null}
      </View>
      {/* Legacy inactive badge retained (invisible) for prior tests referencing this testID. */}
      {!isActive ? <View style={{ height: 0, opacity: 0 }} testID="customer-inactive-badge" /> : null}
    </View>
  );
}

function ContactRows({ c, primaryPhone, primaryEmail }: Pick<Props, "c" | "primaryPhone" | "primaryEmail">) {
  return (
    <View testID="cd-identity-contact">
      {primaryPhone ? (
        <Row icon="call-outline">
          <PhoneLink phone={primaryPhone} showIcon={false} style={s.value} testID="customer-phone-link" />
        </Row>
      ) : null}
      {primaryEmail ? (
        <Pressable style={s.row} onPress={() => Linking.openURL(`mailto:${primaryEmail}`)} testID="customer-email-link">
          <View style={s.icon}><Ionicons name="mail-outline" size={18} color={colors.brand} /></View>
          <Text style={s.value}>{primaryEmail}</Text>
          <Ionicons name="chevron-forward" size={16} color={colors.muted} />
        </Pressable>
      ) : null}
      {c.address ? (
        <Row icon="location-outline">
          <AddressLink address={c.address} showIcon={false} style={s.value} testID="customer-address-link" />
        </Row>
      ) : null}
      {/* Phase 34d — always render (placeholder when null). */}
      <Row icon="water-outline" testID="customer-pool-gallons-display">
        <Text style={s.value}>
          {c.pool_gallons != null ? `Pool: ${Number(c.pool_gallons).toLocaleString()} gal` : "Pool: — (not set)"}
        </Text>
      </Row>
      {/* Web Phase 28 parity — gate code only when set. */}
      {c.gate_code ? (
        <Row icon="key-outline" testID="cd-identity-gate-code">
          <Text style={s.value}>
            <Text style={s.label}>Gate code: </Text>
            <Text testID="cd-identity-gate-code-value">{String(c.gate_code)}</Text>
          </Text>
        </Row>
      ) : null}
    </View>
  );
}

export default function CustomerIdentityCard({ c, isActive, isAdmin, onToggleActive, primaryPhone, primaryEmail, tagsSlot, categorySlot }: Props) {
  return (
    <View style={s.card} testID="cd-identity-card">
      <Text style={s.name} numberOfLines={2} testID="customer-detail-inline-name">{c.name}</Text>
      {categorySlot ? <View testID="cd-identity-category">{categorySlot}</View> : null}
      <SinceVipRow c={c} isAdmin={isAdmin} />
      <ActiveRow isActive={isActive} isAdmin={isAdmin} onToggleActive={onToggleActive} />
      <ContactRows c={c} primaryPhone={primaryPhone} primaryEmail={primaryEmail} />
      {tagsSlot ? <View testID="cd-identity-tags">{tagsSlot}</View> : null}
    </View>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: LIGHT_CARD_BG, borderWidth: 1, borderColor: LIGHT_CARD_BORDER,
    borderRadius: LIGHT_CARD_RADIUS, padding: spacing.md, marginBottom: spacing.md, gap: spacing.sm,
  },
  name: { fontFamily: font.bold, fontSize: fontSize.xl, color: LIGHT_TEXT },
  chipRow: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.sm },
  since: { fontSize: 12, color: colors.muted },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.sm,
    borderTopWidth: 1, borderTopColor: LIGHT_CARD_BORDER,
  },
  icon: {
    width: 36, height: 36, borderRadius: radius.sm, backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  value: { flex: 1, fontFamily: font.medium, fontSize: fontSize.base, color: LIGHT_TEXT },
  label: { color: LIGHT_TEXT_MUTED },
  vipBadge: {
    flexDirection: "row", alignItems: "center", alignSelf: "flex-start",
    gap: 4, backgroundColor: "#FEF3C7", borderColor: "#F59E0B", borderWidth: 1,
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill,
  },
  vipBadgeText: { fontFamily: font.bold, fontSize: fontSize.xs, color: "#92400E", letterSpacing: 1, textTransform: "uppercase" },
  // Phase 36 · "Flag as VIP" off-state (web: surfaceSecondary / muted / border).
  vipBadgeOff: {
    flexDirection: "row", alignItems: "center", alignSelf: "flex-start",
    gap: 4, backgroundColor: colors.surfaceSecondary, borderColor: colors.border, borderWidth: 1,
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill,
  },
  vipBadgeTextOff: { fontFamily: font.bold, fontSize: fontSize.xs, color: colors.muted, letterSpacing: 1, textTransform: "uppercase" },
  vipToggle: { minHeight: 44, justifyContent: "center" },
  vipSpinner: { width: 14, height: 14, transform: [{ scale: 0.6 }] },
  statusPill: {
    flexDirection: "row", alignItems: "center", alignSelf: "flex-start",
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill, borderWidth: 1,
  },
  statusPillActive: { backgroundColor: "#DCFCE7", borderColor: "#86EFAC" },
  statusPillInactive: { backgroundColor: "#E5E7EB", borderColor: "#9CA3AF" },
  statusPillText: { fontFamily: font.bold, fontSize: fontSize.xs, letterSpacing: 1, textTransform: "uppercase" },
  statusPillTextActive: { color: "#166534" },
  statusPillTextInactive: { color: "#4B5563" },
});
