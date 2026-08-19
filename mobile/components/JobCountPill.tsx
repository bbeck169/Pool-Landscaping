/**
 * Feb-2026 · JobCountPill — mobile port.
 *
 * Rounded rectangle badge showing "remaining/total" for SERVICES
 * or REPAIRS. Mirrors ``frontend/src/components/JobCountPill.jsx``
 * one-to-one; both surfaces consume the same classifier from
 * ``lib/jobCategory``.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";

type Category = "services" | "repairs";

interface Props {
  category: Category;
  total: number;
  remaining: number;
  testID?: string;
}

// Same tokens the web component pulls from Tailwind's ``sky-500`` /
// ``slate-800``. Kept as raw hex here because React Native has no
// Tailwind runtime; the values match what the web pill compiles
// down to at run-time.
const _PALETTE: Record<Category, { bg: string; label: string }> = {
  services: { bg: "#0EA5E9", label: "SERVICES" },  // sky-500
  repairs:  { bg: "#1E293B", label: "REPAIRS"  },  // slate-800
};

export default function JobCountPill({
  category,
  total,
  remaining,
  testID,
}: Props) {
  const p = _PALETTE[category];
  if (!p) return null;
  const safeTotal = Math.max(0, Number(total) || 0);
  const safeRemaining = Math.max(0, Math.min(safeTotal, Number(remaining) || 0));
  const rootTestID = testID || `job-count-pill-${category}`;
  return (
    <View style={[styles.pill, { backgroundColor: p.bg }]} testID={rootTestID}>
      <Text style={styles.count} testID={`${rootTestID}-count`}>
        <Text testID={`${rootTestID}-remaining`}>{safeRemaining}</Text>
        <Text style={styles.slash}>/</Text>
        <Text testID={`${rootTestID}-total`}>{safeTotal}</Text>
      </Text>
      <Text style={styles.label} testID={`${rootTestID}-label`}>
        {p.label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    borderRadius: 16,
    paddingHorizontal: 20,
    paddingVertical: 10,
    minWidth: 112,
    alignItems: "center",
    justifyContent: "center",
    // Match the web pill's drop-shadow. iOS uses shadow*, Android
    // uses elevation — set both.
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.2,
    shadowRadius: 2,
    elevation: 2,
  },
  count: {
    color: "#fff",
    fontSize: 28,
    fontWeight: "700",
    letterSpacing: -0.5,
    textShadowColor: "rgba(0,0,0,0.20)",
    textShadowOffset: { width: 0, height: 1 },
    textShadowRadius: 2,
  },
  slash: { opacity: 0.7 },
  label: {
    color: "rgba(255,255,255,0.95)",
    fontSize: 10,
    fontWeight: "600",
    letterSpacing: 2,
    marginTop: 4,
  },
});
