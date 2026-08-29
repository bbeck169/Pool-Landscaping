/**
 * Phase O6 · PendingChangesChip — small tappable chip that shows
 * "N pending" when there are queued writes. Tap opens a bottom
 * sheet listing all queued items with retry/delete actions.
 */
import React, { useState, useEffect, useCallback } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, Modal,
  FlatList, Alert, ActivityIndicator, Pressable,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSyncStatus } from "@/src/services/sync/status";
import {
  getPending, getFailed, retrySingle, triggerSyncNow,
  type SyncEntry,
} from "@/src/services/sync/queue";
import { isOnlineNow } from "@/src/services/sync/netBus";
import { font, fontSize, spacing, radius, colors } from "@/src/theme";

const OP_LABELS: Record<string, string> = {
  "job.update": "Job update",
  "job.status": "Job status change",
  "job.assign": "Job assignment",
  "job.arrive": "On my way",
  "job.create": "New job",
  "job.could_not_service": "Could not service",
  "service_report.patch": "Service report",
  "service_report.upsert": "Service report submit",
  "service_report.submit": "Service report finalize",
  "customer.upsert": "Customer update",
  "customer.create": "New customer",
  "customer.update": "Customer update",
  "customer.service_notes": "Service notes",
  "customer.tags": "Tag update",
  "customer.mute": "Mute control",
  "field_report.update": "Field report",
  "maintenance_log.create": "Maintenance log",
  "issue.create": "Service issue",
  "issue.approve": "Issue approval",
  "clock.punch": "Clock in/out",
  "clock.landscape": "Landscape clock",
  "notification_settings.update": "Notification settings",
  "gps_consent": "GPS consent",
  "lead.create": "New lead",
  "estimate.create": "New estimate",
  "estimate.update": "Estimate update",
  "time_off.request": "Time-off request",
  "automation.toggle": "Automation toggle",
  "tag.create": "Tag create",
  "tag.update": "Tag update",
  "tag.delete": "Tag delete",
  "deal.create": "Deal create",
  "deal.move": "Deal stage move",
  "visit_recap.create": "Visit recap",
  "photo.upload": "Photo upload",
};

function humanLabel(entry: SyncEntry): string {
  return OP_LABELS[entry.op_type] || entry.op_type.replace(/[._]/g, " ");
}

