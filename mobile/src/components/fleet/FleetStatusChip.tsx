/**
 * FLEET-B · Fleet Status Chip
 *
 * Small persistent chip shown in the header/tab area.
 * - Green = In Fleet (actively emitting)
 * - Yellow = Idle / Paused
 * - Red = Off / Not in fleet / No permission
 *
 * Tapping opens a status modal with details.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, Modal } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/auth";
import {
  getEmitterStatus,
  onStatusChange,
  type EmitterStatus,
} from "@/src/services/fleet/locationEmitter";
import { font, fontSize, spacing, radius, colors } from "@/src/theme";
import { isFleetTechRole } from "@/src/lib/fleetRoles";

const STATUS_CONFIG: Record<
  EmitterStatus,
  { bg: string; fg: string; dotColor: string; label: string; icon: string }
> = {
  active: {
    bg: "#DCFCE7",
    fg: "#166534",
    dotColor: "#16A34A",
    label: "In Fleet",
    icon: "navigate-circle",
  },
  idle: {
    bg: "#FEF9C3",
    fg: "#854D0E",
    dotColor: "#CA8A04",
    label: "Idle",
    icon: "pause-circle-outline",
  },
  paused: {
    bg: "#FEF3C7",
    fg: "#92400E",
    dotColor: "#F59E0B",
    label: "Paused",
    icon: "pause-circle",
  },
  stopped: {
    bg: "#FEE2E2",
    fg: "#991B1B",
    dotColor: "#DC2626",
    label: "Off",
    icon: "stop-circle-outline",
  },
  not_in_fleet: {
    bg: "#F4F4F5",
    fg: "#71717A",
    dotColor: "#A1A1AA",
    label: "Not in Fleet",
    icon: "remove-circle-outline",
  },
  no_permission: {
    bg: "#FEE2E2",
    fg: "#991B1B",
    dotColor: "#DC2626",
    label: "No GPS",
    icon: "location-outline",
  },
};

export default function FleetStatusChip() {
  const { user } = useAuth();
  const [status, setStatus] = useState<EmitterStatus>(getEmitterStatus());
  const [modalVisible, setModalVisible] = useState(false);

  useEffect(() => {
    const unsub = onStatusChange((s) => setStatus(s));
    // Sync on mount
    setStatus(getEmitterStatus());
    return unsub;
  }, []);

  // Only show for fleet-eligible techs (all 6 tech roles) and admins for debugging
  const role = (user?.role || "") as string;
  if (!isFleetTechRole(role) && role !== "admin" && role !== "super_admin") {
    return null;
  }

  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.stopped;

  return (
    <>
      <Pressable
        testID="fleet-status-chip"
        style={[s.chip, { backgroundColor: cfg.bg }]}
        onPress={() => setModalVisible(true)}
        hitSlop={{ top: 12, bottom: 12, left: 16, right: 16 }}
      >
        <View style={[s.dot, { backgroundColor: cfg.dotColor }]} />
        <Text style={[s.label, { color: cfg.fg }]} numberOfLines={1}>
          {cfg.label}
        </Text>
      </Pressable>

      <Modal
        visible={modalVisible}
        transparent
        animationType="fade"
        onRequestClose={() => setModalVisible(false)}
      >
        <Pressable
          style={s.overlay}
          onPress={() => setModalVisible(false)}
        >
          <Pressable style={s.modal} onPress={() => {}}>
            <View style={s.modalHeader}>
              <Ionicons name={cfg.icon as any} size={28} color={cfg.dotColor} />
              <Text style={s.modalTitle}>Fleet Tracking</Text>
            </View>

            <View style={[s.statusRow, { backgroundColor: cfg.bg }]}>
              <View style={[s.dot, { backgroundColor: cfg.dotColor }]} />
              <Text style={[s.statusText, { color: cfg.fg }]} testID="fleet-status-modal-label">
                {cfg.label}
              </Text>
            </View>

            <Text style={s.description} testID="fleet-status-modal-description">
              {status === "active" && "GPS location is being shared with dispatch."}
              {status === "idle" && "Tracking is on but idle (app minimized or low battery)."}
              {status === "paused" && "Tracking paused for this shift. Toggle in Settings > More."}
              {status === "stopped" && "Fleet tracking is not running."}
              {status === "not_in_fleet" && "You are not enrolled in the fleet. Ask an admin to enable you."}
              {status === "no_permission" && "Location permission not granted. Enable in device Settings."}
            </Text>

            <Pressable
              style={s.closeBtn}
              onPress={() => setModalVisible(false)}
              testID="fleet-status-modal-close"
            >
              <Text style={s.closeBtnText}>Close</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}

const s = StyleSheet.create({
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radius.pill,
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 4,
  },
  label: {
    fontFamily: font.semibold,
    fontSize: 10,
  },
  overlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.4)",
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.xl,
  },
  modal: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.xl,
    width: "100%",
    maxWidth: 340,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.15,
    shadowRadius: 16,
    elevation: 10,
  },
  modalHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  modalTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  statusRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.md,
    marginBottom: spacing.md,
  },
  statusText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
  },
  description: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    lineHeight: 20,
    marginBottom: spacing.lg,
  },
  closeBtn: {
    alignSelf: "flex-end",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
  },
  closeBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
});
