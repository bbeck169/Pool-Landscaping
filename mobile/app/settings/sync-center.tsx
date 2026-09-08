/**
 * Phase 2 · Sync Center — manage pending/failed offline operations.
 *
 * Route: /settings/sync-center
 *
 * Sections:
 *   1. Summary banner (pending / in-flight / failed / done counts)
 *   2. "Sync Now" manual trigger
 *   3. Pending operations list
 *   4. Failed operations list (with retry per item)
 *   5. Recently synced (done) — with "Clear" button
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
  ActivityIndicator, RefreshControl, Alert,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useSyncStatus } from "@/src/services/sync/status";
import {
  getAll, clearDone,
  triggerSyncNow, retrySingle,
  type SyncEntry,
} from "@/src/services/sync/queue";
import {
  getPendingPhotos, getStalledPhotos, retryAllStalled as retryAllStalledPhotos,
  type PendingPhoto,
} from "@/src/services/sync/photoWorker";
import {
  getPendingVideos, getStalledVideos, retryAllStalledVideos,
  type PendingVideo,
} from "@/src/services/sync/videoWorker";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

// ─── Op-type human labels ──────────────────────────────────────────
const OP_LABELS: Record<string, string> = {
  "service_report.upsert": "Service Report",
  "service_report.patch": "Service Report Edit",
  "service_report.submit": "Submit Report",
  "job.arrive": "On My Way",
  "job.update": "Job Update",
  "job.status": "Job Status Change",
  "job.complete": "Mark Complete",
  "job.assign": "Reassign Job",
  "job.create": "Create Job",
  "job.could_not_service": "Could Not Service",
  "customer.upsert": "Customer Update",
  "customer.create": "New Customer",
  "customer.service_notes": "Service Notes",
  "checklist.answer": "Checklist Answer",
  "checklist.update": "Checklist Edit",
  "on_my_way": "On My Way SMS",
  "photo.upload": "Photo Upload",
  "video.upload": "Video Upload",
  "field_report.update": "Field Report",
};

function opLabel(opType: string): string {
  return OP_LABELS[opType] || opType.replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function statusIcon(status: string): { name: string; color: string } {
  switch (status) {
    case "pending":   return { name: "time-outline", color: "#854D0E" };
    case "in_flight": return { name: "cloud-upload-outline", color: "#1E40AF" };
    case "done":      return { name: "checkmark-circle", color: "#166534" };
    case "failed":    return { name: "alert-circle", color: "#991B1B" };
    default:          return { name: "ellipse-outline", color: colors.muted };
  }
}

function formatTime(iso: string): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch {
    return "";
  }
}

export default function SyncCenterScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const syncStatus = useSyncStatus();

  const [entries, setEntries] = useState<SyncEntry[]>([]);
  const [photos, setPhotos] = useState<PendingPhoto[]>([]);
  const [stalledPhotos, setStalledPhotos] = useState<PendingPhoto[]>([]);
  const [videos, setVideos] = useState<PendingVideo[]>([]);
  const [stalledVideos, setStalledVideos] = useState<PendingVideo[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const [all, pPhotos, sPhotos, pVideos, sVideos] = await Promise.all([
        getAll(),
        getPendingPhotos(),
        getStalledPhotos(),
        getPendingVideos(),
        getStalledVideos(),
      ]);
      setEntries(all);
      setPhotos(pPhotos);
      setStalledPhotos(sPhotos);
      setVideos(pVideos);
      setStalledVideos(sVideos);
    } catch (e) {
      console.warn("[SyncCenter] Load failed:", e);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  // Auto-refresh every 3s while syncing
  useEffect(() => {
    if (syncStatus.is_flushing) {
      const t = setInterval(loadAll, 3000);
      return () => clearInterval(t);
    }
  }, [syncStatus.is_flushing, loadAll]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await loadAll();
    setRefreshing(false);
  }, [loadAll]);

  const handleSyncNow = useCallback(async () => {
    if (!syncStatus.is_online) {
      Alert.alert("Offline", "You need an internet connection to sync.");
      return;
    }
    setSyncing(true);
    try {
      const result = await triggerSyncNow();
      await loadAll();
      Alert.alert(
        "Sync Complete",
        `${result.succeeded} synced, ${result.failed} failed${result.errors.length ? `\n${result.errors[0]}` : ""}`,
      );
    } catch (e: any) {
      Alert.alert("Sync Error", e?.message || "Unknown error");
    } finally {
      setSyncing(false);
    }
  }, [syncStatus.is_online, loadAll]);

  const handleRetryOne = useCallback(async (entryId: string) => {
    await retrySingle(entryId);
    setTimeout(loadAll, 1500);
  }, [loadAll]);

  const handleClearDone = useCallback(async () => {
    await clearDone();
    await loadAll();
  }, [loadAll]);

  const handleRetryAllPhotos = useCallback(async () => {
    await retryAllStalledPhotos();
    setTimeout(loadAll, 1500);
  }, [loadAll]);

  const handleRetryAllVideos = useCallback(async () => {
    await retryAllStalledVideos();
    setTimeout(loadAll, 1500);
  }, [loadAll]);

  // Split entries by status
  const pending = entries.filter((e) => e.status === "pending");
  const inFlight = entries.filter((e) => e.status === "in_flight");
  const failed = entries.filter((e) => e.status === "failed");
  const done = entries.filter((e) => e.status === "done");

  return (
    <View style={[styles.root, { paddingTop: insets.top }]} testID="sync-center-screen">
      {/* Header */}
      <View style={styles.header}>
        <Pressable
          onPress={() => router.back()}
          style={styles.backBtn}
          testID="sync-center-back-btn"
          hitSlop={12}
        >
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Sync Center</Text>
        <View style={{ width: 36 }} />
      </View>

      <ScrollView
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
        testID="sync-center-scroll"
      >
        {/* Status Summary */}
        <View style={styles.summaryCard} testID="sync-center-summary">
          <View style={styles.summaryRow}>
            <StatusChip
              icon="wifi"
              label={syncStatus.is_online ? "Online" : "Offline"}
              bg={syncStatus.is_online ? "#DCFCE7" : "#FEE2E2"}
              fg={syncStatus.is_online ? "#166534" : "#991B1B"}
              testID="sync-center-online-chip"
            />
            {syncStatus.last_sync_at ? (
              <Text style={styles.lastSync} testID="sync-center-last-sync">
                Last sync: {formatTime(syncStatus.last_sync_at)}
              </Text>
            ) : null}
          </View>

          <View style={styles.countsRow}>
            <CountBox label="Pending" count={pending.length} color="#854D0E" bg="#FEF3C7" testID="sync-center-pending-count" />
            <CountBox label="In Flight" count={inFlight.length} color="#1E40AF" bg="#DBEAFE" testID="sync-center-inflight-count" />
            <CountBox label="Failed" count={failed.length + stalledPhotos.length + stalledVideos.length} color="#991B1B" bg="#FEE2E2" testID="sync-center-failed-count" />
            <CountBox label="Done" count={done.length} color="#166534" bg="#DCFCE7" testID="sync-center-done-count" />
          </View>

          {/* Sync Now Button */}
          <Pressable
            onPress={handleSyncNow}
            disabled={syncing || syncStatus.is_flushing || !syncStatus.is_online}
            style={[
              styles.syncNowBtn,
              (!syncStatus.is_online || syncing || syncStatus.is_flushing) && styles.syncNowBtnDisabled,
            ]}
            testID="sync-center-sync-now-btn"
          >
            {syncing || syncStatus.is_flushing ? (
              <ActivityIndicator size={14} color="#fff" />
            ) : (
              <Ionicons name="sync" size={16} color="#fff" />
            )}
            <Text style={styles.syncNowText}>
              {syncing || syncStatus.is_flushing ? "Syncing…" : "Sync Now"}
            </Text>
          </Pressable>
        </View>

        {/* Pending Section */}
        {pending.length > 0 ? (
          <Section
            title="Pending"
            icon="time-outline"
            iconColor="#854D0E"
            count={pending.length}
            testID="sync-center-section-pending"
          >
            {pending.map((entry) => (
              <EntryRow key={entry.id} entry={entry} testID={`sync-entry-pending-${entry.id}`} />
            ))}
          </Section>
        ) : null}

        {/* In Flight Section */}
        {inFlight.length > 0 ? (
          <Section
            title="In Flight"
            icon="cloud-upload-outline"
            iconColor="#1E40AF"
            count={inFlight.length}
            testID="sync-center-section-inflight"
          >
            {inFlight.map((entry) => (
              <EntryRow key={entry.id} entry={entry} testID={`sync-entry-inflight-${entry.id}`} />
            ))}
          </Section>
        ) : null}

        {/* Failed Section */}
        {(failed.length > 0 || stalledPhotos.length > 0 || stalledVideos.length > 0) ? (
          <Section
            title="Failed"
            icon="alert-circle"
            iconColor="#991B1B"
            count={failed.length + stalledPhotos.length + stalledVideos.length}
            testID="sync-center-section-failed"
          >
            {failed.map((entry) => (
              <EntryRow
                key={entry.id}
                entry={entry}
                onRetry={() => handleRetryOne(entry.id)}
                testID={`sync-entry-failed-${entry.id}`}
              />
            ))}
            {stalledPhotos.length > 0 ? (
              <View style={styles.mediaSection}>
                <View style={styles.mediaHeader}>
                  <Ionicons name="camera-outline" size={14} color="#991B1B" />
                  <Text style={styles.mediaSectionTitle}>
                    {stalledPhotos.length} stalled photo{stalledPhotos.length !== 1 ? "s" : ""}
                  </Text>
                  <Pressable
                    onPress={handleRetryAllPhotos}
                    style={styles.retryAllBtn}
                    testID="sync-center-retry-all-photos"
                  >
                    <Ionicons name="refresh" size={12} color="#1E40AF" />
                    <Text style={styles.retryAllText}>Retry all</Text>
                  </Pressable>
                </View>
                {stalledPhotos.map((p) => (
                  <Text key={p.id} style={styles.mediaItem} numberOfLines={1}>
                    Photo {p.id.slice(0, 8)}… — {p.last_error || "Upload failed"}
                  </Text>
                ))}
              </View>
            ) : null}
            {stalledVideos.length > 0 ? (
              <View style={styles.mediaSection}>
                <View style={styles.mediaHeader}>
                  <Ionicons name="videocam-outline" size={14} color="#991B1B" />
                  <Text style={styles.mediaSectionTitle}>
                    {stalledVideos.length} stalled video{stalledVideos.length !== 1 ? "s" : ""}
                  </Text>
                  <Pressable
                    onPress={handleRetryAllVideos}
                    style={styles.retryAllBtn}
                    testID="sync-center-retry-all-videos"
                  >
                    <Ionicons name="refresh" size={12} color="#1E40AF" />
                    <Text style={styles.retryAllText}>Retry all</Text>
                  </Pressable>
                </View>
                {stalledVideos.map((v) => (
                  <Text key={v.id} style={styles.mediaItem} numberOfLines={1}>
                    Video {v.id.slice(0, 8)}… — {v.last_error || "Upload failed"}
                  </Text>
                ))}
              </View>
            ) : null}
          </Section>
        ) : null}

        {/* Pending Media */}
        {(photos.length > 0 || videos.length > 0) ? (
          <Section
            title="Media Uploads"
            icon="images-outline"
            iconColor="#0891B2"
            count={photos.length + videos.length}
            testID="sync-center-section-media"
          >
            {photos.map((p) => (
              <View key={p.id} style={styles.entryRow} testID={`sync-media-photo-${p.id}`}>
                <Ionicons name="camera-outline" size={14} color="#0891B2" />
                <View style={{ flex: 1, marginLeft: 8 }}>
                  <Text style={styles.entryOp}>Photo upload</Text>
                  <Text style={styles.entryMeta}>
                    {p.upload_status} · {formatTime(p.created_at)}
                  </Text>
                </View>
              </View>
            ))}
            {videos.map((v) => (
              <View key={v.id} style={styles.entryRow} testID={`sync-media-video-${v.id}`}>
                <Ionicons name="videocam-outline" size={14} color="#0891B2" />
                <View style={{ flex: 1, marginLeft: 8 }}>
                  <Text style={styles.entryOp}>Video upload ({v.duration_sec}s)</Text>
                  <Text style={styles.entryMeta}>
                    {v.upload_status} · {formatTime(v.created_at)}
                  </Text>
                </View>
              </View>
            ))}
          </Section>
        ) : null}

        {/* Done Section */}
        {done.length > 0 ? (
          <Section
            title="Recently Synced"
            icon="checkmark-circle"
            iconColor="#166534"
            count={done.length}
            testID="sync-center-section-done"
            rightAction={
              <Pressable
                onPress={handleClearDone}
                style={styles.clearDoneBtn}
                testID="sync-center-clear-done"
              >
                <Ionicons name="trash-outline" size={12} color={colors.muted} />
                <Text style={styles.clearDoneText}>Clear</Text>
              </Pressable>
            }
          >
            {done.slice(0, 20).map((entry) => (
              <EntryRow key={entry.id} entry={entry} testID={`sync-entry-done-${entry.id}`} />
            ))}
            {done.length > 20 ? (
              <Text style={styles.moreText}>…and {done.length - 20} more</Text>
            ) : null}
          </Section>
        ) : null}

        {/* Empty State */}
        {entries.length === 0 && photos.length === 0 && videos.length === 0 ? (
          <View style={styles.emptyState} testID="sync-center-empty">
            <Ionicons name="checkmark-circle" size={36} color="#059669" />
            <Text style={styles.emptyTitle}>All synced!</Text>
            <Text style={styles.emptySub}>No pending offline operations.</Text>
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

// ─── Sub-components ────────────────────────────────────────────────

function StatusChip({ icon, label, bg, fg, testID }: {
  icon: string; label: string; bg: string; fg: string; testID?: string;
}) {
  return (
    <View style={[styles.statusChip, { backgroundColor: bg }]} testID={testID}>
      <Ionicons name={icon as any} size={12} color={fg} />
      <Text style={[styles.statusChipText, { color: fg }]}>{label}</Text>
    </View>
  );
}

function CountBox({ label, count, color, bg, testID }: {
  label: string; count: number; color: string; bg: string; testID?: string;
}) {
  return (
    <View style={[styles.countBox, { backgroundColor: bg }]} testID={testID}>
      <Text style={[styles.countNum, { color }]}>{count}</Text>
      <Text style={[styles.countLabel, { color }]}>{label}</Text>
    </View>
  );
}

function Section({ title, icon, iconColor, count, children, testID, rightAction }: {
  title: string; icon: string; iconColor: string; count: number;
  children: React.ReactNode; testID?: string; rightAction?: React.ReactNode;
}) {
  return (
    <View style={styles.section} testID={testID}>
      <View style={styles.sectionHeader}>
        <Ionicons name={icon as any} size={16} color={iconColor} />
        <Text style={styles.sectionTitle}>{title}</Text>
        <View style={styles.sectionBadge}>
          <Text style={styles.sectionBadgeText}>{count}</Text>
        </View>
        {rightAction ? <View style={{ marginLeft: "auto" }}>{rightAction}</View> : null}
      </View>
      {children}
    </View>
  );
}

function EntryRow({ entry, onRetry, testID }: {
  entry: SyncEntry; onRetry?: () => void; testID?: string;
}) {
  const si = statusIcon(entry.status);
  return (
    <View style={styles.entryRow} testID={testID}>
      <Ionicons name={si.name as any} size={16} color={si.color} />
      <View style={{ flex: 1, marginLeft: 8 }}>
        <Text style={styles.entryOp}>{opLabel(entry.op_type)}</Text>
        <Text style={styles.entryMeta} numberOfLines={1}>
          {entry.entity_id.slice(0, 12)}… · {formatTime(entry.created_at)}
          {entry.attempt_count > 0 ? ` · ${entry.attempt_count} attempts` : ""}
        </Text>
        {entry.last_error ? (
          <Text style={styles.entryError} numberOfLines={2}>
            {entry.last_error}
          </Text>
        ) : null}
      </View>
      {onRetry && entry.status === "failed" ? (
        <Pressable
          onPress={onRetry}
          style={styles.retryBtn}
          testID={`${testID}-retry`}
          hitSlop={8}
        >
          <Ionicons name="refresh" size={14} color="#1E40AF" />
          <Text style={styles.retryText}>Retry</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

// ─── Styles ────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.surfaceSecondary,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  backBtn: {
    width: 36,
    height: 36,
    alignItems: "center",
    justifyContent: "center",
  },
  headerTitle: {
    flex: 1,
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
    textAlign: "center",
  },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: 80,
  },
  // Summary
  summaryCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    marginBottom: spacing.lg,
    shadowColor: "#000",
    shadowOpacity: 0.06,
    shadowOffset: { width: 0, height: 2 },
    shadowRadius: 8,
    elevation: 2,
  },
  summaryRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.md,
  },
  lastSync: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  countsRow: {
    flexDirection: "row",
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  countBox: {
    flex: 1,
    alignItems: "center",
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
  },
  countNum: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
  },
  countLabel: {
    fontFamily: font.semibold,
    fontSize: 9,
    letterSpacing: 0.5,
    textTransform: "uppercase",
    marginTop: 2,
  },
  syncNowBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    backgroundColor: colors.brand,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
  },
  syncNowBtnDisabled: {
    opacity: 0.5,
  },
  syncNowText: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: "#fff",
  },
  // Status chip
  statusChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.pill,
  },
  statusChipText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
  },
  // Sections
  section: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  sectionTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  sectionBadge: {
    backgroundColor: colors.surfaceSecondary,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
  },
  sectionBadgeText: {
    fontFamily: font.bold,
    fontSize: 10,
    color: colors.onSurface,
  },
  // Entry row
  entryRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  entryOp: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  entryMeta: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 2,
  },
  entryError: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#991B1B",
    marginTop: 2,
  },
  retryBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.md,
    backgroundColor: "#EFF6FF",
  },
  retryText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#1E40AF",
  },
  retryAllBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.md,
    backgroundColor: "#EFF6FF",
    marginLeft: "auto",
  },
  retryAllText: {
    fontFamily: font.semibold,
    fontSize: 11,
    color: "#1E40AF",
  },
  clearDoneBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
  },
  clearDoneText: {
    fontFamily: font.semibold,
    fontSize: 11,
    color: colors.muted,
  },
  // Media section
  mediaSection: {
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  mediaHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: spacing.sm,
  },
  mediaSectionTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#991B1B",
  },
  mediaItem: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    paddingVertical: 3,
    paddingLeft: 20,
  },
  moreText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
    paddingVertical: spacing.sm,
  },
  // Empty
  emptyState: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: spacing["3xl"],
  },
  emptyTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
    marginTop: spacing.md,
  },
  emptySub: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    marginTop: spacing.xs,
  },
});