function timeSince(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return "just now";
  if (ms < 3600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3600_000)}h ago`;
  return `${Math.floor(ms / 86_400_000)}d ago`;
}

export function PendingChangesChip() {
  const { pending_count, failed_count, in_flight_count } = useSyncStatus();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [entries, setEntries] = useState<SyncEntry[]>([]);
  const [syncing, setSyncing] = useState(false);

  const total = pending_count + failed_count;

  const loadEntries = useCallback(async () => {
    const [p, f] = await Promise.all([getPending(), getFailed()]);
    setEntries([...f, ...p]); // Failed first.
  }, []);

  useEffect(() => {
    if (sheetOpen) loadEntries();
  }, [sheetOpen, loadEntries, pending_count, failed_count]);

  if (total === 0 && in_flight_count === 0) return null;

  const handleSyncAll = async () => {
    if (!isOnlineNow()) {
      Alert.alert("Offline", "Cannot sync while offline.");
      return;
    }
    setSyncing(true);
    try {
      await triggerSyncNow();
      await loadEntries();
    } finally {
      setSyncing(false);
    }
  };

  const handleRetry = async (id: string) => {
    if (!isOnlineNow()) {
      Alert.alert("Offline", "Cannot retry while offline.");
      return;
    }
    await retrySingle(id);
    await loadEntries();
  };

  const chipBg = failed_count > 0 ? "#FEE2E2" : "#FEF3C7";
  const chipFg = failed_count > 0 ? "#991B1B" : "#854D0E";

  return (
    <>
      <TouchableOpacity
        testID="pending-changes-chip"
        style={[s.chip, { backgroundColor: chipBg }]}
        onPress={() => setSheetOpen(true)}
        activeOpacity={0.7}
      >
        {in_flight_count > 0 ? (
          <ActivityIndicator size={11} color={chipFg} />
        ) : (
          <Ionicons
            name={failed_count > 0 ? "alert-circle" : "time-outline"}
            size={13}
            color={chipFg}
          />
        )}
        <Text style={[s.chipText, { color: chipFg }]} testID="pending-count-label">
          {in_flight_count > 0
            ? "Syncing..."
            : `${total} pending`}
        </Text>
      </TouchableOpacity>

      <Modal
        visible={sheetOpen}
        animationType="slide"
        transparent
        onRequestClose={() => setSheetOpen(false)}
      >
        <Pressable style={s.backdrop} onPress={() => setSheetOpen(false)} />
        <View style={s.sheet}>
          <View style={s.sheetHeader}>
            <Text style={s.sheetTitle}>Pending Changes</Text>
            <TouchableOpacity
              testID="pending-sheet-close"
              onPress={() => setSheetOpen(false)}
            >
              <Ionicons name="close" size={22} color={colors.muted} />
            </TouchableOpacity>
          </View>

          {entries.length === 0 ? (
            <View style={s.emptyState}>
              <Ionicons name="checkmark-circle" size={36} color={colors.success} />
              <Text style={s.emptyText}>All synced!</Text>
            </View>
          ) : (
            <>
              <TouchableOpacity
                testID="sync-all-btn"
                style={[s.syncAllBtn, !isOnlineNow() && s.btnDisabled]}
                onPress={handleSyncAll}
                disabled={syncing}
              >
                {syncing ? (
                  <ActivityIndicator size={14} color="#fff" />
                ) : (
                  <Ionicons name="sync" size={14} color="#fff" />
                )}
                <Text style={s.syncAllText}>
                  {syncing ? "Syncing..." : "Sync all now"}
                </Text>
              </TouchableOpacity>

              <FlatList
                data={entries}
                keyExtractor={(e) => e.id}
                style={s.list}
                renderItem={({ item }) => (
                  <View
                    style={[s.row, item.status === "failed" && s.rowFailed]}
                    testID={`pending-row-${item.id}`}
                  >
                    <View style={s.rowLeft}>
                      <Text style={s.rowLabel}>{humanLabel(item)}</Text>
                      <Text style={s.rowMeta}>
                        {timeSince(item.created_at)}
                        {item.status === "failed" && item.last_error
                          ? ` · ${item.last_error.slice(0, 40)}`
                          : ""}
                      </Text>
                    </View>
                    {item.status === "failed" && (
                      <TouchableOpacity
                        testID={`retry-btn-${item.id}`}
                        style={s.retryBtn}
                        onPress={() => handleRetry(item.id)}
                      >
                        <Ionicons name="refresh" size={16} color={colors.brand} />
                      </TouchableOpacity>
                    )}
                    <View
                      style={[
                        s.statusDot,
                        {
                          backgroundColor:
                            item.status === "failed"
                              ? colors.error
                              : item.status === "in_flight"
                              ? colors.brand
                              : colors.warning,
                        },
                      ]}
                    />
                  </View>
                )}
              />
            </>
          )}
        </View>
      </Modal>
    </>
  );
}

const s = StyleSheet.create({
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.pill,
  },
  chipText: {
    fontFamily: font.semibold,
    fontSize: 11,
  },
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.4)",
  },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    maxHeight: "60%",
    paddingBottom: 32,
  },
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sheetTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  syncAllBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brand,
    marginHorizontal: spacing.lg,
    marginTop: spacing.md,
    paddingVertical: spacing.sm + 2,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.sm,
    justifyContent: "center",
  },
  btnDisabled: {
    opacity: 0.5,
  },
  syncAllText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
  list: {
    marginTop: spacing.sm,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  rowFailed: {
    backgroundColor: "#FEF2F2",
  },
  rowLeft: {
    flex: 1,
  },
  rowLabel: {
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  rowMeta: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginTop: 2,
  },
  retryBtn: {
    padding: 8,
    marginRight: 4,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  emptyState: {
    alignItems: "center",
    paddingVertical: spacing["2xl"],
    gap: spacing.sm,
  },
  emptyText: {
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.muted,
  },
});
