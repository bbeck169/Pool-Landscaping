/**
 * Phase O6 · SyncToast — auto-sync progress feedback.
 *
 * Listens to queue flush events and shows brief toasts:
 *   - "Synced N changes" (success)
 *   - "Sync failed — N errors" (failure)
 *   - Pulse animation on the sync pill during flush
 *
 * Uses a simple custom toast implementation (no external lib).
 */
import React, { useState, useEffect, useRef, useCallback } from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { subscribe as subscribeQueue } from "@/src/services/sync/queue";
import { getSyncStatus } from "@/src/services/sync/status";
import { on } from "@/src/services/sync/netBus";
import { font, fontSize, spacing, radius } from "@/src/theme";

type ToastKind = "success" | "error" | "info";

type ToastItem = {
  id: number;
  message: string;
  kind: ToastKind;
};

let _toastId = 0;

export function SyncToast() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const prevStatusRef = useRef({ pending: 0, failed: 0, done: 0, flushing: false });

  const showToast = useCallback((message: string, kind: ToastKind) => {
    const id = ++_toastId;
    setToasts((prev) => [...prev.slice(-2), { id, message, kind }]);

    // Auto-dismiss after 3s.
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3000);
  }, []);

  // Track queue state changes for toast triggers.
  useEffect(() => {
    const unsub = subscribeQueue(async () => {
      const s = await getSyncStatus();
      const prev = prevStatusRef.current;

      // Detect transitions.
      const newDone = s.done_count - prev.done;
      const newFailed = s.failed_count - prev.failed;

      if (newDone > 0 && s.pending_count === 0 && !s.is_flushing) {
        showToast(
          newDone === 1
            ? "1 change synced"
            : `${newDone} changes synced`,
          "success",
        );
      }

      if (newFailed > 0 && !s.is_flushing) {
        showToast(
          `Sync failed — ${s.failed_count} error${s.failed_count > 1 ? "s" : ""}`,
          "error",
        );
      }

      prevStatusRef.current = {
        pending: s.pending_count,
        failed: s.failed_count,
        done: s.done_count,
        flushing: s.is_flushing,
      };
    });

    return unsub;
  }, [showToast]);

  // Show toast on reconnect.
  useEffect(() => {
    const unsub = on("network:online", () => {
      showToast("Back online — syncing changes...", "info");
    });
    return unsub;
  }, [showToast]);

  if (toasts.length === 0) return null;

  return (
    <View style={s.container} pointerEvents="none" testID="sync-toast-container">
      {toasts.map((toast) => {
        const cfg = TOAST_CFG[toast.kind];
        return (
          <View
            key={toast.id}
            style={[s.toast, { backgroundColor: cfg.bg }]}
            testID={`sync-toast-${toast.kind}`}
          >
            <Ionicons name={cfg.icon as any} size={16} color={cfg.fg} />
            <Text style={[s.toastText, { color: cfg.fg }]}>{toast.message}</Text>
          </View>
        );
      })}
    </View>
  );
}

const TOAST_CFG: Record<ToastKind, { bg: string; fg: string; icon: string }> = {
  success: { bg: "#DCFCE7", fg: "#166534", icon: "checkmark-circle" },
  error: { bg: "#FEE2E2", fg: "#991B1B", icon: "alert-circle" },
  info: { bg: "#DBEAFE", fg: "#1E40AF", icon: "information-circle" },
};

const s = StyleSheet.create({
  container: {
    position: "absolute",
    bottom: 90,
    left: spacing.lg,
    right: spacing.lg,
    zIndex: 9998,
    gap: spacing.sm,
  },
  toast: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.sm,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 4,
  },
  toastText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    flex: 1,
  },
});
