/**
 * Phase 41.5c · Feb-2026 — Mobile Weather screen (drawer route ``/weather``).
 *
 * Composes:
 *   • The existing ``<WeatherWidget />`` (current conditions, 24h
 *     hourly strip, 5-day forecast, radar) — reused as-is, no
 *     duplication of its rendering logic.
 *   • A service-risk 5-day grid using ``GET /api/weather/risk`` and
 *     a reschedule-recommendations card via
 *     ``GET /api/weather/reschedule-recommendations`` — mirroring
 *     the web ``WeatherHub`` at ``/weather``.
 *
 * Backend endpoints (no new endpoints):
 *   • GET /api/tenants/mine/location             (via WeatherWidget)
 *   • GET /api/weather/current|hourly|daily|radar (via WeatherWidget)
 *   • GET /api/weather/risk?lat=&lng=&days=5
 *   • GET /api/weather/reschedule-recommendations
 *
 * Role gate: admin / super_admin — mirrors the web ``<AdminOnly>``
 * route wrapper on ``/weather``.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
  ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import WeatherWidget from "@/src/components/weather/WeatherWidget";
import { fetchTenantLocation } from "@/src/api/weather";

type RiskDay = {
  date: string;
  high?: number;
  low?: number;
  precip: number;
  wind_mph: number;
  service_risk_rating: "good" | "fair" | "poor" | string;
  risk_reasons?: string[];
};

type Reschedule = {
  suggested: any[];
  poor_days: string[];
};

const RISK_BG: Record<string, string> = {
  good:  "#DCFCE7",
  fair:  "#FEF3C7",
  poor:  "#FEE2E2",
};
const RISK_FG: Record<string, string> = {
  good:  "#166534",
  fair:  "#854D0E",
  poor:  "#991B1B",
};

export default function WeatherScreen() {
  const { user } = useAuth();
  // Mirror the web ``<AdminOnly>`` guard verbatim.
  const isAdmin = user?.role === "admin" || (user?.role as any) === "super_admin";

  const [risk, setRisk] = useState<{ days: RiskDay[] } | null>(null);
  const [recs, setRecs] = useState<Reschedule | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [widgetKey, setWidgetKey] = useState(0);

  const load = useCallback(async () => {
    if (!isAdmin) return;
    setError(null);
    try {
      // Prefer tenant HQ coords (matches WeatherWidget's default);
      // fall back to the hardcoded Vistancia lat/lng the web page
      // uses so the screen still renders on tenants without a
      // location configured.
      let lat = 33.7897, lng = -112.3226;
      try {
        const loc = await fetchTenantLocation();
        if (loc?.hq_lat && loc?.hq_lng) { lat = loc.hq_lat; lng = loc.hq_lng; }
      } catch { /* keep defaults */ }

      const [r, rc] = await Promise.all([
        api.get(`/weather/risk?lat=${lat}&lng=${lng}&days=5`)
          .catch(() => ({ days: [] })),
        api.get("/weather/reschedule-recommendations")
          .catch(() => ({ suggested: [], poor_days: [] })),
      ]);
      setRisk(r);
      setRecs(rc);
    } catch (e: any) {
      setError(e?.message || "Failed to load weather");
    } finally {
      setRefreshing(false);
    }
  }, [isAdmin]);

  useEffect(() => { load(); }, [load]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    // Remount WeatherWidget so it refetches current/hourly/daily too.
    setWidgetKey((k) => k + 1);
    load();
  }, [load]);

  if (!isAdmin) {
    return (
      <View style={s.root} testID="weather-page-role-gate">
        <Header title="Weather" back />
        <View style={s.center}>
          <Ionicons name="lock-closed" size={32} color={colors.muted} />
          <Text style={s.centerText}>Admin only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={s.root} testID="weather-page">
      <Header title="Weather" subtitle="5-day forecast · service risk" back />
      <ScrollView
        testID="weather-page-scroll"
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={<RefreshControl refreshing={refreshing}
                            onRefresh={onRefresh} />}
      >
        {/* Reused: current + hourly + 5-day forecast + radar */}
        <WeatherWidget key={widgetKey} />

        {/* Service-risk grid — mirrors the web WeatherHub. */}
        <Text style={s.sectionLabel}>Service risk · next 5 days</Text>
        {error ? (
          <View style={s.errorBanner} testID="weather-page-error">
            <Ionicons name="warning" size={16} color="#7F1D1D" />
            <Text style={s.errorText}>{error}</Text>
          </View>
        ) : !risk ? (
          <ActivityIndicator color={colors.brand}
                             testID="weather-page-risk-loading" />
        ) : risk.days.length === 0 ? (
          <View style={s.emptyCard} testID="weather-page-risk-empty">
            <Text style={s.emptyText}>Risk forecast unavailable.</Text>
          </View>
        ) : (
          <View style={s.riskGrid} testID="weather-page-risk-grid">
            {risk.days.map((d) => {
              const bg = RISK_BG[d.service_risk_rating] || colors.surfaceTertiary;
              const fg = RISK_FG[d.service_risk_rating] || colors.onSurfaceSecondary;
              return (
                <View key={d.date}
                      style={[s.riskCell, { backgroundColor: bg }]}
                      testID={`weather-page-risk-${d.date}`}>
                  <Text style={[s.riskDate, { color: fg }]}>
                    {d.date.slice(5)}
                  </Text>
                  <Text style={[s.riskTemp, { color: fg }]}>
                    {Math.round(d.high ?? 0)}°/{Math.round(d.low ?? 0)}°
                  </Text>
                  <Text style={[s.riskMeta, { color: fg }]}>
                    {d.precip}% · {Math.round(d.wind_mph)} mph
                  </Text>
                  <Text style={[s.riskRating, { color: fg }]}
                        testID={`weather-page-risk-rating-${d.date}`}>
                    {d.service_risk_rating}
                  </Text>
                </View>
              );
            })}
          </View>
        )}

        {/* Reschedule recommendations. */}
        <Text style={s.sectionLabel}>Reschedule recommendations</Text>
        {!recs ? (
          <ActivityIndicator color={colors.brand}
                             testID="weather-page-recs-loading" />
        ) : (recs.suggested || []).length === 0 ? (
          <View style={s.emptyCard} testID="weather-page-recs-empty">
            <Text style={s.emptyText}>
              No poor-weather days in the next 3 days.
            </Text>
          </View>
        ) : (
          <View style={s.recsCard} testID="weather-page-recs-card">
            {recs.poor_days?.length ? (
              <Text style={s.poorDaysText}>
                Poor days: {recs.poor_days.join(", ")}
              </Text>
            ) : null}
            {recs.suggested.slice(0, 10).map((j: any) => (
              <View key={j.id} style={s.recRow}
                    testID={`weather-page-rec-${j.id}`}>
                <Text style={s.recTitle}>{j.title || "Job"}</Text>
                <Text style={s.recMeta}>
                  {j.customer_name || "—"} · {(j.scheduled_date || "").slice(0, 10)}
                  {j.technician_name ? ` · ${j.technician_name}` : ""}
                </Text>
              </View>
            ))}
          </View>
        )}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md },
  centerText: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.muted },

  sectionLabel: {
    fontFamily: font.bold, fontSize: 11, textTransform: "uppercase",
    letterSpacing: 0.8, color: colors.muted,
    marginTop: spacing.md, marginBottom: spacing.sm,
  },

  errorBanner: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#FEE2E2", borderColor: "#FCA5A5", borderWidth: 1,
    borderRadius: radius.md, padding: spacing.md,
  },
  errorText: { fontFamily: font.regular, fontSize: fontSize.sm, color: "#7F1D1D" },

  emptyCard: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, alignItems: "center",
  },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },

  riskGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  riskCell: {
    flexBasis: "31%", flexGrow: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    alignItems: "center",
  },
  riskDate: { fontFamily: font.bold, fontSize: 11 },
  riskTemp: { fontFamily: font.bold, fontSize: fontSize.lg, marginTop: 4 },
  riskMeta: { fontFamily: font.regular, fontSize: fontSize.xs, marginTop: 2 },
  riskRating: {
    fontFamily: font.bold, fontSize: 10, textTransform: "uppercase",
    letterSpacing: 0.8, marginTop: 4,
  },

  recsCard: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md,
  },
  poorDaysText: {
    fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted,
    marginBottom: spacing.sm,
  },
  recRow: {
    borderTopWidth: 1, borderTopColor: colors.border,
    paddingVertical: spacing.sm,
  },
  recTitle: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  recMeta:  { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 2 },
});
