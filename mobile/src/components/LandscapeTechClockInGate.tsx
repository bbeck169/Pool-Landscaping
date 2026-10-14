/**
 * LandscapeTechClockInGate — full-screen clock-in gate for landscape techs.
 *
 * Mobile parity for web commit f5dd1eb0a. If the current user is a
 * landscape technician who is NOT clocked in, this component renders
 * a full-viewport Clock In screen instead of `children`. Pool techs,
 * admins, and already-clocked-in landscape techs see `children` normally.
 *
 * Clock-out is handled elsewhere (the landscape-time-clock screen).
 */
import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
} from "react-native";
import * as Location from "expo-location";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { isLandscapeTech, useClockInStatus } from "@/src/utils/clockInGate";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

interface Props {
  children: React.ReactNode;
}

export default function LandscapeTechClockInGate({ children }: Props) {
  const { user } = useAuth();
  const gated = isLandscapeTech(user as any);
  const { clockedIn, loading, refetch } = useClockInStatus();

  const [punching, setPunching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [geoStatus, setGeoStatus] = useState<string | null>(null);

  // Not a landscape tech → pass through immediately
  if (!gated) return <>{children}</>;

  // Still loading clock-in status → show a subtle loader, not the gate
  if (loading || clockedIn === null) {
    return (
      <View style={s.center} testID="landscape-clock-gate">
        <ActivityIndicator size="large" color={colors.brand} />
      </View>
    );
  }

  // Already clocked in → pass through
  if (clockedIn) return <>{children}</>;

  // ── Not clocked in: show full-screen gate ──
  const handleClockIn = async () => {
    setPunching(true);
    setError(null);
    setGeoStatus("Acquiring GPS…");

    let lat: number | null = null;
    let lng: number | null = null;
    let accuracy_m: number | null = null;
    let geo_denied = false;

    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (perm.status !== "granted") {
        geo_denied = true;
        setGeoStatus("GPS denied — clocking in without location");
      } else {
        setGeoStatus("Getting location…");
        const pos = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        lat = pos.coords.latitude;
        lng = pos.coords.longitude;
        accuracy_m = pos.coords.accuracy ?? null;
        setGeoStatus("Location acquired");
      }
    } catch {
      geo_denied = true;
      setGeoStatus("GPS unavailable — clocking in without location");
    }

    try {
      await api.post("/timeclock/punch", {
        punch_type: "in",
        lat,
        lng,
        accuracy_m,
        // Backend PunchReq.source is Literal["mobile","web"] (422 otherwise).
        source: "mobile",
        geo_denied,
      });
      setGeoStatus(null);
      await refetch();
    } catch (e: any) {
      const msg =
        e?.body?.detail || e?.message || "Clock-in failed. Please try again.";
      setError(String(msg));
      setGeoStatus(null);
    } finally {
      setPunching(false);
    }
  };

  return (
    <View style={s.root} testID="landscape-clock-gate">
      <View style={s.card}>
        <View style={s.iconCircle}>
          <Ionicons name="time-outline" size={48} color={colors.brand} />
        </View>

        <Text style={s.title}>Clock In to Start</Text>
        <Text style={s.subtitle}>
          You must clock in before accessing your schedule and jobs.
        </Text>

        {geoStatus ? (
          <Text style={s.geoStatus} testID="landscape-clock-gate-geo-status">
            {geoStatus}
          </Text>
        ) : null}

        {error ? (
          <View style={s.errorBox} testID="landscape-clock-gate-error">
            <Ionicons name="alert-circle" size={16} color="#DC2626" />
            <Text style={s.errorText}>{error}</Text>
          </View>
        ) : null}

        <Pressable
          style={[s.btn, punching && s.btnDisabled]}
          onPress={handleClockIn}
          disabled={punching}
          testID="landscape-clock-gate-in-btn"
        >
          {punching ? (
            <ActivityIndicator size={18} color="#fff" />
          ) : (
            <Ionicons name="log-in-outline" size={20} color="#fff" />
          )}
          <Text style={s.btnText}>
            {punching ? "Clocking In…" : "Clock In"}
          </Text>
        </Pressable>

        <Text style={s.footer}>
          Clock out later via the Landscape Time Clock screen.
        </Text>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.surfaceSecondary,
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.xl,
  },
  center: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: colors.surface,
  },
  card: {
    width: "100%",
    maxWidth: 380,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.xl,
    alignItems: "center",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 6,
  },
  iconCircle: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: colors.brandTertiary,
    justifyContent: "center",
    alignItems: "center",
    marginBottom: spacing.lg,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
    marginBottom: spacing.xs,
    textAlign: "center",
  },
  subtitle: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
    marginBottom: spacing.lg,
    lineHeight: 20,
  },
  geoStatus: {
    fontFamily: font.regular,
    fontSize: 12,
    color: colors.muted,
    marginBottom: spacing.sm,
  },
  errorBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FEF2F2",
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginBottom: spacing.md,
    width: "100%",
  },
  errorText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#DC2626",
    flex: 1,
  },
  btn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: colors.brand,
    borderRadius: radius.md,
    paddingVertical: 14,
    paddingHorizontal: 32,
    width: "100%",
    minHeight: 52,
    marginBottom: spacing.md,
  },
  btnDisabled: {
    opacity: 0.6,
  },
  btnText: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#fff",
  },
  footer: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    textAlign: "center",
  },
});
