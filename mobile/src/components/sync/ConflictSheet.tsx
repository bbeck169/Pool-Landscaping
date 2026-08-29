/**
 * Phase O6 · ConflictSheet — bottom sheet that appears when
 * a sync:conflict event fires. Shows a diff between the client's
 * queued payload and the server's current state.
 *
 * Resolution options:
 *   - "Keep server version" (discard local change)
 *   - "Keep my version" (re-enqueue with force flag)
 *   - Dismiss (mark resolved, no action)
 */
import React, { useState, useEffect, useCallback } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, TouchableOpacity,
  ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import {
  onConflict, getUnresolvedConflicts, resolveConflict,
  type SyncConflict,
} from "@/src/services/sync/conflicts";
import { enqueue } from "@/src/services/sync/queue";
import { font, fontSize, spacing, radius, colors } from "@/src/theme";

function parseJSON(str: string): Record<string, any> {
  try { return JSON.parse(str); } catch { return {}; }
}

/** Compute which keys differ between two objects. */
function diffKeys(a: Record<string, any>, b: Record<string, any>): string[] {
  const allKeys = new Set([...Object.keys(a), ...Object.keys(b)]);
  const changed: string[] = [];
  for (const k of allKeys) {
    if (JSON.stringify(a[k]) !== JSON.stringify(b[k])) changed.push(k);
  }
  return changed;
}

function formatValue(v: any): string {
  if (v === undefined || v === null) return "(empty)";
  if (typeof v === "object") return JSON.stringify(v, null, 2).slice(0, 200);
  return String(v);
}

export function ConflictSheet() {
  const [conflicts, setConflicts] = useState<SyncConflict[]>([]);
  const [current, setCurrent] = useState<SyncConflict | null>(null);

  const refresh = useCallback(async () => {
    const list = await getUnresolvedConflicts();
    setConflicts(list);
    if (!current && list.length > 0) setCurrent(list[0]);
  }, [current]);

  // Listen for new conflicts.
  useEffect(() => {
    const unsub = onConflict(() => { refresh(); });
    refresh();
    return unsub;
  }, [refresh]);

  const handleKeepServer = async () => {
    if (!current) return;
    await resolveConflict(current.id);
    console.log(`[ConflictSheet] Resolved ${current.id} — kept server version`);
    setCurrent(null);
    refresh();
  };

  const handleKeepLocal = async () => {
    if (!current) return;
    // Re-enqueue the original payload with a force hint.
    const payload = parseJSON(current.client_payload);
    await enqueue({
      op_type: current.op_type,
      entity_id: current.entity_id,
      endpoint: `/api/${current.entity_id}`, // Best-effort — the original endpoint
      method: "PATCH",
      payload: { ...payload, __force_overwrite: true },
    });
    await resolveConflict(current.id);
    console.log(`[ConflictSheet] Resolved ${current.id} — re-enqueued local version`);
    setCurrent(null);
    refresh();
  };

  const handleDismiss = async () => {
    if (!current) return;
    await resolveConflict(current.id);
    console.log(`[ConflictSheet] Dismissed conflict ${current.id}`);
    setCurrent(null);
    refresh();
  };

  if (!current) return null;

  const clientData = parseJSON(current.client_payload);
  const serverData = parseJSON(current.server_state);
  const diffs = diffKeys(clientData, serverData);

  return (
    <Modal
      visible={!!current}
      animationType="slide"
      transparent
      onRequestClose={handleDismiss}
    >
      <Pressable style={s.backdrop} onPress={handleDismiss} />
      <View style={s.sheet} testID="conflict-sheet">
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerIcon}>
            <Ionicons name="git-compare" size={20} color={colors.warning} />
          </View>
          <View style={s.headerText}>
            <Text style={s.title}>Sync Conflict</Text>
            <Text style={s.subtitle}>
              {current.op_type.replace(/[._]/g, " ")} — changes differ from server
            </Text>
          </View>
          <TouchableOpacity
            testID="conflict-sheet-close"
            onPress={handleDismiss}
          >
            <Ionicons name="close" size={22} color={colors.muted} />
          </TouchableOpacity>
        </View>

        {/* Diff table */}
        <ScrollView style={s.diffScroll}>
          {diffs.length === 0 ? (
            <Text style={s.noDiff}>No field-level differences detected.</Text>
          ) : (
            diffs.map((key) => (
              <View key={key} style={s.diffRow}>
                <Text style={s.diffKey}>{key}</Text>
                <View style={s.diffValues}>
                  <View style={[s.diffCell, s.diffLocal]}>
                    <Text style={s.diffLabel}>Your change</Text>
                    <Text style={s.diffValue}>{formatValue(clientData[key])}</Text>
                  </View>
                  <View style={[s.diffCell, s.diffServer]}>
                    <Text style={s.diffLabel}>Server</Text>
                    <Text style={s.diffValue}>{formatValue(serverData[key])}</Text>
                  </View>
                </View>
              </View>
            ))
          )}
        </ScrollView>

        {/* Count badge */}
        {conflicts.length > 1 && (
          <Text style={s.countBadge}>
            {conflicts.length - 1} more conflict{conflicts.length > 2 ? "s" : ""}
          </Text>
        )}

        {/* Action buttons */}
        <View style={s.actions}>
          <TouchableOpacity
            testID="conflict-keep-server"
            style={[s.actionBtn, s.serverBtn]}
            onPress={handleKeepServer}
          >
            <Ionicons name="cloud-done" size={16} color="#166534" />
            <Text style={[s.actionText, { color: "#166534" }]}>Keep server</Text>
          </TouchableOpacity>
          <TouchableOpacity
            testID="conflict-keep-local"
            style={[s.actionBtn, s.localBtn]}
            onPress={handleKeepLocal}
          >
            <Ionicons name="phone-portrait" size={16} color="#1E40AF" />
            <Text style={[s.actionText, { color: "#1E40AF" }]}>Keep mine</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.4)",
  },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    maxHeight: "70%",
    paddingBottom: 32,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: spacing.sm,
  },
  headerIcon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: "#FEF3C7",
    justifyContent: "center",
    alignItems: "center",
  },
  headerText: {
    flex: 1,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  subtitle: {
    fontFamily: font.regular,
    fontSize: 12,
    color: colors.muted,
    marginTop: 2,
  },
  diffScroll: {
    maxHeight: 300,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  noDiff: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    textAlign: "center",
    paddingVertical: spacing.xl,
  },
  diffRow: {
    marginBottom: spacing.md,
  },
  diffKey: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    marginBottom: 4,
  },
  diffValues: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  diffCell: {
    flex: 1,
    borderRadius: radius.sm,
    padding: spacing.sm,
  },
  diffLocal: {
    backgroundColor: "#EFF6FF",
  },
  diffServer: {
    backgroundColor: "#F0FDF4",
  },
  diffLabel: {
    fontFamily: font.semibold,
    fontSize: 10,
    color: colors.muted,
    textTransform: "uppercase",
    marginBottom: 2,
  },
  diffValue: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  countBadge: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    textAlign: "center",
    paddingVertical: spacing.sm,
  },
  actions: {
    flexDirection: "row",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
  },
  actionBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: spacing.md,
    borderRadius: radius.sm,
  },
  serverBtn: {
    backgroundColor: "#DCFCE7",
  },
  localBtn: {
    backgroundColor: "#DBEAFE",
  },
  actionText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
  },
});
