/**
 * Lead Profile parity (web Z1) · "Requested Service" card — verbatim form text.
 * Fetches GET /leads/{id}/raw-submission only when lead.meta.submission_id is set
 * (web parity); legacy leads / 404 render "—" silently.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { pickRequestedService } from "@/src/lib/leadRequestedService";

export default function LeadRequestedServiceCard({ leadId, submissionId }: { leadId: string; submissionId?: string | null }) {
  const [text, setText] = useState("");

  useEffect(() => {
    let alive = true;
    setText("");
    if (!submissionId) return;
    api.get(`/leads/${encodeURIComponent(leadId)}/raw-submission`)
      .then((sub: any) => { if (alive) setText(pickRequestedService(sub)); })
      .catch(() => { /* legacy lead / missing submission — keep "—" */ });
    return () => { alive = false; };
  }, [leadId, submissionId]);

  return (
    <View style={st.card} testID="lead-requested-service-card">
      <View style={st.labelRow}>
        <Ionicons name="clipboard-outline" size={14} color={colors.muted} />
        <Text style={st.label}>REQUESTED SERVICE</Text>
      </View>
      {text ? (
        <Text style={st.value} selectable testID="lead-requested-service-text">{text}</Text>
      ) : (
        <Text style={st.empty} testID="lead-requested-service-empty">—</Text>
      )}
    </View>
  );
}

const st = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  labelRow: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: spacing.sm },
  label: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 1 },
  value: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 22 },
  empty: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
});
