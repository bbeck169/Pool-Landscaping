/**
 * Daily Route Map — web implementation.
 *
 * Renders a Leaflet + OpenStreetMap map inside an <iframe srcDoc>
 * with one marker per geocoded stop. No API key or native SDK
 * required — Leaflet + OSM tiles load from CDN inside the iframe.
 *
 * Falls back to the "No mapped stops" placeholder when 0 jobs
 * have coordinates.
 *
 * Native (.native.tsx) is untouched — it ships the real
 * @rnmapbox/maps view.
 */
import React, { useMemo } from "react";
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

/* ── Status → marker color map ─────────────────────────────────────── */

const STATUS_COLORS: Record<ReturnType<typeof statusKind>, string> = {
  pending: "#3B82F6",   // blue
  completed: "#22C55E", // green
  cns: "#EF4444",       // red
};

/* ── Component ─────────────────────────────────────────────────────── */

export default function DailyRouteMap({ jobs, testID }: DailyRouteMapProps) {
  if (!jobs || jobs.length === 0) return null;

  const pins = useMemo(() => {
    const out: Array<{ lat: number; lng: number; label: string; color: string; idx: number }> = [];
    for (let i = 0; i < jobs.length; i++) {
      const j = jobs[i];
      const c = resolveJobCoords(j);
      if (!c) continue;
      const kind = statusKind(j.status);
      const label = (j.customer_name || `Stop ${i + 1}`).replace(/'/g, "\\'").replace(/"/g, "&quot;");
      out.push({ ...c, label, color: STATUS_COLORS[kind], idx: i + 1 });
    }
    return out;
  }, [jobs]);

  // Fallback: no geocoded stops → placeholder
  if (pins.length === 0) {
    return (
      <View style={s.placeholder} testID={testID || "schedule-daily-route-map"}>
        <Ionicons name="map-outline" size={28} color={colors.muted} />
        <Text style={s.placeholderText}>No mapped stops today</Text>
      </View>
    );
  }

  // Compute center + zoom bounds
  const center = useMemo(() => {
    const lats = pins.map((p) => p.lat);
    const lngs = pins.map((p) => p.lng);
    return {
      lat: (Math.min(...lats) + Math.max(...lats)) / 2,
      lng: (Math.min(...lngs) + Math.max(...lngs)) / 2,
    };
  }, [pins]);

  // Build the Leaflet HTML page for the iframe
  const html = useMemo(() => {
    const markersJs = pins
      .map(
        (p) =>
          `L.circleMarker([${p.lat},${p.lng}],{radius:8,fillColor:'${p.color}',color:'#fff',weight:2,fillOpacity:0.9}).addTo(m).bindPopup('<b>${p.idx}.</b> ${p.label}');`
      )
      .join("\n");

    // Compute bounds for fitBounds
    const boundsJs =
      pins.length > 1
        ? `m.fitBounds([${pins.map((p) => `[${p.lat},${p.lng}]`).join(",")}],{padding:[30,30]});`
        : `m.setView([${pins[0].lat},${pins[0].lng}],13);`;

    return `<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"><\/script>
<style>*{margin:0;padding:0}html,body,#m{width:100%;height:100%}</style>
</head><body>
<div id="m"></div>
<script>
var m=L.map('m',{zoomControl:false,attributionControl:false});
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18}).addTo(m);
${markersJs}
${boundsJs}
L.control.attribution({prefix:false}).addTo(m);
<\/script>
</body></html>`;
  }, [pins, center]);

  return (
    <View style={s.wrap} testID={testID || "schedule-daily-route-map"}>
      {React.createElement("iframe", {
        srcDoc: html,
        style: {
          width: "100%",
          height: "100%",
          border: "none",
          borderRadius: 8,
        },
        title: "Route map",
        sandbox: "allow-scripts",
      })}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: {
    height: 240,
    borderRadius: radius.md,
    overflow: "hidden",
    marginBottom: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  placeholder: {
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
  placeholderText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
    lineHeight: 20,
    paddingHorizontal: spacing.md,
  },
});
