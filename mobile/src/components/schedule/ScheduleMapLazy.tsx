/**
 * ScheduleMapLazy — K36 · lazy-mount wrapper around `<ScheduleMap>`.
 *
 * `react-native-maps` registers native components at module load
 * time. Statically importing `<ScheduleMap>` from `calendar.tsx`
 * therefore forced the AIRMap native module to register the moment
 * a tech opened the Schedule tab — regardless of whether they ever
 * toggled the Map sub-view. On builds where the Google Maps API
 * key is missing or the entitlement flip hasn't caught up, the
 * native side throws during that registration and the tab crashes.
 *
 * Wrapping the import in `React.lazy` + `<Suspense>` defers the
 * native registration until the caller actually mounts this
 * component, and confines any load-time failure to the fallback
 * (or the parent's error boundary) instead of the whole screen.
 */
import React from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import { colors, radius, spacing } from "@/src/theme";
import { MapErrorBoundary } from "@/src/components/MapErrorBoundary";

// Metro requires a static string in the dynamic import — this is
// still tree-shaken away when not mounted at runtime.
const LazyScheduleMap = React.lazy(
  () => import("@/src/components/schedule/ScheduleMap"),
);

interface Job {
  id: string;
  status?: string;
  customer_name?: string;
  address?: string;
  scheduled_time?: string | null;
  location_lat?: number | null;
  location_lng?: number | null;
  // Phase 4 multi-property pins (web 723e28204).
  coord_source?: string | null;
  property_id?: string | null;
  property_label?: string | null;
}

interface Props {
  jobs: Job[];
  // Phase B.5 parity (web 9eb08b5c1) — per-tech pin colors + legend.
  techs?: any[];
  crews?: any[];
  testID?: string;
}

export default function ScheduleMapLazy(props: Props) {
  return (
    <MapErrorBoundary testID="schedule-map-error-boundary">
      <React.Suspense
        fallback={
          <View style={s.fallback} testID="schedule-map-loading">
            <ActivityIndicator color={colors.brand} />
          </View>
        }
      >
        <LazyScheduleMap {...props} />
      </React.Suspense>
    </MapErrorBoundary>
  );
}

const s = StyleSheet.create({
  fallback: {
    height: 350,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    marginBottom: spacing.md,
  },
});
