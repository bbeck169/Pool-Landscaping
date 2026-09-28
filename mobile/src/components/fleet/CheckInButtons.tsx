/**
 * FLEET-B · Check-In Buttons
 *
 * "On My Way" and "Arrived" buttons for the job detail screen.
 * POST /api/fleet/checkin with kind="on_the_way" or "arrived".
 *
 * Idempotent — backend deduplicates. Frontend shows a custom toast.
 */
import React, { useState, useCallback, useRef, useEffect } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import * as Location from "expo-location";
import { Ionicons } from "@expo/vector-icons";

import { api, ApiError } from "@/src/api";
import { useToast } from "@/src/components/ToastProvider";
import { font, fontSize, spacing, radius } from "@/src/theme";

const COOLDOWN_MS = 10_000;

interface Props {
  jobId: string;
  testID?: string;
}

export default function CheckInButtons({ jobId, testID }: Props) {
  const { showToast } = useToast();
  const [omwBusy, setOmwBusy] = useState(false);
  const [arrBusy, setArrBusy] = useState(false);
  const [omwDone, setOmwDone] = useState(false);
  const [arrDone, setArrDone] = useState(false);
  const [omwCooldown, setOmwCooldown] = useState(false);
  const [arrCooldown, setArrCooldown] = useState(false);
  const omwTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const arrTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (omwTimer.current) clearTimeout(omwTimer.current);
      if (arrTimer.current) clearTimeout(arrTimer.current);
    };
  }, []);

  const getCoords = useCallback(async () => {
    try {
      const { status } = await Location.getForegroundPermissionsAsync();
      if (status !== "granted") return null;
      const loc = await Promise.race([
        Location.getLastKnownPositionAsync(),
        new Promise<null>((r) => setTimeout(() => r(null), 3000)),
      ]);
      if (!loc) return null;
      return { lat: loc.coords.latitude, lng: loc.coords.longitude };
    } catch {
      return null;
    }
  }, []);

  const handleCheckin = useCallback(
    async (kind: "on_the_way" | "arrived") => {
      const isOmw = kind === "on_the_way";
      if (isOmw) {
        if (omwBusy || omwCooldown) return;
        setOmwBusy(true);
      } else {
        if (arrBusy || arrCooldown) return;
        setArrBusy(true);
      }

      try {
        const coords = await getCoords();
        const body: Record<string, any> = { kind, job_id: jobId };
        if (coords) {
          body.lat = coords.lat;
          body.lng = coords.lng;
        }

        const resp = await api.post("/fleet/checkin", body);

        if (isOmw) {
          setOmwDone(true);
          const eta = resp?.notification?.eta_minutes;
          const sent = resp?.notification?.sent;
          if (sent && eta) {
            showToast(`On my way — ETA ${eta} min`, "success");
          } else if (sent) {
            showToast("On my way — customer notified", "success");
          } else {
            showToast("On my way — check-in recorded", "info");
          }
        } else {
          setArrDone(true);
          showToast("Arrived — check-in recorded", "success");
        }
      } catch (e: any) {
        if (e instanceof ApiError && e.status === 403) {
          showToast("Not in fleet — ask admin to enable", "error");
        } else {
          showToast(e?.message || "Check-in failed", "error");
        }
      } finally {
        if (isOmw) {
          setOmwBusy(false);
          setOmwCooldown(true);
          omwTimer.current = setTimeout(() => setOmwCooldown(false), COOLDOWN_MS);
        } else {
          setArrBusy(false);
          setArrCooldown(true);
          arrTimer.current = setTimeout(() => setArrCooldown(false), COOLDOWN_MS);
        }
      }
    },
    [jobId, omwBusy, arrBusy, omwCooldown, arrCooldown, getCoords, showToast],
  );

  const omwDisabled = omwBusy || omwCooldown;
  const arrDisabled = arrBusy || arrCooldown;

  return (
    <View style={s.row} testID={testID || "fleet-checkin-buttons"}>
      <Pressable
        testID="fleet-checkin-omw-btn"
        style={[s.btn, s.omwBtn, omwDisabled && s.btnDisabled]}
        onPress={() => handleCheckin("on_the_way")}
        disabled={omwDisabled}
      >
        {omwBusy ? (
          <ActivityIndicator size={14} color="#fff" />
        ) : (
          <Ionicons
            name={omwDone ? "checkmark-circle" : "car-outline"}
            size={16}
            color="#fff"
          />
        )}
        <Text style={s.btnText}>
          {omwBusy ? "Sending…" : omwDone ? "Sent" : "On My Way"}
        </Text>
      </Pressable>

      <Pressable
        testID="fleet-checkin-arrived-btn"
        style={[s.btn, s.arrBtn, arrDisabled && s.btnDisabled]}
        onPress={() => handleCheckin("arrived")}
        disabled={arrDisabled}
      >
        {arrBusy ? (
          <ActivityIndicator size={14} color="#fff" />
        ) : (
          <Ionicons
            name={arrDone ? "checkmark-circle" : "location"}
            size={16}
            color="#fff"
          />
        )}
        <Text style={s.btnText}>
          {arrBusy ? "Checking in…" : arrDone ? "Arrived" : "Arrived"}
        </Text>
      </Pressable>
    </View>
  );
}

const s = StyleSheet.create({
  row: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  btn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 12,
    borderRadius: radius.md,
    minHeight: 48,
  },
  omwBtn: {
    backgroundColor: "#1B1F5C",
  },
  arrBtn: {
    backgroundColor: "#059669",
  },
  btnDisabled: {
    opacity: 0.55,
  },
  btnText: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: "#fff",
    letterSpacing: 0.3,
  },
});
