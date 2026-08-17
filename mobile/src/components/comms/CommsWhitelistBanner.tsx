/**
 * Task 1 · Feb-2026 — Mobile mirror of the web ``CommsWhitelistBanner``.
 *
 * Reads GET /api/comms/whitelist/status and renders a compact red
 * banner communicating that outbound comms are currently demo-only.
 * Silent no-op when the gate is off or when the fetch fails (the
 * underlying comms gate is fail-closed on the backend, so an
 * inability to fetch the status is not a data-loss surface).
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { spacing, radius, font } from "@/src/theme";

type Status = {
  whitelist_active?: boolean;
  users_flagged_demo?: number;
  customers_flagged_demo?: number;
  suppressed_last_24h?: number;
};

export default function CommsWhitelistBanner() {
  const [status, setStatus] = useState<Status | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.get("/comms/whitelist/status")
      .then((r: any) => { if (!cancelled) setStatus(r || {}); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, []);

  if (failed || !status?.whitelist_active) return null;

  return (
    <View style={ss.banner} accessibilityRole="alert"
             testID="comms-whitelist-banner">
      <View style={ss.headline}>
        <Ionicons name="shield-outline" size={16} color="#B91C1C" />
        <Text style={ss.title}>Outbound comms gated (demo-only mode).</Text>
      </View>
      <Text style={ss.body}>
        Emails and SMS only send to recipients explicitly flagged{" "}
        <Text style={ss.bold}>is_demo_account = true</Text>. Everything
        else is suppressed and audit-logged.
      </Text>
      <View style={ss.chipRow} testID="comms-whitelist-banner-counts">
        <Chip label="Users" value={status?.users_flagged_demo || 0}
                testid="comms-whitelist-users-count" />
        <Chip label="Customers" value={status?.customers_flagged_demo || 0}
                testid="comms-whitelist-customers-count" />
        <Chip label="Blocked 24h" value={status?.suppressed_last_24h || 0}
                testid="comms-whitelist-suppressed-count" danger />
      </View>
    </View>
  );
}

function Chip({ label, value, danger, testid }: {
  label: string; value: number; danger?: boolean; testid: string;
}) {
  return (
    <View style={[ss.chip, danger ? ss.chipDanger : null]} testID={testid}>
      <Text style={[ss.chipLabel, danger ? ss.chipLabelDanger : null]}>{label}</Text>
      <View style={[ss.chipBadge, danger ? ss.chipBadgeDanger : null]}>
        <Text style={ss.chipBadgeText}>{value}</Text>
      </View>
    </View>
  );
}

const ss = StyleSheet.create({
  banner: {
    backgroundColor: "#FEF2F2",
    borderWidth: 1, borderColor: "#FECACA",
    borderRadius: radius.md, padding: spacing.md,
    marginHorizontal: spacing.lg, marginVertical: spacing.sm,
  },
  headline: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 },
  title: { fontFamily: font.bold, fontSize: 13, color: "#991B1B", flex: 1 },
  body: { fontFamily: font.regular, fontSize: 11, color: "#7F1D1D", marginBottom: 6 },
  bold: { fontFamily: font.bold },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderRadius: 999, borderWidth: 1, borderColor: "#FECACA",
    backgroundColor: "#FFF", paddingHorizontal: 8, paddingVertical: 3,
  },
  chipDanger: { borderColor: "#FCA5A5", backgroundColor: "#FEE2E2" },
  chipLabel: { fontFamily: font.semibold, fontSize: 10, color: "#991B1B" },
  chipLabelDanger: { color: "#7F1D1D" },
  chipBadge: {
    backgroundColor: "#F87171", paddingHorizontal: 5, paddingVertical: 1,
    borderRadius: 3,
  },
  chipBadgeDanger: { backgroundColor: "#B91C1C" },
  chipBadgeText: { fontFamily: font.bold, fontSize: 10, color: "#FFF" },
});
