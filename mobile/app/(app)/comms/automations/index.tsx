/**
 * Comms Automations List — Phase 4 · Mobile Parity.
 *
 * Read-only list of automation rules with active toggle and tap → detail.
 */
import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
  Switch,
  Alert,
} from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { listAutomations, toggleAutomation } from "@/src/api/comms";
import ChannelIcon from "@/src/components/comms/ChannelIcon";

export default function CommsAutomationsListScreen() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const reload = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const d = await listAutomations();
      setRows(d.automations || d.automation_rules || d || []);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      reload();
    }, [reload])
  );

  const onToggle = async (code: string, active: boolean) => {
    try {
      await toggleAutomation(code, active);
      setRows((prev) =>
        prev.map((r) => (r.code === code ? { ...r, active } : r))
      );
    } catch (e: any) {
      Alert.alert("Error", e.message || "Failed to toggle");
    }
  };

  const renderRow = ({ item }: { item: any }) => (
    <TouchableOpacity
      testID={`comms-automation-row-${item.code}`}
      style={styles.row}
      activeOpacity={0.7}
      onPress={() =>
        router.push({
          pathname: "/(app)/comms/automations/[code]",
          params: { code: item.code },
        })
      }
    >
      <View style={styles.rowTop}>
        <Text style={styles.rowName} numberOfLines={1}>
          {item.name || item.code}
        </Text>
        <Switch
          testID={`comms-automation-toggle-${item.code}`}
          value={!!item.active}
          onValueChange={(v) => onToggle(item.code, v)}
          trackColor={{ false: colors.border, true: colors.brand + "80" }}
          thumbColor={item.active ? colors.brand : colors.muted}
        />
      </View>

      <View style={styles.tagRow}>
        <ChannelIcon channel={item.channel} />
        <View style={styles.triggerBadge}>
          <Ionicons name="flash-outline" size={11} color={colors.muted} />
          <Text style={styles.triggerText}>{item.trigger_event}</Text>
        </View>
        {item.ai_generated_copy && (
          <View style={styles.aiCopyBadge}
                testID={`comms-automation-ai-badge-${item.code}`}>
            <Ionicons name="sparkles-outline" size={11} color="#fff" />
            <Text style={styles.aiCopyBadgeText}>AI Copy</Text>
          </View>
        )}
      </View>

      <View style={styles.metaRow}>
        <Text style={styles.metaText}>
          Template: {item.template_code || "—"}
        </Text>
        <Text style={styles.metaText}>
          Delay: {item.send_delay_minutes || 0}m
        </Text>
      </View>
    </TouchableOpacity>
  );

  return (
    <View testID="comms-automations-page" style={styles.root}>
      <Header title="Automations" subtitle="Trigger rules & test-fire" back />
      {loading ? (
        <ActivityIndicator
          testID="comms-automations-loader"
          style={{ marginTop: 40 }}
          color={colors.brand}
        />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item) => item.code}
          renderItem={renderRow}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => {
                setRefreshing(true);
                reload(true);
              }}
            />
          }
          ListEmptyComponent={
            <View style={styles.empty}>
              <Ionicons name="flash-outline" size={36} color={colors.muted} />
              <Text style={styles.emptyText}>No automation rules yet</Text>
              <Text style={styles.emptyHint}>
                Create rules in the web admin console.
              </Text>
            </View>
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  list: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: 40,
  },
  row: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.lg,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  rowTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  rowName: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
    flex: 1,
    marginRight: 12,
  },
  tagRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 8,
  },
  triggerBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 4,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  triggerText: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
  },
  aiCopyBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    backgroundColor: colors.brand,
    borderRadius: 4,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  aiCopyBadgeText: {
    fontFamily: font.semibold,
    fontSize: 10,
    color: "#fff",
  },
  metaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
  },
  metaText: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
  },
  empty: { alignItems: "center", paddingTop: 60, gap: 8 },
  emptyText: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  emptyHint: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
  },
});
