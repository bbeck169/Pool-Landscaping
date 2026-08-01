// Phase 16 · Feb-2026 — Brand Mentions (mobile parity).
//
// KPI strip + sentiment/domain/range chips + scrollable mention list.
// Tap a row → mention detail screen.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, EmptyState, Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

type Sentiment = "any" | "positive" | "neutral" | "negative";
type Range = "24h" | "7d" | "30d";

type Mention = {
  id: string;
  provider?: string;
  sentiment?: string;
  snippet?: string;
  domain?: string;
  is_own_domain?: boolean;
  is_competitor?: boolean;
  captured_at?: string;
  brand_mentioned?: boolean;
};

const SENTS: { key: Sentiment; label: string }[] = [
  { key: "any",      label: "Any" },
  { key: "positive", label: "Positive" },
  { key: "neutral",  label: "Neutral" },
  { key: "negative", label: "Negative" },
];

const RANGES: { key: Range; label: string }[] = [
  { key: "24h", label: "24h" },
  { key: "7d",  label: "7d"  },
  { key: "30d", label: "30d" },
];

function _sentColor(s?: string): string {
  const v = (s || "").toLowerCase();
  if (v === "positive") return colors.success;
  if (v === "negative") return colors.error;
  return colors.muted;
}

export default function AeoMentions() {
  const [sent, setSent] = useState<Sentiment>("any");
  const [range, setRange] = useState<Range>("7d");
  const [domainFilter, setDomainFilter] = useState<"any" | "own" | "competitor">("any");
  const [items, setItems] = useState<Mention[]>([]);
  const [kpi, setKpi] = useState<{ total?: number; positive?: number; negative?: number }>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("range", range);
      if (sent !== "any") params.set("sentiment", sent);
      if (domainFilter === "own") params.set("scope", "own");
      if (domainFilter === "competitor") params.set("scope", "competitor");
      const j: any = await api.get(`/aeo/mentions/list?${params.toString()}`);
      setItems(j?.items || j?.mentions || []);
      const d: any = await api.get(`/aeo/mentions/dashboard?range=${range}`);
      setKpi(d?.summary || d || {});
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [range, sent, domainFilter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <RoleGate level="admin_plus">
      <View style={styles.container}>
        <Header title="Brand Mentions" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await load(); setRefreshing(false);
            }} />
          }
        >
          <View style={styles.kpiRow}>
            <Kpi label="Total" value={String(kpi.total ?? items.length)} tid="mentions-kpi-total" />
            <Kpi label="Positive" value={String(kpi.positive ?? "—")} tid="mentions-kpi-positive" />
            <Kpi label="Negative" value={String(kpi.negative ?? "—")} tid="mentions-kpi-negative" />
          </View>

          <Card>
            <Text style={styles.sectionLabel}>Filters</Text>
            <ChipRow
              label="Sentiment"
              options={SENTS.map((s) => ({ key: s.key, label: s.label }))}
              value={sent}
              onSelect={(v) => setSent(v as Sentiment)}
              testIDPrefix="mentions-chip-sent"
            />
            <View style={{ height: spacing.sm }} />
            <ChipRow
              label="Range"
              options={RANGES.map((r) => ({ key: r.key, label: r.label }))}
              value={range}
              onSelect={(v) => setRange(v as Range)}
              testIDPrefix="mentions-chip-range"
            />
            <View style={{ height: spacing.sm }} />
            <ChipRow
              label="Domain"
              options={[
                { key: "any", label: "Any" },
                { key: "own", label: "Own" },
                { key: "competitor", label: "Competitor" },
              ]}
              value={domainFilter}
              onSelect={(v) => setDomainFilter(v as any)}
              testIDPrefix="mentions-chip-domain"
            />
          </Card>

          {loading ? (
            <Loading />
          ) : items.length === 0 ? (
            <EmptyState
              icon="chatbubbles-outline"
              title="No mentions in this range"
              subtitle="Try widening the range or clearing filters."
              testID="mentions-empty"
            />
          ) : (
            items.map((m) => (
              <Pressable
                key={m.id}
                testID={`mention-row-${m.id}`}
                accessibilityLabel={`Open mention ${m.id}`}
                onPress={() => router.push({ pathname: "/aeo/mention-detail", params: { id: m.id } })}
                style={({ pressed }) => [
                  styles.mentionCard, pressed && { opacity: 0.8 },
                ]}
              >
                <View style={styles.mentionHeader}>
                  <Text style={styles.mentionProvider}>
                    {m.provider || "unknown provider"}
                  </Text>
                  <Text style={[styles.sentDot, { color: _sentColor(m.sentiment) }]}>
                    ● {m.sentiment || "neutral"}
                  </Text>
                </View>
                <Text style={styles.snippet} numberOfLines={3}>
                  {m.snippet || "(snippet missing)"}
                </Text>
                <View style={styles.badgesRow}>
                  {m.is_own_domain ? (
                    <Badge label="Own" color={colors.brand} />
                  ) : null}
                  {m.is_competitor ? (
                    <Badge label="Competitor" color={colors.warning} />
                  ) : null}
                  {m.brand_mentioned ? (
                    <Badge label="Brand mentioned" color={colors.success} />
                  ) : null}
                  {m.domain ? (
                    <Text style={styles.domainText}>{m.domain}</Text>
                  ) : null}
                </View>
              </Pressable>
            ))
          )}
        </ScrollView>
      </View>
    </RoleGate>
  );
}

function Kpi({ label, value, tid }: { label: string; value: string; tid?: string }) {
  return (
    <View style={styles.kpi} testID={tid}>
      <Text style={styles.kpiLabel}>{label}</Text>
      <Text style={styles.kpiValue}>{value}</Text>
    </View>
  );
}

function ChipRow({
  label, options, value, onSelect, testIDPrefix,
}: {
  label: string;
  options: { key: string; label: string }[];
  value: string;
  onSelect: (v: string) => void;
  testIDPrefix?: string;
}) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={styles.chipLabel}>{label}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}>
        {options.map((o) => {
          const on = value === o.key;
          return (
            <Pressable
              key={o.key}
              testID={`${testIDPrefix}-${o.key}`}
              accessibilityLabel={`${label} ${o.label}`}
              onPress={() => onSelect(o.key)}
              style={[styles.chip, on && styles.chipOn]}
            >
              <Text style={[styles.chipText, on && styles.chipTextOn]}>{o.label}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <View style={[styles.badge, { backgroundColor: `${color}20` }]}>
      <Text style={[styles.badgeText, { color }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  kpiRow: { flexDirection: "row", gap: spacing.sm },
  kpi: { flex: 1, padding: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  kpiLabel: { fontFamily: font.medium, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.4 },
  kpiValue: { fontFamily: font.bold, fontSize: 22, color: colors.onSurface, marginTop: 4 },
  sectionLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  chipLabel: { fontFamily: font.medium, fontSize: 11, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.4 },
  chip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  chipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  chipTextOn: { color: "#FFFFFF" },
  mentionCard: {
    padding: spacing.md, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
    gap: 8,
  },
  mentionHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  mentionProvider: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, textTransform: "capitalize" },
  sentDot: { fontFamily: font.medium, fontSize: fontSize.sm, textTransform: "capitalize" },
  snippet: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 20 },
  badgesRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, alignItems: "center" },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.sm },
  badgeText: { fontFamily: font.semibold, fontSize: 11 },
  domainText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginLeft: 4 },
});
