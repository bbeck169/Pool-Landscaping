/**
 * CreditsBudgetChip — Admin mobile top bar chip (B3).
 * Green >= 500, Amber < 500, Red < 100. Tap opens AI Dock.
 */
import React, { useCallback, useEffect, useState } from "react";
import { Text, StyleSheet, TouchableOpacity, AppState } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { font } from "@/src/theme";
import { getAICreditsBalance } from "@/src/api/aiDock";

type Tier = "green" | "amber" | "red";

const TIER_STYLES: Record<Tier, { bg: string; fg: string; border: string }> = {
  green: { bg: "#DCFCE7", fg: "#166534", border: "#86EFAC" },
  amber: { bg: "#FEF3C7", fg: "#92400E", border: "#FDE68A" },
  red: { bg: "#FEE2E2", fg: "#991B1B", border: "#FECACA" },
};

function getTier(balance: number): Tier {
  if (balance >= 500) return "green";
  if (balance >= 100) return "amber";
  return "red";
}

type Props = { onPress?: () => void };

export default function CreditsBudgetChip({ onPress }: Props) {
  const [balance, setBalance] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await getAICreditsBalance();
      setBalance(d.balance ?? null);
    } catch {
      setBalance(null);
    }
  }, []);

  useEffect(() => {
    load();
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active") load();
    });
    return () => sub.remove();
  }, [load]);

  if (balance === null) return null;

  const tier = getTier(balance);
  const s = TIER_STYLES[tier];

  return (
    <TouchableOpacity
      testID="credits-budget-chip"
      accessibilityLabel={`Credits: ${balance}`}
      style={[styles.chip, { backgroundColor: s.bg, borderColor: s.border }]}
      onPress={onPress}
      activeOpacity={0.7}
    >
      <Ionicons name="sparkles" size={12} color={s.fg} />
      <Text style={[styles.label, { color: s.fg }]}>{balance}c</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 999,
    borderWidth: 1,
  },
  label: { fontFamily: font.bold, fontSize: 11 },
});
