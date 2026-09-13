/**
 * Portal Onboarding Health Tile — mobile parity (Dispatch A, Feature 2).
 *
 * Horizontal 4-card admin snapshot of the customer portal funnel:
 *   Invited → Activated → Signed in → Never logged in
 *
 * Reads: GET /api/reports/portal-onboarding-health?window_days=30
 * Admin-gated (parent must only render for admin/super_admin).
 *
 * Each card is tappable and triggers a filter callback on the parent
 * Customers List. The "Chase" button under Invited opens the
 * ChaseStalledInvitesSheet.
 */
import React, { useCallback, useEffect, useState } from "react";
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
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { mapApiError } from "@/src/utils/mapApiError";
import ChaseStalledInvitesSheet from "@/src/components/customers/ChaseStalledInvitesSheet";

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

type CohortKey = "invited" | "activated" | "signed_in" | "never_logged_in";

interface CohortDef {
  key: CohortKey;
  label: string;
  icon: string;
  testid: string;
}

const COHORT_ORDER: CohortDef[] = [
  { key: "invited",          label: "Invited",          icon: "mail-outline",         testid: "onboarding-cohort-invited" },
  { key: "activated",        label: "Activated",        icon: "checkmark-circle-outline", testid: "onboarding-cohort-activated" },
  { key: "signed_in",        label: "Signed in",        icon: "log-in-outline",       testid: "onboarding-cohort-signed-in" },
  { key: "never_logged_in",  label: "Never logged in",  icon: "time-outline",         testid: "onboarding-cohort-never" },
];

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface CohortData {
  count: number;
  delta_30d: number | null;
}

interface HealthResponse {
  cohorts: Record<CohortKey, CohortData>;
}

export interface OnboardingTileFilterCallbacks {
  onFilterInvited: () => void;
  onFilterActivated: () => void;
  onFilterSignedIn: () => void;
  onFilterNever: () => void;
}

interface Props extends OnboardingTileFilterCallbacks {
  /** Changing this value triggers a refetch (e.g., after bulk invite). */
  refetchToken?: unknown;
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                     */
/* ------------------------------------------------------------------ */

function DeltaArrow({ delta, testid }: { delta: number | null; testid: string }) {
  if (delta === null || delta === undefined) {
    return (
      <Text style={s.deltaNull} testID={testid}>
        — vs 30d
      </Text>
    );
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

function CohortCard({
  def,
  data,
  onPress,
}: {
  def: CohortDef;
  data: CohortData | undefined;
  onPress: () => void;
}) {
  const count = data?.count;
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [s.card, pressed && s.cardPressed]}
      testID={def.testid}
      accessibilityRole="button"
      accessibilityLabel={`View ${def.label} customers`}
    >
      <View style={s.cardLabelRow}>
        <Ionicons name={def.icon as any} size={14} color={colors.muted} />
        <Text style={s.cardLabel}>{def.label}</Text>
      </View>
      <Text style={s.cardCount}>
        {typeof count === "number" ? count.toLocaleString() : "—"}
      </Text>
      <DeltaArrow delta={data?.delta_30d ?? null} testid={`${def.testid}-delta`} />
    </Pressable>
  );
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export default function PortalOnboardingHealthTile({
  refetchToken,
  onFilterInvited,
  onFilterActivated,
  onFilterSignedIn,
  onFilterNever,
}: Props) {
  const { showToast } = useToast();
  const [data, setData] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [chaseOpen, setChaseOpen] = useState(false);
  const [refetchTick, setRefetchTick] = useState(0);

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
  }, [refetchTick, refetchToken]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChaseClose = useCallback(() => {
    setChaseOpen(false);
    setRefetchTick((t) => t + 1);
  }, []);

  // Map cohort key → filter callback
  const filterMap: Record<CohortKey, () => void> = {
    invited: onFilterInvited,
    activated: onFilterActivated,
    signed_in: onFilterSignedIn,
    never_logged_in: onFilterNever,
  };

  if (loading) {
    return (
      <View style={s.skeletonWrap} testID="onboarding-health-tile-skeleton">
        <ActivityIndicator size="small" color={colors.brand} />
        <Text style={s.skeletonText}>Loading onboarding health…</Text>
      </View>
    );
  }

  if (error || !data?.cohorts) {
    return null;
  }

  const invitedCount = data.cohorts.invited?.count ?? 0;
  const neverCount = data.cohorts.never_logged_in?.count ?? 0;
  const chaseAudienceUpperBound = Math.min(invitedCount, neverCount);

  return (
    <>
      <View style={s.tileWrap} testID="onboarding-health-tile">
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={s.scrollContent}
        >
          {COHORT_ORDER.map((def) => {
            const block = data.cohorts[def.key];
            const isInvited = def.key === "invited";
            return (
              <View key={def.key} style={s.cardCol}>
                <CohortCard
                  def={def}
                  data={block}
                  onPress={filterMap[def.key]}
                />
                {isInvited ? (
                  <Pressable
                    onPress={() => setChaseOpen(true)}
                    disabled={chaseAudienceUpperBound === 0}
                    style={({ pressed }) => [
                      s.chaseBtn,
                      chaseAudienceUpperBound === 0 && s.chaseBtnDisabled,
                      pressed && chaseAudienceUpperBound > 0 && s.chaseBtnPressed,
                    ]}
                    testID="onboarding-tile-invited-chase-cta"
                    accessibilityRole="button"
                    accessibilityLabel="Chase stalled portal invites"
                  >
                    <Ionicons name="megaphone-outline" size={14} color="#fff" />
                    <Text style={s.chaseBtnText}>Chase</Text>
                  </Pressable>
                ) : null}
              </View>
            );
          })}
        </ScrollView>
      </View>
      <ChaseStalledInvitesSheet
        visible={chaseOpen}
        onClose={handleChaseClose}
      />
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Styles                                                             */
/* ------------------------------------------------------------------ */

const s = StyleSheet.create({
  tileWrap: {
    marginBottom: spacing.md,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
    overflow: "hidden",
  },
  scrollContent: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
  },
  cardCol: {
    width: 150,
    gap: spacing.xs,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    minHeight: 96,
    justifyContent: "space-between",
  },
  cardPressed: {
    backgroundColor: colors.brandTertiary,
    borderColor: colors.brand,
  },
  cardLabelRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginBottom: 2,
  },
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
  deltaText: {
    fontFamily: font.semibold,
    fontSize: 10,
  },
  deltaNull: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
  },
  chaseBtn: {
    backgroundColor: colors.brand,
    borderRadius: radius.md,
    paddingVertical: 8,
    paddingHorizontal: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  chaseBtnPressed: {
    opacity: 0.85,
  },
  chaseBtnDisabled: {
    opacity: 0.4,
  },
  chaseBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
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
  skeletonText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
});
