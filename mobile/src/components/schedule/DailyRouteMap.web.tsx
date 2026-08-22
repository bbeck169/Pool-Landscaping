/**
 * Daily Route Map — web fallback.
 *
 * @rnmapbox/maps is native-only; on web we show a placeholder.
 * Mirrors the ScheduleMap.web.tsx pattern.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, font, fontSize, radius } from "@/src/theme";

/* ── Shared types (duplicated to avoid importing from .native) ────── */

export type RouteMapJob = {
  id: string;
  status?: string | null;
  route_index?: number | null;
  route_order?: number | null;
  scheduled_date?: string | null;
  customer_name?: string | null;
  address?: string | null;
  service_address?: any;
  scheduled_time?: string | null;
  scheduled_time_end?: string | null;
  time_window?: string | null;
  location_lat?: number | null;
  location_lng?: number | null;
  location?: { lat?: number | null; lng?: number | null; lon?: number | null } | null;
  property?: {
    location?: { lat?: number | null; lng?: number | null; lon?: number | null } | null;
  } | null;
};

export interface DailyRouteMapProps {
  jobs: RouteMapJob[];
  userId: string;
  onOpenJob?: (jobId: string) => void;
  testID?: string;
}

/* ── Re-export helpers so barrel export shape matches .native ─────── */

export function resolveJobCoords(job: RouteMapJob): { lat: number; lng: number } | null {
  const trySet = (lat: any, lng: any): { lat: number; lng: number } | null => {
    const la = Number(lat);
    const lo = Number(lng);
    if (Number.isFinite(la) && Number.isFinite(lo) && (la !== 0 || lo !== 0)) {
      return { lat: la, lng: lo };
    }
    return null;
  };
  const canonical = job.property?.location;
  if (canonical) {
    const hit = trySet(canonical.lat, canonical.lng ?? canonical.lon);
    if (hit) return hit;
  }
  const flat = trySet(job.location_lat, job.location_lng);
  if (flat) return flat;
  if (job.location) {
    const hit = trySet(job.location.lat, job.location.lng ?? job.location.lon);
    if (hit) return hit;
  }
  const sa = job.service_address?.coordinates;
  if (sa) {
    const hit = trySet(sa.lat ?? sa.latitude, sa.lng ?? sa.lon ?? sa.longitude);
    if (hit) return hit;
  }
  return null;
}

export function statusKind(status?: string | null): "pending" | "completed" | "cns" {
  const s = (status || "").toLowerCase();
  if (s === "completed") return "completed";
  if (s === "could_not_service" || s === "skipped" || s === "canceled" || s === "cancelled") return "cns";
  return "pending";
}

/* ── Component ─────────────────────────────────────────────────────── */

export default function DailyRouteMap({ jobs, testID }: DailyRouteMapProps) {
  if (!jobs || jobs.length === 0) return null;

  const geocoded = jobs.filter((j) => resolveJobCoords(j) !== null);

  return (
    <View style={s.wrap} testID={testID || "schedule-daily-route-map"}>
      <Ionicons name="map-outline" size={28} color={colors.muted} />
      <Text style={s.text}>
        {geocoded.length === 0
          ? "No mapped stops today"
          : `Route map with ${geocoded.length} stop${geocoded.length > 1 ? "s" : ""} available on the mobile app.`}
      </Text>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: {
    height: 200,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: colors.border,
    marginBottom: spacing.md,
  },
  text: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
    lineHeight: 20,
    paddingHorizontal: spacing.md,
  },
});
