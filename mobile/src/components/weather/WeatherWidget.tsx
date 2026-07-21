/**
 * WeatherWidget — Mobile Parity (A1/B2).
 * Renders current conditions, 24h hourly strip, 5-day forecast, radar button.
 * Role-gated: tech + admin only. Customer must never see.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, AppState, Modal, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { WebView } from "react-native-webview";

import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import {
  fetchTenantLocation, fetchCurrentWeather, fetchHourlyWeather,
  fetchDailyWeather, fetchWeatherRadar,
  CurrentWeather, HourlyEntry, DailyEntry,
} from "@/src/api/weather";

const REFRESH_MS = 5 * 60 * 1000;

type Props = { onHourlyLoaded?: (hourly: HourlyEntry[]) => void };

export default function WeatherWidget({ onHourlyLoaded }: Props) {
  const [current, setCurrent] = useState<CurrentWeather | null>(null);
  const [hourly, setHourly] = useState<HourlyEntry[]>([]);
  const [daily, setDaily] = useState<DailyEntry[]>([]);
  const [radarUrl, setRadarUrl] = useState<string | null>(null);
  const [radarOpen, setRadarOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
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
      const [cur, hr, dy] = await Promise.all([
        fetchCurrentWeather(lat, lon).catch(() => null),
        fetchHourlyWeather(lat, lon).catch(() => null),
        fetchDailyWeather(lat, lon).catch(() => null),
      ]);
      if (cur && cur.ok !== false) setCurrent(cur);
      if (hr?.hourly) {
        setHourly(hr.hourly);
        onHourlyLoaded?.(hr.hourly);
      }
      if (dy?.daily) setDaily(dy.daily);
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

  const openRadar = async () => {
    if (!coordsRef.current) return;
    try {
      const r = await fetchWeatherRadar(coordsRef.current.lat, coordsRef.current.lon);
      if (r?.embed_url) { setRadarUrl(r.embed_url); setRadarOpen(true); }
    } catch {}
  };

  if (loading) return (
    <View testID="weather-widget" style={styles.container}>
      <ActivityIndicator color={colors.brand} />
    </View>
  );
  if (failed || !current) return null;

  return (
    <View testID="weather-widget" style={styles.container}>
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

      {/* 5-day forecast */}
      {daily.length > 0 && (
        <View testID="weather-5day-forecast">
          <Text style={styles.sectionLabel}>5-Day Forecast</Text>
          {daily.slice(0, 5).map((d, i) => {
            const dayName = new Date(d.date + "T12:00:00").toLocaleDateString("en-US", { weekday: "short" });
            return (
              <View key={i} style={styles.dailyRow}>
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

      {/* Radar button */}
      <TouchableOpacity testID="weather-radar-open" style={styles.radarBtn} onPress={openRadar} activeOpacity={0.7}>
        <Ionicons name="navigate-outline" size={16} color={colors.brand} />
        <Text style={styles.radarBtnText}>Live Radar</Text>
      </TouchableOpacity>

      {/* Radar modal */}
      <Modal visible={radarOpen} animationType="slide" onRequestClose={() => setRadarOpen(false)}>
        <View style={styles.radarModal}>
          <View style={styles.radarHeader}>
            <Text style={styles.radarTitle}>Live Radar</Text>
            <TouchableOpacity onPress={() => setRadarOpen(false)}>
              <Ionicons name="close" size={24} color={colors.onSurface} />
            </TouchableOpacity>
          </View>
          {radarUrl ? (
            <WebView source={{ uri: radarUrl }} style={{ flex: 1 }} />
          ) : (
            <ActivityIndicator style={{ flex: 1 }} color={colors.brand} />
          )}
        </View>
      </Modal>
    </View>
  );
}

function MiniStat({ icon, value }: { icon: string; value: string }) {
  return (
    <View style={styles.miniStat}>
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
});
