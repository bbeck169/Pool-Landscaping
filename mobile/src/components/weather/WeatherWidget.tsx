/**
 * WeatherWidget — Mobile Parity (A1/B2).
 * Renders current conditions, 24h hourly strip, 5-day forecast, radar button.
 * Role-gated: tech + admin only. Customer must never see.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, AppState, Modal, Platform, Pressable, Image,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
// Feb-2026 · P39c — the Windy iframe / WebView is replaced by the
// NWS ridge/standard animated GIF. ``<Image>`` renders on native +
// web out of the box; no more ``react-native-webview`` gating.

import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import {
  fetchTenantLocation, fetchCurrentWeather, fetchHourlyWeather,
  fetchDailyWeather, fetchWeatherRadar, fetchWeatherAlerts,
  CurrentWeather, HourlyEntry, DailyEntry, WeatherAlert,
} from "@/src/api/weather";

const REFRESH_MS = 5 * 60 * 1000;

type Props = { onHourlyLoaded?: (hourly: HourlyEntry[]) => void };

export default function WeatherWidget({ onHourlyLoaded }: Props) {
  const [current, setCurrent] = useState<CurrentWeather | null>(null);
  const [hourly, setHourly] = useState<HourlyEntry[]>([]);
  const [daily, setDaily] = useState<DailyEntry[]>([]);
  // Feb-2026 · P39c — radar is now an NWS envelope
  // ``{ok, provider:"nws", radar_station, loop_url, still_url, ...}``.
  // Prefetched with the other endpoints so we can hide the Radar
  // button up-front when the tenant is outside NWS coverage.
  const [radar, setRadar] = useState<any | null>(null);
  const [radarOpen, setRadarOpen] = useState(false);
  const [radarBust, setRadarBust] = useState(0);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  // Feb-2026 · P39b — active NWS alerts banner + expand-collapse.
  const [alerts, setAlerts] = useState<WeatherAlert[]>([]);
  const [alertsExpanded, setAlertsExpanded] = useState(false);
  const coordsRef = useRef<{ lat: number; lon: number } | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadAll = useCallback(async (silent = false) => {
    try {
      let coords = coordsRef.current;
      if (!coords) {
        const loc = await fetchTenantLocation();
        coords = { lat: loc.hq_lat, lon: loc.hq_lng };
        coordsRef.current = coords;
      }
      const { lat, lon } = coords;
      const [cur, hr, dy, al, rd] = await Promise.all([
        fetchCurrentWeather(lat, lon).catch(() => null),
        fetchHourlyWeather(lat, lon).catch(() => null),
        // Feb-2026 · P39b — bumped 5 → 7 days.
        fetchDailyWeather(lat, lon, 7).catch(() => null),
        fetchWeatherAlerts(lat, lon).catch(() => null),
        // Feb-2026 · P39c — pre-fetch radar so the button hides on
        // out-of-US / no_radar_station tenants without teasing an
        // empty modal.
        fetchWeatherRadar(lat, lon).catch(() => null),
      ]);
      if (cur && cur.ok !== false) setCurrent(cur);
      if (hr?.hourly) {
        setHourly(hr.hourly);
        onHourlyLoaded?.(hr.hourly);
      }
      if (dy?.daily) setDaily(dy.daily);
      // ok:false or reject → banner just doesn't render.
      setAlerts(al && al.ok !== false && al.alerts ? al.alerts : []);
      // ok:false or reject → button hides + modal never opens.
      setRadar(rd && (rd as any).ok !== false && (rd as any).loop_url
        ? rd : null);
      if (!cur && !hr && !dy) setFailed(true);
      else setFailed(false);
    } catch {
      if (!silent) setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [onHourlyLoaded]);

  useEffect(() => {
    loadAll();
    timerRef.current = setInterval(() => loadAll(true), REFRESH_MS);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [loadAll]);

  useEffect(() => {
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "active") loadAll(true);
    });
    return () => sub.remove();
  }, [loadAll]);

  const openRadar = () => {
    // Feb-2026 · P39c — radar is pre-fetched in loadAll(); guard is
    // defensive (button below is hidden when ``radar`` is null).
    if (radar?.loop_url) setRadarOpen(true);
  };

  if (loading) return (
    <View testID="weather-widget" style={styles.container}>
      <ActivityIndicator color={colors.brand} />
    </View>
  );
  if (failed || !current) return null;

  // Feb-2026 · P39b — alerts banner severity coloring.
  const _severityRank = (s?: string): "red" | "amber" | "slate" => {
    const t = String(s || "").toLowerCase();
    if (t === "extreme" || t === "severe") return "red";
    if (t === "moderate") return "amber";
    return "slate";
  };
  const _palette = (rank: "red" | "amber" | "slate") => {
    if (rank === "red") return { bg: "#FEE2E2", border: "#FCA5A5", fg: "#7F1D1D" };
    if (rank === "amber") return { bg: "#FEF3C7", border: "#FCD34D", fg: "#78350F" };
    return { bg: "#E2E8F0", border: "#94A3B8", fg: "#1E293B" };
  };
  const _rank = { red: 0, amber: 1, slate: 2 };
  const _sortedAlerts = [...alerts].sort(
    (a, b) => _rank[_severityRank(a.severity)] - _rank[_severityRank(b.severity)]
  );
  const _topRank = _sortedAlerts.length
    ? _severityRank(_sortedAlerts[0].severity) : "slate";
  const _bannerPalette = _palette(_topRank);
  const _visibleAlerts = alertsExpanded
    ? _sortedAlerts : _sortedAlerts.slice(0, 1);
  const _hiddenCount = Math.max(0, _sortedAlerts.length - _visibleAlerts.length);
  const _truncate = (s: string | undefined, n = 180) =>
    !s ? "" : (s.length > n ? s.slice(0, n - 1) + "…" : s);
  const _fmtExpires = (iso?: string) => {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return "";
      const h = d.getHours();
      const m = String(d.getMinutes()).padStart(2, "0");
      const h12 = h % 12 === 0 ? 12 : h % 12;
      return `${h12}:${m}${h >= 12 ? "pm" : "am"}`;
    } catch { return ""; }
  };

  return (
    <View testID="weather-widget" style={styles.container}>
      {/* Feb-2026 · P39b — Alerts banner. Above current conditions,
          same severity palette as web. Multi-alert case: first row
          visible + "and N more" pill that expands the list inline. */}
      {_sortedAlerts.length > 0 && (
        <View
          testID="mobile-weather-alerts-banner"
          style={[styles.alertsBanner, {
            backgroundColor: _bannerPalette.bg,
            borderColor: _bannerPalette.border,
          }]}
        >
          {_visibleAlerts.map((a, i) => (
            <View
              key={i}
              testID={`mobile-weather-alert-item-${i}`}
              style={[styles.alertRow, i > 0 && {
                borderTopWidth: 1, borderTopColor: _bannerPalette.border,
                marginTop: 8, paddingTop: 8,
              }]}
            >
              <Text style={[styles.alertEvent, { color: _bannerPalette.fg }]}>
                {a.event || "Alert"}
              </Text>
              <Text style={[styles.alertHeadline, { color: _bannerPalette.fg }]}>
                {_truncate(a.headline, 180)}
              </Text>
              {a.expires_at ? (
                <Text style={[styles.alertExpires, { color: _bannerPalette.fg }]}>
                  Expires {_fmtExpires(a.expires_at)}
                </Text>
              ) : null}
            </View>
          ))}
          {_hiddenCount > 0 && (
            <Pressable
              testID="mobile-weather-alerts-more-pill"
              onPress={() => setAlertsExpanded(true)}
              style={[styles.alertsMorePill, {
                backgroundColor: _bannerPalette.fg,
              }]}
            >
              <Text style={[styles.alertsMorePillText, {
                color: _bannerPalette.bg,
              }]}>and {_hiddenCount} more</Text>
            </Pressable>
          )}
        </View>
      )}

      {/* Current conditions */}
      <View style={styles.currentRow}>
        <View style={styles.currentLeft}>
          <Text style={styles.temp}>{Math.round(current.temp_f || 0)}°F</Text>
          <Text style={styles.condition}>{current.condition}</Text>
        </View>
        <View style={styles.currentRight}>
          <MiniStat icon="arrow-up" value={`${Math.round(current.high || 0)}°`} />
          <MiniStat icon="arrow-down" value={`${Math.round(current.low || 0)}°`} />
          <MiniStat icon="water-outline" value={`${current.humidity || 0}%`} />
          <MiniStat icon="speedometer-outline" value={`${Math.round(current.wind_mph || 0)} mph`} />
          {/* Feb-2026 · P39b — UV; NWS doesn't publish so render "—" on null. */}
          <MiniStat
            icon="sunny-outline"
            value={current.uv == null ? "UV —" : `UV ${current.uv}`}
            testID="mobile-weather-current-uv"
          />
        </View>
      </View>

      {/* Hourly strip */}
      {hourly.length > 0 && (
        <View testID="weather-hourly-strip">
          <Text style={styles.sectionLabel}>Next 24 hours</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.hourlyScroll}>
            {hourly.slice(0, 24).map((h, i) => {
              const hr = new Date(h.time).getHours();
              const label = hr === 0 ? "12a" : hr < 12 ? `${hr}a` : hr === 12 ? "12p" : `${hr - 12}p`;
              const isRainy = h.chance_of_rain >= 60;
              return (
                <View key={i} style={styles.hourlyCell}>
                  <Text style={styles.hourlyTime}>{label}</Text>
                  <Text style={styles.hourlyTemp}>{Math.round(h.temp_f)}°</Text>
                  {isRainy && (
                    <View style={styles.rainDot}>
                      <Ionicons name="rainy" size={10} color="#2563EB" />
                      <Text style={styles.rainPct}>{h.chance_of_rain}%</Text>
                    </View>
                  )}
                </View>
              );
            })}
          </ScrollView>
        </View>
      )}

      {/* 7-day forecast — Feb-2026 · P39b bumped 5 → 7 */}
      {daily.length > 0 && (
        <View testID="weather-5day-forecast">
          <Text style={styles.sectionLabel}>7-Day Forecast</Text>
          {daily.slice(0, 7).map((d, i) => {
            const dayName = new Date(d.date + "T12:00:00").toLocaleDateString("en-US", { weekday: "short" });
            return (
              <View
                key={i}
                style={styles.dailyRow}
                testID={`mobile-weather-day-${i}`}
              >
                <Text style={styles.dailyDay}>{i === 0 ? "Today" : dayName}</Text>
                <Text style={styles.dailyCondition} numberOfLines={1}>{d.condition}</Text>
                {d.chance_of_rain >= 30 && (
                  <View style={styles.dailyRain}>
                    <Ionicons name="rainy" size={10} color="#2563EB" />
                    <Text style={styles.dailyRainText}>{d.chance_of_rain}%</Text>
                  </View>
                )}
                <Text style={styles.dailyHigh}>{Math.round(d.high)}°</Text>
                <View style={styles.tempBar}>
                  <View style={[styles.tempBarFill, { width: `${Math.max(20, ((d.high - d.low) / 40) * 100)}%` }]} />
                </View>
                <Text style={styles.dailyLow}>{Math.round(d.low)}°</Text>
              </View>
            );
          })}
        </View>
      )}

      {/* Radar button — hidden when radar.ok:false (out-of-US). */}
      {radar?.loop_url ? (
        <TouchableOpacity testID="weather-radar-open" style={styles.radarBtn} onPress={openRadar} activeOpacity={0.7}>
          <Ionicons name="navigate-outline" size={16} color={colors.brand} />
          <Text style={styles.radarBtnText}>Live Radar</Text>
        </TouchableOpacity>
      ) : null}

      {/* Feb-2026 · P39c — Radar modal. Windy WebView swapped for
          the NWS ridge/standard animated GIF. Cross-platform
          ``<Image>`` handles native + web; cache-busted by appending
          ``?t=<bust>`` when the user taps the refresh button. */}
      <Modal visible={radarOpen} animationType="slide" onRequestClose={() => setRadarOpen(false)}>
        <View style={styles.radarModal}>
          <View style={styles.radarHeader}>
            <Text style={styles.radarTitle}>Live Radar</Text>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <TouchableOpacity
                testID="mobile-weather-radar-refresh"
                onPress={() => setRadarBust(Date.now())}
              >
                <Ionicons name="refresh" size={22} color={colors.onSurface} />
              </TouchableOpacity>
              <TouchableOpacity onPress={() => setRadarOpen(false)}>
                <Ionicons name="close" size={24} color={colors.onSurface} />
              </TouchableOpacity>
            </View>
          </View>
          {radar?.loop_url ? (
            <>
              <Image
                testID="mobile-weather-radar-img"
                source={{ uri: radarBust
                  ? `${radar.loop_url}?t=${radarBust}`
                  : radar.loop_url }}
                accessibilityLabel={`NEXRAD radar loop for ${radar.radar_station}`}
                resizeMode="contain"
                style={{ flex: 1, width: "100%", backgroundColor: "#000" }}
              />
              <Text
                testID="mobile-weather-radar-station"
                style={styles.radarStationCaption}
              >
                NEXRAD radar station: {radar.radar_station}
              </Text>
            </>
          ) : (
            <ActivityIndicator style={{ flex: 1 }} color={colors.brand} />
          )}
        </View>
      </Modal>
    </View>
  );
}

