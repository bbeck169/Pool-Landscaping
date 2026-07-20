/**
 * Comms Templates Library — Phase 4 · Mobile Parity.
 *
 * Read-only list of email + SMS templates. Two-tab toggle, search filter,
 * tap → detail view.
 */
import React, { useCallback, useMemo, useState } from "react";
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
import { listEmailTemplates, listSmsTemplates } from "@/src/api/comms";
import ChannelIcon from "@/src/components/comms/ChannelIcon";

export default function CommsTemplatesListScreen() {
  const router = useRouter();
  const [tab, setTab] = useState<"email" | "sms">("email");
  const [rows, setRows] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const reload = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const d =
          tab === "email"
            ? await listEmailTemplates()
            : await listSmsTemplates();
        setRows(
          d.templates ||
            d[tab === "email" ? "email_templates" : "sms_templates"] ||
            d ||
            []
        );
      } catch {
        setRows([]);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [tab]
  );

  useFocusEffect(
    useCallback(() => {
      reload();
    }, [reload])
  );

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return rows;
    return rows.filter(
      (r: any) =>
        (r.code || "").toLowerCase().includes(s) ||
        (r.name || "").toLowerCase().includes(s)
    );
  }, [rows, q]);

  const onRefresh = () => {
    setRefreshing(true);
    reload(true);
  };

  const renderRow = ({ item }: { item: any }) => (
    <TouchableOpacity
      testID={`comms-template-row-${item.code}`}
      style={styles.row}
      activeOpacity={0.7}
      onPress={() =>
        router.push({
          pathname: "/(app)/comms/templates/[code]",
          params: { code: item.code, channel: tab },
        })
      }
    >
      <View style={styles.rowTop}>
        <Text style={styles.rowName} numberOfLines={1}>
          {item.name || item.code}
        </Text>
        {item.is_system ? (
          <View style={styles.systemBadge}>
            <Text style={styles.systemLabel}>SYSTEM</Text>
          </View>
        ) : (
          <View style={styles.customBadge}>
            <Text style={styles.customLabel}>CUSTOM</Text>
          </View>
        )}
      </View>
      <Text style={styles.rowCode} numberOfLines={1}>
        {item.code}
      </Text>
      <Text style={styles.rowDate}>
        Updated {(item.updated_at || item.created_at || "").slice(0, 10)}
      </Text>
    </TouchableOpacity>
  );

  return (
    <View testID="comms-templates-library" style={styles.root}>
      <Header title="Comms Templates" subtitle="Email & SMS templates" back />

      {/* Tab toggle */}
      <View style={styles.tabBar}>
        <TouchableOpacity
          testID="comms-tab-email"
          style={[styles.tabBtn, tab === "email" && styles.tabBtnActive]}
          onPress={() => setTab("email")}
        >
          <Ionicons
            name="mail-outline"
            size={14}
            color={tab === "email" ? "#fff" : colors.onSurface}
          />
          <Text
            style={[
              styles.tabLabel,
              tab === "email" && styles.tabLabelActive,
            ]}
          >
            Email
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          testID="comms-tab-sms"
          style={[styles.tabBtn, tab === "sms" && styles.tabBtnActive]}
          onPress={() => setTab("sms")}
        >
          <Ionicons
            name="chatbubble-outline"
            size={14}
            color={tab === "sms" ? "#fff" : colors.onSurface}
          />
          <Text
            style={[styles.tabLabel, tab === "sms" && styles.tabLabelActive]}
          >
            SMS
          </Text>
        </TouchableOpacity>
      </View>

      {/* Search */}
      <View style={styles.searchWrap}>
        <Ionicons name="search-outline" size={16} color={colors.muted} />
        <TextInput
          testID="comms-templates-search"
          style={styles.searchInput}
          value={q}
          onChangeText={setQ}
          placeholder="Search templates…"
          placeholderTextColor={colors.muted}
        />
        {q.length > 0 && (
          <TouchableOpacity onPress={() => setQ("")}>
            <Ionicons name="close-circle" size={18} color={colors.muted} />
          </TouchableOpacity>
        )}
      </View>

      {loading ? (
        <ActivityIndicator
          testID="comms-templates-loader"
          style={{ marginTop: 40 }}
          color={colors.brand}
        />
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={(item) => item.code}
          renderItem={renderRow}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
          ListEmptyComponent={
            <View style={styles.empty}>
              <Ionicons
                name="mail-open-outline"
                size={36}
                color={colors.muted}
              />
              <Text style={styles.emptyText}>
                No {tab} templates found
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
  tabBar: {
    flexDirection: "row",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
  },
  tabBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  tabBtnActive: {
    backgroundColor: colors.brand,
    borderColor: colors.brand,
  },
  tabLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  tabLabelActive: { color: "#fff" },
  searchWrap: {
    flexDirection: "row",
    alignItems: "center",
    marginHorizontal: spacing.lg,
    marginTop: spacing.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  searchInput: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    paddingVertical: 0,
  },
  list: { paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: 40 },
  row: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    padding: spacing.lg,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  rowTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 4,
  },
  rowName: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
    flex: 1,
    marginRight: 8,
  },
  systemBadge: {
    backgroundColor: "#DBEAFE",
    borderWidth: 1,
    borderColor: "#93C5FD",
    borderRadius: 4,
    paddingHorizontal: 5,
    paddingVertical: 1,
  },
  systemLabel: {
    fontFamily: font.bold,
    fontSize: 9,
    color: "#1E3A8A",
    letterSpacing: 0.5,
  },
  customBadge: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 4,
    paddingHorizontal: 5,
    paddingVertical: 1,
  },
  customLabel: {
    fontFamily: font.bold,
    fontSize: 9,
    color: colors.muted,
    letterSpacing: 0.5,
  },
  rowCode: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginBottom: 2,
  },
  rowDate: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
  },
  empty: {
    alignItems: "center",
    paddingTop: 60,
    gap: 8,
  },
  emptyText: {
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.muted,
  },
});
