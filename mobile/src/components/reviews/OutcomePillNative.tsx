import React from "react";
import { View, Text } from "react-native";

const TONES: Record<string, { bg: string; fg: string; label: string }> = {
  pending: { bg: "#FEF3C7", fg: "#92400E", label: "Pending" },
  public_posted_intent: { bg: "#DCFCE7", fg: "#166534", label: "Posted" },
  private_feedback_captured: { bg: "#DBEAFE", fg: "#1E3A8A", label: "Private" },
  expired: { bg: "#E5E7EB", fg: "#374151", label: "Expired" },
  opted_out: { bg: "#FEE2E2", fg: "#991B1B", label: "Opted out" },
};

/** Compact outcome pill for review-request rows. */
export function OutcomePillNative({
  outcome,
  testID,
}: {
  outcome?: string;
  testID?: string;
}) {
  const t = TONES[outcome || "pending"] || TONES.pending;
  return (
    <View
      style={{
        alignSelf: "flex-start",
        backgroundColor: t.bg,
        paddingHorizontal: 8,
        paddingVertical: 2,
        borderRadius: 999,
      }}
      testID={testID || `outcome-${outcome}`}
    >
      <Text style={{ color: t.fg, fontSize: 10, fontWeight: "700" }}>
        {t.label}
      </Text>
    </View>
  );
}

export default OutcomePillNative;
