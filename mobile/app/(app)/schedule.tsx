import React, { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, SectionList, RefreshControl } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import * as Location from "expo-location";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useAttendance } from "@/src/hooks/useAttendance";
import { useOnline, cacheJobs, getCachedJobs, flushPendingPhotos, flushPendingMutations } from "@/src/offline";
import { colors, spacing, font, fontSize, radius } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, JobCard, OfflineBanner } from "@/src/components/widgets";
import ClockInCard from "@/src/components/ClockInCard";
import { syncJobGeofences } from "@/src/geofence";

const DEFAULT_LOC = { lat: 33.7405, lng: -112.3373 }; // service-area fallback

export default function Schedule() {
  const { user } = useAuth();
  const attendance = useAttendance();
  const isTech = user?.role === "technician";
  const locked = isTech && !attendance.clockedIn;
  const online = useOnline();
  const [jobs, setJobs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [usingCache, setUsingCache] = useState(false);
  const [weather, setWeather] = useState<Record<string, any>>({});

  const loadWeather = useCallback(async () => {
    let loc = DEFAULT_LOC;
    try {
      const perm = await Location.getForegroundPermissionsAsync();
      if (perm.granted) {
        const pos = await Location.getLastKnownPositionAsync();
        if (pos) loc = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      }
    } catch {}
    try {
      const res = await api.get(`/weather/forecast?lat=${loc.lat}&lng=${loc.lng}&days=14`);
      setWeather(res.days || {});
    } catch {}
  }, []);

  const load = useCallback(async () => {
    const cacheKey = `${user?.role}_${user?.id}`;
    try {
      await flushPendingMutations().catch(() => {});
      await flushPendingPhotos().catch(() => {});
      const data = await api.get("/jobs");
      setJobs(data);
      setUsingCache(false);
      cacheJobs(cacheKey, data);
    } catch (e) {
      const cached = await getCachedJobs(cacheKey);
      if (cached) {
        setJobs(cached);
        setUsingCache(true);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [user?.role, user?.id]);

  useFocusEffect(
    useCallback(() => {
      load();
      loadWeather();
      // Register background geofences so the job timer auto-starts on arrival (native builds only).
      if (user?.role === "technician") syncJobGeofences();
    }, [load, loadWeather, online, user?.role])
  );

  const sections = useMemo(() => {
    const map: Record<string, any[]> = {};
    jobs
      .slice()
      .sort((a, b) => (a.scheduled_date || "").localeCompare(b.scheduled_date || ""))
      .forEach((j) => {
        const key = j.scheduled_date || "Unscheduled";
        (map[key] = map[key] || []).push(j);
      });
    return Object.entries(map).map(([title, data]) => ({ title, data }));
  }, [jobs]);

  return (
    <View style={styles.root}>
      <Header title="Schedule" subtitle="Grouped by date" />
      {usingCache ? <OfflineBanner /> : null}
      {isTech ? <ClockInCard onChange={attendance.refresh} /> : null}
      {locked ? (
        <View style={styles.lockBanner} testID="schedule-lock-banner">
          <Ionicons name="lock-closed-outline" size={16} color="#92400E" />
          <Text style={styles.lockBannerText}>
            Clock in to open jobs. Your schedule is read-only until then.
          </Text>
        </View>
      ) : null}
      {loading ? (
        <Loading testID="schedule-loading" />
      ) : sections.length === 0 ? (
        <EmptyState icon="calendar-outline" title="Nothing scheduled" subtitle="Your upcoming jobs will show here." testID="schedule-empty" />
      ) : (
        <SectionList
          testID="schedule-list"
          sections={sections}
          keyExtractor={(i) => i.id}
          stickySectionHeadersEnabled={false}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          renderSectionHeader={({ section }) => {
            const w = weather[section.title];
            return (
              <View style={styles.dateHeaderRow}>
                <Text style={styles.dateHeader}>{formatDate(section.title)}</Text>
                {w ? (
                  <View style={styles.wxChip} testID={`schedule-wx-${section.title}`}>
                    <Ionicons name={w.icon} size={14} color={colors.brand} />
                    <Text style={styles.wxTemp}>{w.high}°/{w.low}°</Text>
                    {w.precip != null && w.precip >= 30 ? (
                      <View style={styles.wxRain}>
                        <Ionicons name="water" size={11} color="#0369A1" />
                        <Text style={styles.wxRainText}>{w.precip}%</Text>
                      </View>
                    ) : null}
                  </View>
                ) : null}
              </View>
            );
          }}
          renderItem={({ item }) => <JobCard job={item} locked={locked} testID={`schedule-job-${item.id}`} />}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        />
      )}
    </View>
  );
}

function formatDate(d: string) {
  if (d === "Unscheduled") return d;
  try {
    return new Date(d + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  } catch {
    return d;
  }
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  lockBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: "#FEF3C7",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    marginHorizontal: spacing.lg,
    marginTop: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: "#FDE68A",
  },
  lockBannerText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.sm, color: "#92400E" },
  dateHeaderRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.md, marginBottom: spacing.sm },
  dateHeader: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.brand,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  wxChip: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.pill, paddingHorizontal: 8, height: 26 },
  wxTemp: { fontFamily: font.semibold, fontSize: 12, color: colors.onSurface },
  wxRain: { flexDirection: "row", alignItems: "center", gap: 2, marginLeft: 2 },
  wxRainText: { fontFamily: font.semibold, fontSize: 11, color: "#0369A1" },
});
