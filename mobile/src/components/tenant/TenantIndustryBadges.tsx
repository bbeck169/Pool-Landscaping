/**
 * TenantIndustryBadges — compact chip strip for tenant's active industries.
 *
 * Mirrors ``frontend/src/components/tenant/TenantIndustryBadges.jsx``.
 * ≤4 → all inline. >4 → first 3 + "+N more" chip that expands on press.
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { colors, font, radius } from "@/src/theme";
import { INDUSTRY_LABELS } from "@/src/config/industries";
import { useIndustries } from "@/src/hooks/useIndustries";

export default function TenantIndustryBadges({ max = 4 }: { max?: number }) {
  const { industries, labels, loaded } = useIndustries();
  const [expanded, setExpanded] = useState(false);

  if (!loaded || !industries.length) return null;

  const overflow = industries.length > max && !expanded;
  const shown = overflow ? industries.slice(0, max - 1) : industries;
  const hidden = overflow ? industries.slice(max - 1) : [];

  return (
    <View style={s.wrap} testID="tenant-industry-badges">
      {shown.map((slug: string) => (
        <View key={slug} style={s.chip} testID={`tenant-industry-badge-${slug}`}>
          <Text style={s.chipText}>
            {(labels || INDUSTRY_LABELS)[slug] || slug}
          </Text>
        </View>
      ))}
      {overflow ? (
        <Pressable
          onPress={() => setExpanded(true)}
          style={s.overflowChip}
          testID="tenant-industry-badge-overflow"
        >
          <Text style={s.overflowText}>+{hidden.length} more</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 4,
  },
  chip: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
    backgroundColor: "rgba(2,132,199,0.10)",
    borderWidth: 1,
    borderColor: "rgba(2,132,199,0.25)",
  },
  chipText: {
    fontFamily: font.semibold,
    fontSize: 11,
    color: colors.brand,
  },
  overflowChip: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  overflowText: {
    fontFamily: font.semibold,
    fontSize: 11,
    color: colors.muted,
  },
});
