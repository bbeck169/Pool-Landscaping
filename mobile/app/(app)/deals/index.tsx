/**
 * QuoteIQ Q1-UI · Mobile — Deals list.
 *
 * Vertical scroll list (mobile-friendly) with a segmented stage filter
 * at top. Tap a card → detail screen. FAB → new deal modal.
 */
import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
} from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Header } from "@/src/components/widgets";
import { colors, fontSize, radius, spacing } from "@/src/theme";
import { listPipelines, listDeals } from "@/src/api/quoteiq_q1";

const centsToUsd = (c: number) =>
  `$${((c || 0) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;

export default function DealsIndex() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [pipelines, setPipelines] = useState<any[]>([]);
  const [pipeline, setPipeline] = useState<any>(null);
  const [stageId, setStageId] = useState<string>("__all");
  const [deals, setDeals] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const pps = await listPipelines();
      setPipelines(pps.pipelines || []);
      const def =
        pps.pipelines.find((p: any) => p.is_default) || pps.pipelines[0];
      setPipeline(def);
      const opts: any = { pipeline_id: def?.id, status: "open", limit: 200 };
      if (stageId !== "__all") opts.stage_id = stageId;
      const d = await listDeals(opts);
      setDeals(d.deals || []);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [stageId]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <Header title="Deals" />
      {loading && deals.length === 0 ? (
        <View style={{ padding: spacing.xl, alignItems: "center" }}>
          <ActivityIndicator />
        </View>
      ) : (
        <View style={{ flex: 1 }}>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            style={s.filterRow}
            contentContainerStyle={{ paddingHorizontal: spacing.md }}
          >
            <StageChip
              label="All open"
              active={stageId === "__all"}
              onPress={() => setStageId("__all")}
              testID="stage-chip-all"
            />
            {(pipeline?.stages || []).map((st: any) => (
              <StageChip
                key={st.id}
                label={st.name}
                active={stageId === st.id}
                color={st.color}
                onPress={() => setStageId(st.id)}
                testID={`stage-chip-${st.name.toLowerCase().replace(/\s+/g, "-")}`}
              />
            ))}
          </ScrollView>
          <ScrollView
            contentContainerStyle={{
              padding: spacing.md,
              paddingBottom: insets.bottom + 80,
            }}
            refreshControl={
              <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
            }
          >
            {deals.length === 0 && (
              <Text style={s.empty}>No deals in this stage.</Text>
            )}
            {deals.map((d) => (
              <TouchableOpacity
                key={d.id}
                onPress={() => router.push(`/(app)/deals/${d.id}`)}
                style={s.dealCard}
                testID={`deal-card-${d.id}`}
              >
                <View style={{ flex: 1 }}>
                  <Text style={s.dealTitle}>{d.title}</Text>
                  <Text style={s.dealContact}>
                    {d.contact_name || d.contact_email || "—"}
                  </Text>
                  <Text style={s.dealMeta}>
                    Prob {d.probability_pct}% ·{" "}
                    {new Date(d.updated_at).toLocaleDateString()}
                  </Text>
                </View>
                <Text style={s.dealValue}>{centsToUsd(d.value_cents)}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
          <TouchableOpacity
            style={[s.fab, { bottom: insets.bottom + 16 }]}
            onPress={() => router.push("/(app)/deals/new")}
            testID="deals-mobile-fab"
          >
            <Ionicons name="add" size={28} color="#fff" />
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
}

function StageChip({
  label,
  active,
  onPress,
  color,
  testID,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
  color?: string;
  testID?: string;
}) {
  return (
    <TouchableOpacity
      onPress={onPress}
      style={[
        s.chip,
        active && { backgroundColor: color || colors.primary, borderColor: color || colors.primary },
      ]}
      testID={testID}
    >
      <Text style={[s.chipText, active && { color: "#fff", fontWeight: "700" }]}>
        {label}
      </Text>
    </TouchableOpacity>
  );
}

const s = StyleSheet.create({
  filterRow: {
    flexGrow: 0,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    marginRight: 8,
  },
  chipText: { fontSize: fontSize.sm, color: colors.text },
  dealCard: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.card,
    padding: spacing.md,
    borderRadius: radius.md,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  dealTitle: { fontSize: fontSize.md, fontWeight: "600", color: colors.text },
  dealContact: { fontSize: fontSize.sm, color: colors.textDim, marginTop: 2 },
  dealMeta: { fontSize: fontSize.xs, color: colors.textDim, marginTop: 4 },
  dealValue: { fontSize: fontSize.md, fontWeight: "700", color: colors.primary },
  empty: {
    fontSize: fontSize.sm,
    color: colors.textDim,
    textAlign: "center",
    paddingVertical: spacing.xl,
  },
  fab: {
    position: "absolute",
    right: 16,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.2,
    shadowRadius: 4,
    elevation: 6,
  },
});
