/**
 * Portal Onboarding Health Tile — mobile parity.
 *
 * Phase 9-M (web parity 42e72c6a4 · Phase 9b): THREE cohort cards
 *   Activated → Signed in → Cards on file
 *
 * The former "Invited" card, its "Chase" button and the mobile-only
 * "Never logged in" card were removed.  The server still returns
 * those cohort blocks — the tile just no longer consumes them.
 * (``ChaseStalledInvitesSheet.tsx`` stays on disk, unimported, same
 * as web's ``ChaseStalledInvitesModal.jsx``.)
 *
 * Toggle semantics (single-select, owned by the parent list):
 *   * tap inactive card → activate its filter (swaps any other card)
 *   * tap the active card → clear the filter
 * Active visual: brand-colored 2px ring + bold brand-colored count.
 *
 * Reads: GET /api/reports/portal-onboarding-health?window_days=30
 * Admin-gated (parent must only render for admin/super_admin).
 */
import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { mapApiError } from "@/src/utils/mapApiError";

export type TileKey = "activated" | "signed_in" | "active_with_card_on_file";

// Phase 9-M (web parity 42e72c6a4) — onboarding tile filters live in the
// route params so they survive in-app nav + deep links, mirroring web's
// ``?portal_activated=1`` / ``?first_access=any`` /
// ``?has_payment_method=true`` URL convention.
export type TileParams = { portal_activated?: string; first_access?: string; has_payment_method?: string };

export function tileKeyFromParams(p: TileParams): TileKey | null {
  if (p.portal_activated === "1" || p.portal_activated === "true") return "activated";
  if (p.first_access === "any") return "signed_in";
  if (p.has_payment_method === "true" || p.has_payment_method === "1") return "active_with_card_on_file";
  return null;
}

export function tileParamsFor(key: TileKey | null): TileParams {
  return {
    portal_activated: key === "activated" ? "1" : undefined,
    first_access: key === "signed_in" ? "any" : undefined,
    has_payment_method: key === "active_with_card_on_file" ? "true" : undefined,
  };
}

interface CohortDef {
  key: TileKey;
  label: string;
  icon: string;
  testid: string;
}

export const COHORT_ORDER: CohortDef[] = [
  { key: "activated",                label: "Activated",     icon: "checkmark-circle-outline", testid: "onboarding-cohort-activated" },
  { key: "signed_in",                label: "Signed in",     icon: "log-in-outline",           testid: "onboarding-cohort-signed-in" },
  { key: "active_with_card_on_file", label: "Cards on file", icon: "card-outline",             testid: "portal-onboarding-cards-on-file-tile" },
];

interface CohortData {
  count: number;
  delta_30d: number | null;
}

interface HealthResponse {
  cohorts: Partial<Record<string, CohortData>>;
}

interface Props {
  /** Currently-active tile (derived from route params by the parent). */
  activeKey: TileKey | null;
  /** Fired with the tapped tile key; parent applies toggle semantics. */
  onToggle: (key: TileKey) => void;
  /** Changing this value triggers a refetch (e.g., after bulk invite). */
  refetchToken?: unknown;
}

function DeltaArrow({ delta, testid }: { delta: number | null; testid: string }) {
  if (delta === null || delta === undefined) {
    return <Text style={s.deltaNull} testID={testid}>— vs 30d</Text>;
  }
  const isUp = delta > 0;
  const isFlat = delta === 0;
  const arrow = isFlat ? "→" : isUp ? "↑" : "↓";
  const color = isFlat ? colors.muted : isUp ? "#059669" : "#DC2626";
  return (
    <Text style={[s.deltaText, { color }]} testID={testid}>
      {arrow} {Math.abs(delta).toLocaleString()} vs 30d
    </Text>
  );
}

function CohortCard({ def, data, isActive, onPress }: {
  def: CohortDef; data: CohortData | undefined; isActive: boolean; onPress: () => void;
}) {
  const count = data?.count;
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [s.card, isActive && s.cardActive, pressed && s.cardPressed]}
      testID={def.testid}
      accessibilityRole="button"
      accessibilityState={{ selected: isActive }}
      accessibilityLabel={isActive ? `Clear ${def.label} filter` : `Filter customers to ${def.label}`}
    >
      <View style={s.cardLabelRow}>
        <Ionicons name={def.icon as any} size={14} color={isActive ? colors.brand : colors.muted} />
        <Text style={[s.cardLabel, isActive && { color: colors.brand }]}>{def.label}</Text>
      </View>
      <Text style={[s.cardCount, isActive && s.cardCountActive]} testID={`${def.testid}-count`}>
        {typeof count === "number" ? count.toLocaleString() : "—"}
      </Text>
      <DeltaArrow delta={data?.delta_30d ?? null} testid={`${def.testid}-delta`} />
    </Pressable>
  );
}

export default function PortalOnboardingHealthTile({ refetchToken, activeKey, onToggle }: Props) {
  const { showToast } = useToast();
  const [data, setData] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const r = await api.get("/reports/portal-onboarding-health?window_days=30") as HealthResponse;
        if (!cancelled) { setData(r); setLoading(false); }
      } catch (e) {
        if (!cancelled) {
          setError(e);
          setLoading(false);
          showToast(mapApiError(e).message, "error");
        }
      }
    })();
    return () => { cancelled = true; };
  }, [refetchToken]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <View style={s.skeletonWrap} testID="onboarding-health-tile-skeleton">
        <ActivityIndicator size="small" color={colors.brand} />
        <Text style={s.skeletonText}>Loading onboarding health…</Text>
      </View>
    );
  }

  if (error || !data?.cohorts) return null;

  return (
    <View style={s.tileWrap} testID="onboarding-health-tile">
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.scrollContent}>
        {COHORT_ORDER.map((def) => (
          <View key={def.key} style={s.cardCol}>
            <CohortCard
              def={def}
              data={data.cohorts[def.key]}
              isActive={activeKey === def.key}
              onPress={() => onToggle(def.key)}
            />
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  tileWrap: {
    marginBottom: spacing.md,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
    overflow: "hidden",
  },
  scrollContent: { paddingHorizontal: spacing.sm, paddingVertical: spacing.sm, gap: spacing.sm },
  cardCol: { width: 150, gap: spacing.xs },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    minHeight: 96,
    justifyContent: "space-between",
  },
  cardActive: { borderWidth: 2, borderColor: colors.brand, backgroundColor: colors.brandTertiary },
  cardPressed: { opacity: 0.85 },
  cardLabelRow: { flexDirection: "row", alignItems: "center", gap: 4, marginBottom: 2 },
  cardLabel: {
    fontFamily: font.semibold,
    fontSize: 10,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    color: colors.muted,
  },
  cardCount: {
    fontFamily: font.bold,
    fontSize: 26,
    color: colors.onSurface,
    marginVertical: 2,
    fontVariant: ["tabular-nums"],
  },
  cardCountActive: { color: colors.brand, fontWeight: "800" },
  deltaText: { fontFamily: font.semibold, fontSize: 10 },
  deltaNull: { fontFamily: font.regular, fontSize: 10, color: colors.muted },
  skeletonWrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.md,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
    backgroundColor: colors.surface,
  },
  skeletonText: { fontFamily: font.regular, fontSize: 12, color: colors.muted },
});
