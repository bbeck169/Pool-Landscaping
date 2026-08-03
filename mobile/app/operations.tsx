import React from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

/**
 * Phase (Feb-2026) · mobile Operations hub.
 *
 * Mirrors ``frontend/src/pages/ops/OpsHub.jsx`` — the web renders 16
 * tabs under ``/ops``, ``/crews``, and ``/team``. Mobile keeps each
 * sub-screen as a flat route (``/coverage``, ``/maintenance``, ...)
 * and this hub gives admin-like users a single tile-grid entry so
 * they don't have to hunt through the drawer for every workflow.
 *
 * Role gate: admin / super_admin / manager. Techs and customers
 * never reach this screen (the drawer entry is gated the same way).
 */
type Tile = {
  key: string;
  label: string;
  hint: string;
  icon: any;
  route: string;
  testID: string;
};

const TILES: Tile[] = [
  { key: "dispatch",   label: "Dispatch",     hint: "Assign & route today",           icon: "car-outline",             route: "/dispatch",       testID: "ops-tile-dispatch" },
  { key: "schedule",   label: "Schedule",     hint: "Calendar + tracker tiles",       icon: "calendar-outline",        route: "/schedule",       testID: "ops-tile-schedule" },
  { key: "workstream", label: "Work Stream",  hint: "Live job feed",                  icon: "pulse-outline",           route: "/workstream",     testID: "ops-tile-workstream" },
  { key: "team",       label: "Team",         hint: "Staff roster & roles",           icon: "people-outline",          route: "/team",           testID: "ops-tile-team" },
  { key: "crews",      label: "Crews",        hint: "Crew groups & members",          icon: "people-circle-outline",   route: "/crews",          testID: "ops-tile-crews" },
  { key: "timesheets", label: "Timesheets",   hint: "Hours worked",                   icon: "clipboard-outline",       route: "/timesheets",     testID: "ops-tile-timesheets" },
  { key: "timeclock",  label: "Time Clock",   hint: "Clock in / out",                 icon: "time-outline",            route: "/time-clock",     testID: "ops-tile-timeclock" },
  { key: "coverage",   label: "Coverage",     hint: "Service area coverage",          icon: "map-outline",             route: "/coverage",       testID: "ops-tile-coverage" },
  { key: "maintenance",label: "Maintenance",  hint: "Recurring visits",               icon: "construct-outline",       route: "/maintenance",    testID: "ops-tile-maintenance" },
  { key: "pool",       label: "Pool Service", hint: "Pool-specific workflow",         icon: "water-outline",           route: "/pool-service",   testID: "ops-tile-pool" },
  { key: "equipment",  label: "Equipment",    hint: "Truck & tool inventory",         icon: "hammer-outline",          route: "/equipment",      testID: "ops-tile-equipment" },
  { key: "pricebook",  label: "Price Book",   hint: "Services & materials",           icon: "pricetag-outline",        route: "/price-book",     testID: "ops-tile-pricebook" },
  { key: "loghistory", label: "Log History",  hint: "Audit trail",                    icon: "list-outline",            route: "/log-history",    testID: "ops-tile-loghistory" },
  { key: "timers",     label: "Job Timers",   hint: "Active job timers",              icon: "stopwatch-outline",       route: "/job-timers",     testID: "ops-tile-timers" },
  { key: "avgtime",    label: "Avg Job Time", hint: "Time-per-job trend",             icon: "bar-chart-outline",       route: "/avg-job-time",   testID: "ops-tile-avgtime" },
];

export default function Operations() {
  const { user } = useAuth();
  const router = useRouter();
  const role = (user?.role as string) || "";
  const canAccess = role === "super_admin" || role === "admin" || role === "manager";

  if (!canAccess) {
    return (
      <View style={s.root} testID="operations-forbidden">
        <Header title="Operations" back />
        <View style={s.forbiddenBox}>
          <Ionicons name="lock-closed-outline" size={32} color={colors.muted} />
          <Text style={s.forbiddenTitle}>Operations is admin-only</Text>
          <Text style={s.forbiddenSub}>
            Ask your admin if you need access to dispatch, crews, or timesheets.
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={s.root} testID="operations-page">
      <Header title="Operations" back subtitle="All ops workflows in one place" />
      <ScrollView contentContainerStyle={s.scroll}>
        <View style={s.grid} testID="operations-tile-grid">
          {TILES.map((t) => (
            <Pressable
              key={t.key}
              testID={t.testID}
              onPress={() => router.push(t.route)}
              style={({ pressed }) => [s.tile, pressed && { opacity: 0.85 }]}
              accessibilityRole="button"
              accessibilityLabel={t.label}
            >
              <View style={s.iconBox}>
                <Ionicons name={t.icon} size={22} color={colors.brand} />
              </View>
              <Text style={s.tileLabel}>{t.label}</Text>
              <Text style={s.tileHint} numberOfLines={2}>{t.hint}</Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  scroll: { padding: spacing.lg, paddingBottom: spacing["3xl"] },
  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.md,
  },
  tile: {
    flexBasis: "47%",
    flexGrow: 1,
    minWidth: 150,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    gap: 6,
  },
  iconBox: {
    width: 40, height: 40, borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
    marginBottom: 4,
  },
  tileLabel: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  tileHint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  forbiddenBox: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing["2xl"],
    gap: 6,
  },
  forbiddenTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  forbiddenSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
});
