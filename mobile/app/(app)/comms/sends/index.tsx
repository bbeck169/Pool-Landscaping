/**
 * Comms Sends List — Phase 4 · Mobile Parity.
 *
 * Filterable list of send records. Tap → detail screen.
 */
import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { listSends } from "@/src/api/comms";
import SendStatusPill from "@/src/components/comms/SendStatusPill";
import ChannelIcon from "@/src/components/comms/ChannelIcon";

const KIND_OPTIONS = [
  { value: "", label: "All kinds" },
  { value: "email", label: "Email" },
  { value: "sms", label: "SMS" },
];

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "queued", label: "Queued" },
  { value: "sent", label: "Sent" },
  { value: "mocked", label: "Mocked" },
  { value: "failed", label: "Failed" },
  { value: "opted_out", label: "Opted out" },
  { value: "missing_key", label: "Missing key" },
];

export default function CommsSendsListScreen() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [recipientQ, setRecipientQ] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);

  const reload = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const d = await listSends({
          kind: kind || undefined,
          status: status || undefined,
          recipient: recipientQ || undefined,
          limit: "100",
        });
        setRows(d.sends || d || []);
      } catch {
        setRows([]);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [kind, status, recipientQ]
  );

  useFocusEffect(
    useCallback(() => {
      reload();
    }, [reload])
  );

  const cycleOption = (
    options: { value: string; label: string }[],
    current: string,
    setter: (v: string) => void
  ) => {
    const idx = options.findIndex((o) => o.value === current);
    const next = (idx + 1) % options.length;
    setter(options[next].value);
  };

  const renderRow = ({ item }: { item: any }) => (
    <TouchableOpacity
      testID={`comms-sends-row-${item.id}`}
      style={styles.row}
      activeOpacity={0.7}
      onPress={() =>
        router.push({
          pathname: "/(app)/comms/sends/[id]",
          params: { id: item.id },
        })
      }
    >
      <View style={styles.rowTop}>
        <ChannelIcon channel={item.kind} />
        <SendStatusPill status={item.status} />
      </View>
      <Text style={styles.rowTemplate} numberOfLines={1}>
        {item.template_code || "—"}
      </Text>
      <Text style={styles.rowRecipient} numberOfLines={1}>
        {item.recipient_address || item.recipient_id || "—"}
      </Text>
      {item.automation_code ? (
        <Text style={styles.rowAuto}>
          Auto: {item.automation_code}
        </Text>
      ) : null}
      <Text style={styles.rowDate}>
        {(item.sent_at || item.queued_at || "")
          .slice(0, 19)
          .replace("T", " ")}
      </Text>
    </TouchableOpacity>
  );

  return (
    <View testID="comms-sends-page" style={styles.root}>
      <Header
        title="Sends History"
        subtitle={`${rows.length} records`}
        back
        right={
          <TouchableOpacity
            testID="comms-sends-filter-toggle"
            onPress={() => setFiltersOpen(!filtersOpen)}
            style={styles.filterToggle}
          >
            <Ionicons
              name="filter-outline"
              size={18}
              color={filtersOpen ? colors.brand : colors.onSurface}
            />
          </TouchableOpacity>
        }
      />

      {/* Filters */}
      {filtersOpen && (
        <View style={styles.filterBar}>
          <TouchableOpacity
            testID="comms-sends-filter-kind"
            style={styles.filterChip}
            onPress={() => cycleOption(KIND_OPTIONS, kind, setKind)}
          >
            <Text style={styles.filterChipText}>
              {KIND_OPTIONS.find((o) => o.value === kind)?.label}
            </Text>
            <Ionicons name="chevron-down" size={12} color={colors.muted} />
          </TouchableOpacity>
          <TouchableOpacity
            testID="comms-sends-filter-status"
            style={styles.filterChip}
            onPress={() =>
              cycleOption(STATUS_OPTIONS, status, setStatus)
            }
          >
            <Text style={styles.filterChipText}>
              {STATUS_OPTIONS.find((o) => o.value === status)?.label}
            </Text>
            <Ionicons name="chevron-down" size={12} color={colors.muted} />
          </TouchableOpacity>
          <View style={styles.filterInput}>
            <Ionicons name="search-outline" size={14} color={colors.muted} />
            <TextInput
              testID="comms-sends-filter-recipient"
              style={styles.filterInputText}
              value={recipientQ}
              onChangeText={setRecipientQ}
              placeholder="Recipient…"
              placeholderTextColor={colors.muted}
              returnKeyType="search"
              onSubmitEditing={() => reload()}
            />
          </View>
        </View>
      )}

      {loading ? (
        <ActivityIndicator
          testID="comms-sends-loader"
          style={{ marginTop: 40 }}
          color={colors.brand}
        />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item) => item.id}
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
              <Ionicons
                name="paper-plane-outline"
                size={36}
                color={colors.muted}
              />
              <Text style={styles.emptyText}>No sends yet</Text>
              <Text style={styles.emptyHint}>
                Send a template or fire an automation to see records.
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
  filterToggle: {
    padding: 6,
  },
  filterBar: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
    flexWrap: "wrap",
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  filterChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  filterChipText: {
    fontFamily: font.medium,
    fontSize: 11,
    color: colors.onSurface,
  },
  filterInput: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 8,
    paddingVertical: 6,
    minWidth: 120,
  },
  filterInputText: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.onSurface,
    flex: 1,
    paddingVertical: 0,
  },
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
    marginBottom: 6,
  },
  rowTemplate: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    marginBottom: 2,
  },
  rowRecipient: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginBottom: 2,
  },
  rowAuto: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
    marginBottom: 2,
  },
  rowDate: {
    fontFamily: font.regular,
    fontSize: 10,
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