function MiniStat({ icon, value, testID }: { icon: string; value: string; testID?: string }) {
  return (
    <View style={styles.miniStat} testID={testID}>
      <Ionicons name={icon as any} size={12} color={colors.muted} />
      <Text style={styles.miniStatText}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.lg,
  },
  currentRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.md },
  currentLeft: {},
  temp: { fontFamily: font.bold, fontSize: 36, color: colors.onSurface },
  condition: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted, marginTop: -2 },
  currentRight: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, maxWidth: 160 },
  miniStat: { flexDirection: "row", alignItems: "center", gap: 3 },
  miniStatText: { fontFamily: font.medium, fontSize: 11, color: colors.muted },
  sectionLabel: { fontFamily: font.bold, fontSize: 11, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginTop: spacing.sm, marginBottom: spacing.xs },
  hourlyScroll: { gap: 2, paddingVertical: spacing.xs },
  hourlyCell: { alignItems: "center", width: 48, paddingVertical: 6 },
  hourlyTime: { fontFamily: font.medium, fontSize: 10, color: colors.muted },
  hourlyTemp: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface, marginTop: 2 },
  rainDot: { flexDirection: "row", alignItems: "center", gap: 1, marginTop: 2 },
  rainPct: { fontFamily: font.bold, fontSize: 8, color: "#2563EB" },
  dailyRow: { flexDirection: "row", alignItems: "center", paddingVertical: 6, borderTopWidth: 1, borderTopColor: colors.divider },
  dailyDay: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, width: 50 },
  dailyCondition: { fontFamily: font.regular, fontSize: 11, color: colors.muted, flex: 1, marginRight: spacing.sm },
  dailyRain: { flexDirection: "row", alignItems: "center", gap: 2, marginRight: spacing.sm },
  dailyRainText: { fontFamily: font.bold, fontSize: 9, color: "#2563EB" },
  dailyHigh: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface, width: 30, textAlign: "right" },
  tempBar: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.surfaceTertiary, marginHorizontal: 4 },
  tempBarFill: { height: 4, borderRadius: 2, backgroundColor: colors.brand },
  dailyLow: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, width: 30, textAlign: "right" },
  radarBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: spacing.md, paddingVertical: 8, borderRadius: radius.sm, backgroundColor: colors.brandTertiary },
  radarBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  radarModal: { flex: 1, backgroundColor: colors.surface },
  radarHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: spacing.lg, paddingTop: Platform.OS === "ios" ? 56 : spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border },
  radarTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  // Feb-2026 · P39c — station caption below the radar image.
  radarStationCaption: {
    fontFamily: font.medium, fontSize: fontSize.xs,
    color: colors.onSurfaceMuted,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.border,
  },
  // Feb-2026 · P39b — alerts banner styles.
  alertsBanner: {
    borderRadius: radius.md,
    borderWidth: 1,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  alertRow: {},
  alertEvent: { fontFamily: font.bold, fontSize: fontSize.sm },
  alertHeadline: { fontFamily: font.regular, fontSize: fontSize.xs, marginTop: 2 },
  alertExpires: { fontFamily: font.medium, fontSize: 10, marginTop: 2, opacity: 0.8 },
  alertsMorePill: {
    alignSelf: "flex-start",
    paddingHorizontal: 8, paddingVertical: 2,
    borderRadius: 999, marginTop: spacing.sm,
  },
  alertsMorePillText: {
    fontFamily: font.bold, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.8,
  },
});
