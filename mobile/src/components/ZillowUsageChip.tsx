/**
 * Phase 56.9b Step 7 — Zillow usage chip (mobile).
 *
 * Renders a compact chip suitable for the Header `right` slot. Polls
 * /zillow/me/usage; goes yellow ≥80% and red at 100% cap or budget
 * exhaustion. When rateLimited={true} the caller can render the full
 * banner below the header via <ZillowRateLimitedBanner />.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, Linking } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { colors, font, fontSize, radius, spacing } from "@/src/theme";

const POLL_MS = 60_000;

interface UsageCaps {
  role: string;
  usage: { tech_today: number; tech_month: number; tech_daily_cap: number; tech_monthly_cap: number };
  allowed: boolean;
  reason: string | null;
  reset_at: string | null;
  tenant_budget: number;
  tenant_used: number;
  tenant_pct: number;
  budget_warning: boolean;
}

export function ZillowUsageChip({ refreshKey, testID = "zillow-usage-chip" }: { refreshKey?: number; testID?: string }) {
  const [caps, setCaps] = useState<UsageCaps | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/zillow/me/usage");
      setCaps(r);
    } catch {
      // fail silent — chip absent is a fine degradation
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load, refreshKey]);

  if (!caps) return null;

  const isTech = caps.role === "technician";
  const { tech_today, tech_month, tech_daily_cap, tech_monthly_cap } = caps.usage || ({} as any);
  const dayPct = tech_daily_cap ? tech_today / tech_daily_cap : 0;
  const monthPct = tech_monthly_cap ? tech_month / tech_monthly_cap : 0;
  const capPct = Math.max(dayPct, monthPct);

  let bg = colors.surface;
  let fg = colors.onSurface;
  let borderColor = colors.border;
  if (capPct >= 1 || caps.reason === "tenant_budget_exhausted") {
    bg = "#FEE2E2"; fg = "#991B1B"; borderColor = "#FCA5A5";
  } else if (capPct >= 0.8 || caps.budget_warning) {
    bg = "#FEF3C7"; fg = "#92400E"; borderColor = "#FCD34D";
  }

  const label = isTech
    ? `Zillow ${tech_today}/${tech_daily_cap}d · ${tech_month}/${tech_monthly_cap}m`
    : `Zillow ${caps.tenant_used}/${caps.tenant_budget}`;

  return (
    <View style={[styles.chip, { backgroundColor: bg, borderColor }]} testID={testID}>
      <Ionicons name="information-circle-outline" size={12} color={fg} />
      <Text style={[styles.chipText, { color: fg }]} numberOfLines={1}>{label}</Text>
    </View>
  );
}

export function ZillowRateLimitedBanner({ testID = "zillow-rate-banner" }: { testID?: string }) {
  const [caps, setCaps] = useState<UsageCaps | null>(null);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await api.get("/zillow/me/usage");
        if (alive) setCaps(r);
      } catch { /* silent */ }
    };
    load();
    const t = setInterval(load, POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!caps) return null;
  const capReached = (caps.usage?.tech_today ?? 0) >= (caps.usage?.tech_daily_cap ?? Infinity)
    || (caps.usage?.tech_month ?? 0) >= (caps.usage?.tech_monthly_cap ?? Infinity)
    || caps.reason === "tenant_budget_exhausted";
  if (!capReached) return null;
  return (
    <View style={styles.banner} testID={testID}>
      <Ionicons name="warning-outline" size={14} color="#991B1B" />
      <View style={{ flex: 1 }}>
        <Text style={styles.bannerTitle}>Zillow lookup limit reached</Text>
        <Text style={styles.bannerBody}>
          {caps.reason === "tenant_budget_exhausted"
            ? "Your tenant is out of Zillow budget for the month."
            : caps.reset_at
            ? `Resets ${caps.reset_at.slice(0, 16).replace("T", " ")}.`
            : "Try again later."}
        </Text>
      </View>
      <Pressable
        onPress={() => Linking.openURL("mailto:admin@aquaterra.com?subject=Zillow%20lookup%20limit%20reached")}
        style={styles.askBtn}
        testID={`${testID}-ask-admin`}
      >
        <Text style={styles.askBtnText}>Ask admin</Text>
      </Pressable>
    </View>
  );
}

export default ZillowUsageChip;

const styles = StyleSheet.create({
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: radius.pill,
    borderWidth: 1,
    maxWidth: 200,
  },
  chipText: { fontFamily: font.semibold, fontSize: 10, letterSpacing: 0.2 },
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: "#FEE2E2",
    borderColor: "#FCA5A5",
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginHorizontal: spacing.lg,
    marginTop: spacing.sm,
  },
  bannerTitle: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#991B1B" },
  bannerBody: { fontFamily: font.regular, fontSize: fontSize.xs, color: "#991B1B", marginTop: 1 },
  askBtn: {
    backgroundColor: "#991B1B",
    borderRadius: radius.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
  },
  askBtnText: { fontFamily: font.bold, fontSize: fontSize.xs, color: "#fff" },
});
